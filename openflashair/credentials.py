"""Small Windows-only DPAPI wrapper for local FlashAir mode profiles."""
from __future__ import annotations

import base64
import ctypes
import os
from ctypes import wintypes


class _Blob(ctypes.Structure):
    _fields_=[('cbData',wintypes.DWORD),('pbData',ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer=(ctypes.c_byte*len(data)).from_buffer_copy(data) if data else None
    return _Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)) if buffer else None),buffer


def protect_secret(value: str) -> str | None:
    """Return a user-bound DPAPI token; never fall back to plaintext storage."""
    if not value: return ''
    if os.name != 'nt': return None
    source,keepalive=_blob(value.encode('utf-8')); target=_Blob()
    try:
        ok=ctypes.windll.crypt32.CryptProtectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
        if not ok: return None
        try: return base64.b64encode(ctypes.string_at(target.pbData,target.cbData)).decode('ascii')
        finally: ctypes.windll.kernel32.LocalFree(target.pbData)
    except Exception: return None


def unprotect_secret(token: str | None) -> str | None:
    """Read a DPAPI token for the same Windows user; invalid tokens stay unavailable."""
    if token == '': return ''
    if not token or os.name != 'nt': return None
    try: encrypted=base64.b64decode(token.encode('ascii'),validate=True)
    except Exception: return None
    source,keepalive=_blob(encrypted); target=_Blob()
    try:
        ok=ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target))
        if not ok: return None
        try: return ctypes.string_at(target.pbData,target.cbData).decode('utf-8')
        finally: ctypes.windll.kernel32.LocalFree(target.pbData)
    except Exception: return None
