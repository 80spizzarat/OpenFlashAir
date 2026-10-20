import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from openflashair.tray import TrayController, _checked_windows_icon_class
from openflashair.gui import App


class _FakeIcon:
    def __init__(self, name, image, title, menu):
        self.name, self.image, self.title, self.menu = name, image, title, menu
        self.started = self.stopped = False
    def run_detached(self, setup=None):
        self.started = True
        if setup: setup(self)
    def stop(self): self.stopped = True
    def update_menu(self): pass


class _FakeMenu:
    SEPARATOR = object()
    def __init__(self, *items): self.items = items


class _FakeMenuItem:
    def __init__(self, text, callback, default=False, enabled=True): self.text, self.callback, self.default, self.enabled = text, callback, default, enabled


class TrayControllerTests(unittest.TestCase):
    def _icon_file(self, directory):
        path = Path(directory) / 'tray.png'
        Image.new('RGBA', (16, 16), '#008000').save(path)
        return path

    def test_start_actions_tooltip_and_exit_cleanup(self):
        actions=[]
        fake=types.SimpleNamespace(Icon=_FakeIcon, Menu=_FakeMenu, MenuItem=_FakeMenuItem)
        with TemporaryDirectory() as directory, patch.dict(sys.modules, {'pystray': fake}), patch('openflashair.tray._checked_windows_icon_class', side_effect=lambda cls, callback: cls):
            controller=TrayController(self._icon_file(directory), actions.append, 'OpenFlashAir — Paused')
            self.assertTrue(controller.start())
            self.assertTrue(controller.running)
            self.assertTrue(controller._icon.started)
            labels=[item.text for item in controller._icon.menu.items if hasattr(item, 'text')]
            self.assertEqual(labels[0:2], ['Open OpenFlashAir', 'Scan Now'])
            self.assertEqual(labels[2](None), 'Resume Auto Scan')
            self.assertTrue(controller._icon.menu.items[1].enabled(None))
            controller.set_state(True,False)
            self.assertFalse(controller._icon.menu.items[1].enabled(None))
            self.assertEqual(labels[2](None), 'Pause Auto Scan')
            controller._icon.menu.items[0].callback(None,None)
            controller._icon.menu.items[1].callback(None,None)
            controller._icon.menu.items[2].callback(None,None)
            controller._icon.menu.items[4].callback(None,None)
            self.assertEqual(actions, ['tray_ready','restore','scan','toggle_auto','exit'])
            controller.set_title('OpenFlashAir — Scanning')
            self.assertEqual(controller._icon.title, 'OpenFlashAir — Scanning')
            icon=controller._icon; controller.stop()
            self.assertFalse(controller.running); self.assertTrue(icon.stopped)

    def test_failed_start_leaves_no_running_icon(self):
        with TemporaryDirectory() as directory, patch.dict(sys.modules, {'pystray': None}):
            controller=TrayController(self._icon_file(directory), lambda _action: None)
            self.assertFalse(controller.start())
            self.assertFalse(controller.running)

    def test_delayed_initialization_failure_is_reported(self):
        class DelayedIcon(_FakeIcon):
            def run_detached(self, setup=None): self.setup = setup
            @property
            def visible(self): return False
            @visible.setter
            def visible(self, _value): raise RuntimeError('delayed failure')
        actions=[]
        fake=types.SimpleNamespace(Icon=DelayedIcon, Menu=_FakeMenu, MenuItem=_FakeMenuItem)
        with TemporaryDirectory() as directory, patch.dict(sys.modules, {'pystray': fake}), patch('openflashair.tray._checked_windows_icon_class', side_effect=lambda cls, callback: cls):
            controller=TrayController(self._icon_file(directory), actions.append)
            self.assertTrue(controller.start())
            self.assertEqual(actions, [])
            controller._icon.setup(controller._icon)
            self.assertEqual(actions, ['tray_failed'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows notification API')
    def test_windows_shell_registration_failure_is_not_ready(self):
        from pystray._util import win32
        class Base:
            _hwnd=0
            _icon_handle=0
            title='OpenFlashAir'
            def _assert_icon_handle(self): pass
        actions=[]
        icon=_checked_windows_icon_class(Base, actions.append)()
        with patch.object(win32, 'Shell_NotifyIcon', return_value=0):
            with self.assertRaisesRegex(OSError, 'did not register'):
                icon._show()
        self.assertEqual(actions, ['tray_failed'])
        with patch.object(win32, 'Shell_NotifyIcon', return_value=1):
            icon._show()

    def test_close_waits_for_active_transfer(self):
        class Status:
            def set(self, value): self.value = value
        app=types.SimpleNamespace(scanning=True, auto=True, status=Status(), _finish_close_main_window=lambda: self.fail('closed during transfer'))
        App._close_main_window(app)
        self.assertTrue(app._closing)
        self.assertFalse(app.auto)
        self.assertIn('Finishing', app.status.value)
        closed=[]
        app._finish_close_main_window=lambda: closed.append(True)
        App._finish_scan(app)
        self.assertEqual(closed, [True])
        self.assertFalse(app.scanning)


if __name__ == '__main__':
    unittest.main()
