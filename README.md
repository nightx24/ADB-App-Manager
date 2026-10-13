# ADB App Manager

A cross-platform Android package manager and debloating utility for Windows and Linux, powered by Android Debug Bridge (ADB).

## Features

- Detect ADB and connected Android devices
- Wireless ADB connection and Android 11+ Wireless Debugging pairing-code workflow
- Browse installed packages, with search and third-party/system filters
- Uninstall an app for the current Android user (does not remove the APK from the system partition)
- Disable and re-enable packages
- Export the package inventory to CSV
- Activity log and confirmation dialogs for potentially disruptive actions
- Multi-select batch enable, disable, and uninstall operations
- Batch APK installation, multi-file upload to Downloads, and package data clearing
- Interactive ADB shell, device reboot modes, and package-list presets
- Optional ACBridge companion detection and guided installation from a user-selected APK
- Automated Windows, Linux, AppImage, and Flatpak packaging through GitHub Actions

## Downloads

Open the [GitHub Actions builds](https://github.com/nightx24/ADB-App-Manager/actions) and download the artifact from the latest successful run. Tagged releases (`v*`) also publish release files.

- **Windows:** `ADB-App-Manager-Windows.zip` — extract and run `ADB-App-Manager.exe`.
- **Linux AppImage:** `ADB-App-Manager-x86_64.AppImage` — mark it executable, then launch it.
- **Linux portable binary:** `ADB-App-Manager-Linux.tar.gz` — extract and run `ADB-App-Manager`.
- **Linux Flatpak:** `ADB-App-Manager.flatpak` — install using the command below.

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

Use this only on a trusted local network and only with devices you are authorized to manage. This workflow does not enable legacy `adb tcpip` mode over USB; that can be added separately for older Android versions.

## Optional ACBridge companion

When an authorized device is selected, the app checks whether `com.cybercat.acbridge` is installed and offers a guided setup if it is missing. You can also use **ACBridge helper** to check again. If you choose to install it, select the APK you obtained from the official ACBridge source; this project does not bundle or redistribute Cyber.Cat's proprietary APK. The installer uses ADB and displays setup guidance for Android 6+ devices.

Keep the phone awake and unlocked during setup. Some devices may require enabling installation via ADB and USB debugging security settings, then granting ACBridge the storage/files access requested by its documentation.

**Current limitation:** this commit adds companion detection and installation guidance only. It does not yet read ACBridge's private data-exchange protocol, so package rows still show package IDs rather than ACBridge-provided app names/icons. The **Load packages** button refreshes the existing package inventory, not ACBridge metadata. A real names/icons integration needs a documented interface or protocol that can be implemented without guessing.

## Safety notes

Package operations can disable important Android features. Review the package name before applying an action. The app intentionally does not provide one-click bulk debloating or automatically remove packages. “Uninstall for user” uses `pm uninstall --user 0`, which generally removes the package for the primary user while leaving system image files intact. Availability varies by Android version and device vendor. Reinstall/enable actions may not work for every package.

## License

MIT License. ADB App Manager is an independent project and is not affiliated with the authors of ADB AppControl or Universal Android Debloater Next Generation.
