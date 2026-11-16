# Known issues (Linux port, iPhone 6 / N61)

Observed on one iPhone 6 installed from one Debian x86_64 laptop. "Cause unknown" means exactly that; nothing here is a confirmed diagnosis. See also [N61.md](N61.md) and [LINUX.md](LINUX.md).

## After installing: package managers and jailbreak

The install includes the checkra1n loader and a Cydia bootstrap. That bootstrap is old, and most trouble reported below comes from it.

| Symptom | What was seen | Status | Fix |
| --- | --- | --- |
| `/` is read-only, `dpkg` says "Read-only file system" | Seen once, together with a safe-mode loop and a stuck lockdown. A **fresh reinstall** (stock iOS 12, then the install again) cleared it | Cause unknown. Not reproduced since | You can use ssh using the same commands as in NewTerm, or if you have NewTerm or any Terminal Emulator, type `su` (password: alpine), `mount -uw /`. |
| Cydia upgrade fails on a `bigboss.gpg` conflict | Two sources ship the same key file | Remove the duplicate source or key; no fix in this repo |
| Old `dpkg` cannot read `.deb` files compressed with zstd | Procursus packages, including `libzstd`, loop on dependencies | Workaround is experimental: `tools/extras/deb_zst_to_xz.py` repacks as xz. The zstd step was **never run** |
| Zebra shows `Popen` errors | Zebra could not run its helper commands | Unresolved. Sileo did not show the error |
| Sileo installs and works | Sileo was installed once and could install packages | Works for that user. Not a verified recipe |
| Sileo cannot add `https://apt.procurs.us` | Procursus is a *suite* repo, not a flat one. Tapping Add did nothing | Needs the suite file: suite `iphoneos-arm64/1600`, component `main`, architecture `iphoneos-arm`. Not confirmed to work |
| Tweaks don't work at reboot | Tweaks don't inject (Anything that shows in Settings, etc.)  | Do not assume it will always work... | In NewTerm/SSH Tunnel: `su` (password: alpine), `/etc/rc.d/substrate && killall -9 installd && ldrestart`. The iPhone's userspace will restart, do not worry. |
| Odysseyra1n migration script | Suggested elsewhere; **not run or checked here** | **Untested**. Do not assume it will work. |
| `cydia.status` is fetched without a hash | The bootstrap pieces are not integrity-checked by this repo | Known gap |

### Things that might work (untested)

- Reinstall with `--exclude rootfs.cydia`, then put a Procursus bootstrap on from the laptop.
- `tools/extras/dep_closure.py --dry-run --target dpkg --installed <copy of /var/lib/dpkg/status> --repo https://apt.procurs.us --suite iphoneos-arm64/1600 --arch iphoneos-arm`, read the plan, then repack and install the whole set in one `dpkg -i` run. Only tested on made-up data.

Treat both as experiments on a phone you are ready to reinstall.

## Apps and system

| Area | Status |
| --- | --- |
| App Store sign-in | Worked in original macOS repo, as is in Linux one. Needs StoreAuthFix by computershik to function normally.|
| NewTerm | Works fine |
| Touch ID | Not working (disabled; SEP errors when enabled) |
| Audio recording, AirPods output | Not working |
| Health | Excluded |
| Cellular, Bluetooth, GPS, cameras, battery | Not comprehensively tested |

## Boot and install

- **Tethered boot.** Every cold start needs the computer and DFU. Keep `build/<workdir>/`.
- **No uninstall.** An Apple restore wipes everything; there is no tool that removes only the added volumes.
- **Boot arguments disable AMFI and code-signing enforcement**, and the build with the `checkra1n` feature off behaved the same on the tested phone. It is not a clean system.
- `install` / `rootfs` / `all` clear SystemB. Do not re-run them to reboot.
- `--dry-run` does not exercise the phone-side steps or the Linux-only code.
- Passwords: the ramdisk SSH password is `alpine` (in the code). The **iOS 13 userland** root password has not been confirmed here.

## Linux port

- Parity of `core/codesign.py` with Apple's `codesign` has not been checked on a Mac.
- `apfs-fuse` metadata has not been compared with a macOS mount.
- Only x86_64 Debian was tried. arm64 hosts, VMs and WSL are untested; USB passthrough is a likely problem.
- `tools/n61_wallpapers.py` and the audio launcher scripts still need macOS.

## Reporting

Open an issue with the commit, command, failing stage and a redacted log (no ECID, UDID, serial or account data).
