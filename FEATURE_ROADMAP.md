# Feature roadmap: ADB App Manager

This project implements its own feature set inspired by common Android device-management workflows. It does not copy ADB AppControl's proprietary implementation, artwork, branding, or license system.

## Planned feature parity

### Package management
- [ ] Multi-select and safe batch disable/enable/uninstall
- [x] Conservative exact-package debloat guidance with conditional risk labels and a review-only filter
- [ ] Device/OEM-aware recommendations and editable debloat presets
- [ ] Restore packages uninstalled for the current Android user
- [ ] App-data clearing with an explicit data-loss confirmation
- [ ] Show app label, version, install source, enabled state, and package size where Android exposes the information
- [ ] Sort by name, package, size, and app type

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
- [ ] Automated tests and Windows/Linux packaging verification

## Implementation order

1. Batch package operations, package state, presets, and debloat recommendations.
2. APK installation/export, multi-file transfer, and local APK library.
3. Shell, logcat, permissions, resolution/DPI, and reboot tools.
4. Process information, multi-device connection history, drag-and-drop, scrcpy integration, customization, and secure key handling.

Features will be marked complete only after implementation and a successful build/test. Some capabilities depend on the Android version, OEM restrictions, host permissions, or external tools such as scrcpy.
