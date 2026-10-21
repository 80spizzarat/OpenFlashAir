"""Windows per-user-session single-instance coordination using kernel objects."""
import ctypes
import os
from ctypes import wintypes


class SingleInstance:
    def __init__(self):
        self.mutex = self.event = None
        self.primary = True
        if os.name != 'nt':
            return
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.SetEvent.argtypes = (wintypes.HANDLE,)
        kernel.SetEvent.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel = kernel
        self.event = kernel.CreateEventW(None, False, False, 'Local\\OpenFlashAir.Restore.v1')
        if not self.event:
            raise ctypes.WinError(ctypes.get_last_error())
        self.mutex = kernel.CreateMutexW(None, False, 'Local\\OpenFlashAir.SingleInstance.v1')
        if not self.mutex:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183
        if not self.primary and not kernel.SetEvent(self.event):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def restore_requested(self):
        return bool(self.event and self.kernel.WaitForSingleObject(self.event, 0) == 0)

    def close(self):
        for name in ('event', 'mutex'):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)
