# Building the Windows application

This candidate was built on 64-bit Windows with CPython 3.12.14, PyInstaller 6.22.3, pyinstaller-hooks-contrib 2026.8, Pillow 13.0.0, six 1.17.0, pywin32-ctypes 0.2.3, pefile 2024.8.26, altgraph 0.17.5 and setuptools 84.0.0; Inno Setup 6 compiles the installer. These versions are an inventory, not a hash-locked reproducibility guarantee.

Install build dependencies in an isolated environment. From the source directory run:

```powershell
./packaging/build.ps1 -ReleaseLabel 0.1.0 -Python <path-to-python.exe> -PystraySource (Resolve-Path ./vendor/pystray).Path
& <path-to-ISCC.exe> ./packaging/OpenFlashAir-0.1.0.iss
```

The LGPL-covered pystray 0.19.5 source is in `vendor/pystray`. The build excludes it from the frozen Python archive and copies it to `_internal/pystray`, where a user may replace it with an interface-compatible modified version. Retain its copyright notices, LGPL/GPL texts, and applicable build and distribution materials. Running the resulting executable from protected Program Files may require administrator permission to replace files; a writable copy can be used for testing modifications.
