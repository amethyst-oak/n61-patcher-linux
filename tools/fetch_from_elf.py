#!/usr/bin/env python3
"""Build donors/checkra1n from a Linux checkra1n 0.12.4 ELF instead of the macOS DMG.

Put this file in n61-patcher/tools/ and run:
    python3 tools/fetch_from_elf.py /usr/bin/checkra1n
then run tools/setup.py again (it skips the download when donors/checkra1n is complete).

The offsets were derived from the Mach-O headers found in the binary with
sha256 dac9968939ea6e6bfbdedeb41d7e2579c4711dc2c5083f91dced66ca397dc51d.
Unverified against the macOS DMG: the script checks Mach-O magic and sizes, nothing more."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO))
import fetch_checkra1n as fc  # noqa: E402

ELF_SHA256 = "dac9968939ea6e6bfbdedeb41d7e2579c4711dc2c5083f91dced66ca397dc51d"
# Same relative layout as fc.RAMDISK_FILES; only the base differs.
SHIFT = 0x63cd3b - 0x438b8


def main(path):
    blob = Path(path).read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != ELF_SHA256:
        raise SystemExit(f"Unexpected binary (sha256 {digest}); offsets were derived for {ELF_SHA256}.")
    dest = fc.DEST
    partial = dest.with_name(dest.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)

    ramdisk = partial / "ramdisk-files"
    for name in fc.RAMDISK_DIRS:
        (ramdisk / name).mkdir(parents=True)
    for name, offset, size in fc.RAMDISK_FILES:
        start = offset - SHIFT
        data = blob[start:start + size]
        if data[:4] != bytes.fromhex("cffaedfe"):
            raise SystemExit(f"{name}: no Mach-O header at {start:#x}")
        target = ramdisk / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755)
        print(f"  {name:22} {start:#9x} {size:7}")

    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "overlay.img"
        image.write_bytes(fc.overlay_image(blob))
        with fc.mounted(image, raw=True) as volume:
            shutil.copytree(volume, partial / "overlay-files", symlinks=True, dirs_exist_ok=True)
        with fc.mounted(partial / "overlay-files/loader.dmg",
                        markers=("Applications/loader.app",)) as volume:
            shutil.copytree(volume / "Applications/loader.app", partial / "loader.app", symlinks=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(dest, ignore_errors=True)
    partial.replace(dest)
    print("Done:", dest)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
