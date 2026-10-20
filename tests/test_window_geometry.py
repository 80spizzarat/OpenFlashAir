import unittest
from pathlib import Path

from openflashair.gui import (
    WINDOWS_APP_USER_MODEL_ID,
    application_icon_path,
    clamp_menu_position,
    practical_window_geometry,
    usable_window_geometry,
)


class WindowGeometryTests(unittest.TestCase):
    WORK=(0,0,1400,900)

    def test_fresh_and_stale_narrow_startups_use_practical_default(self):
        fresh=practical_window_geometry(None,self.WORK)
        narrow=practical_window_geometry('560x700+0+0',self.WORK)
        self.assertEqual(fresh,narrow)
        self.assertTrue(fresh.startswith('1200x820+'))

    def test_valid_resized_geometry_is_restored(self):
        saved='1000x700+200+100'
        self.assertEqual(usable_window_geometry(saved,self.WORK),saved)
        self.assertEqual(practical_window_geometry(saved,self.WORK),saved)

    def test_offscreen_and_oversized_geometry_is_rejected(self):
        for value in ('1000x700+600+100','1500x700+0+0','1000x500+10+10','invalid'):
            self.assertIsNone(usable_window_geometry(value,self.WORK))

    def test_gear_dropdown_is_clamped_inside_the_work_area(self):
        self.assertEqual(clamp_menu_position(1380,880,180,160,self.WORK),(1220,740))
        self.assertEqual(clamp_menu_position(-30,-20,180,160,self.WORK),(0,0))

    def test_approved_icon_and_dedicated_windows_taskbar_identity_are_declared(self):
        icon=application_icon_path()
        self.assertEqual(icon.name, 'OpenFlashAir_icon_centered.ico')
        self.assertTrue(icon.is_file(), icon)
        self.assertEqual(WINDOWS_APP_USER_MODEL_ID, 'OpenFlashAir.P3-1A')


if __name__ == '__main__':
    unittest.main()
