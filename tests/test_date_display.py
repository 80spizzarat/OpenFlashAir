import unittest
import tempfile
import tkinter as tk
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from openflashair.date_display import DATE_FORMATS, TIME_FORMATS, format_timestamp

class DateDisplayTests(unittest.TestCase):
    def test_all_combinations_and_camera_local_exif(self):
        expected_dates={'MM/DD/YYYY':'10/19/2026','DD/MM/YYYY':'19/10/2026','YYYY-MM-DD':'2026-10-19'}
        expected_times={'12-hour (AM/PM)':'09:07:06 PM','24-hour':'21:07:06'}
        for date in DATE_FORMATS:
            for time in TIME_FORMATS:
                expected=expected_dates[date]+' '+expected_times[time]
                self.assertEqual(format_timestamp(datetime(2026,10,19,21,7,6),date,time),expected)
                self.assertEqual(format_timestamp('2026:10:19 21:07:06',date,time),expected)

    def test_missing_and_invalid(self):
        for value in (None,'','bad date'):
            self.assertEqual(format_timestamp(value,'MM/DD/YYYY','24-hour'),'Unavailable')

    def test_iso_and_exif_preserve_displayed_clock(self):
        self.assertEqual(format_timestamp('2026-10-19T21:07:06+09:00','YYYY-MM-DD','24-hour'),'2026-10-19 21:07:06')
        self.assertEqual(format_timestamp('2026:10:19 21:07:06','YYYY-MM-DD','24-hour'),'2026-10-19 21:07:06')

    def test_restart_and_existing_install_defaults(self):
        from openflashair.gui import App
        with tempfile.TemporaryDirectory() as directory:
            settings=Path(directory)/'settings.json'; legacy=Path(directory)/'legacy.json'
            with patch.object(App,'_settings_path',return_value=settings), patch.object(App,'_legacy_settings_path',return_value=legacy):
                root=tk.Tk(); app=App(root)
                self.assertEqual((app.date_format,app.time_format),('MM/DD/YYYY','12-hour (AM/PM)'))
                self.assertTrue(app._save_settings(date_display_format='DD/MM/YYYY',time_display_format='24-hour'))
                app._close_main_window()

    def test_dropdown_post_selection_save_and_cancel(self):
        from tkinter import ttk
        from openflashair.gui import App
        with tempfile.TemporaryDirectory() as directory:
            settings=Path(directory)/'settings.json'; legacy=Path(directory)/'legacy.json'
            with patch.object(App,'_settings_path',return_value=settings), patch.object(App,'_legacy_settings_path',return_value=legacy):
                root=tk.Tk(); app=App(root); root.update()
                def dialog():
                    app.date_time_settings(); root.update()
                    window=next(w for w in app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='Date & Time Display')
                    body=window.winfo_children()[0]
                    return window,[w for w in body.winfo_children() if isinstance(w,ttk.Combobox)],[w for w in body.winfo_children() if isinstance(w,ttk.Button)]
                window,boxes,buttons=dialog()
                for box in boxes:
                    box.tk.call('ttk::combobox::Post',str(box)); root.update()
                    popup=box.tk.call('ttk::combobox::PopdownWindow',str(box))
                    self.assertEqual(int(box.tk.call('winfo','ismapped',popup)),1)
                    box.tk.call('ttk::combobox::Unpost',str(box))
                boxes[0].current(1); boxes[1].current(1); root.update()
                next(b for b in buttons if b.cget('text')=='Save').invoke(); root.update()
                self.assertEqual((app.date_format,app.time_format),('DD/MM/YYYY','24-hour'))
                window,boxes,buttons=dialog(); boxes[0].current(0)
                next(b for b in buttons if b.cget('text')=='Cancel').invoke()
                self.assertEqual(app._settings()['date_display_format'],'DD/MM/YYYY')
                app._close_main_window()
                root=tk.Tk(); app=App(root)
                self.assertEqual((app.date_format,app.time_format),('DD/MM/YYYY','24-hour'))
                app._close_main_window()
                settings.write_text('{"poll_interval": 60}',encoding='utf-8')
                root=tk.Tk(); app=App(root)
                self.assertEqual((app.date_format,app.time_format),('YYYY-MM-DD','24-hour'))
                app._close_main_window()
