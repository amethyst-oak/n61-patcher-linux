#!/usr/bin/env python3
"""Extract the checkra1n 0.12.4 userland from the official DMG into donors/checkra1n."""
import hashlib
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zlib

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from core import hostos  # noqa: E402

DEST = REPO / "donors/checkra1n"
SHA256 = "754bb6ec4747b2e700f01307315da8c9c32c8b5816d0fe1e91d1bdfc298fe07b"
URL = f"https://assets.checkra.in/downloads/macos/{SHA256}/checkra1n%20beta%200.12.4.dmg"
BINARY = "checkra1n.app/Contents/MacOS/checkra1n"
# Raw ramdisk files inside the pinned binary: (path, offset, size).
RAMDISK_FILES = (
    ("patch_dyld.bridgeos", 0x63cd3b, 56336),
    ("patch_dyld.ios", 0x64ad3b, 56336),
    ("patch_dyld.tvos", 0x658d3b, 56336),
    ("payload", 0x666d3b, 116768),
    ("payload.dylib", 0x683d3b, 52608),
    ("sbin/launchd", 0x690d3b, 35168),
    ("usr/lib/dyld", 0x699d3b, 50560),
)
RAMDISK_DIRS = ("binpack/lib", "dev")
UDIF_ZERO = (0, 2)
UDIF_ZLIB = 0x80000005
UDIF_END = 0xffffffff


def mounted(image, raw=False, markers=()):
    """Mount/unpack an HFS+ image; see core.hostos.open_hfs_image for the Linux strategy."""
    return hostos.open_hfs_image(image, raw=raw, markers=markers)


def overlay_image(blob):
    """Rebuild the raw HFSX image from the UDIF stream embedded in the binary."""
    koly = blob.index(b"koly")
    data_size = struct.unpack(">Q", blob[koly + 32:koly + 40])[0]
    xml_size = struct.unpack(">Q", blob[koly + 224:koly + 232])[0]
    sectors = struct.unpack(">Q", blob[koly + 492:koly + 500])[0]
    base = koly - xml_size - data_size
    image = bytearray(sectors * 512)
    table = plistlib.loads(blob[koly - xml_size:koly])["resource-fork"]["blkx"]
    for partition in table:
        mish = partition["Data"]
        start = struct.unpack(">Q", mish[8:16])[0]
        for i in range(struct.unpack(">I", mish[200:204])[0]):
            kind, _, sector, count, offset, size = struct.unpack(
                ">IIQQQQ", mish[204 + i * 40:244 + i * 40])
            if kind == UDIF_END or kind in UDIF_ZERO:
                continue
            if kind != UDIF_ZLIB:
                raise SystemExit(f"Unsupported UDIF block type: {kind:#x}")
            at = (start + sector) * 512
            image[at:at + count * 512] = zlib.decompress(blob[base + offset:base + offset + size])
    return image


def obtain_dmg(dmg):
    """Copy a user-supplied DMG (N56_CHECKRA1N_DMG) or download it, trying urllib, curl, wget."""
    local = os.environ.get("N56_CHECKRA1N_DMG")
    if local:
        shutil.copyfile(local, dmg)
        return
    errors = []
    try:
        with urllib.request.urlopen(URL, timeout=60) as source, open(dmg, "wb") as output:
            shutil.copyfileobj(source, output)
        return
    except Exception as exc:  # network blocks and TLS resets show up as many exception types
        errors.append(f"urllib: {exc}")
    for cmd in (["curl", "-fL", "--retry", "3", "-o", str(dmg), URL],
                ["wget", "-O", str(dmg), URL]):
        if shutil.which(cmd[0]):
            if subprocess.run(cmd).returncode == 0 and Path(dmg).exists() and Path(dmg).stat().st_size:
                return
            errors.append(f"{cmd[0]} failed")
    raise SystemExit(
        "Could not download the checkra1n DMG (" + "; ".join(errors) + ").\n"
        "Download it another way (browser, VPN) from:\n  " + URL + "\n"
        "then run:  N56_CHECKRA1N_DMG=/path/to/the.dmg python3 tools/setup.py")


def fetch(dest=DEST):
    if all((dest / name).is_dir() for name in ("overlay-files", "ramdisk-files", "loader.app")):
        return
    print("Downloading and extracting checkra1n 0.12.4…")
    partial = dest.with_name(dest.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    with tempfile.TemporaryDirectory() as tmp:
        dmg = Path(tmp) / "checkra1n.dmg"
        obtain_dmg(dmg)
        if hashlib.sha256(dmg.read_bytes()).hexdigest() != SHA256:
            raise SystemExit("checkra1n DMG SHA-256 mismatch")
        with mounted(dmg, markers=("checkra1n.app",)) as volume:
            blob = (volume / BINARY).read_bytes()

        ramdisk = partial / "ramdisk-files"
        for name in RAMDISK_DIRS:
            (ramdisk / name).mkdir(parents=True)
        for name, offset, size in RAMDISK_FILES:
            path = ramdisk / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob[offset:offset + size])
            path.chmod(0o755)

        image = Path(tmp) / "overlay.img"
        image.write_bytes(overlay_image(blob))
        # terminfo has case-only name collisions; they merge on case-insensitive volumes.
        with mounted(image, raw=True) as volume:
            shutil.copytree(volume, partial / "overlay-files", symlinks=True, dirs_exist_ok=True)
        with mounted(partial / "overlay-files/loader.dmg", markers=("Applications/loader.app",)) as volume:
            shutil.copytree(volume / "Applications/loader.app", partial / "loader.app", symlinks=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(partial, dest)


if __name__ == "__main__":
    fetch()
