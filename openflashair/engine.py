from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

from .client import FlashAirClient, FlashAirError, RemoteFile
from .history import HistoryRecord, TransferHistory
from .naming import FilenamePolicy

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".orf", ".nef", ".cr2", ".cr3", ".arw", ".dng", ".tif", ".tiff", ".png", ".heif", ".heic", ".mp4", ".mov"}

@dataclass(frozen=True)
class SyncOptions:
    extensions: frozenset[str] = field(default_factory=lambda: frozenset(PHOTO_EXTENSIONS))
    excluded_directories: frozenset[str] = field(default_factory=lambda: frozenset({"/dcim/100__tsb"}))
    @classmethod
    def photos(cls): return cls()
    @classmethod
    def jpeg_only(cls): return cls(frozenset({".jpg", ".jpeg"}))
    @classmethod
    def custom(cls, extensions): return cls(frozenset(x.lower() if x.startswith(".") else "." + x.lower() for x in extensions))
    def accepts(self, item: RemoteFile) -> bool:
        path = item.path.replace("\\", "/").rstrip("/").lower()
        if any(path == d or path.startswith(d + "/") for d in self.excluded_directories): return False
        return Path(item.path).suffix.lower() in self.extensions

@dataclass(frozen=True)
class SyncResult:
    discovered: int; downloaded: int; skipped: int; failed: int

class SyncEngine:
    def __init__(self, client: FlashAirClient, destination: Path, staging: Path, history_path: Path | None = None, naming: FilenamePolicy | None = None, progress=None):
        self.client, self.destination, self.staging = client, Path(destination), Path(staging)
        self.history = TransferHistory(history_path or self.staging / "history.sqlite3")
        self.paused = False
        self.last_errors: list[str] = []
        self.last_network_error = False
        self.last_inventory: list[RemoteFile] = []
        self.naming = naming or FilenamePolicy()
        self.progress = progress

    def _progress(self, event, **values):
        if self.progress is not None:
            try: self.progress(event, **values)
            except Exception: pass  # telemetry never alters transfer safety

    def _already_downloaded(self, remote, key_time):
        old=self.history.completed(remote.path,remote.size,key_time)
        return bool(old and Path(old.destination).is_file() and Path(old.destination).stat().st_size == remote.size)

    def pause(self): self.paused = True
    def resume(self): self.paused = False
    def close(self): self.history.close()
    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def scan_now(self, options: SyncOptions) -> SyncResult:
        # Keep the single authoritative listing for callers that need to reconcile UI state.
        # It avoids a second card scan after a successful polling pass.
        self.last_inventory=list(self.client.discover())
        return self.download_files(self.last_inventory, options)

    def download_files(self, remotes, options: SyncOptions) -> SyncResult:
        """Transfer an explicitly ordered iterable using the same safety checks as a scan."""
        self.last_errors = []
        self.last_network_error = False
        discovered = downloaded = skipped = failed = 0
        remotes=list(remotes)
        keys=set()
        if self.progress:
            for remote in remotes:
                stamp=remote.modified_utc.isoformat() if remote.modified_utc else None
                if options.accepts(remote) and not self._already_downloaded(remote,stamp):
                    keys.add((remote.path,remote.size,stamp))
        pending=len(keys); ordinals={}
        for sequence, remote in enumerate(remotes, 1):
            if not options.accepts(remote): continue
            discovered += 1
            if self.paused: break
            key_time = remote.modified_utc.isoformat() if remote.modified_utc else None
            if self._already_downloaded(remote,key_time):
                skipped += 1; continue
            identity=(remote.path,remote.size,key_time)
            if identity not in ordinals: ordinals[identity]=len(ordinals)+1
            self._progress('start',current=ordinals[identity],total=pending,path=remote.path,size=remote.size)
            try:
                self._transfer(remote, key_time, sequence); downloaded += 1
                self._progress('finished',success=True)
            except Exception as exc:
                if isinstance(exc,FlashAirError): self.last_network_error=True
                self.last_errors.append(f"{remote.path}: {type(exc).__name__}: {exc}")
                failed += 1
                self._progress('finished',success=False)
        self._progress('idle',cancelled=self.paused)
        return SyncResult(discovered, downloaded, skipped, failed)

    def _transfer(self, remote: RemoteFile, key_time: str | None, sequence: int) -> None:
        self.staging.mkdir(parents=True, exist_ok=True); self.destination.mkdir(parents=True, exist_ok=True)
        if self.progress is not None and isinstance(self.client,FlashAirClient):
            data=self.client.fetch(remote.path,progress=lambda received,attempt:self._progress('bytes',received=received,attempt=attempt))
        else:
            data = self.client.fetch(remote.path)
        if len(data) != remote.size: raise IOError(f"size changed/incomplete: {remote.path}")
        digest = hashlib.sha256(data).hexdigest()
        desired = self.destination / self.naming.render(remote, sequence)
        final = desired
        if final.exists() and (final.stat().st_size != remote.size or hashlib.sha256(final.read_bytes()).hexdigest() != digest):
            # A digest suffix is deterministic for this source payload and never overwrites.
            final = desired.with_name(f"{desired.stem}__{digest[:12]}{desired.suffix}")
        temp = self.staging / (digest + ".part")
        try:
            if final.exists():
                if final.stat().st_size != remote.size or hashlib.sha256(final.read_bytes()).hexdigest() != digest:
                    raise FileExistsError(f"collision at {final}")
                self.history.record(HistoryRecord(remote.path, remote.size, key_time, digest, str(final), "completed"))
                return
            with open(temp, "xb") as handle: handle.write(data)
            if temp.stat().st_size != remote.size: raise IOError("staging verification failed")
            # Exclusive creation prevents any overwrite, including on a collision.
            with open(temp, "rb") as src, open(final, "xb") as dst:
                while block := src.read(1024 * 1024): dst.write(block)
            if final.stat().st_size != remote.size or hashlib.sha256(final.read_bytes()).hexdigest() != digest: raise IOError("final verification failed")
            self.history.record(HistoryRecord(remote.path, remote.size, key_time, digest, str(final), "completed"))
        except Exception:
            self.history.record(HistoryRecord(remote.path, remote.size, key_time, digest, str(final), "failed"))
            raise
        finally:
            if temp.exists(): temp.unlink()
