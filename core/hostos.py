"""Host-OS differences in one place.

The patcher was written on macOS. Everything that depends on the host (mounting
DMGs, tar flavour, building iOS binaries, image conversion, per-OS tool paths)
goes through this module so Linux can supply equivalents. On macOS every
function does what the original inline code did.

Linux needs: apfs-fuse (or dmg2img/7z plus apfs-fuse) to read the IPSW rootfs
images, ldid, clang with ld64.lld plus an iPhoneOS SDK, and Pillow (with
pillow-heif) or heif-convert/ImageMagick. tools/doctor.py reports what is missing.
"""
import contextlib
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import log

IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
NATIVE_DIR = "Darwin" if IS_MAC else "Linux"
TAR = "/usr/bin/tar" if IS_MAC else (shutil.which("tar") or "tar")


# Tools with no Linux build that have a drop-in replacement in this repository.
LINUX_REPLACEMENTS = {
    "tools/devicetree-parse/devicetree-repack": "tools/devicetree_repack.py",
}


def native_path(rel):
    """Map a repository-relative tool path from its Darwin directory to this host's."""
    rel = str(rel)
    if IS_MAC:
        return rel
    if rel in LINUX_REPLACEMENTS:
        return LINUX_REPLACEMENTS[rel]
    return "/".join("Linux" if part == "Darwin" else part for part in rel.split("/"))


def need(tool, hint):
    """Return the path of an executable, or stop with an install hint."""
    path = shutil.which(tool)
    if not path:
        log.die(f"Missing host tool '{tool}'. {hint}")
    return path


def privileged(cmd):
    """Prefix a command with sudo when not already root (Linux mounts need it)."""
    if os.geteuid() == 0:
        return list(cmd)
    if not shutil.which("sudo"):
        log.die(f"'{cmd[0]}' needs root; re-run as root or install sudo")
    return ["sudo", *cmd]


# ---- tar ---------------------------------------------------------------------
def tar_create(args, uid=None, gid=None, preserve=True, mac_no_xattrs=True):
    """Command line for a tar stream to stdout.

    uid/gid force ownership of the archived entries (macOS --uid/--gid, GNU
    --owner/--group). Linux always uses --numeric-owner and never stores
    xattrs/ACLs so the device-side extraction matches what bsdtar produced.
    """
    cmd = [TAR]
    if IS_MAC:
        if mac_no_xattrs:
            cmd.append("--no-xattrs")
        if uid is not None:
            cmd += ["--uid", str(uid)]
        if gid is not None:
            cmd += ["--gid", str(gid)]
    else:
        cmd += ["--no-xattrs", "--no-acls", "--no-selinux", "--numeric-owner"]
        if uid is not None:
            cmd.append(f"--owner={uid}")
        if gid is not None:
            cmd.append(f"--group={gid}")
    cmd.append("-cpf" if preserve else "-cf")
    cmd.append("-")
    return cmd + list(args)


def decompress_stream_cmd(archive):
    """Command that writes the decompressed tar stream of a .tar.lzma/.tar.xz to stdout."""
    if IS_MAC:
        return ["/usr/bin/bsdtar", "-cf", "-", f"@{archive}"]
    for tool, args in (("xz", ["-dc"]), ("lzma", ["-dc"]), ("unlzma", ["-c"])):
        if shutil.which(tool):
            return [tool, *args, str(archive)]
    log.die("Missing 'xz' (package xz-utils) to unpack the checkra1n bootstrap archives")


# ---- DMG / image mounting ------------------------------------------------------
def _wait_mounted(mountpoint, seconds=15):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if os.path.ismount(mountpoint):
            return True
        time.sleep(0.2)
    return False


def _dmg_to_raw(dmg, out):
    """Convert a UDIF image to a raw image for tools that cannot read UDIF."""
    for tool in ("dmg2img",):
        if shutil.which(tool):
            r = subprocess.run([tool, "-i", str(dmg), "-o", str(out)], capture_output=True, text=True)
            if r.returncode == 0 and Path(out).exists():
                return
            log.warn(f"{tool} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    for tool in ("7zz", "7z"):
        exe = shutil.which(tool)
        if not exe:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([exe, "e", "-y", f"-o{tmp}", str(dmg)], capture_output=True, text=True)
            parts = sorted(Path(tmp).glob("*"), key=lambda p: p.stat().st_size, reverse=True)
            if r.returncode == 0 and parts:
                shutil.move(str(parts[0]), str(out))
                return
        log.warn(f"{tool} could not unpack {dmg}")
    log.die("Cannot convert the DMG to a raw image: install dmg2img or p7zip/7zip with LZFSE support")


def attach_dmg(dmg, mountpoint):
    """Mount a read-only rootfs DMG (UDIF holding APFS) at mountpoint."""
    mountpoint = str(mountpoint)
    os.makedirs(mountpoint, exist_ok=True)
    if IS_MAC:
        subprocess.run(["hdiutil", "attach", "-readonly", "-owners", "on", "-nobrowse",
                        "-mountpoint", mountpoint, str(dmg)], check=True, capture_output=True)
        return
    fuse = need("apfs-fuse", "Build https://github.com/sgan81/apfs-fuse (needs fuse3, cmake, "
                             "zlib, bzip2, libattr dev packages).")
    errors = []
    for options in ("ro,allow_other", "ro"):
        r = subprocess.run([fuse, "-o", options, str(dmg), mountpoint], capture_output=True, text=True)
        if r.returncode == 0 and _wait_mounted(mountpoint):
            return
        errors.append((r.stderr or r.stdout).strip())
    # Fallback: some apfs-fuse builds cannot read ULFO (LZFSE) UDIF chunks, so
    # convert to a raw image first. This needs as much free disk as the volume.
    raw = Path(mountpoint).with_name(Path(mountpoint).name + ".raw.img")
    if not raw.exists():
        log.log(f"apfs-fuse could not read {Path(dmg).name} directly; converting to a raw image…")
        _dmg_to_raw(dmg, raw)
    for options in ("ro,allow_other", "ro"):
        r = subprocess.run([fuse, "-o", options, str(raw), mountpoint], capture_output=True, text=True)
        if r.returncode == 0 and _wait_mounted(mountpoint):
            return
        errors.append((r.stderr or r.stdout).strip())
    log.die(f"apfs-fuse could not mount {dmg}:\n" + "\n".join(e for e in errors if e)[-1200:])


def detach(mountpoint):
    mountpoint = str(mountpoint)
    if IS_MAC:
        subprocess.run(["hdiutil", "detach", mountpoint], capture_output=True)
        return
    for cmd in (["fusermount3", "-u", mountpoint], ["fusermount", "-u", mountpoint],
                ["umount", mountpoint]):
        if shutil.which(cmd[0]) and subprocess.run(cmd, capture_output=True).returncode == 0:
            return
    subprocess.run(privileged(["umount", "-l", mountpoint]), capture_output=True)


def mount_keeps_owners(mountpoint):
    """macOS can mount with 'noowners'; Linux FUSE always exposes the stored uid/gid."""
    if not IS_MAC:
        return True
    mounts = subprocess.run(["/sbin/mount"], check=True, capture_output=True, text=True).stdout
    line = next((l for l in mounts.splitlines() if f" on {mountpoint} " in l), "")
    return bool(line) and "noowners" not in line


def clone_file(source, dest):
    """Copy a (potentially huge) file; use an APFS clone on macOS when possible."""
    if IS_MAC and subprocess.run(["cp", "-c", str(source), str(dest)], capture_output=True).returncode == 0:
        return
    shutil.copyfile(source, dest)


def _find_root(base, markers):
    base = Path(base)
    if all((base / m).exists() for m in markers):
        return base
    for depth in (1, 2, 3):
        for candidate in base.glob("/".join(["*"] * depth)):
            if candidate.is_dir() and all((candidate / m).exists() for m in markers):
                return candidate
    return base


def _fix_exec_bits(root):
    """7-Zip does not restore Unix modes from HFS+; infer them for app bundles."""
    magics = (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"#!")
    for path in Path(root).rglob("*"):
        if path.is_symlink():
            continue
        if path.is_dir():
            path.chmod(0o755)
        elif path.is_file():
            with path.open("rb") as stream:
                head = stream.read(4)
            path.chmod(0o755 if head.startswith(magics) else 0o644)


@contextlib.contextmanager
def open_hfs_image(image, raw=False, markers=()):
    """Yield the root of an HFS+/HFSX image (UDIF .dmg, or a raw image with raw=True).

    macOS attaches it with hdiutil. Linux: a raw image is loop-mounted with the
    kernel hfsplus driver (keeps modes and symlinks; needs root or sudo); a UDIF
    image is unpacked with 7-Zip and exec bits are inferred.
    """
    tmp = tempfile.mkdtemp(prefix="n56-hfs-")
    mountpoint = os.path.join(tmp, "mnt")
    os.makedirs(mountpoint)
    mounted = False
    try:
        if IS_MAC:
            cmd = ["hdiutil", "attach", "-quiet", "-nobrowse", "-readonly", "-mountpoint", mountpoint]
            if raw:
                cmd += ["-imagekey", "diskimage-class=CRawDiskImage"]
            subprocess.run([*cmd, str(image)], check=True)
            mounted = True
            yield Path(mountpoint)
        elif raw:
            need("mount", "Install util-linux.")
            r = subprocess.run(privileged(["mount", "-t", "hfsplus", "-o", "loop,ro,force",
                                           str(image), mountpoint]), capture_output=True, text=True)
            if r.returncode:
                log.die("Could not loop-mount the HFS+ image (is the 'hfsplus' kernel module "
                        f"available?):\n{(r.stderr or r.stdout).strip()}")
            mounted = True
            yield Path(mountpoint)
        else:
            seven = shutil.which("7zz") or shutil.which("7z") or need(
                "7z", "Install p7zip-full or 7zip to unpack DMG files.")
            out = os.path.join(tmp, "x")
            r = subprocess.run([seven, "x", "-y", f"-o{out}", str(image)], capture_output=True, text=True)
            if r.returncode:
                log.die(f"7-Zip could not unpack {image}:\n{(r.stderr or r.stdout).strip()[-800:]}")
            root = _find_root(out, markers)
            _fix_exec_bits(root)
            yield root
    finally:
        if mounted:
            if IS_MAC:
                subprocess.run(["hdiutil", "detach", "-quiet", mountpoint])
            else:
                subprocess.run(privileged(["umount", mountpoint]), capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)


# ---- building iOS binaries -------------------------------------------------------
def ios_sdk():
    """Path of an iPhoneOS SDK."""
    if IS_MAC:
        return subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    for value in (os.environ.get("N56_IPHONEOS_SDK"), os.environ.get("IPHONEOS_SDK")):
        if value and os.path.isdir(value):
            return value
    patterns = ("~/theos/sdks/iPhoneOS*.sdk", "/opt/theos/sdks/iPhoneOS*.sdk",
                "/opt/iPhoneOS*.sdk", "/usr/share/iPhoneOS*.sdk")
    found = sorted(p for pattern in patterns for p in glob.glob(os.path.expanduser(pattern)))
    if found:
        return found[-1]
    log.die("No iPhoneOS SDK found. Set IPHONEOS_SDK to a directory like iPhoneOS14.5.sdk "
            "(for example from https://github.com/theos/sdks).")


def _ld64():
    exe = shutil.which("ld64.lld")
    if exe:
        return exe
    found = sorted(glob.glob("/usr/lib/llvm-*/bin/ld64.lld"))
    if found:
        return found[-1]
    log.die("Missing ld64.lld (package 'lld') to link iOS binaries on Linux.")


def compile_ios(source, output, min_version, opt="-O2"):
    """Compile a single C file for arm64 iOS; the caller signs the result."""
    sdk = ios_sdk()
    if IS_MAC:
        cmd = ["clang", "-arch", "arm64", "-isysroot", sdk, f"-miphoneos-version-min={min_version}",
               opt, str(source), "-o", str(output)]
    else:
        cmd = ["clang", f"--target=arm64-apple-ios{min_version}", "-arch", "arm64",
               "-isysroot", sdk, f"-fuse-ld={_ld64()}",
               "-Wl,-arch,arm64", "-Wl,-platform_version,ios,13.0,14.5",
               opt, str(source), "-o", str(output)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        log.die(f"Command failed({r.returncode}): {' '.join(cmd)}\n{r.stderr.decode(errors='replace')}")


# ---- image conversion --------------------------------------------------------------
def _open_image(path):
    from PIL import Image
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    try:
        image = Image.open(path)
        image.load()
        return image
    except Exception:
        pass
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "decoded.png")
        for cmd in (["heif-convert", str(path), png], ["magick", str(path), png],
                    ["convert", str(path), png]):
            if shutil.which(cmd[0]) and subprocess.run(cmd, capture_output=True).returncode == 0 \
                    and os.path.exists(png):
                image = Image.open(png)
                image.load()
                return image
    log.die(f"Cannot decode {path}: install pillow-heif (pip) or libheif-examples / ImageMagick with HEIC support")


def heic_to_jpeg(source, dest, crop=None, resample=None, quality=90):
    """HEIC/HEIF to JPEG. crop=(height, width) centre-crops first, resample=(height, width) resizes.

    macOS uses sips (ImageIO) exactly as before; Linux uses Pillow and keeps the ICC profile.
    """
    source, dest = str(source), str(dest)
    if IS_MAC:
        cmd = ["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality)]
        if crop:
            cmd += ["--cropToHeightWidth", str(crop[0]), str(crop[1])]
        if resample:
            cmd += ["--resampleHeightWidth", str(resample[0]), str(resample[1])]
        subprocess.run(cmd + [source, "--out", dest], check=True, stdout=subprocess.DEVNULL)
        return
    from PIL import Image
    image = _open_image(source)
    profile = image.info.get("icc_profile")
    if crop:
        height, width = crop
        w, h = image.size
        left = max((w - width) // 2, 0)
        top = max((h - height) // 2, 0)
        image = image.crop((left, top, left + min(width, w), top + min(height, h)))
    if resample:
        image = image.resize((resample[1], resample[0]), Image.LANCZOS)
    image = image.convert("RGB")
    extra = {"icc_profile": profile} if profile else {}
    image.save(dest, "JPEG", quality=quality, **extra)
