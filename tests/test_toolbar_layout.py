import inspect
import tkinter as tk
from tkinter import ttk
import unittest

from openflashair.gui import App


class ToolbarLayoutTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Real Tk is unavailable: {exc}')
        self.root.geometry('900x700')
        self.app=App(self.root)
        self.root.geometry('900x700')
        self.root.deiconify()
        self.root.update()

    def tearDown(self):
        self.app._close_main_window()

    def test_gear_dropdown_and_state_aware_auto_button(self):
        self.assertFalse(self.root.cget('menu'))
        self.assertEqual(self.app.settings_button.grid_info()['row'],0)
        self.assertEqual(self.app.settings_button.grid_info()['column'],2)
        self.assertGreaterEqual(len(self.app.settings_button.find_withtag('gear')),2)
        self.assertTrue(self.app.settings_button.find_withtag('label'))
        self.assertGreaterEqual(self.app.settings_button.winfo_height(),38)
        labels=[self.app.settings_popup.entrycget(index,'label') for index in range(self.app.settings_popup.index('end')+1) if self.app.settings_popup.type(index) == 'command']
        self.assertEqual(labels[:3],['Check Connection','Filename Settings…','Edit FlashAir CONFIG…'])
        self.assertEqual(self.app.auto_control_button.cget('text'),'Start Auto Scan')
        self.app._auto_has_started=True; self.app._update_auto_control_label()
        self.assertEqual(self.app.auto_control_button.cget('text'),'Resume Auto Scan')
        self.app.auto=True; self.app._update_auto_control_label()
        self.assertEqual(self.app.auto_control_button.cget('text'),'Pause Auto Scan')

    def test_scan_controls_and_check_connection_are_not_a_sync_scan(self):
        labels=[self.app.scan_once_button.cget('text'),self.app.auto_control_button.cget('text')]
        self.assertEqual(labels,['Scan Once','Start Auto Scan'])
        self.assertEqual(self.app.auto_control_button.master,self.app.auto_scan_group)
        self.assertEqual(self.app.interval_box.grid_info()['row'],2)
        check_source=inspect.getsource(App.check)
        self.assertIn('FlashAirClient',check_source)
        self.assertNotIn('SyncEngine',check_source)
        self.assertNotIn('.discover(',check_source)

    def test_controls_remain_mapped_at_wide_and_narrow_sizes(self):
        for width in (900,560):
            self.root.geometry(f'{width}x700'); self.root.update()
            self.app._apply_header_layout(width)
            self.root.update_idletasks()
            for widget in (self.app.sync_box,self.app.auto_control_button,self.app.interval_box,self.app.gallery_actions,self.app.download_selected_button,self.app.pager):
                self.assertGreater(widget.winfo_reqwidth(),0)
            self.assertLessEqual(self.app.gallery_actions.winfo_reqwidth(),width)
        self.assertEqual(self.app.gallery_selection_label.grid_info()['row'],1)
        self.assertEqual(self.app.pager_controls.grid_info()['row'],1)
        self.app._apply_header_layout(900)
        self.assertEqual(self.app.gallery_selection_label.grid_info()['row'],0)
        self.assertEqual(self.app.pager_controls.grid_info()['row'],0)

    def test_top_connection_fields_visually_align_with_full_size_buttons(self):
        self.root.geometry('1200x850'); self.root.update()
        browse=next(widget for widget in self.app.winfo_children()
                    if widget.grid_info().get('row') == 1 and widget.grid_info().get('column') == 2)
        self.assertGreaterEqual(self.app.endpoint_entry.winfo_height(),browse.winfo_height()-5)
        self.assertGreaterEqual(self.app.destination_entry.winfo_height(),browse.winfo_height()-5)
        self.assertGreaterEqual(self.app.settings_button.winfo_width(),browse.winfo_width())

    def test_text_context_menu_obeys_editability_and_selection(self):
        for field in (self.app.endpoint_entry,self.app.destination_entry):
            field.configure(state='normal')
            field.delete(0,'end'); field.insert(0,'test value')
            field.selection_range(0,'end')
            menu=self.app._build_text_context_menu(field)
            self.assertEqual(menu.entrycget(0,'state'),'normal')
            self.assertEqual(menu.entrycget(1,'state'),'normal')
        entry=ttk.Entry(self.root); entry.insert(0,'endpoint'); entry.selection_range(0,'end')
        menu=self.app._build_text_context_menu(entry)
        self.assertEqual([menu.entrycget(i,'label') for i in (0,1,2,4)],['Cut','Copy','Paste','Select All'])
        self.assertEqual(menu.entrycget(0,'state'),'normal')
        self.assertEqual(menu.entrycget(1,'state'),'normal')
        entry.configure(state='readonly'); menu=self.app._build_text_context_menu(entry)
        self.assertEqual(menu.entrycget(0,'state'),'disabled')
        self.assertEqual(menu.entrycget(1,'state'),'normal')
        text=tk.Text(self.root); text.insert('1.0','diagnostic'); text.tag_add('sel','1.0','1.4')
        menu=self.app._build_text_context_menu(text)
        self.assertEqual(menu.entrycget(0,'state'),'normal')
        self.assertEqual(menu.entrycget(1,'state'),'normal')
        self.assertIn("root.bind_all('<Button-3>'",__import__('inspect').getsource(App._install_text_context_menus))
        # Filename Settings and CONFIG use ttk.Entry controls; the root-class
        # binding above applies the same menu to their dynamically created fields.
        source=__import__('inspect').getsource(App.filename_settings)+__import__('inspect').getsource(App.config_editor)
        self.assertIn('ttk.Entry',source)


if __name__ == '__main__':
    unittest.main()
