# n61-patcher (Linux port): iOS 13.7 as a second system on iPhone 6

Build and install tool for running **iOS 13.7 beside iOS 12.5.8 on an iPhone 6 (N61AP / iPhone7,2)**, driven from a **Linux host**.

This is a Linux port of [tlfares/n61-patcher](https://github.com/tlfares/n61-patcher), which is itself a fork of [CelestialSayuki/n56-patcher](https://github.com/CelestialSayuki/n56-patcher) (the original iPhone 6 Plus project). The upstream tools needed macOS and Xcode. This port replaces the macOS-only pieces so the same flow runs on Debian-style Linux. macOS behaviour is unchanged.

> [!WARNING]
> The tool creates APFS volumes and writes system files on your phone. Back up first. A mistake or an Apple restore can erase everything on the device. It is not affiliated with Apple, it does not bypass Activation Lock, and you use it at your own risk.

## Status

| Area | State |
| --- | --- |
| Linux host: build, install and tethered boot to iOS 13.7 | **Worked on one iPhone 6 (N61), Debian x86_64.** One tester, one device |
| Other Linux distributions, arm64 hosts, other devices | Not tested |
| Signatures made by `core/codesign.py` (launchd cache, trust-cache hashes) | Pure-Python code; boots on the tested phone. Parity with Apple's `codesign` **not yet checked** (needs a Mac: `tools/codesign_parity.py`) |
| Hardware support on the phone | Inherited from the upstream N61 work: Touch ID does not work; see [docs/N61.md](docs/N61.md) |
| Package managers on the phone | **Rough.** The bundled Cydia bootstrap is old; see [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) |

The boot is **tethered**: after a restart the phone needs this computer and DFU mode to start iOS 13 again. Keep your `build/` folder.

## Quick start

```sh
sudo apt install git build-essential clang lld llvm xz-utils p7zip-full dmg2img \
    libusb-1.0-0-dev libssl-dev xxd libblocksruntime-dev fuse3 ldid libusbmuxd-tools \
    gcc-aarch64-linux-gnu libc6-dev-arm64-cross qemu-user
# apfs-fuse is not packaged: https://github.com/sgan81/apfs-fuse
sudo modprobe hfsplus fuse

git clone --recursive https://github.com/amethyst-oak/n61-patcher.git && cd n61-patcher
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt pillow pillow-heif
export IPHONEOS_SDK=/path/to/iPhoneOS14.5.sdk      # e.g. from https://github.com/theos/sdks

.venv/bin/python tools/doctor.py      # lists anything still missing
.venv/bin/python tools/setup.py
```

Then follow **[docs/N61.md](docs/N61.md)**: download the four IPSWs, put the phone in DFU, generate the ramdisk, dry-run, install, boot.

## Documentation

- **[docs/N61.md](docs/N61.md)**: the installation guide (Linux), device table, what works.
- **[docs/LINUX.md](docs/LINUX.md)**: what the port changed, what is verified, Linux troubleshooting.
- **[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md)**: problems seen after installation (package managers, jailbreak, App Store).
- [tools/UPSTREAM.md](tools/UPSTREAM.md): where each helper tool comes from.
- [docs/conclusions.md](docs/conclusions.md) and [docs/N56-upstream.md](docs/N56-upstream.md): upstream notes for the iPhone 6 Plus (N56), kept for reference. They are not Linux or N61 validation.

Use `--target n61-ios13` in every command. **N66 is the iPhone 6s Plus donor, not the iPhone 6 Plus.**

## What is not in this repository

Apple firmware, your phone's boot ticket (`state/`, IM4M), build output, and checkra1n's userland are never distributed here. You download the IPSWs with `tools/fetch_ipsw.py` (hashes are pinned), the tool extracts your own ticket from your own phone, and checkra1n's files are extracted from a checkra1n 0.12.4 binary you supply.

## Credits and license

The N56 port, the patcher design and the driver work are by **[CelestialSayuki](https://github.com/CelestialSayuki)** and the contributors credited in the upstream project and the tool submodules. The N61 adaptation is by [tlfares](https://github.com/tlfares). The Linux host layer (`core/hostos.py`, `core/codesign.py`, `tools/devicetree_repack.py`, the Linux build of the kernel patch finder) was added in this port.

Code is licensed under [GPL-3.0](LICENSE). Submodules and separately sourced tools keep their own licenses. Apple's firmware is not covered. [Support the original project](DONATE.md).
