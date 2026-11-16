# Running n61-patcher on Linux

Everything in the main flow (IPSW extraction, rootfs build, boot images, DFU boot) runs from a Linux host. This page lists what was replaced, how to set up, what has been verified, and what goes wrong on Linux and how to fix it. For the step-by-step install, see [N61.md](N61.md).

## Verification status

| Claim | Evidence |
| --- | --- |
| The full flow works on Debian x86_64 with one iPhone 6 (N61): install, build, tethered boot to iOS 13.7 | One tester, one device. It reached the home screen and Cydia ran |
| The Python helpers behave as designed | `tests/test_linux_port.py`: 19 offline tests (`pytest tests/test_linux_port.py`) |
| Pure-Python signatures equal Apple's `codesign` output | **Not verified.** Run `python3 tools/codesign_parity.py <mrm.plist>` on a Mac and compare |
| `ldid` is equivalent to `codesign` for Mach-O helpers | **Not verified** (entitlements and SHA-256 directory should match; binaries are not byte-identical) |
| `apfs-fuse` gives the same rootfs metadata as a macOS mount | **Not verified.** Compare one rootfs tar stream from both hosts before trusting a second device |
| The kernel patch finder under `qemu-user` matches the macOS one | **Not verified**, but the resulting kernel booted on the tested phone |
| arm64 Linux hosts, other distributions, virtual machines, WSL | **Not tested.** USB passthrough in VMs and WSL is a known source of DFU failures |

## What changed from the macOS tool

| macOS dependency | Linux replacement |
| --- | --- |
| `hdiutil attach` on IPSW rootfs DMGs | `apfs-fuse` (read-only), with a `dmg2img` / 7-Zip raw-image fallback |
| `hdiutil` on checkra1n bootstrap DMGs | 7-Zip unpack (UDIF) or loop mount with the `hfsplus` kernel module (raw) |
| `codesign` (Mach-O) | `ldid` |
| `codesign --detached` (launchd `mrm.plist`) and cdhash extraction | pure Python in `core/codesign.py` (handles flat files, Mach-O and the dyld shared cache) |
| `xcrun` + `clang -arch arm64` | `clang --target=arm64-apple-ios` + `ld64.lld` + an iPhoneOS SDK you provide |
| `sips` (HEIC wallpapers) | Pillow + `pillow-heif` (or `heif-convert` / ImageMagick) |
| `bsdtar @file`, BSD `tar --uid/--gid` | `xz -dc`, GNU `tar --owner/--group --numeric-owner` |
| `devicetree-repack` (Objective-C) | `tools/devicetree_repack.py` (pure Python) |
| `nm` (kernel symbols) | `llvm-nm` (GNU `nm` cannot read Mach-O) |
| `kpf-test.macos` (checkra1n kernel patch finder, arm64 macOS only) | built as an aarch64 Linux executable (`checkra1n/kpf-test/Makefile.linux`) and run under `qemu-aarch64`; runs natively on arm64 hosts |
| checkra1n 0.12.4 macOS DMG | the same files extracted from a checkra1n **Linux binary** you supply: `tools/fetch_from_elf.py` |
| `SSHRD_Script/Darwin`, `dualra1n/binaries/Darwin` | the `Linux` directories of the same submodules |

On macOS every helper in `core/hostos.py` and `core/codesign.py` runs the original command, so the macOS path is unchanged.

## Setup (Debian / Ubuntu package names)

```sh
sudo apt install git build-essential clang lld llvm xz-utils p7zip-full dmg2img \
    libusb-1.0-0-dev libssl-dev xxd libblocksruntime-dev fuse3 ldid libusbmuxd-tools \
    gcc-aarch64-linux-gnu libc6-dev-arm64-cross qemu-user
# apfs-fuse is not packaged: https://github.com/sgan81/apfs-fuse
#   needs cmake, libfuse3-dev, zlib1g-dev, libbz2-dev, libattr1-dev
sudo modprobe hfsplus fuse

python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pillow pillow-heif
export IPHONEOS_SDK=/path/to/iPhoneOS14.5.sdk     # e.g. from https://github.com/theos/sdks

.venv/bin/python tools/doctor.py      # reports anything missing, with install hints
.venv/bin/python tools/setup.py
```

- **iPhoneOS SDK:** required for two small helpers (`systembag`, the checkra1n info tool). It cannot be downloaded by the tool. The Theos `iPhoneOS14.5.sdk` is accepted.
- **checkra1n 0.12.4 files:** `tools/setup.py` normally downloads the macOS DMG. If that download fails (`SSLEOFError`, site down), either set `N56_CHECKRA1N_DMG=/path/to/the.dmg` (SHA-256 `754bb6ec…e07b`), or extract the files from a Linux binary: `python3 tools/fetch_from_elf.py /path/to/checkra1n`, then re-run `tools/setup.py`. The ELF route only accepts the binary with SHA-256 `dac99689…c51d`. Its offsets were derived from the Mach-O headers inside that file and match the macOS layout; the extracted files have not been hash-compared with the DMG's. `tools/extras/scan_checkra1n.py` is a read-only scanner for checking another binary.
- **Root stages** need the venv Python and your environment. Use `sudo env`, not plain `sudo`:

  ```sh
  sudo env TMPDIR="$HOME/.cache/n61-patcher-tmp" IPHONEOS_SDK="$IPHONEOS_SDK" \
      .venv/bin/python n56patcher.py <stage> --target n61-ios13 --workdir build/n61-current
  ```
  Create that `TMPDIR` folder first. `/tmp` is often RAM-backed, and the build writes multi-gigabyte temporary files.

## Troubleshooting on Linux

| Symptom | Cause and fix |
| --- | --- |
| `tools/doctor.py` seems to hang | Older versions globbed all of `/usr/lib`. Update to the current `doctor.py` |
| `doctor` says `libBlocksRuntime` is missing though installed | `ldconfig` is in `/sbin`, not on a normal user's `PATH` on Debian. The current `doctor.py` calls `/sbin/ldconfig -p` |
| `doctor` says `SSHRD_Script tools` missing | Run `tools/setup.py`; it fetches the submodule. Do not loop on `doctor` first |
| gaster static link fails (`libusb.a` needs udev, `libcrypto.a` needs zlib) | Harmless: setup falls back to the prebuilt Linux gaster from dualra1n |
| checkra1n DMG download fails with `ssl.SSLEOFError` | See "checkra1n 0.12.4 files" above |
| `./sshrd.sh` prints only usage text | It needs the iOS version as an argument: `./sshrd.sh 12.5.8`, run with the phone in DFU |
| `ramdisk` stage says the chain was sent, the screen stays dark, SSH is refused | `tools/SSHRD_Script/sshramdisk/` is empty. The images were never generated. Run `./sshrd.sh 12.5.8` and check the folder lists `iBSS.img4`, `iBEC.img4`, `ramdisk.img4`, `kernelcache.img4`, … |
| `Connection reset by peer` on `ssh -p 2222 root@localhost` | `iproxy` is listening but the phone has no SSH server: the ramdisk did not boot. See the row above, then re-enter DFU and re-run |
| `bind(): Address in use` from `iproxy 2222:22` | Another `iproxy` already holds the port (often the patcher's). Stop only that process, then retry |
| `build` ends with `Killed` | Out of memory. Current code maps big files instead of reading them; if it still happens, add swap |
| `build`: `... has no code signature` on `dyld_shared_cache_arm64.combined` | Old `core/codesign.py`. The current one reads the signature location from the cache header |
| `build`: `FileNotFoundError: kpf-test.macos` | Old kernel-stage code. The current one builds `kpf-test.linux` (needs `gcc-aarch64-linux-gnu`, `libc6-dev-arm64-cross`, `qemu-user`) |
| `qemu: uncaught target signal 4 (Illegal instruction)` in the kernel patch finder | Fixed by reading the virtual timer (`cntvct_el0`); `qemu-user` does not expose the physical one to user code |
| `build`: `nm ... returned non-zero exit status 1` | GNU `nm` cannot read Mach-O. Install `llvm` (provides `llvm-nm`) |
| DFU detection is flaky, `usb_timeout` errors | Use a USB 2 port or a powered hub. xHCI behaves differently from macOS |

## Known gaps

1. **Signatures come from new code.** `mrm.plist.sig` and the cdhashes in the trust cache are produced by `core/codesign.py`, not Apple's tool. A wrong byte means the device rejects the cache at boot. It worked on the tested phone, but run `tools/codesign_parity.py` on a Mac to check structure field by field.
2. **Extended attributes and ACLs** are stripped (as the macOS path already did with `--no-xattrs`); `base_stream` on macOS still archives xattrs via `tar -cpf`.
3. **Not ported:** `tools/checkra1n-kpf` packaging scripts and `patches/impl/kc/audio/*` produce macOS launchers; the experimental `audio` patch stays disabled.
4. **The install stages write APFS metadata to the phone.** Back up first, and run `ramdisk`, `status` and a `--dry-run` before the first write.

## Extra tools (experimental)

`tools/extras/` holds helpers written while debugging package-manager problems after installation. They are not part of the install flow and are only partly tested:

- `scan_checkra1n.py`: read-only report on a checkra1n binary (size, SHA-256, embedded disk images, Mach-O files).
- `deb_zst_to_xz.py`: repacks a `.deb` that uses zstd compression as xz so an old `dpkg` can read it. Parsing and rewriting were tested; the zstd step was **not run**.
- `dep_closure.py`: lists the packages (and versions) needed for a target on a given phone and can download and repack them. Tested on made-up data only; start with `--dry-run`. See [KNOWN_ISSUES.md](KNOWN_ISSUES.md).
