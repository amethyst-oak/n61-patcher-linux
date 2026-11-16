# Tool sources

Run from the repository root. On **Linux** follow [docs/LINUX.md](../docs/LINUX.md) for packages, then:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pillow pillow-heif
export IPHONEOS_SDK=/path/to/iPhoneOS14.5.sdk
.venv/bin/python tools/doctor.py
.venv/bin/python tools/setup.py
```

On macOS install full Xcode instead (the iPhoneOS SDK is needed by `n56-jb-info` and `create_systembag`) and run `python3 tools/setup.py`.

| Upstream submodule | Purpose | Local path (Linux / macOS) |
| --- | --- | --- |
| [SSHRD_Script](https://github.com/verygenericname/SSHRD_Script) | gaster, irecovery, iBoot64Patcher, KPlooshFinder, sshpass, iproxy | `tools/SSHRD_Script/Linux/` / `Darwin/` |
| [img4lib](https://github.com/xerub/img4lib) | IMG4 extraction and packaging | `tools/img4lib/img4` |
| [dualra1n](https://github.com/dualra1n/dualra1n) | Kernel64Patcher, kairos, dtree_patcher; iOS 14 fsck and apfs.fs | `tools/dualra1n/binaries/Linux/` / `Darwin/` |
| [gaster](https://github.com/verygenericname/gaster) | DFU exploit and iBoot decryption; built from source, or the prebuilt Linux copy from dualra1n | `tools/SSHRD_Script/<host>/gaster` |
| [devicetree-parse](https://github.com/khanhduytran0/devicetree-parse) | DeviceTree extraction (repacking is `tools/devicetree_repack.py` on Linux) | `tools/devicetree-parse/` |

Versions are pinned by submodule gitlinks (`git submodule status`).

## checkra1n userland

Setup normally downloads the official [checkra1n 0.12.4](https://checkra.in/releases/) macOS DMG, verifies its SHA-256 and extracts the userland into `donors/checkra1n/` (`tools/fetch_checkra1n.py`). If that fails, either set `N56_CHECKRA1N_DMG` to a DMG you downloaded, or extract the same files from the Linux binary with `tools/fetch_from_elf.py` (accepts only SHA-256 `dac99689…c51d`). Details in [docs/LINUX.md](../docs/LINUX.md).

## Other

- Extra local tools may be placed in `tools/bin/`.
- Linux-only host helpers live in `core/hostos.py`, `core/codesign.py` and `tools/devicetree_repack.py`.
- `tools/extras/` holds experimental helpers (see [docs/KNOWN_ISSUES.md](../docs/KNOWN_ISSUES.md)).
