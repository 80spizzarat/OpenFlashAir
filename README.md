# OpenFlashAir

OpenFlashAir is a Windows application for browsing and downloading photographs from Toshiba FlashAir cards. It provides manual and automatic synchronization, a thumbnail gallery, prioritized selections, photo previews and metadata, and locally mounted card connection settings.

## Compatibility

- FlashAir W-04: tested by the owner.
- W-03: expected to be compatible, but not tested.
- W-02 and W-01: compatibility unknown.
- Windows: see the installation guide. Specific supported versions have not yet been established.
- Linux and macOS are not currently supported; community ports are welcome.

Download the Windows installer from the project's GitHub Releases page once published. The installer is unsigned; Windows SmartScreen or antivirus software may show a warning. Verify its origin and compare its SHA-256 checksum with the release listing before deciding whether to run it. A checksum alone does not authenticate the publisher. See [USER-GUIDE.md](USER-GUIDE.md) for setup and safety guidance and [RELEASE-NOTES.md](RELEASE-NOTES.md) for the candidate's status.

Application code is available under the [MIT License](LICENSE); see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) for separate dependency terms and unresolved native-library review. OpenFlashAir is an independent project; affiliation with Toshiba or Kioxia is not implied.

## Run from source on Windows

Install 64-bit Python 3.12 with Tcl/Tk support from [python.org](https://www.python.org/downloads/windows/), then run in PowerShell from this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install "Pillow>=10" "pystray==0.19.5"
.\.venv\Scripts\python.exe run_openflashair.py
```

Python 3.12 was used for qualification; other versions have not been qualified. Keep `openflashair/assets` alongside the source. See [BUILDING.md](BUILDING.md) for Windows packaging and replaceable pystray instructions.
