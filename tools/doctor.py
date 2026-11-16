#!/usr/bin/env python3
"""Report which host prerequisites are present (macOS or Linux).

Run before tools/setup.py. Exit status 1 when a required item is missing.
Debian/Ubuntu package names are given as hints; adapt them for other distributions."""
import glob
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import hostos  # noqa: E402


def have_exe(*names):
    return any(shutil.which(n) for n in names)


def have_module(name):
    return importlib.util.find_spec(name) is not None


def have_pkg_config(name):
    return shutil.which("pkg-config") is not None and \
        subprocess.run(["pkg-config", "--exists", name]).returncode == 0


def have_lib(pattern):
    return bool(glob.glob(f"/usr/lib/**/{pattern}", recursive=True) or
                glob.glob(f"/usr/lib64/**/{pattern}", recursive=True))


def have_sdk():
    try:
        hostos.ios_sdk()
        return True
    except SystemExit:
        return False


def have_hfsplus():
    try:
        return "hfsplus" in Path("/proc/filesystems").read_text() or \
            subprocess.run(["modinfo", "hfsplus"], capture_output=True).returncode == 0
    except OSError:
        return False


def have_ld64():
    return have_exe("ld64.lld") or bool(glob.glob("/usr/lib/llvm-*/bin/ld64.lld"))


def have_native_tools():
    names = ("iBoot64Patcher", "KPlooshFinder", "irecovery", "iproxy", "sshpass")
    return all((REPO / "tools/SSHRD_Script" / hostos.NATIVE_DIR / n).exists() for n in names)


# (label, check, required, hint)
COMMON = [
    ("python >= 3.9", lambda: sys.version_info >= (3, 9), True, "install a newer python3"),
    ("git", lambda: have_exe("git"), True, "apt install git"),
    ("make + C compiler", lambda: have_exe("make") and have_exe("cc", "gcc", "clang"), True,
     "apt install build-essential"),
    ("capstone (pip)", lambda: have_module("capstone"), True, "pip install -r requirements.txt"),
    ("SSHRD_Script tools (submodule)", have_native_tools, True,
     "git submodule update --init tools/SSHRD_Script"),
]
LINUX = [
    ("GNU tar", lambda: have_exe("tar"), True, "apt install tar"),
    ("xz (bootstrap archives)", lambda: have_exe("xz", "lzma"), True, "apt install xz-utils"),
    ("FUSE device", lambda: Path("/dev/fuse").exists(), True, "apt install fuse3; modprobe fuse"),
    ("apfs-fuse (read IPSW rootfs)", lambda: have_exe("apfs-fuse"), True,
     "build https://github.com/sgan81/apfs-fuse (cmake, libfuse3-dev, zlib1g-dev, libbz2-dev, libattr1-dev)"),
    ("dmg2img or 7z (DMG fallback)", lambda: have_exe("dmg2img", "7zz", "7z"), False,
     "apt install dmg2img p7zip-full  (7-Zip >= 23 reads LZFSE/ULFO images)"),
    ("7z (checkra1n loader DMG)", lambda: have_exe("7zz", "7z"), True, "apt install p7zip-full"),
    ("hfsplus kernel module", have_hfsplus, True, "modprobe hfsplus (needs root; used for the checkra1n overlay)"),
    ("ldid (Procursus)", lambda: have_exe("ldid"), True, "apt install ldid"),
    ("clang", lambda: have_exe("clang"), True, "apt install clang"),
    ("ld64.lld", have_ld64, True, "apt install lld"),
    ("iPhoneOS SDK", have_sdk, True, "export IPHONEOS_SDK=/path/to/iPhoneOS14.5.sdk (e.g. from theos/sdks)"),
    ("libusb-1.0 dev (gaster)", lambda: have_pkg_config("libusb-1.0"), True, "apt install libusb-1.0-0-dev"),
    ("OpenSSL dev (img4lib, gaster)", lambda: have_pkg_config("openssl"), True, "apt install libssl-dev"),
    ("xxd (gaster payloads)", lambda: have_exe("xxd"), True, "apt install xxd"),
    ("libBlocksRuntime (devicetree-parse)", lambda: have_lib("libBlocksRuntime.*"), True,
     "apt install libblocksruntime-dev"),
    ("aarch64 cross gcc + libc (kernel patch finder)",
     lambda: have_exe("aarch64-linux-gnu-gcc") and Path("/usr/aarch64-linux-gnu/include/stdio.h").exists(),
     True, "apt install gcc-aarch64-linux-gnu libc6-dev-arm64-cross"),
    ("qemu-aarch64 (runs the kernel patch finder)",
     lambda: have_exe("qemu-aarch64", "qemu-aarch64-static") or os.uname().machine in ("aarch64", "arm64"),
     True, "apt install qemu-user"),
    ("llvm-nm (reads Mach-O kernels)",
     lambda: have_exe("llvm-nm") or bool(glob.glob("/usr/lib/llvm-*/bin/llvm-nm")),
     True, "apt install llvm"),
    ("Pillow (wallpapers)", lambda: have_module("PIL"), True, "pip install pillow"),
    ("pillow-heif or heif-convert", lambda: have_module("pillow_heif") or have_exe("heif-convert", "magick", "convert"),
     True, "pip install pillow-heif  (or apt install libheif-examples)"),
    ("sudo or root", lambda: os.geteuid() == 0 or have_exe("sudo"), True, "the install stages need root"),
]
MAC = [
    ("Xcode + iPhoneOS SDK", have_sdk, True, "install Xcode and open it once"),
    ("codesign", lambda: have_exe("codesign"), True, "ships with macOS"),
    ("hdiutil", lambda: have_exe("hdiutil"), True, "ships with macOS"),
]


def main():
    checks = COMMON + (MAC if hostos.IS_MAC else LINUX)
    missing_required = 0
    width = max(len(label) for label, *_ in checks)
    print(f"Host: {'macOS' if hostos.IS_MAC else 'Linux'}  ({sys.platform})\n")
    for label, check, required, hint in checks:
        try:
            ok = bool(check())
        except Exception:
            ok = False
        status = "ok     " if ok else ("MISSING" if required else "missing")
        print(f"  [{status}] {label:<{width}}" + ("" if ok else f"  -> {hint}"))
        if not ok and required:
            missing_required += 1
    print()
    if missing_required:
        print(f"{missing_required} required item(s) missing.")
        return 1
    print("All required items present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
