"""Offline checks for the host-OS layer (core/hostos.py, core/codesign.py, devicetree_repack).

These run on any host. They cannot prove that a Linux-built install boots on a
device; they check that the pieces we replaced are internally consistent.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import codesign, hostos  # noqa: E402


def load_repack():
    spec = importlib.util.spec_from_file_location("devicetree_repack", ROOT / "tools/devicetree_repack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DetachedSignatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "mrm.plist"
        # 2.5 pages so the last page is partial.
        self.path.write_bytes(os.urandom(4096 * 2 + 2048))

    def test_structure_and_page_hashes(self):
        blob = codesign.make_detached_signature(self.path)
        parts = codesign.parse_superblob(blob)
        self.assertEqual(sorted(parts), [codesign.CSSLOT_CODEDIRECTORY,
                                         codesign.CSSLOT_ALTERNATE_CODEDIRECTORIES])
        primary = codesign.parse_code_directory(parts[0])
        alternate = codesign.parse_code_directory(parts[0x1000])
        self.assertEqual((primary["hash_type"], alternate["hash_type"]), (1, 2))
        for info in (primary, alternate):
            self.assertEqual(info["identifier"], "mrm.plist")
            self.assertEqual(info["page_log2"], 12)
            self.assertEqual(info["code_limit"], self.path.stat().st_size)
            self.assertEqual(info["n_code"], 3)
            self.assertEqual(info["flags"] & codesign.CS_ADHOC, codesign.CS_ADHOC)
            self.assertEqual(info["length"], len(parts[0] if info is primary else parts[0x1000]))
        data = self.path.read_bytes()
        self.assertEqual(alternate["code_hashes"][2], hashlib.sha256(data[8192:]).digest())
        self.assertEqual(primary["code_hashes"][0], hashlib.sha1(data[:4096]).digest())
        self.assertTrue(codesign.verify_detached_signature(self.path, blob))

    def test_cdhash_is_truncated_hash_of_sha256_directory(self):
        blob = codesign.make_detached_signature(self.path)
        directory = codesign.parse_superblob(blob)[0x1000]
        self.assertEqual(codesign.cdhash_from_signature(blob), hashlib.sha256(directory).digest()[:20])

    def test_tampering_is_detected(self):
        blob = codesign.make_detached_signature(self.path)
        data = bytearray(self.path.read_bytes())
        data[5000] ^= 1
        self.path.write_bytes(bytes(data))
        self.assertFalse(codesign.verify_detached_signature(self.path, blob))

    def test_sha256_only_goes_in_primary_slot(self):
        blob = codesign.make_detached_signature(self.path, digests=("sha256",))
        self.assertEqual(sorted(codesign.parse_superblob(blob)), [0])
        self.assertEqual(len(codesign.cdhash_from_signature(blob)), 20)

    def test_empty_file(self):
        empty = Path(self.tmp.name) / "empty"
        empty.write_bytes(b"")
        blob = codesign.make_detached_signature(empty)
        self.assertTrue(codesign.verify_detached_signature(empty, blob))

    @patch.dict(os.environ, {"N56_CODESIGN_BACKEND": "python"})
    def test_public_api_python_backend(self):
        sig = Path(self.tmp.name) / "mrm.plist.sig"
        codesign.detached_sign(self.path, sig)
        self.assertEqual(codesign.cdhash(self.path, detached=sig),
                         codesign.cdhash_from_signature(sig.read_bytes()))


def fake_macho(signature, fat=False):
    """Minimal arm64 Mach-O header with one LC_CODE_SIGNATURE pointing at `signature`."""
    code = b"\0" * 64
    lc = struct.pack("<IIII", codesign.LC_CODE_SIGNATURE, 16, 32 + 16 + len(code), len(signature))
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, codesign.CPU_TYPE_ARM64, 0, 2, 1, len(lc), 0, 0)
    thin = header + lc + code + signature
    if not fat:
        return thin
    # fat header with an x86_64 stub slice first and the arm64 slice second
    stub = b"\0" * 32
    offset_stub, offset_arm = 4096, 8192
    table = struct.pack(">II", 0xCAFEBABE, 2)
    table += struct.pack(">iiIII", 0x01000007, 3, offset_stub, len(stub), 12)
    table += struct.pack(">iiIII", codesign.CPU_TYPE_ARM64, 0, offset_arm, len(thin), 12)
    out = bytearray(offset_arm + len(thin))
    out[:len(table)] = table
    out[offset_stub:offset_stub + len(stub)] = stub
    out[offset_arm:] = thin
    return bytes(out)


class MachOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        source = Path(self.tmp.name) / "payload"
        source.write_bytes(os.urandom(5000))
        self.blob = codesign.make_detached_signature(source, identifier="com.example.tool")

    @patch.dict(os.environ, {"N56_CODESIGN_BACKEND": "python"})
    def test_thin_and_fat_cdhash(self):
        expected = codesign.cdhash_from_signature(self.blob)
        for fat in (False, True):
            path = Path(self.tmp.name) / f"bin{fat}"
            path.write_bytes(fake_macho(self.blob, fat=fat))
            self.assertEqual(codesign.macho_signature(path), self.blob)
            self.assertEqual(codesign.cdhash(path), expected)

    def test_unsigned_macho_has_no_signature(self):
        path = Path(self.tmp.name) / "plain"
        data = bytearray(fake_macho(self.blob))
        struct.pack_into("<I", data, 16, 0)      # ncmds = 0
        path.write_bytes(bytes(data))
        self.assertIsNone(codesign.macho_signature(path))

    def test_non_macho_is_ignored(self):
        path = Path(self.tmp.name) / "text"
        path.write_text("not a binary")
        self.assertIsNone(codesign.macho_signature(path))


class HostOsTests(unittest.TestCase):
    def test_native_path_maps_darwin_dirs_on_linux(self):
        with patch.object(hostos, "IS_MAC", False):
            self.assertEqual(hostos.native_path("tools/SSHRD_Script/Darwin/irecovery"),
                             "tools/SSHRD_Script/Linux/irecovery")
            self.assertEqual(hostos.native_path("tools/dualra1n/binaries/Darwin/kairos"),
                             "tools/dualra1n/binaries/Linux/kairos")
            self.assertEqual(hostos.native_path("tools/devicetree-parse/devicetree-repack"),
                             "tools/devicetree_repack.py")
            self.assertEqual(hostos.native_path("tools/img4lib/img4"), "tools/img4lib/img4")

    def test_native_path_is_identity_on_macos(self):
        with patch.object(hostos, "IS_MAC", True):
            for rel in ("tools/SSHRD_Script/Darwin/irecovery",
                        "tools/devicetree-parse/devicetree-repack"):
                self.assertEqual(hostos.native_path(rel), rel)

    def test_tar_flags(self):
        with patch.object(hostos, "IS_MAC", False), patch.object(hostos, "TAR", "tar"):
            cmd = hostos.tar_create(["-C", "/x", "."], uid=0, gid=0)
            self.assertEqual(cmd[0], "tar")
            self.assertIn("--owner=0", cmd)
            self.assertIn("--group=0", cmd)
            self.assertIn("--numeric-owner", cmd)
            self.assertNotIn("--uid", cmd)
            self.assertEqual(cmd[-3:], ["-C", "/x", "."])
            self.assertEqual(cmd[cmd.index("-cpf") + 1], "-")
        with patch.object(hostos, "IS_MAC", True), patch.object(hostos, "TAR", "/usr/bin/tar"):
            cmd = hostos.tar_create(["-C", "/x", "."], uid=0, gid=0, preserve=False)
            self.assertEqual(cmd[:8], ["/usr/bin/tar", "--no-xattrs", "--uid", "0", "--gid", "0", "-cf", "-"])
            plain = hostos.tar_create(["-C", "/x", "."], mac_no_xattrs=False)
            self.assertEqual(plain, ["/usr/bin/tar", "-cpf", "-", "-C", "/x", "."])

    def test_find_root_descends_into_volume_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Volume/Applications/loader.app").mkdir(parents=True)
            self.assertEqual(hostos._find_root(tmp, ("Applications/loader.app",)), Path(tmp) / "Volume")

    def test_fix_exec_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "loader"
            script = Path(tmp) / "run.sh"
            data = Path(tmp) / "Info.plist"
            binary.write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 8)
            script.write_text("#!/bin/sh\n")
            data.write_text("<plist/>")
            for path in (binary, script, data):
                path.chmod(0o600)
            hostos._fix_exec_bits(tmp)
            self.assertEqual(binary.stat().st_mode & 0o777, 0o755)
            self.assertEqual(script.stat().st_mode & 0o777, 0o755)
            self.assertEqual(data.stat().st_mode & 0o777, 0o644)


def read_node(data, offset=0):
    """Independent mini parser for the DeviceTree binary format."""
    n_props, n_children = struct.unpack_from("<II", data, offset)
    offset += 8
    props = []
    for _ in range(n_props):
        name = data[offset:offset + 32].split(b"\0", 1)[0].decode()
        length, flags = struct.unpack_from("<HH", data, offset + 32)
        offset += 36
        props.append((name, flags, data[offset:offset + length]))
        offset += (length + 3) & ~3
    children = []
    for _ in range(n_children):
        child, offset = read_node(data, offset)
        children.append(child)
    return (props, children), offset


class DeviceTreeRepackTests(unittest.TestCase):
    def test_round_trip(self):
        repack = load_repack()
        document = {"device-tree": [
            {"name": "compatible", "length": 11, "flags": 0, "value": "N61AP\\x00iPh"},
            {"name": "#size-cells", "length": 4, "flags": 0, "value": 2},
            {"name": "big", "length": 8, "value": 0x1122334455667788},
            {"name": "short", "length": 1, "value": 255},
            {"name": "empty", "length": 6, "flags": 0},
            {"name": "placeholder", "length": 4, "flags": 0x8000, "value": ""},
            [{"name": "name", "length": 4, "value": "cpu"}, [{"name": "leaf", "length": 2, "value": 513}]],
            [{"name": "name", "length": 3, "value": "bt"}],
        ]}
        data = repack.repack(document)
        (props, children), end = read_node(data)
        self.assertEqual(end, len(data))
        got = {name: (flags, value) for name, flags, value in props}
        self.assertEqual(got["compatible"][1], b"N61AP\x00iPh\x00\x00"[:11])
        self.assertEqual(got["#size-cells"][1], struct.pack("<I", 2))
        self.assertEqual(got["big"][1], struct.pack("<Q", 0x1122334455667788))
        self.assertEqual(got["short"][1], b"\xff")
        self.assertEqual(got["empty"][1], b"\0" * 6)
        self.assertEqual(got["placeholder"][0], 0x8000)
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0][0][0][2], b"cpu\0"[:4])
        self.assertEqual(children[0][1][0][0][0][2], struct.pack("<H", 513))
        # every property is padded to four bytes
        self.assertEqual(len(data) % 4, 0)

    def test_trailing_commas_are_accepted(self):
        repack = load_repack()
        text = '{"device-tree": [{"name": "a", "length": 4, "value": 1,},],}'
        document = repack.load_json(text)
        (props, _), _ = read_node(repack.repack(document))
        self.assertEqual(props[0][2], struct.pack("<I", 1))

    def test_rejects_unhandled_int_width(self):
        repack = load_repack()
        with self.assertRaises(ValueError):
            repack.pack_property({"name": "x", "length": 3, "value": 1})

    def test_cli(self):
        repack = load_repack()
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "dt.json", Path(tmp) / "dt.bin"
            src.write_text(json.dumps({"device-tree": [{"name": "n", "length": 4, "value": 7}]}))
            self.assertEqual(repack.main(["x", str(src), str(out)]), 0)
            self.assertEqual(len(out.read_bytes()), 8 + 36 + 4)


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow not installed")
class WallpaperTests(unittest.TestCase):
    @unittest.skipIf(hostos.IS_MAC, "macOS uses sips")
    def test_crop_resample_and_quality(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / "wall.png", Path(tmp) / "wall.jpg"
            Image.new("RGB", (1634, 1634), (200, 30, 30)).save(source)
            hostos.heic_to_jpeg(source, dest, crop=(1634, 919), resample=(1334, 750))
            self.assertEqual(dest.read_bytes()[:2], b"\xff\xd8")
            with Image.open(dest) as image:
                self.assertEqual(image.size, (750, 1334))
            thumb = Path(tmp) / "thumb.jpg"
            hostos.heic_to_jpeg(source, thumb)
            with Image.open(thumb) as image:
                self.assertEqual(image.size, (1634, 1634))


if __name__ == "__main__":
    unittest.main()
