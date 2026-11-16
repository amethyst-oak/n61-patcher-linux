#!/usr/bin/env python3
"""Compare core.codesign's pure-Python signing with Apple's codesign (run this on a Mac).

    python3 tools/codesign_parity.py <flat-file> [<mach-o> ...]

For the flat file it signs with `codesign --detached` and with the Python
implementation, then prints the CodeDirectory fields side by side (version,
flags, identifier, special slots, page size, hashes, cdhash). For each Mach-O it
prints the cdhash read by codesign and by the Python reader. Use it to decide
whether the Linux-generated launchd cache signature is structurally identical
to what macOS produces before trusting it on a device."""
import os
from pathlib import Path
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import codesign, hostos  # noqa: E402


def describe(blob):
    out = {}
    for slot, part in sorted(codesign.parse_superblob(blob).items()):
        if part[:4] == b"\xfa\xde\x0c\x02":
            info = codesign.parse_code_directory(part)
            info.pop("code_hashes")
            out[hex(slot)] = info
        else:
            out[hex(slot)] = f"blob magic {part[:4].hex()} length {len(part)}"
    return out


def main(argv):
    if not hostos.IS_MAC:
        print("This comparison needs macOS codesign.")
        return 2
    if len(argv) < 2:
        print(__doc__)
        return 1
    flat = Path(argv[1])
    with tempfile.TemporaryDirectory() as tmp:
        real_sig, py_sig = Path(tmp, "real.sig"), Path(tmp, "py.sig")
        os.environ["N56_CODESIGN_BACKEND"] = "codesign"
        codesign.detached_sign(flat, real_sig)
        py_sig.write_bytes(codesign.make_detached_signature(flat))
        real, mine = describe(real_sig.read_bytes()), describe(py_sig.read_bytes())
        for slot in sorted(set(real) | set(mine)):
            print(f"slot {slot}")
            a, b = real.get(slot), mine.get(slot)
            if isinstance(a, dict) and isinstance(b, dict):
                for key in sorted(set(a) | set(b)):
                    mark = " " if a.get(key) == b.get(key) else "!"
                    print(f"  {mark} {key:12} codesign={a.get(key)!r}  python={b.get(key)!r}")
            else:
                print(f"    codesign={a!r}\n    python={b!r}")
    for path in argv[2:]:
        os.environ["N56_CODESIGN_BACKEND"] = "codesign"
        real = codesign.cdhash(path)
        os.environ["N56_CODESIGN_BACKEND"] = "python"
        mine = codesign.cdhash(path)
        print(f"{path}: {'match' if real == mine else 'DIFFERENT'}  codesign={real.hex()} python={mine.hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
