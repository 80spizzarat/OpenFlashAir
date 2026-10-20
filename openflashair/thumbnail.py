"""Isolated, read-only FlashAir thumbnail.cgi client."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import urlopen

@dataclass(frozen=True)
class Thumbnail:
    state: str; data: bytes | None

class ThumbnailClient:
    def __init__(self, base_url='http://openflashair/', timeout=5, concurrency=2):
        self.base_url=base_url.rstrip('/')+'/'; self.timeout=timeout; self.concurrency=concurrency; self.cache={}; self.cancelled=False
    def get(self,path,size=None,modified=None):
        key=(path.lower(),size,modified)
        if key in self.cache:return self.cache[key]
        if self.cancelled:return Thumbnail('cancelled',None)
        try:
            with urlopen(urljoin(self.base_url,'thumbnail.cgi?'+quote(path,safe='/')),timeout=self.timeout) as r:
                data=r.read(); result=Thumbnail('ok',data) if data.startswith(b'\xff\xd8') else Thumbnail('invalid',None)
        except HTTPError as e: result=Thumbnail('missing',None) if e.code==404 else Thumbnail('error',None)
        except (URLError,TimeoutError): result=Thumbnail('error',None)
        self.cache[key]=result; return result
    def fetch_many(self,items):
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:return list(pool.map(lambda x:self.get(*x),items))
    def cancel(self): self.cancelled=True
