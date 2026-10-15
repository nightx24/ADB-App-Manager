# OxygenOS / ColorOS OEM debloat guide

This guide is built into ADB App Manager's **OEM Debloat Guide** window. It is a curated reference for common OnePlus/OPlus/HeyTap/Google package IDs, not a universal complete inventory and not a guarantee that any package is safe on every device.

## Before you debloat

1. Load the package list from your connected phone and check that the exact package ID is present.
2. Check the model, region, Android version, OxygenOS version and app label. The same feature may use different package IDs on different releases.
3. Prefer **Disable** or uninstall-for-user only after reviewing the impact. Neither action is guaranteed to be reversible for every OEM package.
4. Make a backup. APK backup does not include private app data, login sessions or settings.
5. Change one package at a time, then test calls, SMS, mobile data, Wi-Fi, Bluetooth, camera, notifications, gestures, launcher, updates and the features you use.
6. Keep another keyboard installed and tested before changing the keyboard package. Keep the stock launcher and core system providers.
7. If a system package causes trouble, try `adb shell cmd package install-existing PACKAGE_ID` for a package uninstalled only for the current user, or `adb shell pm enable --user 0 PACKAGE_ID` for a disabled package. These commands do not guarantee recovery on every build.

## Risk labels

- **Low — optional app:** generally a user-facing app; removing it usually loses that app only, but verify your usage.
- **Conditional — feature loss:** expected to remove a specific feature; keep it if you use that feature.
- **Review first:** the exact role or dependencies vary by OS build. Do not treat these as safe/isolated.
- **High / Critical — keep:** shown as a warning, not a removal recommendation.

**Dependency limitation:** Android package names alone do not expose all runtime or vendor dependencies. ADB App Manager cannot prove that a package has no dependencies just by seeing it in the installed package list. The “features affected / dependencies” column records known or plausible impacts and explicitly marks uncertain cases.

## Curated package reference

| Package ID | App | Function | Risk | Features affected / dependencies |
|---|---|---|---|---|
| `com.oneplus.gamespace` | OnePlus Game Space | Game launcher, gaming tools and in-game overlay. | **Conditional — feature loss** | Loses Game Space overlay, game profiles and any gaming features integrated with this package. No universal package dependency guarantee; newer builds may use OPlus packages. |
| `com.oplus.games` | OPlus Games platform | OEM gaming hub / game services on some builds. | **Conditional — feature loss** | May affect Game Space or gaming recommendations. Package name and dependencies vary by OxygenOS build. |
| `com.oneplus.brickmode` | Zen Mode / Brick Mode (variant) | Focus or digital-wellbeing mode on some older builds. | **Conditional — feature loss** | Removes the matching focus feature if this exact package is present. Other versions use different package names; verify before acting. |
| `com.oneplus.zen` | Zen Mode (variant) | Focus / screen-time restriction feature on some builds. | **Conditional — feature loss** | Zen Mode may stop working. This package ID is not universal across OxygenOS versions. |
| `net.oneplus.forums` | OnePlus Community (variant) | Brand community forum application. | **Low — optional app** | Removes the community app only if this exact package is installed; does not remove the phone's core forum/network framework. |
| `com.oneplus.community` | OnePlus Community (variant) | Brand community forum application. | **Low — optional app** | Only the community app is expected to be lost. Package ID varies by region and OS release. |
| `com.oneplus.membership` | OnePlus Membership (variant) | Membership, offers or brand account benefits. | **Low — optional app** | Loses the membership/promotions app. Check whether warranty or regional account features rely on it. |
| `com.oplus.orelax` | O Relax | Relaxation audio and ambient sound application. | **Low — optional app** | Removes O Relax content and shortcuts; package may be absent on some builds. |
| `com.oplus.omoji` | Omoji | OEM avatar creation and related effects. | **Conditional — feature loss** | Omoji avatar features may disappear from supported apps or personalization surfaces. Exact integration differs by OS version. |
| `com.oplus.riderMode` | Rider Mode | Riding/driving focus features on supported regions/builds. | **Conditional — feature loss** | May remove ride-mode automation or its UI. Confirm the package's label on your own phone before changing it. |
| `com.oplus.linker` | OPlus Linker / cross-device service | May support cross-device connection or integration features. | **Review first — dependencies unclear** | Could break tablet/PC/device linking on builds that use it. Public lists disagree on its exact role; do not treat as universally safe. |
| `com.redteamobile.roaming` | ORoaming / travel data | Regional travel roaming or virtual-SIM service. | **Conditional — feature loss** | May disable the OEM travel-data service. Do not remove if you use it; mobile network core services are separate and must be kept. |
| `com.heytap.usercenter` | HeyTap / OPPO account center | OEM account sign-in and related account services. | **Review first — dependencies unclear** | May affect HeyTap cloud, account sync, themes or OEM apps. Keep if you use any HeyTap/OPlus account feature. |
| `com.heytap.market` | HeyTap App Market | OEM application store. | **Conditional — feature loss** | Removes the OEM store and its updates/recommendations. Keep Google Play Store or another trusted installer available. |
| `com.heytap.mcs` | HeyTap Push Service | Push notifications for some OEM applications. | **Review first — dependencies unclear** | May stop notifications from dependent HeyTap/OPlus apps. Google push notifications are separate, but some OEM apps may lose alerts. |
| `com.oplus.aiunit` | OPlus AI Unit | OEM AI framework/service used by selected features on some builds. | **Review first — dependencies unclear** | Could affect AI features, assistant surfaces or other OPlus components. Do not assume it is telemetry-only or safe to remove. |
| `com.oplus.ai.service` | OPlus AI Service (variant) | Possible OEM AI service; availability and purpose vary by build. | **Review first — dependencies unclear** | Could affect AI search, summaries, translation or camera/gallery features if linked on your OS. Verify app label and dependencies first. |
| `com.oplus.statistics.rom` | OPlus statistics / user experience service | OEM statistics or user-experience reporting on some ColorOS-based builds. | **Review first — verify build** | May affect diagnostics or OEM services; exact behavior varies. Do not promise battery or performance gains from removing it. |
| `com.oplus.logkit` | OPlus Log Kit | System logging and diagnostic collection. | **Review first — verify build** | Could reduce access to OEM diagnostics/logging. Do not remove if you need service diagnostics or if another system component depends on it. |
| `com.oplus.crashbox` | OPlus CrashBox | OEM crash/diagnostic reporting on some builds. | **Review first — verify build** | May affect crash reports or service troubleshooting; removing it is not guaranteed to improve battery life. |
| `com.opos.ads` | OPlus commercial/ad service (variant) | Commercial content or promotional services on some builds. | **Review first — verify build** | May remove promotional content but can be linked to OEM content surfaces. Confirm package label and region first. |
| `com.coloros.floatassistant` | Smart Sidebar / floating assistant (variant) | Floating shortcuts or sidebar tools. | **Conditional — feature loss** | May disable floating sidebar/shortcut features. Don't remove if you use the sidebar or accessibility shortcuts. |
| `com.oplus.smartengine` | OPlus Smart Engine | OEM smart-card, context or system recommendation features on some builds. | **Review first — dependencies unclear** | May affect Shelf/smart cards or other context features. Avoid blind removal because its role differs by OS version. |
| `com.microsoft.appmanager` | Microsoft App Manager / Link to Windows (variant) | Microsoft cross-device integration on some phones. | **Low — optional app** | May disable Link to Windows integration. Package IDs vary; keep if you use phone-to-PC sync. |
| `com.netflix.mediaclient` | Netflix | Streaming application. | **Low — optional app** | Removes Netflix from this user; it can usually be reinstalled from a trusted app store if compatible. |
| `com.google.android.gm` | Gmail | Email client. | **Low — optional app** | Only removes the Gmail app; email accounts and Google Play Services are separate. Keep another email app if needed. |
| `com.google.android.apps.docs` | Google Drive | Cloud storage app; package may also be used by Docs integrations. | **Low — optional app** | Removes the Drive UI app. Verify that files are synced and another client is available before removal. |
| `com.google.android.apps.tachyon` | Google Meet | Video calling application. | **Low — optional app** | Removes Meet if this package ID is used; some builds use a different package name. |
| `com.google.android.videos` | Google TV / Play Movies (variant) | Video library / streaming app. | **Low — optional app** | Removes this video app; purchased content and other Google services are separate. |
| `com.google.android.youtube` | YouTube | Video streaming app. | **Low — optional app** | Removes YouTube app only. You may lose YouTube links opening in the app; browser access remains possible. |
| `com.google.android.apps.youtube.music` | YouTube Music | Music streaming app. | **Low — optional app** | Removes YouTube Music; downloaded music inside the app will no longer be accessible through it. |
| `com.google.android.apps.subscriptions.red` | Google One | Google One subscription/storage management app. | **Low — optional app** | Removes the management app, not necessarily the underlying subscription or cloud-stored data. |
| `com.google.android.apps.chromecast.app` | Google Home | Smart-home and Cast device management. | **Low — optional app** | Removes Google Home controls; keep it if you manage smart-home devices or Chromecast. |
| `com.google.ar.lens` | Google Lens (variant) | Visual search and image recognition. | **Low — optional app** | Lens entry points may stop working in apps that rely on this package. Package may differ by build. |
| `com.google.android.apps.wellbeing` | Digital Wellbeing | Screen-time, focus and bedtime tools. | **Conditional — feature loss** | Removes screen-time/focus dashboards and related features; don't remove if you rely on Focus Mode or bedtime routines. |
| `com.oneplus.backuprestore` | Clone Phone / OnePlus migration (variant) | Local device-to-device data migration on some OxygenOS builds. | **Conditional — feature loss** | Removes the matching migration tool. Use another tested transfer/backup method before removing; package names vary by version. |
| `com.coloros.backuprestore` | Clone Phone / ColorOS migration (variant) | OEM data transfer and backup/migration components on some builds. | **Review first — dependencies unclear** | May affect local migration, restore or related OEM backup flows. Confirm the exact app label and any remote-service dependency first. |
| `com.google.android.apps.photos` | Google Photos | Photo gallery, cloud backup and media management. | **Low — optional app** | Removes Google Photos UI and its photo backup/gallery features. Verify photos are backed up and another gallery is available. |
| `com.google.android.googlequicksearchbox` | Google app / Search / Assistant | Google search, Discover and some Assistant entry points. | **Conditional — feature loss** | May remove Google search widget, Discover feed, voice assistant entry points or integrations. Do not remove if you use these features. |
| `com.coloros.childrenspace` | Kids Space / Children's Space (variant) | Child-oriented profile or restricted-use environment on some builds. | **Conditional — feature loss** | Removes the child-mode app if this exact package is present. Package names and system integration vary by region/build. |
| `com.google.android.gms` | Google Play services — KEEP | Core Google APIs, account/sync, push, location and app integration. | **High — do not remove** | Removing/disabling can break sign-in, push notifications, location and many apps. Not a debloat recommendation. |
| `com.android.providers.telephony` | Telephony provider — KEEP | Core SMS/MMS and telephony database/provider. | **Critical — do not remove** | Can break SMS, telephony-related functions and emergency-related workflows. Never debloat. |
| `com.android.systemui` | System UI — KEEP | Status bar, navigation, quick settings and lock screen. | **Critical — do not remove** | Can make the device difficult or impossible to use normally. Never debloat. |
| `com.android.settings` | Android Settings — KEEP | System settings application. | **Critical — do not remove** | Can remove access to device configuration and recovery options. Never debloat. |
| `com.google.android.inputmethod.latin` | Gboard — KEEP unless replacement tested | Google keyboard / input method. | **High — keep a replacement first** | Removing the only enabled keyboard can prevent text entry during setup or recovery. Install and test another keyboard first. |
| `com.oplus.launcher` | OPlus launcher — KEEP | OEM home screen and launcher integration. | **High — keep** | May break home screen, gestures, widgets or recent-task integrations. Do not remove based on third-party launcher availability alone. |
| `com.oneplus.launcher` | OnePlus launcher — KEEP | OEM home screen and launcher integration on some builds. | **High — keep** | May break home screen, gestures, widgets or recents integration. Keep even if a third-party launcher is installed. |

## What this list does not mean

- “Not listed” does not mean safe or unsafe.
- “Low risk” does not guarantee compatibility with every model, regional firmware or OTA update.
- Removing AI, analytics or push services is not guaranteed to improve battery life or performance.
- Some entries are variants/aliases; only act on the exact package ID installed on the connected device.
- Do not remove Android System UI, Settings, telephony providers, Google Play services, your only keyboard, or the OEM launcher.

## Sources and limitations

This reference was cross-checked against public community debloat repositories, including [Debloater Enhanced](https://github.com/OshekharO/Debloater-Enhanced), [OnePlus/ColorOS debloat scripts](https://github.com/aiy365/oneplus-coloros-debloat), and [community discussions on OxygenOS packages](https://www.reddit.com/r/oneplus/). These are community-maintained lists, not official OnePlus dependency documentation; some entries may be inaccurate or outdated. Confirm behavior on your own device before changing anything.

The app never automatically removes packages from this guide. Selecting entries only checks them in the App library so you can review the actual installed package before choosing an action.
