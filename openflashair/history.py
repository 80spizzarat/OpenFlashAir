from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HistoryRecord:
    remote_path: str
    remote_size: int
    remote_modified: str | None
    sha256: str
    destination: str
    state: str


class TransferHistory:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS transfers (
          remote_path TEXT NOT NULL, remote_size INTEGER NOT NULL, remote_modified TEXT,
          sha256 TEXT, destination TEXT, state TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(remote_path, remote_size, remote_modified))""")
        self.db.commit()

    def completed(self, remote_path: str, size: int, modified: str | None) -> HistoryRecord | None:
        row = self.db.execute("SELECT remote_path,remote_size,remote_modified,sha256,destination,state FROM transfers WHERE remote_path=? AND remote_size=? AND remote_modified IS ? AND state='completed'", (remote_path, size, modified)).fetchone()
        return HistoryRecord(*row) if row else None

    def record(self, record: HistoryRecord) -> None:
        self.db.execute("INSERT OR REPLACE INTO transfers(remote_path,remote_size,remote_modified,sha256,destination,state,updated_at) VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)", (record.remote_path, record.remote_size, record.remote_modified, record.sha256, record.destination, record.state))
        self.db.commit()

    def close(self) -> None:
        self.db.close()
