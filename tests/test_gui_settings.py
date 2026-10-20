import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from openflashair.gui import App, flashair_mode_display

def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class GuiSettingsTests(unittest.TestCase):
    def test_endpoint_and_destination_validation(self):
        self.assertTrue(App._valid_endpoint('http://openflashair/'))
        self.assertTrue(App._valid_endpoint('https://192.168.0.1/'))
        self.assertFalse(App._valid_endpoint('openflashair'))
        self.assertFalse(App._valid_endpoint('ftp://openflashair/'))
        self.assertTrue(App._valid_destination(str(Path.cwd().resolve())))
        self.assertFalse(App._valid_destination('relative-folder'))

    def test_restart_settings_persist_in_one_canonical_store(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'APPDATA': directory}):
            app = object.__new__(App)
            self.assertTrue(App._save_settings(app, endpoint='http://card/', destination=str(Path(directory)/'photos'), poll_interval=30, filename_template='{date}_{original}', filename_prefix='Trip'))
            restarted = object.__new__(App)
            self.assertEqual(App._settings(restarted)['endpoint'], 'http://card/')
            self.assertEqual(App._settings(restarted)['destination'], str(Path(directory)/'photos'))
            self.assertEqual(App._settings(restarted)['poll_interval'], 30)
            self.assertEqual(App._settings(restarted)['filename_template'], '{date}_{original}')

    def test_w04_mode_display_uses_actual_appmode_and_does_not_conflate_saved_selection(self):
        self.assertEqual(flashair_mode_display('4'),'Access Point / hotspot (auto start) — APPMODE=4')
        self.assertEqual(flashair_mode_display('5'),'Station / client (auto start) — APPMODE=5')
        self.assertEqual(flashair_mode_display('0'),'Access Point (manual start) — APPMODE=0')
        self.assertIn('Unsupported or missing',flashair_mode_display('9'))

    def test_connection_dialog_visibly_separates_saved_mode_from_pending_selection(self):
        try: root=tk.Tk()
        except tk.TclError as exc: self.skipTest(f'Real Tk is unavailable: {exc}')
        app=App(root)
        try:
            with tempfile.TemporaryDirectory() as directory:
                config=Path(directory)/'SD_WLAN'/'CONFIG'; config.parent.mkdir()
                config.write_text('APPMODE=4\nAPPSSID=card\nAPPNETWORKKEY=secret123\nVERSION=F00\n',encoding='ascii')
                with patch('openflashair.gui.ConfigEditor.detect_cards',return_value=[config]):
                    app.config_editor(); root.update(); root.update()
                dialog=next(child for child in root.winfo_children() if isinstance(child,tk.Toplevel))
                def variables(widget):
                    values=[]
                    try:
                        name=str(widget.cget('textvariable'))
                        if name: values.append(str(root.getvar(name)))
                    except (tk.TclError,ValueError): pass
                    for child in widget.winfo_children(): values.extend(variables(child))
                    return values
                displayed=variables(dialog)
                static_text=[]
                for widget in descendants(dialog):
                    try:
                        value=str(widget.cget('text'))
                        if value: static_text.append(value)
                    except (tk.TclError,ValueError):
                        pass
                self.assertIn('Current card mode',static_text)
                self.assertIn('Direct Connection (Card Hotspot)',displayed)
                self.assertIn('Creates a Wi-Fi network for this computer to join.',displayed)
                self.assertIn('Pending changes: None',displayed)
                button=next(widget for widget in descendants(dialog) if isinstance(widget,tk.Menubutton))
                self.assertEqual(button.cget('background'),'white')
                self.assertGreaterEqual(button.winfo_height(),38)
                entries=[widget for widget in descendants(dialog) if isinstance(widget,tk.Entry) and widget.winfo_class() == 'Entry']
                self.assertEqual(len(entries),4)
                self.assertTrue(all(entry.winfo_height() >= 38 for entry in entries if entry.winfo_ismapped()))
                menu=root.nametowidget(button.cget('menu'))
                self.assertEqual(menu.entrycget(0,'label'),'Direct Connection (Card Hotspot) (Current)')
                self.assertEqual(menu.entrycget(0,'state'),'disabled')
                self.assertEqual(menu.entrycget(1,'label'),'Client Mode')
                menu.invoke(1); root.update_idletasks()
                self.assertIn('Pending change: Switch to Client Mode',variables(dialog))
                self.assertEqual(menu.index('end'),3)  # includes separator and explicit revert action
                menu.invoke(3); root.update_idletasks()
                self.assertIn('Pending changes: None',variables(dialog))
                dialog.destroy()
        finally:
            app._close_main_window()

    def test_switching_client_to_hotspot_never_carries_client_credentials(self):
        try: root=tk.Tk()
        except tk.TclError as exc: self.skipTest(f'Real Tk is unavailable: {exc}')
        app=App(root)
        try:
            with tempfile.TemporaryDirectory() as directory:
                config=Path(directory)/'SD_WLAN'/'CONFIG'; config.parent.mkdir()
                source=b'APPMODE=5\nAPPNAME=card\nAPPSSID=upstream-network\nAPPNETWORKKEY=synthetic-client-key\nUNKNOWN=keep\n'
                config.write_bytes(source)
                with patch('openflashair.gui.ConfigEditor.detect_cards',return_value=[config]):
                    app.config_editor(); root.update(); root.update()
                dialog=next(child for child in root.winfo_children() if isinstance(child,tk.Toplevel))
                button=next(widget for widget in descendants(dialog) if isinstance(widget,tk.Menubutton)); menu=root.nametowidget(button.cget('menu'))
                entries=[widget for widget in descendants(dialog) if isinstance(widget,tk.Entry) and widget.winfo_class() == 'Entry']
                self.assertEqual(menu.entrycget(1,'state'),'disabled')
                menu.invoke(0); root.update_idletasks()
                self.assertEqual(entries[0].get(),'flashair')
                self.assertEqual(entries[1].get(),'')
                values=[]
                def collect(widget):
                    try:
                        name=str(widget.cget('textvariable'))
                        if name: values.append(str(root.getvar(name)))
                    except (tk.TclError,ValueError): pass
                    for child in widget.winfo_children(): collect(child)
                collect(dialog)
                self.assertIn('Hotspot name (SSID)',values)
                self.assertIn('Pending change: Switch to Direct Connection (Card Hotspot)',values)
                menu.invoke(3); root.update_idletasks()
                self.assertEqual(entries[0].get(),'upstream-network')
                self.assertEqual(entries[1].get(),'synthetic-client-key')
                self.assertEqual(config.read_bytes(),source)
                dialog.destroy()
        finally:
            app._close_main_window()


if __name__ == '__main__':
    unittest.main()
