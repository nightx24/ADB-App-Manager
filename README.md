# ADB App Manager

A cross-platform Android package manager and debloating utility for Windows and Linux, powered by Android Debug Bridge (ADB).

## Features

- Detect ADB and connected Android devices
- Browse installed packages, with search and third-party/system filters
- Uninstall an app for the current Android user (does not remove the APK from the system partition)
- Disable and re-enable packages
- Export the package inventory to CSV
- Activity log and confirmation dialogs for potentially disruptive actions
- GitHub Actions builds for Windows and Linux

## Requirements

- Python 3.11+
- Android SDK Platform-Tools (`adb`) installed and available on `PATH`
- Android device with Developer options and USB debugging enabled
- Accept the USB debugging authorization prompt on the phone

On Fedora, install Qt's runtime dependencies if prompted by PySide6. On Windows, install Android Platform-Tools and add its directory to `PATH`.

## Run from source

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
pyinstaller --noconfirm --clean --windowed --name ADB-App-Manager main.py
```

The executable is created in `dist/`.

## Safety notes

Package operations can disable important Android features. Review the package name before applying an action. The app intentionally does not provide one-click bulk debloating or automatically remove packages. “Uninstall for user” uses `pm uninstall --user 0`, which generally removes the package for the primary user while leaving system image files intact. Availability varies by Android version and device vendor. Reinstall/enable actions may not work for every package.

## License

MIT License. ADB App Manager is an independent project and is not affiliated with the authors of ADB AppControl or Universal Android Debloater Next Generation.