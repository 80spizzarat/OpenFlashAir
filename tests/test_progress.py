import unittest
import tempfile
from pathlib import Path
from openflashair.progress import TransferProgress
from openflashair.client import RemoteFile
from openflashair.engine import SyncEngine, SyncOptions


class ProgressTests(unittest.TestCase):
    def test_rate_retry_reset_and_unknown_size(self):
        now=[0.0]; progress=TransferProgress(clock=lambda:now[0])
        progress.begin(1,2,'/a.JPG',None); progress.update(0,1)
        now[0]=2; progress.update(4_000_000,1)
        self.assertEqual(progress.snapshot()['mbps'],2)
        now[0]=3; progress.update(0,2)
        self.assertEqual(progress.snapshot()['received'],0)
        now[0]=4; progress.update(1_000_000,2)
        self.assertEqual(progress.snapshot()['mbps'],1)
        self.assertIsNone(progress.snapshot()['size'])

    def test_pending_excludes_history_and_duplicate_listing(self):
        first=RemoteFile('/first.JPG',1,None,False); second=RemoteFile('/second.JPG',1,None,False)
        class Client:
            def fetch(self,path): return b'x'
        events=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); engine=SyncEngine(Client(),root/'out',root/'stage')
            engine.download_files([first],SyncOptions.photos())
            engine.progress=lambda event,**values: events.append((event,values))
            result=engine.download_files([first,second,second],SyncOptions.photos())
            engine.close()
        self.assertEqual((result.downloaded,result.skipped),(1,2))
        starts=[values for event,values in events if event=='start']
        self.assertEqual([(x['current'],x['total']) for x in starts],[(1,1)])
        self.assertEqual(events[-1],('idle',{'cancelled':False}))

    def test_pause_and_failure_report_without_success(self):
        first=RemoteFile('/first.JPG',1,None,False); second=RemoteFile('/second.JPG',1,None,False)
        class Client:
            def fetch(self,path): raise OSError('interrupted')
        events=[]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); engine=SyncEngine(Client(),root/'out',root/'stage')
            def report(event,**values):
                events.append((event,values))
                if event=='finished': engine.pause()
            engine.progress=report
            result=engine.download_files([first,second],SyncOptions.photos()); engine.close()
        self.assertEqual((result.downloaded,result.failed),(0,1))
        self.assertIn(('finished',{'success':False}),events)
        self.assertEqual(events[-1],('idle',{'cancelled':True}))

    def test_stalled_rate_falls(self):
        now=[0.0]; progress=TransferProgress(clock=lambda:now[0],window=5)
        progress.begin(1,1,'/x.JPG',10); progress.update(0,1)
        now[0]=1; progress.update(10,1)
        before=progress.snapshot()['mbps']; now[0]=10
        self.assertLess(progress.snapshot()['mbps'],before)
