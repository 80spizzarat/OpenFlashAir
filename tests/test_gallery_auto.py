import inspect
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from openflashair.client import RemoteFile
from openflashair.engine import SyncEngine, SyncOptions
from openflashair.gui import App
from openflashair.history import HistoryRecord, TransferHistory


class GalleryAutoTests(unittest.TestCase):
    def test_verified_download_indicators_require_history_and_matching_local_size(self):
        item=RemoteFile('/DCIM/P0001.JPG',4,datetime(2026,1,1,tzinfo=timezone.utc),False)
        missing=RemoteFile('/DCIM/P0002.JPG',4,datetime(2026,1,1,tzinfo=timezone.utc),False)
        with tempfile.TemporaryDirectory() as directory:
            destination=Path(directory); local=destination/'P0001.JPG'; local.write_bytes(b'data')
            history=TransferHistory(destination/'.openflashair-staging'/'history.sqlite3')
            history.record(HistoryRecord(item.path,item.size,item.modified_utc.isoformat(),'hash',str(local),'completed')); history.close()
            holder=SimpleNamespace(destination=SimpleNamespace(get=lambda:str(destination)))
            verified=App._verified_downloads(holder,[item,missing])
            self.assertEqual(verified[item.path][0],local)
            self.assertEqual(verified[missing.path],(None,None))
            local.write_bytes(b'bad')
            self.assertEqual(App._verified_downloads(holder,[item])[item.path][0],None)

    def test_auto_reconciliation_uses_scan_inventory_without_a_second_discovery(self):
        source=inspect.getsource(App._reconcile_gallery_inventory)
        self.assertNotIn('FlashAirClient',source)
        self.assertIn('SyncOptions.jpeg_only()',source)
        self.assertIn('current_page_paths != prior_page_paths',source)
        self.assertIn('preserve_scroll=True',source)

    def test_canvas_checkmark_and_download_completion_are_incremental(self):
        tile=inspect.getsource(App._create_gallery_tile)
        self.assertIn('download_check_shape',tile)
        self.assertIn('create_oval',tile)
        self.assertIn('download_check_mark',tile)
        self.assertIn('create_line',tile)
        self.assertIn("capstyle='round'",tile)
        self.assertIn("joinstyle='round'",tile)
        self.assertNotIn("text='✓'",tile)
        self.assertIn("outline='#e2e8f0'",tile)
        self.assertIn('width=2',tile)
        self.assertIn('tags=(tag,)',tile)
        complete=inspect.getsource(App._selected_download_complete)
        self.assertIn('_refresh_visible_download_indicators()',complete)
        scan=inspect.getsource(App._scan_complete)
        self.assertIn('_reconcile_gallery_inventory(inventory)',scan)

    def test_badge_layers_are_raised_in_download_then_priority_order(self):
        calls=[]
        holder=SimpleNamespace(gallery_canvas=SimpleNamespace(tag_raise=calls.append))
        tile={key:key for key in ('download_check_shape','download_check_mark','badge_shape','badge_text')}
        App._raise_tile_overlays(holder,tile)
        self.assertEqual(calls,['download_check_shape','download_check_mark','badge_shape','badge_text'])
        self.assertIn('_raise_tile_overlays(tile)',inspect.getsource(App._render_tile_image))
        self.assertIn('_raise_tile_overlays(tile)',inspect.getsource(App._refresh_visible_download_indicators))

    def test_engine_retains_successful_scan_inventory(self):
        class Client:
            def __init__(self): self.item=RemoteFile('/DCIM/P0001.JPG',4,datetime(2026,1,1,tzinfo=timezone.utc),False)
            def discover(self): return [self.item]
            def fetch(self,path): return b'data'
        with tempfile.TemporaryDirectory() as directory:
            engine=SyncEngine(Client(),Path(directory)/'out',Path(directory)/'stage')
            engine.scan_now(SyncOptions.jpeg_only())
            self.assertEqual([item.path for item in engine.last_inventory],['/DCIM/P0001.JPG'])
            engine.close()


if __name__ == '__main__':
    unittest.main()
