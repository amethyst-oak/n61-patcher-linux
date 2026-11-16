#!/usr/bin/env python3
"""Fetch pinned upstream tools and build the ones that have no prebuilt binary.

macOS: builds img4 (CommonCrypto), devicetree-parse and gaster, uses the Darwin
binaries of SSHRD_Script and dualra1n.
Linux: uses their Linux binaries and builds img4 (OpenSSL), devicetree-parse
(clang -fblocks + libBlocksRuntime) and gaster (libusb) from source.
Run tools/doctor.py first to see which host packages are missing."""
from pathlib import Path
import configparser
import platform
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from core import hostos  # noqa: E402
from fetch_checkra1n import fetch as fetch_checkra1n  # noqa: E402


def run(*args, cwd=REPO):
    subprocess.run(args, cwd=cwd, check=True)


def exclude_built(submodule, rules):
    exclude = subprocess.check_output(
        ["git", "rev-parse", "--git-path", "info/exclude"], cwd=submodule, text=True
    ).strip()
    exclude = submodule / exclude
    current = exclude.read_text() if exclude.exists() else ""
    if rules not in current:
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(current + "\n" + rules)


def build_devicetree_parse(dtparse):
    if hostos.IS_MAC:
        run("make", "-C", str(dtparse), f"ARCH={platform.machine()}")
        return
    # The Makefile needs xcrun and Objective-C (repack.m). On Linux only the C parser
    # is built; tools/devicetree_repack.py replaces devicetree-repack.
    cmd = ["clang", "-O2", "-w", "-fblocks", "-D_GNU_SOURCE", "-include", "errno.h",
           "-Dgetprogname()=program_invocation_short_name",
           "-o", "devicetree-parse", "devicetree-parse.c", "parse.c", "-lBlocksRuntime"]
    try:
        run(*cmd, cwd=dtparse)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise SystemExit(f"Could not build devicetree-parse ({exc}). Install clang and "
                         "libblocksruntime-dev, then re-run tools/setup.py.")


def build_gaster(gaster, dualra1n):
    if hostos.IS_MAC:
        target = REPO / "tools/SSHRD_Script/Darwin/gaster"
        if not target.exists():
            run("make", "-C", str(gaster), "macos")
            exclude_built(gaster, "/gaster\n")
            shutil.copy2(gaster / "gaster", target)
        return
    target = REPO / "tools/bin/gaster"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        run("make", "-C", str(gaster), "libusb")
        exclude_built(gaster, "/gaster\n")
        shutil.copy2(gaster / "gaster", target)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        prebuilt = dualra1n / "binaries/Linux/gaster"
        if not prebuilt.exists():
            raise SystemExit(f"Could not build gaster ({exc}). Install libusb-1.0-0-dev, "
                             "libssl-dev, xxd and a C compiler.")
        print(f"gaster build failed ({exc}); using the prebuilt dualra1n Linux binary")
        shutil.copy2(prebuilt, target)
    target.chmod(0o755)


def setup():
    modules = configparser.ConfigParser()
    modules.read(REPO / ".gitmodules")
    for name in ("SSHRD_Script", "img4lib", "devicetree-parse", "DyldExtractor", "gaster"):
        run("git", "submodule", "update", "--init", f"tools/{name}")

    # Keep the tools checkout small; firmware stays in donors/.
    path = "tools/dualra1n"
    dualra1n = REPO / path
    run("git", "submodule", "init", path)
    if not (dualra1n / ".git").exists():
        url = modules['submodule "tools/dualra1n"']["url"]
        run("git", "clone", "--filter=blob:none", "--no-checkout", url, str(dualra1n))
    run("git", "sparse-checkout", "set", f"binaries/{hostos.NATIVE_DIR}", "binaries/.licenses",
        "other/apfsios14", cwd=dualra1n)
    entry = subprocess.check_output(
        ["git", "ls-files", "--stage", path], cwd=REPO, text=True
    )
    commit = entry.split()[1]
    run("git", "fetch", "--depth", "1", "origin", commit, cwd=dualra1n)
    run("git", "checkout", "--detach", commit, cwd=dualra1n)
    run("git", "submodule", "absorbgitdirs", path)

    img4lib = REPO / "tools/img4lib"
    run("git", "submodule", "update", "--init", "lzfse", cwd=img4lib)
    run("make", "-C", str(img4lib / "lzfse"))
    if hostos.IS_MAC:
        run("make", "-C", str(img4lib), "COMMONCRYPTO=1")
    else:
        run("make", "-C", str(img4lib))   # OpenSSL (libssl-dev)
    dtparse = REPO / "tools/devicetree-parse"
    build_devicetree_parse(dtparse)
    exclude_built(dtparse, "*.o\n/devicetree-parse\n/devicetree-repack\n")
    (REPO / "tools/devicetree_repack.py").chmod(0o755)

    # sshrd.sh downloads gaster only when this path is missing; that download is unreliable.
    build_gaster(REPO / "tools/gaster", dualra1n)

    apfs14 = REPO / "donors/projects/dualra1n-bin/apfsios14"
    if not apfs14.exists():
        shutil.copytree(dualra1n / "other/apfsios14", apfs14, symlinks=True)
    fetch_checkra1n()

    run(sys.executable, "-m", "pip", "install", "-q", "--target", "tools/bin/pydeps",
        "progressbar2", "typing_extensions")
    print(f"Tools ready: tools/SSHRD_Script/{hostos.NATIVE_DIR}, "
          f"tools/dualra1n/binaries/{hostos.NATIVE_DIR}, tools/img4lib/img4, donors/")


if __name__ == "__main__":
    setup()
