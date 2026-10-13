# ADB App Manager

A cross-platform Android package manager and debloating utility for Windows and Linux, powered by Android Debug Bridge (ADB).

## Features

- Detect ADB and connected Android devices
- Browse installed packages, with search and third-party/system filters
- Uninstall an app for the current Android user (does not remove the APK from the system partition)
- Disable and re-enable packages
- Export the package inventory to CSV
- Activity log and confirmation dialogs for potentially disruptive actions
- Multi-select batch enable, disable, and uninstall operations
- Batch APK installation, multi-file upload to Downloads, and package data clearing
- Interactive ADB shell, device reboot modes, and package-list presets
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

## Safety notes

Package operations can disable important Android features. Review the package name before applying an action. The app intentionally does not provide one-click bulk debloating or automatically remove packages. “Uninstall for user” uses `pm uninstall --user 0`, which generally removes the package for the primary user while leaving system image files intact. Availability varies by Android version and device vendor. Reinstall/enable actions may not work for every package.

## License

MIT License. ADB App Manager is an independent project and is not affiliated with the authors of ADB AppControl or Universal Android Debloater Next Generation.
