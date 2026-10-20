"""Persistent selection order only; transfer execution remains in SyncEngine."""
import sqlite3
from pathlib import Path
class DownloadQueue:
 def __init__(self,path):
  self.db=sqlite3.connect(Path(path)); self.db.execute('CREATE TABLE IF NOT EXISTS queue(path TEXT PRIMARY KEY, position INTEGER, state TEXT)'); self.db.commit()
 def add(self,path):
  n=self.db.execute('SELECT COALESCE(MAX(position),0)+1 FROM queue').fetchone()[0]; self.db.execute('INSERT OR IGNORE INTO queue VALUES(?,?,?)',(path,n,'queued')); self.db.commit()
 def remove(self,path): self.db.execute('DELETE FROM queue WHERE path=?',(path,)); self.db.commit()
 def replace(self,paths):
  self.db.execute('DELETE FROM queue')
  self.db.executemany('INSERT INTO queue VALUES(?,?,?)',[(p,n,'queued') for n,p in enumerate(paths,1)]); self.db.commit()
 def pending(self): return self.db.execute("SELECT path FROM queue WHERE state='queued' ORDER BY position").fetchall()
