"""Transfer telemetry, independent of transfer success and history records."""
from collections import deque
import time


class TransferProgress:
    def __init__(self, clock=time.monotonic, window=5.0):
        self.clock=clock; self.window=window; self.samples=deque(); self.attempt=0
        self.current=0; self.total=0; self.path=''; self.received=0; self.size=None

    def begin(self, current, total, path, size):
        self.current=current; self.total=total; self.path=path
        self.size=size if size and size > 0 else None
        self.received=0; self.attempt=0; self.samples.clear()

    def update(self, received, attempt, timestamp=None):
        now=self.clock() if timestamp is None else timestamp
        if attempt != self.attempt or received < self.received:
            self.samples.clear(); self.attempt=attempt
            self.samples.append((now,0))
        self.received=max(0,received)
        self.samples.append((now,self.received))
        while len(self.samples)>2 and now-self.samples[1][0]>self.window:
            self.samples.popleft()

    def snapshot(self):
        rate=0.0
        now=self.clock()
        while len(self.samples)>1 and now-self.samples[1][0]>self.window:
            self.samples.popleft()
        if len(self.samples)>1:
            elapsed=max(self.samples[-1][0],now)-self.samples[0][0]
            if elapsed>0: rate=max(0,self.samples[-1][1]-self.samples[0][1])/elapsed/1_000_000
        return dict(current=self.current,total=self.total,path=self.path,received=self.received,size=self.size,mbps=rate)
