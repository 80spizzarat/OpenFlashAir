# 0.1.1 build evidence — unverified

The candidate was built with CPython 3.12.14, PyInstaller 6.22.3 and Inno Setup 6.7.3. The PyInstaller invocation excluded numpy and frozen pystray, included six.moves, copied the external `vendor/pystray` source and application icon and assets, and used `run_openflashair.py` as entry point. The candidate installer specification is `packaging/OpenFlashAir-0.1.1-candidate.iss`.

The build invocation, run from the development project root using the listed interpreter and a local `work/packaging-tools` directory on `PYTHONPATH`, was:

```powershell
python -m PyInstaller --noconfirm --windowed --name OpenFlashAir --exclude-module numpy --exclude-module pystray --hidden-import six.moves --add-data "<project>/release-final-source/vendor/pystray;pystray" --icon "<project>/openflashair/OpenFlashAir_icon_centered.ico" --add-data "<project>/openflashair/OpenFlashAir_icon_centered.ico;openflashair" --add-data "<project>/openflashair/assets;openflashair/assets" --paths "<project>" --distpath "<project>/dist/OpenFlashAir-0.1.1-candidate" --workpath "<project>/work/pyinstaller-0.1.1-candidate" --specpath "<project>/work/pyinstaller-spec-0.1.1-candidate" "<project>/run_openflashair.py"
ISCC packaging/OpenFlashAir-0.1.1-candidate.iss
```

The Inno script references `release-final-source` for notices and license materials; those paths require adjustment for this standalone review tree. Application Python modules were compared against the accepted executable's embedded code objects and matched, and the reviewed Python files match those current inputs. This does not verify the launcher, all data, libraries or build environment, nor establish reproducibility. The dependency inventory and exact distribution rights remain incomplete.
