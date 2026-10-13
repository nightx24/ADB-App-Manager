# ADB App Manager

A cross-platform Android package manager and debloating utility for Windows and Linux, powered by Android Debug Bridge (ADB).

## Features

- Detect ADB and connected Android devices
- Wireless ADB connection and Android 11+ Wireless Debugging pairing-code workflow
- Browse installed packages, with search and third-party/system filters
- Conservative debloat guidance for a small set of exact package IDs, with conditional risk notes and a dedicated review filter
- Uninstall an app for the current Android user (does not remove the APK from the system partition)
- Disable and re-enable packages
- Export the package inventory to CSV
- Activity log and confirmation dialogs for potentially disruptive actions
- Multi-select batch enable, disable, and uninstall operations
- Batch APK installation, multi-file upload to Downloads, and package data clearing
- Interactive ADB shell, device reboot modes, and package-list presets
- Optional NightLab AMBridge companion detection (`com.nightlab.ambridge`) and guided installation from a user-selected APK
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

When an authorized device is selected, the app checks for the companion package ID `com.nightlab.ambridge` and offers guided installation if it is missing. Use **AMBridge helper** to check again. Select an APK that you trust and have permission to use; this project does not bundle a companion APK. The filename does not establish an APK package ID or verify its publisher, so confirm the package ID after installation.

Keep the phone awake and unlocked during setup. Installation may require Android settings that allow installation through ADB. Grant only permissions documented by the companion maintainer.

**Current limitation:** this project checks for `com.nightlab.ambridge` and provides installation guidance only. It does not read a companion data-exchange protocol, so package rows still show package IDs rather than companion-provided app names/icons. **Load packages** refreshes this app’s existing package inventory, not companion metadata. Names/icons integration needs a documented interface or protocol; it will not be guessed.

## Safety notes

Package operations can disable important Android features. Review the package name before applying an action. The app intentionally does not provide one-click bulk debloating or automatically remove packages. “Uninstall for user” uses `pm uninstall --user 0`, which generally removes the package for the primary user while leaving system image files intact. Availability varies by Android version and device vendor. Reinstall/enable actions may not work for every package.

## Debloat recommendation safety

The **Recommended (review first)** filter is deliberately conservative and matches exact package IDs. It is not a universal “safe to remove” list: entries may only apply to particular ROMs, and recommendations are conditional on whether you use the app or feature. The app never automatically removes recommended packages. Check the package name and guidance, keep a backup, and remove only what you understand. Camera, calendar, and gallery entries are marked advanced because removing them without replacements can remove essential user-facing features. Packages absent from the small list are **not** implicitly safe or unsafe.

The project is independently developed and takes inspiration from common Android device-management workflows in [ADB AppControl](https://adbappcontrol.com/en/), [Universal Android Debloater](https://github.com/0x192/universal-android-debloater), and [Universal Android Debloater Next Generation](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation). It does not claim to be any of those projects, and does not copy proprietary implementations, branding, or package databases.

## License

MIT License. ADB App Manager is an independent project inspired by ADB AppControl, Universal Android Debloater, and Universal Android Debloater Next Generation. It is not affiliated with or endorsed by those projects or their maintainers.
