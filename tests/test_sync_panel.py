import tkinter as tk
from tkinter import ttk
import time
import unittest
from unittest.mock import Mock, patch

from openflashair.gui import App


class SynchronizationPanelTests(unittest.TestCase):
    """Real-Tk checks for fixed panel widgets and non-blocking indicators."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Real Tk is unavailable: {exc}')
        self.root.geometry('900x700')
        self.app = App(self.root)
        self.root.geometry('900x700')
        self.root.deiconify()
        self.root.update()

    def tearDown(self):
        self.app._close_main_window()

    def _finish_transitions(self):
        self.app._cancel_indicator_animation()
        for _ in range(10):
            self.app._tick_activity_indicators()
            self.app._cancel_indicator_animation()

    def test_connection_status_and_stale_endpoint_result(self):
        self.root.update_idletasks()
        positions=[(w.winfo_rootx(),w.winfo_rooty()) for w in (self.app.connection_heading,self.app.connection_status_label,self.app.shared_sync_status,self.app.transfer_bar)]
        self.assertEqual(self.app.connection_status.get(), 'Not checked')
        original=self.app.endpoint.get()
        self.app._connection_checked(True,None)
        self.root.update_idletasks()
        self.assertEqual(positions,[(w.winfo_rootx(),w.winfo_rooty()) for w in (self.app.connection_heading,self.app.connection_status_label,self.app.shared_sync_status,self.app.transfer_bar)])
        self.assertIn('Connected',self.app.connection_status.get())
        self.app.endpoint.set('http://127.0.0.1/')
        self.assertEqual(self.app.connection_status.get(), 'Not checked')
        if original != self.app.endpoint.get():
            self.app._connection_check_result(original,True,None)
            self.assertEqual(self.app.connection_status.get(), 'Not checked')
        self.app._connection_checked(False,None)
        self.assertIn('Disconnected',self.app.connection_status.get())

    def test_transfer_progress_panel_and_tooltip(self):
        self.app._transfer_event('start',current=1,total=2,path='/photo.JPG',size=100)
        self.app._transfer_event('bytes',received=0,attempt=1)
        self.app._transfer_event('bytes',received=50,attempt=1)
        self.app._update_transfer_display()
        self.assertIn('1/2',self.app.transfer_text.get())
        self.assertIn('photo.JPG',self.app.transfer_text.get())
        self.assertEqual(float(self.app.transfer_bar['value']),50)
        self.assertIn('1/2',self.app._tray_title())
        self.app._transfer_event('idle',cancelled=False)
        self.app._update_transfer_display()
        self.assertEqual(self.app.transfer_text.get(),'Transfer: Idle')

    def test_connection_network_failure_and_recovery(self):
        from openflashair.client import FlashAirError
        endpoint=self.app.endpoint.get()
        self.app._connection_checked(True,None)
        self.app._selected_error(FlashAirError('unreachable'),endpoint)
        self.assertIn('Disconnected',self.app.connection_status.get())
        self.app._connection_checked(True,None)
        self.assertIn('Connected',self.app.connection_status.get())
        self.app.endpoint.set('http://127.0.0.1/')
        if endpoint != self.app.endpoint.get():
            self.app._selected_error(FlashAirError('old endpoint'),endpoint)
            self.assertEqual(self.app.connection_status.get(),'Not checked')

    def test_select_page_preserves_cross_page_selections(self):
        from openflashair.client import RemoteFile
        from pathlib import Path
        items=[RemoteFile(f'/DCIM/{i:03}.JPG',10,None,False) for i in range(102)]
        self.app.gallery_files=items; self.app.loaded=[item.path for item in items]; self.app.gallery_page=1; self.app.selected=[items[0].path]
        def verified(photos):
            return {p.path:((Path('verified'),object()) if p.path == items[100].path else (None,None)) for p in photos}
        with patch.object(self.app,'_verified_downloads',side_effect=verified), patch.object(self.app,'_persist_selection'):
            self.app.select_page(); self.assertEqual(self.app.selected,[items[0].path,items[101].path])
            self.app.select_all(); self.assertEqual(len(self.app.selected),101)
            self.assertNotIn(items[100].path,self.app.selected)
            self.app.clear_all(); self.assertEqual(self.app.selected,[])

    def test_gallery_fallback_label_and_exif_update(self):
        from datetime import datetime, timezone
        from openflashair.client import RemoteFile
        photo=RemoteFile('/DCIM/a.JPG',10,datetime(2026,1,2,3,4,5,tzinfo=timezone.utc),False)
        self.app._create_gallery_tile(photo)
        tile=self.app._tiles_by_path[photo.path]
        self.assertEqual('FlashAir timestamp',self.app.gallery_canvas.itemcget(tile['capture'],'text'))
        self.app._set_tile_capture_time(self.app._gallery_generation,photo.path,'2026:01:02 03:04:05')
        self.assertEqual(self.app.gallery_canvas.itemcget(tile['capture'],'text'),'EXIF timestamp')
        self.assertEqual(self.app.gallery_canvas.itemcget(tile['capture_value'],'text'),self.app._display_timestamp('2026:01:02 03:04:05'))
        missing=RemoteFile('/DCIM/b.JPG',10,None,False); self.app._create_gallery_tile(missing)
        self.assertEqual(self.app.gallery_canvas.itemcget(self.app._tiles_by_path[missing.path]['capture_value'],'text'),'Unavailable')

    def test_selection_excludes_verified_and_clears_after_download(self):
        from openflashair.client import RemoteFile
        from pathlib import Path
        first=RemoteFile('/DCIM/a.JPG',10,None,False); second=RemoteFile('/DCIM/b.JPG',10,None,False)
        self.app.gallery_files=[first,second]; self.app.loaded=[first.path,second.path]
        self.app.selected=[]
        def verification(items):
            return {item.path:((Path('verified.jpg'),object()) if item.path == first.path else (None,None)) for item in items}
        with patch.object(self.app,'_verified_downloads',side_effect=verification), patch.object(self.app,'_persist_selection'):
            self.app.select_all()
            self.assertEqual(self.app.selected,[second.path])
            self.app.toggle(first.path)
            self.assertEqual(self.app.selected,[second.path])
            self.app.selected=[first.path,second.path]
            self.app._refresh_visible_download_indicators()
            self.assertEqual(self.app.selected,[second.path])

    def test_preview_failure_clears_previous_image(self):
        dialog=Mock(); dialog.winfo_exists.return_value=True
        canvas=Mock(); status=Mock(); state={'generation':2,'image':object(),'photo':object(),'canvas':canvas}
        self.app._preview_failed(dialog,state,2,IOError('offline'),status)
        canvas.delete.assert_called_once_with('preview')
        self.assertIsNone(state['image'])
        self.assertIn('Preview unavailable',status.set.call_args.args[0])

    def test_open_folder_opens_existing_and_reports_missing(self):
        from pathlib import Path
        self.app.destination.set(str(Path(__file__).parent))
        with patch('openflashair.gui.os.startfile') as start, patch('openflashair.gui.messagebox.showerror') as error:
            self.app.open_destination_folder()
            start.assert_called_once()
            error.assert_not_called()
            self.app.destination.set(str(Path(__file__).parent / 'nonexistent-folder-for-rc5'))
            self.app.open_destination_folder()
            self.assertEqual(start.call_count,1)
            error.assert_called_once()

    def test_relayout_does_not_lose_pending_resize_callback(self):
        self.app._gallery_resize(None)
        pending=self.app._resize_after
        self.app._relayout_gallery()
        self.assertEqual(self.app._resize_after,pending)

    def test_state_cycle_keeps_stable_groups_and_bounded_animation(self):
        manual_width = self.app.manual_scan_group.winfo_reqwidth()
        automatic_width = self.app.auto_scan_group.winfo_reqwidth()
        self.assertEqual(self.app.manual_panel_state.get(), 'Idle')
        self.assertEqual(self.app.auto_state.get(), 'Paused')

        self.app._set_panel_activity('manual', 'active', 'Scanning')
        self.root.update_idletasks()
        self.assertEqual(self.app.manual_panel_state.get(), 'Scanning')
        self.assertEqual(self.app._activity_indicators['manual']['mode'], 'active')
        self.assertIsNotNone(self.app._indicator_after)
        asset_set = next(frames for (name, _size), frames in self.app._activity_icon_frames.items()
                         if name == 'sync-states-v1')
        self.assertEqual(len(asset_set['green']), 24)
        self.assertEqual(len(asset_set['transition']), 24)
        self.assertEqual(len(asset_set['transition'][0]), 9)

        self.app._set_panel_activity('manual', 'active', 'Downloading')
        self.app._set_panel_activity('manual', 'complete', 'Complete')
        self.app._set_panel_activity('auto', 'waiting', 'Waiting')
        self.assertEqual(self.app.manual_scan_group.winfo_reqwidth(), manual_width)
        self.assertEqual(self.app.auto_scan_group.winfo_reqwidth(), automatic_width)
        self._finish_transitions()
        self.assertEqual(self.app._indicator_after, None)
        self.assertEqual(len(asset_set['red']), 24)

        self.app._set_panel_activity('auto', 'active', 'Scanning')
        self.assertIsNotNone(self.app._indicator_after)
        self.app._set_panel_activity('auto', 'paused', 'Paused')
        self.app._set_panel_activity('manual', 'error', 'Error')
        self.assertEqual(self.app.auto_state.get(), 'Paused')
        self.assertEqual(self.app.manual_panel_state.get(), 'Error')
        self._finish_transitions()
        self.assertIsNone(self.app._indicator_after)

    def test_controls_guard_overlapping_scans_and_scale_indicator(self):
        self.app.scanning = True
        self.app.auto = False
        self.app._update_scan_controls()
        self.assertEqual(str(self.app.scan_once_button.cget('state')), 'disabled')
        self.assertEqual(str(self.app.auto_control_button.cget('state')), 'disabled')

        self.app.auto = True
        self.app._update_auto_control_label()
        self.app._update_scan_controls()
        self.assertEqual(self.app.auto_control_button.cget('text'), 'Pause Auto Scan')
        self.assertGreaterEqual(self.app._activity_indicators['manual']['canvas'].winfo_reqwidth(), 24)

        for width in (900, 560):
            self.root.geometry(f'{width}x700')
            self.root.update()
            self.assertGreater(self.app.manual_scan_group.winfo_reqwidth(), 0)
            self.assertGreater(self.app.auto_scan_group.winfo_reqwidth(), 0)

    def test_compact_dashboard_has_prominent_counters_without_nested_group_boxes(self):
        self.assertIsInstance(self.app.manual_scan_group, ttk.Frame)
        self.assertIsInstance(self.app.auto_scan_group, ttk.Frame)
        self.assertGreaterEqual(self.app.scan_once_button.winfo_reqheight(), 38)
        self.assertGreaterEqual(self.app.auto_control_button.winfo_reqheight(), 38)
        self.assertEqual(tuple(self.app.counter_values), ('Discovered','Downloaded','Skipped','Failed'))
        self.assertLessEqual(self.app.sync_box.winfo_reqheight(), 300)  # includes transfer and connection status

    def test_dashboard_alignment_and_coordinates_do_not_change_with_state(self):
        self.assertEqual(self.app.manual_heading.winfo_rooty(), self.app.auto_heading.winfo_rooty())
        self.assertEqual(self.app.scan_once_button.winfo_rooty(), self.app.auto_control_button.winfo_rooty())
        self.assertFalse(any(isinstance(child, ttk.Frame) for child in self.app.shared_sync_status.winfo_children()))
        positions=(self.app.scan_once_button.winfo_rootx(), self.app.auto_control_button.winfo_rootx(),
                   self.app._activity_indicators['manual']['canvas'].winfo_rootx(), self.app.auto_indicator.winfo_rootx())
        self.app._set_panel_activity('manual','active','Scanning')
        self.app._set_panel_activity('auto','waiting','Waiting')
        self.root.update_idletasks()
        self.assertEqual(positions,(self.app.scan_once_button.winfo_rootx(), self.app.auto_control_button.winfo_rootx(),
                                    self.app._activity_indicators['manual']['canvas'].winfo_rootx(), self.app.auto_indicator.winfo_rootx()))

    def test_failed_counter_reserves_right_padding_at_normal_and_narrow_widths(self):
        self.app.counter_display['Failed'].set('Failed: 999')
        self.root.update_idletasks()
        failed=self.app.counter_labels[3]
        panel_right=self.app.shared_sync_status.winfo_rootx()+self.app.shared_sync_status.winfo_width()
        self.assertGreaterEqual(panel_right-(failed.winfo_rootx()+failed.winfo_width()),10)
        self.assertGreaterEqual(self.app.shared_sync_status.grid_columnconfigure(3)['minsize'],112)
        self.root.geometry('560x700'); self.root.update()
        self.assertEqual(failed.grid_info()['row'],1)
        self.assertGreaterEqual(self.app.shared_sync_status.winfo_rootx()+self.app.shared_sync_status.winfo_width()-(failed.winfo_rootx()+failed.winfo_width()),10)

    def test_transition_reverses_at_the_current_orientation_without_resetting(self):
        indicator = self.app._activity_indicators['manual']
        self.app._set_panel_activity('manual', 'active', 'Scanning')
        self.assertEqual(indicator['phase'], 'starting')
        self.app._cancel_indicator_animation()
        for _ in range(3):
            self.app._tick_activity_indicators()
            self.app._cancel_indicator_animation()
        held_step = indicator['transition_step']
        self.assertGreater(held_step, 0)

        self.app._set_panel_activity('manual', 'complete', 'Complete')
        self.assertEqual(indicator['phase'], 'stopping')
        self.assertEqual(indicator['transition_step'], held_step)
        self.app._set_panel_activity('manual', 'active', 'Scanning')
        self.assertEqual(indicator['phase'], 'starting')
        self.assertEqual(indicator['transition_step'], held_step)

        self._finish_transitions()
        self.assertEqual(indicator['phase'], 'active')
        held_orientation = indicator['orientation']
        self.app._set_panel_activity('manual', 'complete', 'Complete')
        self.assertEqual(indicator['phase'], 'stopping')
        self.assertEqual(indicator['orientation'], held_orientation)
        self._finish_transitions()
        self.assertEqual(indicator['phase'], 'idle')
        self.assertEqual(indicator['orientation'], held_orientation)

    def test_deferred_scan_error_keeps_original_exception(self):
        callbacks=[]
        def capture_after(delay, callback):
            if delay == 0:
                callbacks.append(callback)
            return None
        with patch.object(self.app, 'after', side_effect=capture_after), patch.object(self.app, 'make_engine', side_effect=ConnectionRefusedError('synthetic refusal')):
            self.app.scan(automatic=False)
            deadline=time.monotonic()+2
            while len(callbacks) < 2 and time.monotonic() < deadline:
                time.sleep(.01)
            for callback in callbacks:
                callback()
        self.assertIn('ConnectionRefusedError: synthetic refusal', self.app.status.get())
        self.assertEqual(self.app.manual_panel_state.get(), 'Error')

    def test_auto_pause_is_acknowledged_before_worker_finishes(self):
        engine=Mock()
        self.app.auto=True; self.app._auto_has_started=True; self.app.scanning=True; self.app._active_scan_automatic=True; self.app._active_engine=engine
        self.app.pause()
        self.assertFalse(self.app.auto)
        self.assertTrue(self.app._auto_pause_requested)
        self.assertEqual(self.app.auto_state.get(), 'Pausing…')
        self.assertEqual(self.app.next_scan.get(), 'Next scan: —')
        self.assertEqual(self.app.auto_control_button.cget('text'), 'Pausing…')
        engine.pause.assert_called_once_with()
        self.app._finish_scan(True)
        self.assertFalse(self.app._auto_pause_requested)
        self.assertEqual(self.app.auto_state.get(), 'Paused')
        self.assertEqual(self.app.status.get(), 'Automatic sync paused')

    def test_auto_countdown_distinguishes_retry_and_scan(self):
        self.app.auto=True; self.app._next_scan_at=time.monotonic()+10
        self.app._auto_retry_pending=False; self.app._update_countdown()
        self.assertTrue(self.app.next_scan.get().startswith('Next scan: '))
        if self.app._countdown_after: self.app.after_cancel(self.app._countdown_after); self.app._countdown_after=None
        self.app._auto_retry_pending=True; self.app._update_countdown()
        self.assertTrue(self.app.next_scan.get().startswith('Retry in: '))
        if self.app._countdown_after: self.app.after_cancel(self.app._countdown_after); self.app._countdown_after=None


if __name__ == '__main__':
    unittest.main()
