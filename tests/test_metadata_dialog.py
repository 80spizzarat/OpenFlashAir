from datetime import datetime, timezone
import tkinter as tk
import unittest
from unittest.mock import patch

from openflashair.client import RemoteFile
from openflashair.gui import App


class _QueuedThread:
    targets=[]
    def __init__(self, target, daemon=False): self.target=target
    def start(self): self.targets.append(self.target)


class MetadataDialogTests(unittest.TestCase):
    def setUp(self):
        try: self.root=tk.Tk()
        except tk.TclError as exc: self.skipTest(f'Real Tk is unavailable: {exc}')
        self.app=App(self.root); self.root.geometry('900x700'); self.root.update()
        now=datetime(2026,10,18,tzinfo=timezone.utc)
        self.first=RemoteFile('/DCIM/100OLYMP/PA10001.JPG',101,now,False)
        self.second=RemoteFile('/DCIM/100OLYMP/PA10002.JPG',102,now,False)
        # Same filename as the first image, but a distinct card identity.
        self.third=RemoteFile('/DCIM/101OLYMP/PA10001.JPG',103,now,False)
        self.app.gallery_files=[self.first,self.second,self.third]
        _QueuedThread.targets=[]

    def tearDown(self): self.app._close_main_window()

    def test_one_dialog_per_card_photo_reuses_and_ignores_stale_results(self):
        with patch('openflashair.gui.threading.Thread',_QueuedThread):
            self.app.show_metadata(self.first.path); first_dialog=self.app._metadata_dialog
            self.app.show_metadata(self.first.path)
            self.assertIs(self.app._metadata_dialog,first_dialog)
            self.app.show_metadata(self.second.path)
            second_dialog=self.app._metadata_dialog
            self.app.show_metadata(self.third.path)
            third_dialog=self.app._metadata_dialog
            self.assertEqual(len(self.app._metadata_dialogs),3)
            self.assertIsNot(first_dialog,second_dialog)
            self.assertIsNot(first_dialog,third_dialog)
            self.assertEqual(first_dialog._metadata_values['Filename'].get(),'PA10001.JPG')
            self.assertEqual(second_dialog._metadata_values['Filename'].get(),'PA10002.JPG')
            self.assertEqual(third_dialog._metadata_values['Card path'].get(),self.third.path)
            _QueuedThread.targets[0](); self.root.update()
            # The stale first request cannot replace the newer request for first.
            self.assertEqual(first_dialog._metadata_path,self.first.path)
            self.app.gallery_files.reverse()
            self.app.show_metadata(self.first.path)
            self.assertIs(self.app._metadata_dialog,first_dialog)
            self.assertEqual(first_dialog._metadata_path,self.first.path)
        second_identity=self.app._metadata_identity(self.second)
        self.app._close_metadata_dialog(second_identity,second_dialog)
        self.assertEqual(len(self.app._metadata_dialogs),2)
        self.assertFalse(second_dialog.winfo_exists())
        with patch('openflashair.gui.threading.Thread',_QueuedThread):
            self.app.show_metadata(self.second.path)
            reopened=self.app._metadata_dialog
            self.assertEqual(len(self.app._metadata_dialogs),3)
            self.assertNotEqual(str(reopened),str(second_dialog))


if __name__ == '__main__': unittest.main()
