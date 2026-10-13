# NightLab AMBridge

Android companion for the independent NightLab ADB App Manager project.

- **Application ID:** `com.nightlab.ambridge`
- **Version:** 1.0.0
- **Minimum Android:** 8.0 (API 26)
- **Purpose:** Export locally installed app labels, package IDs, versions, app type, and PNG icons for desktop metadata import.

## What this first version does

1. Reads the installed application list using Android's package manager.
2. Converts each app icon into PNG data embedded as Base64.
3. Exports one JSON file to `Downloads/NightLab AMBridge/nightlab-ambridge-app-metadata.json`.
4. Keeps processing local on the phone; it does not upload metadata to a server.

The `QUERY_ALL_PACKAGES` permission is used because the app's core purpose is to inventory installed packages for the user's own device-management workflow. Google Play distribution may require a permission declaration and policy review.

## Build

Open this `ambridge` folder in Android Studio and build the debug APK, or use the repository's **Build NightLab AMBridge APK** GitHub Actions workflow. The workflow uploads `app-debug.apk` as an artifact.

The first version exports metadata but does not yet automatically transfer the file over ADB or parse the exported JSON in the desktop UI. Those are follow-up integration steps; do not treat the companion as connected until the desktop importer is implemented and tested.
