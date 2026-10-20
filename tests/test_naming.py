import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from openflashair.client import RemoteFile
from openflashair.engine import SyncEngine, SyncOptions
from openflashair.naming import FilenamePolicy, FilenameTemplateError


class Client:
    def __init__(self, entries, files): self.entries, self.files=entries,files
    def discover(self): return self.entries
    def fetch(self,path): return self.files[path]


class FilenameTests(unittest.TestCase):
    def setUp(self): self.stamp=datetime(2026,1,2,3,4,5,tzinfo=timezone.utc)
    def test_default_preserves_original_and_custom_template_preserves_extension(self):
        item=RemoteFile('/DCIM/101OLYMP/P1010001.JPG',3,self.stamp,False)
        self.assertEqual(FilenamePolicy().render(item),'P1010001.JPG')
        self.assertEqual(FilenamePolicy('{date}_{time}_{sequence}_{original}','OLY').render(item,7),'OLY_2026-01-02_03-04-05_007_P1010001.JPG')
    def test_missing_metadata_and_invalid_windows_templates(self):
        item=RemoteFile('/x/a.JPG',1,None,False)
        self.assertEqual(FilenamePolicy('{date}_{time}_{original}').render(item),'unknown-date_unknown-time_a.JPG')
        with self.assertRaises(FilenameTemplateError): FilenamePolicy('bad:name')
        with self.assertRaises(FilenameTemplateError): FilenamePolicy('{unknown}')
        with self.assertRaises(FilenameTemplateError): FilenamePolicy('CON').render(item)
    def test_collision_is_suffix_safe_and_history_ignores_template_change(self):
        first=RemoteFile('/a/IMG.JPG',1,self.stamp,False); second=RemoteFile('/b/IMG.JPG',1,self.stamp,False)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); client=Client([first,second],{first.path:b'a',second.path:b'b'})
            engine=SyncEngine(client,root/'out',root/'stage',naming=FilenamePolicy())
            result=engine.download_files([first,second],SyncOptions.jpeg_only())
            self.assertEqual(result.downloaded,2); self.assertEqual(sorted(path.name for path in (root/'out').iterdir())[0],'IMG.JPG')
            self.assertEqual(len(list((root/'out').iterdir())),2)
            engine.naming=FilenamePolicy('renamed_{original}')
            self.assertEqual(engine.download_files([first],SyncOptions.jpeg_only()).skipped,1)
            self.assertEqual(len(list((root/'out').iterdir())),2); engine.close()


if __name__ == '__main__': unittest.main()
