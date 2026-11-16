"""Ad-hoc code signing and cdhash helpers for macOS and Linux.

macOS keeps using /usr/bin/codesign with the exact arguments the original code
used. Linux has no codesign, so:

* detached signatures for flat files (the launchd mrm.plist cache) are built
  in pure Python: a SuperBlob holding ad-hoc CodeDirectories (SHA-1 primary,
  SHA-256 alternate, 4 KiB pages, like `codesign --digest-algorithm=sha1,sha256
  --pagesize 4096 --detached`);
* cdhashes are read straight from the CodeDirectory (Mach-O LC_CODE_SIGNATURE
  or a detached blob): the first 20 bytes of the hash of the SHA-256 directory;
* Mach-O binaries are signed with ldid (Procursus build, package `ldid`).

Set N56_CODESIGN_BACKEND=python on macOS to exercise the Linux code path and
compare it with the real codesign (see tools/codesign_parity.py).
"""
import hashlib
import mmap
import os
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from . import hostos, log

CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
CSMAGIC_CODEDIRECTORY = 0xFADE0C02
CSSLOT_CODEDIRECTORY = 0
CSSLOT_ALTERNATE_CODEDIRECTORIES = 0x1000
CS_ADHOC = 0x2
CD_VERSION = 0x20400
HASH_SHA1, HASH_SHA256 = 1, 2
HASH_BY_NAME = {"sha1": HASH_SHA1, "sha256": HASH_SHA256}
HASH_FUNCS = {1: hashlib.sha1, 2: hashlib.sha256, 3: hashlib.sha256, 4: hashlib.sha384}
HASH_SIZES = {1: 20, 2: 32, 3: 20, 4: 48}
# magic, length, version, flags, hashOffset, identOffset, nSpecialSlots, nCodeSlots, codeLimit,
# hashSize, hashType, platform, pageSize, spare2, scatterOffset, teamOffset, spare3,
# codeLimit64, execSegBase, execSegLimit, execSegFlags
CD_HEADER = struct.Struct(">IIIIIIIIIBBBBIIIIQQQQ")
LC_CODE_SIGNATURE = 0x1D
CPU_TYPE_ARM64 = 0x0100000C
MACHO_THIN = {b"\xcf\xfa\xed\xfe": 32, b"\xce\xfa\xed\xfe": 28}   # little-endian magic -> header size


def backend():
    if hostos.IS_MAC and os.environ.get("N56_CODESIGN_BACKEND", "").lower() != "python":
        return "codesign"
    return "python"


# ---- CodeDirectory / SuperBlob (pure Python) ------------------------------------
def build_code_directory(code_limit, page_hashes, hash_type, identifier, page_log2=12, flags=CS_ADHOC):
    if code_limit >= 2 ** 32:
        raise ValueError("files of 4 GiB or more are not supported")
    ident = identifier.encode("utf-8") + b"\0"
    ident_off = CD_HEADER.size
    hash_off = ident_off + len(ident)
    length = hash_off + HASH_SIZES[hash_type] * len(page_hashes)
    header = CD_HEADER.pack(CSMAGIC_CODEDIRECTORY, length, CD_VERSION, flags, hash_off, ident_off,
                            0, len(page_hashes), code_limit, HASH_SIZES[hash_type], hash_type,
                            0, page_log2, 0, 0, 0, 0, 0, 0, 0, 0)
    return header + ident + b"".join(page_hashes)


def page_hashes(path, hash_type, page_size):
    func = HASH_FUNCS[hash_type]
    out = []
    with open(path, "rb") as stream:
        while True:
            page = stream.read(page_size)
            if not page:
                break
            digest = func(page).digest()
            out.append(digest[:HASH_SIZES[hash_type]])
    return out


def pack_superblob(blobs):
    """blobs: list of (slot, blob bytes). Returns a CSMAGIC_EMBEDDED_SIGNATURE SuperBlob."""
    index_size = 12 + 8 * len(blobs)
    offset = index_size
    index = b""
    body = b""
    for slot, blob in blobs:
        index += struct.pack(">II", slot, offset + len(body))
        body += blob
    total = index_size + len(body)
    return struct.pack(">III", CSMAGIC_EMBEDDED_SIGNATURE, total, len(blobs)) + index + body


def parse_superblob(data):
    magic, length, count = struct.unpack_from(">III", data, 0)
    if magic != CSMAGIC_EMBEDDED_SIGNATURE or length > len(data):
        raise ValueError("not a code signature SuperBlob")
    blobs = {}
    for i in range(count):
        slot, offset = struct.unpack_from(">II", data, 12 + 8 * i)
        blob_length, = struct.unpack_from(">I", data, offset + 4)
        blobs[slot] = data[offset:offset + blob_length]
    return blobs


def parse_code_directory(blob):
    fields = CD_HEADER.unpack_from(blob.ljust(CD_HEADER.size, b"\0"), 0)
    magic, length, version, flags, hash_off, ident_off, n_special, n_code, code_limit, \
        hash_size, hash_type, _platform, page_log2 = fields[:13]
    if magic != CSMAGIC_CODEDIRECTORY:
        raise ValueError("not a CodeDirectory")
    end = blob.index(b"\0", ident_off)
    return {
        "version": version, "flags": flags, "identifier": blob[ident_off:end].decode("utf-8", "replace"),
        "hash_type": hash_type, "hash_size": hash_size, "page_log2": page_log2, "code_limit": code_limit,
        "n_code": n_code, "n_special": n_special, "length": length,
        "code_hashes": [blob[hash_off + i * hash_size: hash_off + (i + 1) * hash_size] for i in range(n_code)],
        "cdhash": HASH_FUNCS[hash_type](blob[:length]).digest()[:20],
    }


def cdhash_from_signature(data, hash_type=HASH_SHA256):
    """cdhash of the CodeDirectory using hash_type (SHA-256 is what the trust cache lists)."""
    for blob in parse_superblob(data).values():
        if blob[:4] == struct.pack(">I", CSMAGIC_CODEDIRECTORY):
            info = parse_code_directory(blob)
            if info["hash_type"] == hash_type:
                return info["cdhash"]
    raise ValueError("no CodeDirectory with the requested hash type")


def make_detached_signature(path, digests=("sha1", "sha256"), page_size=4096, identifier=None):
    log2 = page_size.bit_length() - 1
    if 1 << log2 != page_size:
        raise ValueError("page size must be a power of two")
    size = os.path.getsize(path)
    ident = identifier or Path(path).name
    blobs = []
    for i, name in enumerate(digests):
        hash_type = HASH_BY_NAME[name]
        cd = build_code_directory(size, page_hashes(path, hash_type, page_size), hash_type, ident, log2)
        blobs.append((CSSLOT_CODEDIRECTORY if i == 0 else CSSLOT_ALTERNATE_CODEDIRECTORIES + i - 1, cd))
    return pack_superblob(blobs)


def verify_detached_signature(path, sig_data):
    """True when every CodeDirectory page hash matches the file."""
    size = os.path.getsize(path)
    for blob in parse_superblob(sig_data).values():
        if blob[:4] != struct.pack(">I", CSMAGIC_CODEDIRECTORY):
            continue
        info = parse_code_directory(blob)
        if info["code_limit"] != size:
            return False
        if page_hashes(path, info["hash_type"], 1 << info["page_log2"]) != info["code_hashes"]:
            return False
    return True


# ---- Mach-O reading -------------------------------------------------------------
def _slice_offsets(data):
    magic = data[:4]
    if magic in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
        wide = magic[3] == 0xBF
        count, = struct.unpack_from(">I", data, 4)
        entry = struct.Struct(">iiQQII" if wide else ">iiIII")
        slices = []
        for i in range(count):
            fields = entry.unpack_from(data, 8 + i * entry.size)
            slices.append((fields[0] & 0xFFFFFFFF, fields[2]))
        chosen = next((s for s in slices if s[0] == CPU_TYPE_ARM64), slices[0] if slices else None)
        return [chosen[1]] if chosen else []
    return [0]


def macho_signature(path):
    """Return the code-signature SuperBlob of a Mach-O (arm64 slice of a fat file), or None."""
    # Map the file instead of reading it: the dyld shared cache is over 1 GB and
    # reading it whole gets the process killed on low-memory hosts.
    with open(path, "rb") as stream:
        if os.fstat(stream.fileno()).st_size == 0:
            return None
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            if data[:7] == b"dyld_v1":
                # dyld shared cache: not a Mach-O; header holds codeSignatureOffset/Size (u64 at 0x28/0x30).
                offset, size = struct.unpack_from("<QQ", data, 0x28)
                if not size or offset + size > len(data):
                    return None
                return bytes(data[offset:offset + size])
            for base in _slice_offsets(data):
                header = MACHO_THIN.get(data[base:base + 4])
                if header is None:
                    continue
                ncmds, = struct.unpack_from("<I", data, base + 16)
                offset = base + header
                for _ in range(ncmds):
                    cmd, size = struct.unpack_from("<II", data, offset)
                    if cmd == LC_CODE_SIGNATURE:
                        dataoff, datasize = struct.unpack_from("<II", data, offset + 8)
                        return bytes(data[base + dataoff: base + dataoff + datasize])
                    offset += size
    return None


# ---- public API --------------------------------------------------------------------
def _run(cmd, **kwargs):
    return subprocess.run(cmd, check=True, capture_output=True, **kwargs)


def _ldid():
    return hostos.need("ldid", "Install the Procursus build: sudo apt install ldid "
                               "(or build https://github.com/ProcursusTeam/ldid).")


def detached_sign(path, sig, digests=("sha1", "sha256"), page_size=4096):
    """Write a detached ad-hoc signature of a flat file to sig."""
    path, sig = str(path), str(sig)
    if os.path.exists(sig):
        os.remove(sig)
    if backend() == "codesign":
        _run(["codesign", "-s", "-", "-f", f"--digest-algorithm={','.join(digests)}",
              "--pagesize", str(page_size), "--detached", sig, path])
        out = subprocess.run(["codesign", "-d", "-vvvv", "--detached", sig, path],
                             capture_output=True, text=True)
        if out.returncode:
            log.die("Detached signature verification failed: " + path)
        return
    data = make_detached_signature(path, digests, page_size)
    Path(sig).write_bytes(data)
    if not verify_detached_signature(path, data):
        log.die("Generated detached signature does not match the file: " + path)


def cdhash(path, detached=None):
    """SHA-256 cdhash (20 bytes) of a Mach-O, or of a flat file with a detached signature."""
    path = str(path)
    if backend() == "codesign":
        cmd = ["codesign", "-d", "-vvvv"]
        if detached:
            cmd += ["--detached", str(detached)]
        result = subprocess.run(cmd + [path], capture_output=True, text=True)
        if result.returncode:
            log.die(f"Cannot read cdhash: {path}\n{result.stderr}")
        match = re.search(r"CandidateCDHash sha256=([0-9a-f]{40})", result.stderr)
        if match is None:
            log.die(f"codesign did not output a SHA-256 cdhash: {path}")
        return bytes.fromhex(match.group(1))
    try:
        blob = Path(detached).read_bytes() if detached else macho_signature(path)
        if blob is None:
            log.die(f"{path} has no code signature")
        return cdhash_from_signature(blob)
    except (ValueError, struct.error, OSError) as exc:
        log.die(f"Cannot read cdhash of {path}: {exc}")


def sign_macho(path, entitlements=None, digests=None, page_size=None, preserve=False):
    """Ad-hoc sign (or re-sign) a Mach-O. preserve keeps entitlements and identifier."""
    path = str(path)
    if backend() == "codesign":
        cmd = ["codesign", "-s", "-", "-f"]
        if digests:
            cmd.append(f"--digest-algorithm={','.join(digests)}")
        if page_size:
            cmd += ["--pagesize", str(page_size)]
        if preserve:
            cmd.append("--preserve-metadata=identifier,entitlements,requirements,flags")
        if entitlements:
            cmd += ["--entitlements", str(entitlements)]
        _run(cmd + [path])
        return
    ldid = _ldid()
    # ldid always uses 4 KiB pages, which is what these iOS binaries need.
    extra = []
    with tempfile.TemporaryDirectory() as tmp:
        ents = str(entitlements) if entitlements else None
        if preserve:
            blob = macho_signature(path)
            if blob is not None:
                for part in parse_superblob(blob).values():
                    if part[:4] == struct.pack(">I", CSMAGIC_CODEDIRECTORY):
                        extra.append("-I" + parse_code_directory(part)["identifier"])
                        break
            if ents is None:
                saved = os.path.join(tmp, "ents.xml")
                got = subprocess.run([ldid, "-e", path], capture_output=True)
                if got.returncode == 0 and got.stdout.strip():
                    Path(saved).write_bytes(got.stdout)
                    ents = saved
        cmd = [ldid, f"-S{ents}" if ents else "-S"]
        cmd += [f"-H{name}" for name in (digests or ("sha1", "sha256"))]
        _run(cmd + extra + [path])


def remove_signature(path):
    if backend() == "codesign":
        _run(["codesign", "--remove-signature", str(path)])
    else:
        _run([_ldid(), "-r", str(path)])


def verify(path):
    if backend() == "codesign":
        _run(["codesign", "--verify", "--strict", str(path)])
        return
    blob = macho_signature(path)
    if blob is None:
        log.die(f"{path} has no code signature")
    cdhash_from_signature(blob)
