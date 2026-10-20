import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from openflashair.client import FlashAirClient, RemoteFile
from openflashair.engine import SyncEngine, SyncOptions

class FakeClient:
    def __init__(self, entries, files): self.entries, self.files = entries, files
    def discover(self): return self.entries
    def fetch(self, path): return self.files[path]

class SyncTests(unittest.TestCase):
    def test_recursive_camera_neutral_discovery(self):
        class ListingClient(FlashAirClient):
            def _get(self, relative):
                directory = relative.split('DIR=')[1].replace('%2F', '/')
                return {
                    '/': b'/,DCIM,0,0x10,2026/01/01,00:00:00\n',
                    '/DCIM': b'/DCIM,101ANY,0,0x10,2026/01/01,00:00:00\n',
                    '/DCIM/101ANY': b'/DCIM/101ANY,img.NEF,3,0x20,2026/01/02,03:04:05\n',
                }[directory]
        files = ListingClient().discover()
        self.assertEqual([(f.path, f.size) for f in files], [('/DCIM/101ANY/img.NEF', 3)])
    def test_wlansd_filelist_root_and_comma_filename(self):
        class ListingClient(FlashAirClient):
            def _get(self, relative):
                d=relative.split('DIR=')[1].replace('%2F','/')
                return {'/':b',DCIM,0,16,2026/01/01,00:00:00\n','/DCIM':b'/DCIM,101OLYMP,0,16,2026/01/01,00:00:00\n','/DCIM/101OLYMP':b'WLANSD_FILELIST\n/DCIM/101OLYMP,IMG,001.JPG,3,32,2026/01/02,03:04:05\n'}[d]
        self.assertEqual(ListingClient().discover()[0].path,'/DCIM/101OLYMP/IMG,001.JPG')
    def test_owner_fat_fields_recurse_and_preserve_sizes(self):
        class C(FlashAirClient):
            def _get(self,r):
                d=r.split('DIR=')[1].replace('%2F','/')
                return {'/':b',DCIM,0,16,23097,48982\n','/DCIM':b'/DCIM,101OLYMP,0,16,23097,48982\n','/DCIM/101OLYMP':b'/DCIM/101OLYMP,P1010001.JPG,1234,32,23097,48982\n/DCIM/101OLYMP,P1010002.JPG,2345,32,23097,48982\n/DCIM/101OLYMP,P1010003.JPG,3456,32,23097,48982\n'}[d]
        files=C().discover(); self.assertEqual([x.size for x in files],[1234,2345,3456]); self.assertTrue(all(x.modified_utc for x in files))
    def test_default_system_folder_exclusion_is_exact(self):
        opts=SyncOptions.photos()
        self.assertFalse(opts.accepts(RemoteFile('/DCIM/100__TSB/FA000001.JPG',1,None,False)))
        self.assertFalse(opts.accepts(RemoteFile('/dcim/100__tsb/nested/a.JPG',1,None,False)))
        self.assertTrue(opts.accepts(RemoteFile('/DCIM/101OLYMP/PA150001.JPG',1,None,False)))
        self.assertTrue(opts.accepts(RemoteFile('/DCIM/100__TSBX/keep.JPG',1,None,False)))
    def test_bytes_preserved_and_repeat_skips(self):
        item = RemoteFile('/DCIM/X/a.ORF', 4, datetime(2026, 1, 2, tzinfo=timezone.utc), False)
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); e = SyncEngine(FakeClient([item], {item.path:b'RAW!'}), base/'out', base/'stage')
            self.assertEqual(e.scan_now(SyncOptions.photos()).downloaded, 1)
            self.assertEqual(next((base/'out').iterdir()).read_bytes(), b'RAW!')
            self.assertEqual(e.scan_now(SyncOptions.photos()).skipped, 1)
            e.close()
    def test_reused_name_different_size_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); stamp=datetime(2026,1,2,tzinfo=timezone.utc); path='/DCIM/a.JPG'
            first=RemoteFile(path,3,stamp,False); second=RemoteFile(path,4,stamp,False)
            e=SyncEngine(FakeClient([first],{path:b'one'}),base/'out',base/'stage'); e.scan_now(SyncOptions.jpeg_only())
            e.client=FakeClient([second],{path:b'two!'}); e.scan_now(SyncOptions.jpeg_only())
            self.assertEqual(sorted(p.read_bytes() for p in (base/'out').iterdir()), [b'one',b'two!'])
            e.close()
    def test_filter_and_pause(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); item=RemoteFile('/x/a.JPG',1,None,False); e=SyncEngine(FakeClient([item],{item.path:b'x'}),base/'o',base/'s')
            e.pause(); self.assertEqual(e.scan_now(SyncOptions.jpeg_only()).downloaded,0)
            e.resume(); self.assertEqual(e.scan_now(SyncOptions.custom(['nef'])).discovered,0)
            e.close()
    def test_short_transfer_fails_without_destination(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); item=RemoteFile('/x/a.JPG',2,None,False); e=SyncEngine(FakeClient([item],{item.path:b'x'}),base/'o',base/'s')
            self.assertEqual(e.scan_now(SyncOptions.jpeg_only()).failed,1); self.assertFalse(any((base/'o').iterdir()))
            e.close()
    def test_explicit_downloads_preserve_queue_order_and_safety(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); stamp=datetime(2026,1,2,tzinfo=timezone.utc)
            first=RemoteFile('/x/first.JPG',1,stamp,False); second=RemoteFile('/x/second.JPG',1,stamp,False)
            client=FakeClient([first,second],{first.path:b'a',second.path:b'b'})
            e=SyncEngine(client,base/'out',base/'stage')
            result=e.download_files([second,first],SyncOptions.jpeg_only())
            self.assertEqual((result.discovered,result.downloaded,result.failed),(2,2,0))
            self.assertEqual(e.download_files([second,first],SyncOptions.jpeg_only()).skipped,2)
            e.close()

if __name__ == '__main__': unittest.main()
