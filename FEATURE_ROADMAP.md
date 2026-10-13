# Feature roadmap: ADB App Manager

This is an independent project inspired by workflows found in [ADB AppControl](https://adbappcontrol.com/en/), [Universal Android Debloater](https://github.com/0x192/universal-android-debloater), and [Universal Android Debloater Next Generation](https://github.com/Universal-Debloater-Alliance/universal-android-debloater-next-generation). It does not claim to be affiliated with those projects or copy proprietary implementations, artwork, branding, or license systems.

## Planned feature parity

### Package management
- [ ] Multi-select and safe batch disable/enable/uninstall
- [x] Conservative exact-package debloat guidance with conditional risk labels and a review-only filter
- [ ] Device/OEM-aware recommendations and editable debloat presets
- [ ] Restore packages uninstalled for the current Android user
- [ ] App-data clearing with an explicit data-loss confirmation
- [ ] Show app label, version, install source, enabled state, and package size where Android exposes the information
- [ ] Integrate optional NightLab AMBridge metadata only after a documented, compatible protocol is available; current companion check only detects `com.nightlab.ambridge`
- [ ] Sort by name, package, size, and app type
- [x] **Connected-device app history:** show apps disabled on the connected phone in a dedicated list, with an enable/restore action
- [x] **Uninstalled-app history:** record package names and timestamps when this app uninstalls an app, and show the history for that device with a reinstall/restore option when possible
- [ ] Clearly distinguish apps uninstalled by ADB App Manager from apps that were already absent; Android generally does not provide a complete history of apps uninstalled before tracking began
- [ ] Refresh app status from the connected phone and handle device changes/reconnections safely

### APK library and transfer
- [ ] Single and batch APK installation
- [ ] Split APK/APKS installation with validation and clear error reporting
- [ ] Export installed APKs and splits; clearly warn that app data is not included
- [ ] Local APK library with search, version metadata, and batch installation
- [ ] Multi-file upload to the Android Downloads folder
- [ ] Drag-and-drop APK installation and preset application

### Advanced device tools
- [ ] Built-in ADB shell with command history and favorite commands
- [ ] Logcat viewer with filters, save-to-file, and stop controls
- [ ] Process and memory information where supported by the Android version
- [ ] Permission manager using Android package-manager commands, with capability warnings
- [ ] Resolution and DPI controls with reset actions
- [ ] Reboot to system, recovery, and bootloader
- [ ] Optional scrcpy integration for screen viewing and control
- [x] Android 11+ wireless debugging pairing and connection workflow
- [x] Legacy TCP/IP-over-USB workflow
- [ ] Multiple-device connection history
- [ ] Connection history and device profiles

### Usability and safety
- [ ] Dark/light theme and adjustable font/list sizing
- [ ] App metadata lookup links to independent public sources
- [ ] ADB key-file protection using OS-provided secure storage where available
- [ ] Operation queue, progress, cancellation where safe, and exportable logs
- [ ] Explicit warnings for system packages, permission changes, data clearing, shell commands, and reboot actions
- [ ] Expand automated tests beyond package parsing and run device-independent regression checks; Windows/Linux packaging verification is run in GitHub Actions

## Implementation order

1. Batch package operations, package state, presets, debloat recommendations, and connected-device disabled/uninstalled app history.
2. APK installation/export, multi-file transfer, and local APK library.
3. Shell, logcat, permissions, resolution/DPI, and reboot tools.
4. Process information, multi-device connection history, drag-and-drop, scrcpy integration, customization, and secure key handling.

Features will be marked complete only after implementation and a successful build/test. Some capabilities depend on the Android version, OEM restrictions, host permissions, or external tools such as scrcpy.
