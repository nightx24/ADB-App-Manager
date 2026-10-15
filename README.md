# ADB App Manager

A cross-platform Android package manager and debloating utility for Windows and Linux, powered by Android Debug Bridge (ADB).

## Features

- Detect ADB and connected Android devices
- Wireless ADB connection and Android 11+ Wireless Debugging pairing-code workflow
- Browse installed packages, with search and third-party/system filters
- Conservative exact-package debloat guidance plus a searchable OEM Debloat Guide for OxygenOS/ColorOS, Xiaomi HyperOS/MIUI and Samsung One UI, showing risk levels, feature impacts and dependency caveats
- Visible package checkboxes, Select all visible, Clear selection, and checked multi-select batch operations
- Uninstall an app for the current Android user (does not remove the APK from the system partition)
- Disable and re-enable packages
- Export the package inventory to CSV
- Activity log and confirmation dialogs for potentially disruptive actions
- Multi-select batch enable, disable, and uninstall operations
- Batch APK installation, multi-file upload to Downloads, and package data clearing
- Interactive ADB shell, device reboot modes, and package-list presets
- Optional NightLab AMBridge companion with automatic app labels, icon retrieval, per-device local cache, and temporary ADB-forwarded communication
- Automated Windows, Linux, AppImage, and Flatpak packaging through GitHub Actions

## Downloads

Open the [GitHub Actions builds](https://github.com/nightx24/ADB-App-Manager/actions) and download the artifact from the latest successful run. Tagged releases (`v*`) also publish release files.

- **Windows:** `ADB-App-Manager-Windows.zip` — extract and run `ADB-App-Manager.exe`.
- **Linux AppImage (recommended):** `ADB-App-Manager-x86_64.AppImage` — works on many x86_64 Linux distributions; mark it executable, then launch it.
- **Debian/Ubuntu/Linux Mint:** `ADB-App-Manager-amd64.deb` — install with `sudo apt install ./ADB-App-Manager-amd64.deb`.
- **Fedora/RHEL-compatible systems:** `ADB-App-Manager-x86_64.rpm` — install with `sudo dnf install ./ADB-App-Manager-x86_64.rpm`.
- **Portable Linux binary:** `ADB-App-Manager-Linux.tar.gz` — extract and run `ADB-App-Manager`.
- **Flatpak:** `ADB-App-Manager.flatpak` — install using the command below.

Linux downloads currently target **x86_64/amd64 PCs**. The AppImage is the easiest option across distributions; the `.deb` and `.rpm` packages are for their matching package-manager families. All options still require a working ADB installation or host ADB access. The standalone binary and distro packages are not guaranteed to run on every Linux release because system libraries and desktop environments vary.

Install a Flatpak bundle:
```bash
flatpak install --user ./ADB-App-Manager.flatpak
flatpak run io.github.nightx24.ADBAppManager
```

The Flatpak needs access to ADB on the host. It requests read-only host filesystem visibility and device access so it can find host-installed Platform-Tools and connect to USB devices. Depending on your Linux setup, ADB access may require additional udev permissions or a host ADB server.

## Requirements

- Android SDK Platform-Tools (`adb`) installed and available on `PATH` for the regular Linux binary and Windows app.
- Android device with Developer options and USB debugging enabled.
- Accept the USB debugging authorization prompt on the phone.
- For wireless pairing on Android 11+, enable Developer options → Wireless debugging; pairing and connection ports are different. Keep the PC and phone on the same local network.

## Run from source

Python 3.11+ is recommended.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
python main.py
```

## Build locally

```bash
python -m pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name ADB-App-Manager main.py
```

The executable is created in `dist/`.

## Wireless ADB connection

Use **Pair Wi-Fi** for Android 11+ Wireless Debugging pairing. Enter the pairing IP/port and six-digit code shown by the phone. After pairing, use **Connect Wi-Fi** with the separate connection IP/port shown on the main Wireless Debugging screen. The app refreshes the device list after a connection attempt. Ports can change, so read the current values from Android settings each time.

Use this only on a trusted local network and only with devices you are authorized to manage. For older Android versions or devices using classic TCP/IP debugging, connect by USB and select **Enable TCP/IP (USB)**, then enter the phone's Wi-Fi IP with port `5555` in **Connect Wi-Fi**. Use this legacy mode only on a trusted network; it is different from Android 11+ Wireless Debugging.

## Optional NightLab AMBridge companion

The repository includes the Android companion source under `ambridge/` (application ID `com.nightlab.ambridge`, Android 10+). The desktop app checks for it when a device is selected and offers guided installation if it is missing. Use **AMBridge helper** to refresh app metadata or install the companion APK.

When AMBridge is installed, **Load packages** launches the companion and requests its installed-app labels, icons, package IDs, and version details over a temporary ADB-forwarded HTTP connection. The Android endpoint binds to device loopback, serves read-only metadata, and does not upload app inventory to a remote server. The desktop removes the temporary ADB port forward after the request and caches the latest metadata locally per device.

The **Build NightLab AMBridge APK** workflow builds a debug APK and uploads it as a workflow artifact. When a `v*` tag is built, the workflow also attaches the companion APK to that GitHub Release. Debug APKs are for testing; they are not production-signed.

Keep the phone awake and unlocked during the first connection. The companion needs the package-inventory permission to show all installed apps. Android can stop background activities under memory pressure; if metadata retrieval fails, reopen AMBridge and retry. Real-device testing is still required across Android versions and device manufacturers.

## Safety notes

Package operations can disable important Android features. Review the package name before applying an action. The app intentionally does not provide one-click bulk debloating or automatically remove packages. “Uninstall for user” uses `pm uninstall --user 0`, which generally removes the package for the primary user while leaving system image files intact. Availability varies by Android version and device vendor. Reinstall/enable actions may not work for every package.

## OEM debloat guide

Open **Device tools → OEM Debloat Guide** to search common OnePlus/OPlus/HeyTap/Google package IDs and review their purpose, risk, and known or uncertain feature dependencies. It is a curated reference, not a universal complete list: package names and dependencies vary by model, region, Android version, and OxygenOS build. The guide never removes anything automatically; it can only select matching installed packages in the App library for review. See [OXYGENOS_DEBLOAT_GUIDE.md](OXYGENOS_DEBLOAT_GUIDE.md) for the full reference and recovery notes.

## Debloat recommendation safety

The **Recommended (review first)** filter is deliberately conservative and matches exact package IDs. It is not a universal “safe to remove” list: entries may only apply to particular ROMs, and recommendations are conditional on whether you use the app or feature. The app never automatically removes recommended packages. Check the package name and guidance, keep a backup, and remove only what you understand. Camera, calendar, and gallery entries are marked advanced because removing them without replacements can remove essential user-facing features. Packages absent from the small list are **not** implicitly safe or unsafe.

The project is independently developed and takes inspiration from common Android device-management workflows in [ADB AppControl](https://adbappcontrol.com/en/), [Universal Android Debloater](https://github.com/0x192/universal-android-debloater), and [Universal Android Debloater Next Generation](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation). It does not claim to be any of those projects, and does not copy proprietary implementations, branding, or package databases.

## License

MIT License. ADB App Manager is an independent project inspired by ADB AppControl, Universal Android Debloater, and Universal Android Debloater Next Generation. It is not affiliated with or endorsed by those projects or their maintainers.


The unified debloat reference includes supplemental ColorOS/realme UI package risk notes.
