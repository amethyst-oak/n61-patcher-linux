#!/usr/bin/env python3
"""Pure-Python replacement for tools/devicetree-parse/repack.m.

Usage: devicetree_repack.py <devicetree.json> <output>

repack.m needs Foundation (macOS, or GNUstep on Linux). The format it writes is
small, so this script reproduces it byte for byte:

    node      = u32 n_properties, u32 n_children, properties..., children...
    property  = char name[32], u16 length, u16 flags, value padded to 4 bytes

The JSON input is the output of devicetree-parse: "device-tree" holds a node,
a node is a list, a dict inside it is a property and a list inside it is a
child node. Integer values are written little-endian with the property's
declared length; string values may contain literal \\xNN escapes.
"""
import json
import re
import struct
import sys

NAME_SIZE = 32
_TRAILING_COMMA = re.compile(r",(\s*[\]}])")


def load_json(text):
    """Parse strict JSON, tolerating the trailing commas some dumps contain."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_TRAILING_COMMA.sub(r"\1", text))


def process_bytes(text):
    """Turn a string with literal \\xNN escapes into bytes, like processBytes()."""
    raw = text.encode("utf-8", "surrogateescape")
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i:i + 2] == b"\\x" and i + 3 < len(raw):
            try:
                out.append(int(raw[i + 2:i + 4], 16))
                i += 4
                continue
            except ValueError:
                # strtol() on a bad pair yields 0 or a partial value; keep the
                # escape visible instead of silently inventing a byte.
                raise ValueError(f"bad \\x escape in {text!r}")
        out.append(raw[i])
        i += 1
    return bytes(out)


def pack_property(prop):
    name = prop["name"].encode("utf-8")
    if len(name) >= NAME_SIZE:
        raise ValueError(f"property name too long: {prop['name']!r}")
    length = int(prop["length"])
    flags = int(prop.get("flags", 0))
    if not 0 <= length <= 0xFFFF:
        raise ValueError(f"property {prop['name']!r}: length {length} does not fit in 16 bits")
    padded = (length + 3) & ~3
    value = prop.get("value")
    data = bytearray(padded)
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, (int, float)):
        number = int(value) & 0xFFFFFFFFFFFFFFFF
        if length not in (1, 2, 4, 8):
            raise ValueError(f"property {prop['name']!r}: unhandled int size {length}")
        data[:length] = (number & ((1 << (8 * length)) - 1)).to_bytes(length, "little")
    elif isinstance(value, str) and value:
        blob = process_bytes(value)
        data[:length] = blob[:length].ljust(length, b"\0")
    return name.ljust(NAME_SIZE, b"\0") + struct.pack("<HH", length, flags) + bytes(data)


def pack_node(node):
    props = [item for item in node if isinstance(item, dict)]
    children = [item for item in node if not isinstance(item, dict)]
    out = bytearray(struct.pack("<II", len(props), len(children)))
    # repack.m writes properties first, then children, each in input order.
    for item in props:
        out += pack_property(item)
    for item in children:
        out += pack_node(item)
    return bytes(out)


def repack(document):
    return pack_node(document["device-tree"])


def main(argv):
    if len(argv) != 3:
        print(f"Usage: {argv[0]} <devicetree.json> <output>")
        return 1
    with open(argv[1], encoding="utf-8") as stream:
        document = load_json(stream.read())
    data = repack(document)
    with open(argv[2], "wb") as stream:
        stream.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
