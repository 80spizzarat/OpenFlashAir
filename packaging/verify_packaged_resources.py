"""Fail closed if a packaged OpenFlashAir bundle lacks shipped runtime assets."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = PROJECT_ROOT / "openflashair"
RUNTIME_ASSET_DIR = Path("assets")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_assets() -> list[Path]:
    root = SOURCE_PACKAGE / RUNTIME_ASSET_DIR
    if not root.is_dir():
        raise FileNotFoundError(f"Source runtime asset directory is missing: {root}")
    files = sorted(path.relative_to(SOURCE_PACKAGE) for path in root.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError(f"Source runtime asset directory is empty: {root}")
    return files


def verify(bundle_root: Path) -> list[str]:
    """Return all completeness errors for the supplied PyInstaller bundle."""
    package_root = bundle_root / "_internal" / "openflashair"
    errors: list[str] = []
    for relative in expected_assets():
        source = SOURCE_PACKAGE / relative
        packaged = package_root / relative
        if not packaged.is_file():
            errors.append(f"Missing packaged asset: {packaged}")
        elif sha256(source) != sha256(packaged):
            errors.append(f"Packaged asset differs from source: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="PyInstaller application directory containing _internal")
    args = parser.parse_args()
    errors = verify(args.bundle)
    if errors:
        print("Packaged-resource verification failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"Packaged-resource verification passed ({len(expected_assets())} runtime assets).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
