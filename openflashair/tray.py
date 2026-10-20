"""Windows notification-area support, isolated from Tk's main thread."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import os


def _checked_windows_icon_class(icon_class, on_failure):
    """Reject a tray start when Windows Shell_NotifyIcon(NIM_ADD) fails.

    pystray 0.19.5's Windows backend discards that API's return value. Keep
    its normal event loop and menu implementation, but check the initial add.
    """
    import ctypes
    from pystray._util import win32

    class CheckedIcon(icon_class):
        def _show(self):
            self._assert_icon_handle()
            data=win32.NOTIFYICONDATAW(
                cbSize=ctypes.sizeof(win32.NOTIFYICONDATAW), hWnd=self._hwnd,
                hID=id(self), uFlags=win32.NIF_MESSAGE | win32.NIF_ICON | win32.NIF_TIP,
                uCallbackMessage=win32.WM_NOTIFY, hIcon=self._icon_handle, szTip=self.title)
            if not win32.Shell_NotifyIcon(win32.NIM_ADD, data):
                on_failure('tray_failed')
                raise OSError('Windows did not register the notification icon')
    return CheckedIcon


class TrayController:
    """Own one pystray icon and report actions through a thread-safe callback."""

    def __init__(self, icon_path: Path, action: Callable[[str], None], title: str = "OpenFlashAir"):
        self.icon_path = Path(icon_path)
        self._action = action
        self._title = title
        self._icon = None
        self._auto = False
        self._scanning = False

    @property
    def running(self) -> bool:
        return self._icon is not None

    def start(self) -> bool:
        """Create the icon, returning False rather than hiding the app on failure."""
        if self._icon is not None:
            if getattr(self._icon, 'visible', False):
                self._action('tray_ready')
            return True
        try:
            import pystray
            from PIL import Image

            with Image.open(self.icon_path) as source:
                image = source.convert("RGBA").copy()
            menu = pystray.Menu(
                pystray.MenuItem("Open OpenFlashAir", self._queue("restore"), default=True),
                pystray.MenuItem("Scan Now", self._queue("scan"), enabled=lambda _item: not self._auto and not self._scanning),
                pystray.MenuItem(lambda _item: 'Pause Auto Scan' if self._auto else 'Resume Auto Scan', self._queue("toggle_auto"), enabled=lambda _item: self._auto or not self._scanning),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self._queue("exit")),
            )
            icon_class = _checked_windows_icon_class(pystray.Icon, self._action) if os.name == 'nt' else pystray.Icon
            icon = icon_class("OpenFlashAir", image, self._title, menu)
            self._icon = icon
            def setup(started_icon):
                try:
                    started_icon.visible = True
                except Exception:
                    self._action('tray_failed')
                else:
                    self._action('tray_ready')
            icon.run_detached(setup=setup)
            return True
        except Exception:
            self._icon = None
            return False

    def _queue(self, action: str):
        def callback(_icon, _item):
            self._action(action)
        return callback

    def set_title(self, title: str) -> None:
        self._title = title
        if self._icon is not None:
            self._icon.title = title

    def set_state(self, auto: bool, scanning: bool) -> None:
        if (self._auto,self._scanning) == (auto,scanning): return
        self._auto,self._scanning=auto,scanning
        if self._icon is not None: self._icon.update_menu()

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
