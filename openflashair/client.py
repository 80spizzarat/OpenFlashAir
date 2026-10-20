from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.error import URLError, HTTPError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


class FlashAirError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteFile:
    path: str
    size: int
    modified_utc: datetime | None
    is_directory: bool


class FlashAirClient:
    """Minimal read-only client for FlashAir's op=100 listing endpoint."""
    def __init__(self, base_url: str = "http://openflashair/", timeout: float = 10, retries: int = 3):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout, self.retries = timeout, retries

    def _get(self, relative: str) -> bytes:
        url = urljoin(self.base_url, relative)
        last: Exception | None = None
        for attempt in range(self.retries):
            try:
                request = Request(url, method="GET")
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except (URLError, HTTPError, TimeoutError) as exc:
                last = exc
                if attempt + 1 < self.retries:
                    time.sleep(min(0.25 * (2 ** attempt), 2.0))
        raise FlashAirError(f"GET failed for {url}: {last}") from last

    def available(self) -> bool:
        try:
            self.list_directory("/")
            return True
        except FlashAirError:
            return False

    def list_directory(self, directory: str) -> list[RemoteFile]:
        payload = urlencode({"op": "100", "DIR": directory})
        text = self._get("command.cgi?" + payload).decode("utf-8", "replace")
        entries: list[RemoteFile] = []
        for line in text.splitlines():
            # FlashAir does not quote filenames; split the five fixed fields from right.
            row = line.rsplit(",", 5)
            if len(row) != 6:
                continue
            name, size, attr, date, clock = row[1], row[2], row[3], row[4], row[5]
            # FlashAir rows include full parent directory in column 0.
            parent = row[0] or directory
            # For an unquoted comma in a filename, right-splitting leaves the prefix
            # attached to the parent. The requested directory disambiguates it.
            if parent.startswith(directory.rstrip("/") + ","):
                name = parent[len(directory.rstrip("/")) + 1:] + "," + name
                parent = directory
            path = str(PurePosixPath(parent) / name)
            try:
                if "/" in date:
                    modified = datetime.strptime(f"{date} {clock}", "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
                else:
                    d, t = int(date), int(clock); modified = datetime(1980 + (d >> 9), (d >> 5) & 15, d & 31, t >> 11, (t >> 5) & 63, (t & 31) * 2, tzinfo=timezone.utc)
            except (ValueError, OverflowError): modified = None
            try:
                number = int(size.strip())
            except ValueError:
                number = 0
            try:
                attribute = int(attr.strip(), 0)
            except ValueError:
                continue
            entries.append(RemoteFile(path, number, modified, bool(attribute & 0x10)))
        return entries

    def discover(self, root: str = "/") -> list[RemoteFile]:
        found: list[RemoteFile] = []
        pending = [root]
        seen: set[str] = set()
        while pending:
            directory = pending.pop()
            if directory in seen:
                continue
            seen.add(directory)
            for entry in self.list_directory(directory):
                if entry.is_directory:
                    if PurePosixPath(entry.path).name not in {".", ".."}:
                        pending.append(entry.path)
                else:
                    found.append(entry)
        return found

    def fetch(self, remote_path: str, progress=None) -> bytes:
        """Read in bounded chunks; retry restarts the file from byte zero.

        Progress receives (bytes received in this attempt, attempt number).
        No partial payload is returned after an interrupted attempt.
        """
        url=urljoin(self.base_url,quote(remote_path.lstrip('/'),safe='/'))
        last=None
        for attempt in range(1,self.retries+1):
            try:
                if progress: progress(0,attempt)
                chunks=[]; received=0
                with urlopen(Request(url,method='GET'),timeout=self.timeout) as response:
                    while True:
                        chunk=response.read(256*1024)
                        if not chunk: break
                        chunks.append(chunk); received+=len(chunk)
                        if progress: progress(received,attempt)
                return b''.join(chunks)
            except (URLError,HTTPError,TimeoutError,ConnectionError,OSError) as exc:
                last=exc
                if attempt < self.retries: time.sleep(min(0.25*(2**(attempt-1)),2.0))
        raise FlashAirError(f'GET failed for {url}: {last}') from last
