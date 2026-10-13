# NightLab AMBridge

Android companion for the independent NightLab ADB App Manager project.

- **Application ID:** `com.nightlab.ambridge`
- **Version:** 1.0.0
- **Minimum Android:** 10 (API 29)
- **Purpose:** Supply installed app labels, package IDs, versions, app type, and PNG icons directly to the desktop app.

## Desktop integration protocol (v1)

1. The desktop launches the companion activity using authorized ADB.
2. The desktop creates a temporary host port with `adb forward tcp:0 tcp:39876`.
3. The Android activity runs a read-only HTTP endpoint on device loopback at `127.0.0.1:39876`.
4. The desktop requests `GET /v1/apps`, validates schema version 1, then removes its temporary ADB forward.
5. The response contains device details and an `applications` array with `packageName`, `label`, `versionName`, `versionCode`, `systemApp`, and `iconPngBase64` fields.

The endpoint binds to Android loopback rather than a Wi-Fi interface. ADB forwarding requires an authorized ADB connection and the bridge provides read-only metadata; it cannot run shell commands. Keep the phone unlocked while starting the companion. Android may stop background activities under memory pressure, so the desktop reports an actionable error if the endpoint is unavailable.

## Export option

The companion also retains the local JSON export button for manual diagnostics and backup. Exported data is saved to `Downloads/NightLab AMBridge/nightlab-ambridge-app-metadata.json`.

The `QUERY_ALL_PACKAGES` permission is used because the app's core purpose is to inventory installed packages for the user's own device-management workflow. Google Play distribution may require a permission declaration and policy review.

## Build

Open this `ambridge` folder in Android Studio and build the debug APK, or use the repository's **Build NightLab AMBridge APK** GitHub Actions workflow. The workflow uploads `app-debug.apk` as an artifact. This is a debug APK for testing, not a production-signed release.
