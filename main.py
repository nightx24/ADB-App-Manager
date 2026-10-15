from __future__ import annotations

import base64
import csv
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QStandardPaths
from PySide6.QtGui import QAction, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QHeaderView, QInputDialog,
    QStackedWidget, QFrame, QDialog, QCheckBox, QListWidget, QListWidgetItem, QProgressBar,
)

APP_NAME = "ADB App Manager"


def _host_tool_env() -> dict[str, str]:
    """Return an environment safe for launching host binaries from a frozen app.

    PyInstaller one-file builds prepend their extraction directory to
    LD_LIBRARY_PATH. Passing that to the system ADB executable can make ADB
    load the bundled libstdc++ instead of the host version and fail with
    GLIBCXX/CXXABI symbol errors. Restore the original loader path for every
    subprocess that invokes ADB, not only the general command worker.
    """
    child_env = os.environ.copy()
    if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        original = child_env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is not None:
            if original:
                child_env["LD_LIBRARY_PATH"] = original
            else:
                child_env.pop("LD_LIBRARY_PATH", None)
        else:
            current = child_env.get("LD_LIBRARY_PATH", "")
            safe_paths = [p for p in current.split(":") if p and "_MEI" not in p]
            if safe_paths:
                child_env["LD_LIBRARY_PATH"] = ":".join(safe_paths)
            else:
                child_env.pop("LD_LIBRARY_PATH", None)
    return child_env


# Conservative, exact-package recommendations adapted from public debloat research.
# These are conditional suggestions, not guarantees. Never auto-remove any package.
def parse_package_names(output: str) -> list[str]:
    """Parse unique package names from Android package-manager output."""
    names: list[str] = []
    seen: set[str] = set()
    for line in output.splitlines():
        value = line.strip()
        if not value.startswith("package:"):
            continue
        name = value[len("package:"):].strip()
        if name and name not in seen:
            names.append(name)
            seen.add(name)
    return names


DEBLOAT_RECOMMENDATIONS: dict[str, tuple[str, str]] = {
    "org.lineageos.jelly": (
        "Optional — review first",
        "LineageOS browser. Remove only if you have another working browser and do not need this one.",
    ),
    "org.lineageos.recorder": (
        "Optional — review first",
        "LineageOS voice recorder. Remove only if you do not use it or have another recorder.",
    ),
    "org.lineageos.twelve": (
        "Optional — review first",
        "LineageOS music player. Remove only if you use another music player.",
    ),
    "org.lineageos.camelot": (
        "Optional — review first",
        "LineageOS PDF viewer. Remove only if another app can open your PDF files.",
    ),
    "org.lineageos.aperture": (
        "Advanced — verify first",
        "LineageOS camera app. Removing it without a working replacement can leave you without a camera app.",
    ),
    "org.lineageos.etar": (
        "Advanced — verify first",
        "LineageOS calendar. Removing it without a replacement can remove calendar functionality.",
    ),
    "org.lineageos.glimpse": (
        "Advanced — verify first",
        "LineageOS gallery. Removing it without a replacement can leave you without a gallery app.",
    ),
    "com.android.providers.partnerbrowsercustomizations": (
        "Optional — review first",
        "Chrome partner-browser customizations. Relevance depends on the ROM and browser setup; do not remove blindly.",
    ),
}



# Curated OxygenOS / ColorOS debloat reference
# This is a review guide, not an automatically safe-to-remove database.
OEM_DEBLOAT_GUIDE: list[dict[str, str]] = [
    {"package": "com.oneplus.gamespace", "app": "OnePlus Game Space", "function": "Game launcher, gaming tools and in-game overlay.", "risk": "Conditional — feature loss", "impact": "Loses Game Space overlay, game profiles and any gaming features integrated with this package. No universal package dependency guarantee; newer builds may use OPlus packages."},
    {"package": "com.oplus.games", "app": "OPlus Games platform", "function": "OEM gaming hub / game services on some builds.", "risk": "Conditional — feature loss", "impact": "May affect Game Space or gaming recommendations. Package name and dependencies vary by OxygenOS build."},
    {"package": "com.oneplus.brickmode", "app": "Zen Mode / Brick Mode (variant)", "function": "Focus or digital-wellbeing mode on some older builds.", "risk": "Conditional — feature loss", "impact": "Removes the matching focus feature if this exact package is present. Other versions use different package names; verify before acting."},
    {"package": "com.oneplus.zen", "app": "Zen Mode (variant)", "function": "Focus / screen-time restriction feature on some builds.", "risk": "Conditional — feature loss", "impact": "Zen Mode may stop working. This package ID is not universal across OxygenOS versions."},
    {"package": "net.oneplus.forums", "app": "OnePlus Community (variant)", "function": "Brand community forum application.", "risk": "Low — optional app", "impact": "Removes the community app only if this exact package is installed; does not remove the phone's core forum/network framework."},
    {"package": "com.oneplus.community", "app": "OnePlus Community (variant)", "function": "Brand community forum application.", "risk": "Low — optional app", "impact": "Only the community app is expected to be lost. Package ID varies by region and OS release."},
    {"package": "com.oneplus.membership", "app": "OnePlus Membership (variant)", "function": "Membership, offers or brand account benefits.", "risk": "Low — optional app", "impact": "Loses the membership/promotions app. Check whether warranty or regional account features rely on it."},
    {"package": "com.oplus.orelax", "app": "O Relax", "function": "Relaxation audio and ambient sound application.", "risk": "Low — optional app", "impact": "Removes O Relax content and shortcuts; package may be absent on some builds."},
    {"package": "com.oplus.omoji", "app": "Omoji", "function": "OEM avatar creation and related effects.", "risk": "Conditional — feature loss", "impact": "Omoji avatar features may disappear from supported apps or personalization surfaces. Exact integration differs by OS version."},
    {"package": "com.oplus.riderMode", "app": "Rider Mode", "function": "Riding/driving focus features on supported regions/builds.", "risk": "Conditional — feature loss", "impact": "May remove ride-mode automation or its UI. Confirm the package's label on your own phone before changing it."},
    {"package": "com.oplus.linker", "app": "OPlus Linker / cross-device service", "function": "May support cross-device connection or integration features.", "risk": "Review first — dependencies unclear", "impact": "Could break tablet/PC/device linking on builds that use it. Public lists disagree on its exact role; do not treat as universally safe."},
    {"package": "com.redteamobile.roaming", "app": "ORoaming / travel data", "function": "Regional travel roaming or virtual-SIM service.", "risk": "Conditional — feature loss", "impact": "May disable the OEM travel-data service. Do not remove if you use it; mobile network core services are separate and must be kept."},
    {"package": "com.heytap.usercenter", "app": "HeyTap / OPPO account center", "function": "OEM account sign-in and related account services.", "risk": "Review first — dependencies unclear", "impact": "May affect HeyTap cloud, account sync, themes or OEM apps. Keep if you use any HeyTap/OPlus account feature."},
    {"package": "com.heytap.market", "app": "HeyTap App Market", "function": "OEM application store.", "risk": "Conditional — feature loss", "impact": "Removes the OEM store and its updates/recommendations. Keep Google Play Store or another trusted installer available."},
    {"package": "com.heytap.mcs", "app": "HeyTap Push Service", "function": "Push notifications for some OEM applications.", "risk": "Review first — dependencies unclear", "impact": "May stop notifications from dependent HeyTap/OPlus apps. Google push notifications are separate, but some OEM apps may lose alerts."},
    {"package": "com.oplus.aiunit", "app": "OPlus AI Unit", "function": "OEM AI framework/service used by selected features on some builds.", "risk": "Review first — dependencies unclear", "impact": "Could affect AI features, assistant surfaces or other OPlus components. Do not assume it is telemetry-only or safe to remove."},
    {"package": "com.oplus.ai.service", "app": "OPlus AI Service (variant)", "function": "Possible OEM AI service; availability and purpose vary by build.", "risk": "Review first — dependencies unclear", "impact": "Could affect AI search, summaries, translation or camera/gallery features if linked on your OS. Verify app label and dependencies first."},
    {"package": "com.oplus.statistics.rom", "app": "OPlus statistics / user experience service", "function": "OEM statistics or user-experience reporting on some ColorOS-based builds.", "risk": "Review first — verify build", "impact": "May affect diagnostics or OEM services; exact behavior varies. Do not promise battery or performance gains from removing it."},
    {"package": "com.oplus.logkit", "app": "OPlus Log Kit", "function": "System logging and diagnostic collection.", "risk": "Review first — verify build", "impact": "Could reduce access to OEM diagnostics/logging. Do not remove if you need service diagnostics or if another system component depends on it."},
    {"package": "com.oplus.crashbox", "app": "OPlus CrashBox", "function": "OEM crash/diagnostic reporting on some builds.", "risk": "Review first — verify build", "impact": "May affect crash reports or service troubleshooting; removing it is not guaranteed to improve battery life."},
    {"package": "com.opos.ads", "app": "OPlus commercial/ad service (variant)", "function": "Commercial content or promotional services on some builds.", "risk": "Review first — verify build", "impact": "May remove promotional content but can be linked to OEM content surfaces. Confirm package label and region first."},
    {"package": "com.coloros.floatassistant", "app": "Smart Sidebar / floating assistant (variant)", "function": "Floating shortcuts or sidebar tools.", "risk": "Conditional — feature loss", "impact": "May disable floating sidebar/shortcut features. Don't remove if you use the sidebar or accessibility shortcuts."},
    {"package": "com.oplus.smartengine", "app": "OPlus Smart Engine", "function": "OEM smart-card, context or system recommendation features on some builds.", "risk": "Review first — dependencies unclear", "impact": "May affect Shelf/smart cards or other context features. Avoid blind removal because its role differs by OS version."},
    {"package": "com.microsoft.appmanager", "app": "Microsoft App Manager / Link to Windows (variant)", "function": "Microsoft cross-device integration on some phones.", "risk": "Low — optional app", "impact": "May disable Link to Windows integration. Package IDs vary; keep if you use phone-to-PC sync."},
    {"package": "com.netflix.mediaclient", "app": "Netflix", "function": "Streaming application.", "risk": "Low — optional app", "impact": "Removes Netflix from this user; it can usually be reinstalled from a trusted app store if compatible."},
    {"package": "com.google.android.gm", "app": "Gmail", "function": "Email client.", "risk": "Low — optional app", "impact": "Only removes the Gmail app; email accounts and Google Play Services are separate. Keep another email app if needed."},
    {"package": "com.google.android.apps.docs", "app": "Google Drive", "function": "Cloud storage app; package may also be used by Docs integrations.", "risk": "Low — optional app", "impact": "Removes the Drive UI app. Verify that files are synced and another client is available before removal."},
    {"package": "com.google.android.apps.tachyon", "app": "Google Meet", "function": "Video calling application.", "risk": "Low — optional app", "impact": "Removes Meet if this package ID is used; some builds use a different package name."},
    {"package": "com.google.android.videos", "app": "Google TV / Play Movies (variant)", "function": "Video library / streaming app.", "risk": "Low — optional app", "impact": "Removes this video app; purchased content and other Google services are separate."},
    {"package": "com.google.android.youtube", "app": "YouTube", "function": "Video streaming app.", "risk": "Low — optional app", "impact": "Removes YouTube app only. You may lose YouTube links opening in the app; browser access remains possible."},
    {"package": "com.google.android.apps.youtube.music", "app": "YouTube Music", "function": "Music streaming app.", "risk": "Low — optional app", "impact": "Removes YouTube Music; downloaded music inside the app will no longer be accessible through it."},
    {"package": "com.google.android.apps.subscriptions.red", "app": "Google One", "function": "Google One subscription/storage management app.", "risk": "Low — optional app", "impact": "Removes the management app, not necessarily the underlying subscription or cloud-stored data."},
    {"package": "com.google.android.apps.chromecast.app", "app": "Google Home", "function": "Smart-home and Cast device management.", "risk": "Low — optional app", "impact": "Removes Google Home controls; keep it if you manage smart-home devices or Chromecast."},
    {"package": "com.google.ar.lens", "app": "Google Lens (variant)", "function": "Visual search and image recognition.", "risk": "Low — optional app", "impact": "Lens entry points may stop working in apps that rely on this package. Package may differ by build."},
    {"package": "com.google.android.apps.wellbeing", "app": "Digital Wellbeing", "function": "Screen-time, focus and bedtime tools.", "risk": "Conditional — feature loss", "impact": "Removes screen-time/focus dashboards and related features; don't remove if you rely on Focus Mode or bedtime routines."},
    {"package": "com.oneplus.backuprestore", "app": "Clone Phone / OnePlus migration (variant)", "function": "Local device-to-device data migration on some OxygenOS builds.", "risk": "Conditional — feature loss", "impact": "Removes the matching migration tool. Use another tested transfer/backup method before removing; package names vary by version."},
    {"package": "com.coloros.backuprestore", "app": "Clone Phone / ColorOS migration (variant)", "function": "OEM data transfer and backup/migration components on some builds.", "risk": "Review first — dependencies unclear", "impact": "May affect local migration, restore or related OEM backup flows. Confirm the exact app label and any remote-service dependency first."},
    {"package": "com.google.android.apps.photos", "app": "Google Photos", "function": "Photo gallery, cloud backup and media management.", "risk": "Low — optional app", "impact": "Removes Google Photos UI and its photo backup/gallery features. Verify photos are backed up and another gallery is available."},
    {"package": "com.google.android.googlequicksearchbox", "app": "Google app / Search / Assistant", "function": "Google search, Discover and some Assistant entry points.", "risk": "Conditional — feature loss", "impact": "May remove Google search widget, Discover feed, voice assistant entry points or integrations. Do not remove if you use these features."},
    {"package": "com.coloros.childrenspace", "app": "Kids Space / Children's Space (variant)", "function": "Child-oriented profile or restricted-use environment on some builds.", "risk": "Conditional — feature loss", "impact": "Removes the child-mode app if this exact package is present. Package names and system integration vary by region/build."},
    {"package": "com.google.android.gms", "app": "Google Play services — KEEP", "function": "Core Google APIs, account/sync, push, location and app integration.", "risk": "High — do not remove", "impact": "Removing/disabling can break sign-in, push notifications, location and many apps. Not a debloat recommendation."},
    {"package": "com.android.providers.telephony", "app": "Telephony provider — KEEP", "function": "Core SMS/MMS and telephony database/provider.", "risk": "Critical — do not remove", "impact": "Can break SMS, telephony-related functions and emergency-related workflows. Never debloat."},
    {"package": "com.android.systemui", "app": "System UI — KEEP", "function": "Status bar, navigation, quick settings and lock screen.", "risk": "Critical — do not remove", "impact": "Can make the device difficult or impossible to use normally. Never debloat."},
    {"package": "com.android.settings", "app": "Android Settings — KEEP", "function": "System settings application.", "risk": "Critical — do not remove", "impact": "Can remove access to device configuration and recovery options. Never debloat."},
    {"package": "com.google.android.inputmethod.latin", "app": "Gboard — KEEP unless replacement tested", "function": "Google keyboard / input method.", "risk": "High — keep a replacement first", "impact": "Removing the only enabled keyboard can prevent text entry during setup or recovery. Install and test another keyboard first."},
    {"package": "com.oplus.launcher", "app": "OPlus launcher — KEEP", "function": "OEM home screen and launcher integration.", "risk": "High — keep", "impact": "May break home screen, gestures, widgets or recent-task integrations. Do not remove based on third-party launcher availability alone."},
    {"package": "com.oneplus.launcher", "app": "OnePlus launcher — KEEP", "function": "OEM home screen and launcher integration on some builds.", "risk": "High — keep", "impact": "May break home screen, gestures, widgets or recents integration. Keep even if a third-party launcher is installed."},,
    {"package":"com.oppo.launcher","app":"OPPO Launcher (variant) — KEEP","function":"OEM home screen and launcher integration on some ColorOS builds.","risk":"High — keep","impact":"Removing the active home launcher can leave no usable home screen and may disrupt gestures or recents. Package IDs differ by device; keep the active OEM launcher."},
    {"package":"com.oplus.uiengine","app":"OPlus UI Engine (variant) — KEEP / REVIEW","function":"OEM UI or theme-related service on some builds; exact role is version-dependent.","risk":"Review first — dependencies unclear","impact":"The exact dependency role is not consistently documented across builds. Do not assume it is responsible for all screen rendering, but do not debloat it without device-specific evidence."},
    {"package":"com.oplus.deepthinker","app":"OPlus DeepThinker — KEEP / REVIEW","function":"OEM context-aware intelligence, app prediction or smart-service components on some builds.","risk":"Review first — dependencies unclear","impact":"May support OEM smart features or background recommendations. Claims that it universally controls Android memory allocation or causes bootloops if removed are not established for every build."},
    {"package":"com.oplus.strategy","app":"OPlus Strategy Service (variant)","function":"OEM device strategy or configuration service on some builds.","risk":"Review first — dependencies unclear","impact":"Its exact responsibilities and dependencies vary. Do not assume it directly controls thermal safety or CPU frequency without build-specific evidence."},
    {"package":"com.oplus.performance","app":"OPlus Performance Service (variant)","function":"OEM performance-related service on some builds.","risk":"Review first — dependencies unclear","impact":"May be linked to OEM performance modes. Thermal management and CPU scheduling also involve Android kernel/vendor components; removing this package is not proven to cause a specific refresh-rate or overheating outcome on every phone."},
    {"package":"com.android.phone","app":"Phone Services — KEEP","function":"Android telephony framework service for cellular calling and related functions.","risk":"Critical — do not remove","impact":"Can break cellular calling, SIM registration or other telephony functions. Keep."},
    {"package":"com.oplus.wireless","app":"OPlus Wireless Service (variant)","function":"OEM wireless/connectivity-related service on some builds.","risk":"Review first — dependencies unclear","impact":"Exact role varies and the name alone does not prove it controls all Wi-Fi or Bluetooth drivers. Do not remove without confirming the package purpose on the device."},
    {"package":"com.android.keyguard","app":"Keyguard (variant) — KEEP","function":"Lock-screen / keyguard components on builds that expose this package.","risk":"Critical — do not remove","impact":"Lock-screen implementation is integrated with System UI and other framework services; removing a keyguard-related package can compromise lock-screen access. Package may be absent or represented differently on modern Android."},
    {"package":"com.oplus.biometric.fingerprint","app":"OPlus Fingerprint Service (variant)","function":"Possible OEM fingerprint-related service on some builds.","risk":"Review first — dependencies unclear","impact":"If this exact package handles a device's fingerprint integration, disabling it can break fingerprint unlock. Verify the label and package on the phone; sensor HAL/vendor services are also involved."},
    {"package":"com.google.android.gsf","app":"Google Services Framework — KEEP","function":"Google service registration and framework integration used by some Google components.","risk":"High — do not remove","impact":"Removing it can disrupt Google account/device registration or services on many builds. Keep unless you intentionally run a configuration without Google services and understand the consequences."},
    {"package":"com.google.android.packageinstaller","app":"Google Package Installer (variant) — KEEP","function":"Package installation UI/component on some Android builds.","risk":"High — do not remove","impact":"May disrupt APK installation or confirmation flows. Modern Android may use a different package or installer arrangement; keep the active system installer."},
    {"package":"com.google.android.permissioncontroller","app":"Permission Controller — KEEP","function":"Android runtime permission and privacy-control UI/services.","risk":"Critical — do not remove","impact":"Can break permission management and app permission prompts. Keep."},
    {"package":"com.google.android.webview","app":"Android System WebView — KEEP a working provider","function":"Embedded web-content rendering used by many apps.","risk":"High — keep a working provider","impact":"Do not remove or disable the only enabled WebView provider. Some devices use a different provider or Chrome implementation; check Developer options / WebView provider before changing it."},
    {"package":"com.google.android.tts","app":"Speech Services by Google (variant)","function":"Text-to-speech voice engine on many builds.","risk":"Conditional — feature loss","impact":"May remove Google TTS voices and affect apps or accessibility features that rely on this engine. Keep another configured speech engine if you need spoken feedback."},
    {"package":"com.android.chrome","app":"Google Chrome","function":"Web browser and, on some configurations, a WebView provider.","risk":"Conditional — feature loss","impact":"Usually optional if another browser is installed, but check whether Chrome is the active WebView provider before disabling it."},
    {"package":"com.google.android.apps.maps","app":"Google Maps","function":"Maps, navigation and location-based app UI.","risk":"Low — optional app","impact":"Removes the Maps app and navigation UI. Other apps may still use Android location APIs, but Maps-specific intents or integrations may no longer open."},
    {"package":"com.google.android.apps.walletnfcrel","app":"Google Wallet","function":"Payment cards, passes and supported tap-to-pay workflows.","risk":"Low — optional app","impact":"Removes Wallet UI and its payment/pass features. If you use tap-to-pay or stored passes, keep it; payment capability also depends on device, region and bank support."},
    {"package":"com.google.android.apps.fitness","app":"Google Fit (variant)","function":"Fitness activity tracking and health data UI.","risk":"Low — optional app","impact":"Removes Google Fit app features. Package ID may vary, and connected fitness apps may use separate services."},
    {"package":"com.google.android.apps.podcasts","app":"Google Podcasts (legacy)","function":"Legacy Google Podcasts app.","risk":"Low — optional app","impact":"Optional if present. Google Podcasts has been discontinued in many markets, so this package may not exist on current devices."},
    {"package":"com.google.android.as","app":"Android System Intelligence — KEEP / REVIEW","function":"On-device intelligence features such as smart text selection and other system suggestions; feature set varies by Android release.","risk":"Review first — dependencies unclear","impact":"Disabling can remove or degrade selected smart system features. It is not a universal battery-drain culprit; do not assume every listed feature is implemented by this package on every build."},
    {"package": "com.miui.msa.global", "app": "HyperOS: MSA (system ads)", "function": "Ad-related service on some Xiaomi builds.", "risk": "Review first — device-dependent", "impact": "Often associated with ads in Xiaomi apps, but exact behavior and dependencies vary by region/build. Prefer turning off recommendations in app settings first; test before disabling."},
    {"package": "com.miui.analytics", "app": "HyperOS: Xiaomi Analytics", "function": "Analytics/diagnostics component on some builds.", "risk": "Review first — device-dependent", "impact": "May affect diagnostics or usage reporting. Battery impact is not guaranteed; verify exact package label and test after changes."},
    {"package": "com.miui.daemon", "app": "HyperOS: MiuiDaemon", "function": "OEM background/diagnostic service on some builds.", "risk": "Review first — dependencies unclear", "impact": "Its role varies across MIUI/HyperOS versions. Do not assume it is only telemetry or dependency-free."},
    {"package": "com.xiaomi.joyose", "app": "HyperOS: Joyose", "function": "OEM service associated with device/game-related features on some builds.", "risk": "Review first — feature loss", "impact": "May affect gaming or OEM optimization behavior. Do not remove based on package name alone."},
    {"package": "com.xiaomi.glance.mds", "app": "HyperOS: Glance", "function": "Lock-screen content service on supported regions/devices.", "risk": "Conditional — feature loss", "impact": "May affect lock-screen content or Glance features if present. Regional availability and package role vary."},
    {"package": "com.miui.yellowpage", "app": "HyperOS: Yellow Pages", "function": "Caller/business lookup integration on some builds.", "risk": "Conditional — feature loss", "impact": "May remove business lookup or enhanced caller information. Test dialer and caller-ID behavior first."},
    {"package": "com.miui.bugreport", "app": "HyperOS: Bug report", "function": "OEM diagnostics/feedback reporting.", "risk": "Low — optional app", "impact": "May remove the ability to submit Xiaomi bug reports from this component; confirm it is not used by another diagnostics workflow."},
    {"package": "com.miui.miservice", "app": "HyperOS: Services & Feedback", "function": "Xiaomi service/feedback front end on some builds.", "risk": "Conditional — feature loss", "impact": "May remove service/support/feedback features. Exact dependencies vary."},
    {"package": "com.xiaomi.mipicks", "app": "HyperOS: GetApps", "function": "Xiaomi app marketplace.", "risk": "Low — optional app", "impact": "Only consider if you do not use GetApps or its app updates; keep a trusted app store available."},
    {"package": "com.miui.hybrid", "app": "HyperOS: Quick Apps", "function": "Mini-app framework on supported builds.", "risk": "Conditional — feature loss", "impact": "May break Quick Apps and shortcuts that rely on the framework."},
    {"package": "com.miui.hybrid.accessory", "app": "HyperOS: Quick Apps accessory", "function": "Supporting component for Quick Apps on some builds.", "risk": "Review first — dependencies unclear", "impact": "Treat as coupled to Quick Apps; do not remove independently unless you have tested the feature."},
    {"package": "com.miui.cloudservice", "app": "HyperOS: Xiaomi Cloud", "function": "Xiaomi account/cloud sync integration.", "risk": "Conditional — feature loss", "impact": "May affect Xiaomi Cloud sync, contacts or settings backup. Google backup is not a guaranteed replacement for every Xiaomi data type."},
    {"package": "com.miui.cloudservice.sysapp", "app": "HyperOS: Xiaomi Cloud system integration", "function": "System-facing Xiaomi Cloud integration.", "risk": "Review first — dependencies unclear", "impact": "May be used by other Xiaomi apps or sync workflows. Keep if using a Mi Account or Xiaomi Cloud."},
    {"package": "com.miui.cloudbackup", "app": "HyperOS: Cloud Backup", "function": "OEM backup integration on some builds.", "risk": "Review first — dependencies unclear", "impact": "May affect Xiaomi backup/restore flows. Confirm another backup works before changing."},
    {"package": "com.xiaomi.midrop", "app": "HyperOS: ShareMe", "function": "Peer-to-peer file transfer app.", "risk": "Low — optional app", "impact": "Removes ShareMe app functionality; use another transfer method if needed."},
    {"package": "com.miui.weather2", "app": "HyperOS: Mi Weather", "function": "Weather app and possible widgets.", "risk": "Low — optional app", "impact": "Remove only if you do not use its widgets, weather shortcuts or dependent home-screen features."},
    {"package": "com.miui.notes", "app": "HyperOS: Notes", "function": "Xiaomi notes app.", "risk": "Low — optional app", "impact": "Export or sync important notes first; verify the notes are accessible elsewhere."},
    {"package": "com.miui.compass", "app": "HyperOS: Compass", "function": "Compass utility.", "risk": "Low — optional app", "impact": "Removes the compass UI; the magnetometer hardware remains available to other apps."},
    {"package": "com.miui.calculator", "app": "HyperOS: Calculator", "function": "Calculator app.", "risk": "Low — optional app", "impact": "Keep another calculator installed and working before removing."},
    {"package": "com.android.soundrecorder", "app": "HyperOS: Sound Recorder", "function": "Voice recording app on some builds.", "risk": "Low — optional app", "impact": "Only remove if you do not use it; package may be shared by region-specific builds."},
    {"package": "com.miui.screenrecorder", "app": "HyperOS: Screen Recorder", "function": "Screen recording utility.", "risk": "Conditional — feature loss", "impact": "Removes or affects built-in screen recording. Check whether screenshots, game recording or control-center shortcuts depend on it."},
    {"package": "com.miui.videoplayer", "app": "HyperOS: Mi Video", "function": "Local video player and media portal.", "risk": "Conditional — feature loss", "impact": "Install and test another video player and file-intent handler before disabling."},
    {"package": "com.miui.player", "app": "HyperOS: Mi Music", "function": "Music player/media portal.", "risk": "Low — optional app", "impact": "Remove if unused; verify local audio files open in another player."},
    {"package": "com.miui.gallery", "app": "HyperOS: Gallery", "function": "Gallery and photo-management app.", "risk": "Review first — feature loss", "impact": "Camera thumbnail previews, editing, albums or Xiaomi-specific effects may depend on it. Test camera preview and photo editing before changing."},
    {"package": "com.milink.service", "app": "HyperOS: MiLink / UniPlay", "function": "Casting and wireless media integration on some builds.", "risk": "Conditional — feature loss", "impact": "May affect casting or connections to Xiaomi displays/speakers."},
    {"package": "com.miui.extraphoto", "app": "HyperOS: Gallery extras", "function": "Additional gallery/photo effects on some builds.", "risk": "Conditional — feature loss", "impact": "May remove special editing effects; exact feature set depends on the Gallery version."},
    {"package": "com.miui.mishare.connectivity", "app": "HyperOS: Mi Share connectivity", "function": "Nearby device sharing integration on some builds.", "risk": "Review first — dependencies unclear", "impact": "May affect Xiaomi/Oppo/Vivo/Realme cross-device sharing on supported builds. Verify the exact installed label and test sharing."},
    {"package": "com.miui.cleanmaster", "app": "HyperOS: Cleaner component", "function": "Cleaning feature associated with Xiaomi Security on some builds.", "risk": "Review first — dependencies unclear", "impact": "Do not assume this is isolated from Security app workflows. Prefer built-in settings to disable unwanted cleaning prompts."},
    {"package": "com.miui.securitycenter", "app": "HyperOS: Security Center — KEEP", "function": "Security, permissions and OEM device-management features.", "risk": "Critical — keep", "impact": "Do not disable or uninstall. May affect permissions, battery/device management, security and OEM features. Exact failure mode varies; treat as essential."},
    {"package": "com.xiaomi.finddevice", "app": "HyperOS: Find device — KEEP if used", "function": "Find-device and account security features.", "risk": "High — keep if enabled", "impact": "Disabling can weaken or break device-finding and account protection features. Keep if using Xiaomi account/device recovery; behavior varies by build."},
    {"package": "com.mi.android.globalminusscreen", "app": "HyperOS: App Vault / left screen", "function": "Launcher side-screen/content surface on some global builds.", "risk": "Conditional — feature loss", "impact": "May remove the left-side content pane. Prefer turning it off in Home Screen settings; package name varies."},
    {"package": "com.android.updater", "app": "HyperOS: System Updater — KEEP", "function": "System update client.", "risk": "Critical — keep", "impact": "Keep for official OTA updates and update notifications."},
    {"package": "com.samsung.android.bixby.agent", "app": "Samsung One UI: Bixby Voice", "function": "Bixby assistant app/service.", "risk": "Conditional — feature loss", "impact": "May remove Bixby features and integrations. Test side key, voice activation and routines before disabling."},
    {"package": "com.samsung.android.bixby.wakeup", "app": "Samsung One UI: Bixby Wakeup", "function": "Bixby voice wake-up component.", "risk": "Conditional — feature loss", "impact": "May disable Bixby wake-word activation; exact coupling varies by One UI version."},
    {"package": "com.samsung.android.app.settings.bixby", "app": "Samsung One UI: Bixby settings", "function": "Bixby configuration interface.", "risk": "Low — optional app", "impact": "May remove Bixby settings UI; do not assume this removes all Bixby components."},
    {"package": "com.samsung.android.bixby.service", "app": "Samsung One UI: Bixby service", "function": "Bixby integration service on some builds.", "risk": "Review first — dependencies unclear", "impact": "May affect Bixby-linked Samsung apps or system integrations. Review installed label and usage first."},
    {"package": "com.samsung.android.app.routines", "app": "Samsung One UI: Modes and Routines", "function": "Automation and context-based routines.", "risk": "Conditional — feature loss", "impact": "Removing loses custom modes/routines and automation."},
    {"package": "com.samsung.android.arzone", "app": "Samsung One UI: AR Zone", "function": "AR Emoji and augmented-reality app hub.", "risk": "Low — optional app", "impact": "Removes AR Zone features; verify you do not use AR tools or related camera features."},
    {"package": "com.samsung.android.aremoji", "app": "Samsung One UI: AR Emoji", "function": "Animated avatar features.", "risk": "Low — optional app", "impact": "Removes AR Emoji features if this exact package is present."},
    {"package": "com.samsung.android.aremojieditor", "app": "Samsung One UI: AR Emoji Editor", "function": "AR Emoji editing component.", "risk": "Conditional — feature loss", "impact": "May affect avatar editing or related assets."},
    {"package": "com.samsung.android.app.camera.sticker.facear.preload", "app": "Samsung One UI: Camera AR preload", "function": "Camera AR/sticker support assets on some builds.", "risk": "Review first — dependencies unclear", "impact": "Could affect camera stickers or AR effects. Test the stock camera before changing."},
    {"package": "com.sec.android.app.sbrowser", "app": "Samsung One UI: Samsung Internet", "function": "Samsung's browser app.", "risk": "Low — optional app", "impact": "Only remove after confirming another browser is installed and handles links, downloads and web sign-in."},
    {"package": "com.samsung.android.scloud", "app": "Samsung One UI: Samsung Cloud", "function": "Samsung account cloud sync/backup integration.", "risk": "Conditional — feature loss", "impact": "May affect Samsung Cloud sync, Gallery sync, notes or device backup. Google backup does not replace every Samsung service."},
    {"package": "com.microsoft.icedee", "app": "Samsung One UI: Link to Windows service (variant)", "function": "Windows linking integration on some builds.", "risk": "Review first — dependencies unclear", "impact": "May affect Phone Link integration. Package identity and function can vary; verify installed app label."},
    {"package": "com.samsung.android.mdx", "app": "Samsung One UI: Link to Windows / cross-device (variant)", "function": "Cross-device integration component on some builds.", "risk": "Review first — dependencies unclear", "impact": "May affect Windows linking or Samsung ecosystem features; confirm role on the exact phone."},
    {"package": "com.samsung.android.app.spage", "app": "Samsung One UI: Samsung Free / Daily", "function": "Launcher side-panel content service on some builds.", "risk": "Conditional — feature loss", "impact": "May remove the left-side media/news panel. Prefer disabling the panel in Home screen settings first."},
    {"package": "com.sec.android.app.desktoplauncher", "app": "Samsung One UI: DeX launcher", "function": "Desktop interface for Samsung DeX.", "risk": "Conditional — feature loss", "impact": "Keep if you use DeX or external-display desktop mode."},
    {"package": "com.samsung.android.kidshome", "app": "Samsung One UI: Samsung Kids", "function": "Child-friendly restricted environment.", "risk": "Low — optional app", "impact": "Remove only if you do not use Samsung Kids or family-controlled modes."},
    {"package": "com.sec.android.app.launcher", "app": "Samsung One UI Home — KEEP", "function": "Stock launcher and home-screen integration.", "risk": "Critical — keep", "impact": "Do not uninstall or disable. Third-party launchers do not guarantee replacement of every One UI Home/Recents integration."},
    {"package": "com.samsung.android.securitylogagent", "app": "Samsung One UI: Security Log Agent — KEEP", "function": "Samsung security logging component.", "risk": "High — keep", "impact": "Keep unless following authoritative, model-specific service guidance; security/Knox behavior may be affected."},
    {"package": "com.samsung.android.biometrics.app.setting", "app": "Samsung One UI: Biometrics settings — KEEP", "function": "Biometric enrollment and settings integration.", "risk": "Critical — keep", "impact": "Do not disable. May break fingerprint/face enrollment or related lock-screen security features."},
    {"package": "com.vivo.appstore", "app": "Vivo/iQOO: V-Appstore", "function": "Manufacturer app marketplace and update source.", "risk": "Low — optional app", "impact": "Consider only if you use Google Play or another trusted store and do not rely on V-Appstore for OEM app updates."},
    {"package": "com.vivo.browser", "app": "Vivo/iQOO: Browser", "function": "Stock browser app on some builds.", "risk": "Low — optional app", "impact": "Install and test another browser first; confirm links, downloads and sign-in flows work."},
    {"package": "com.ibimuyu.lockscreen", "app": "Vivo/iQOO: Glance lock screen (variant)", "function": "Lock-screen content or wallpaper service on some builds.", "risk": "Review first — device-dependent", "impact": "Package role and availability vary. Prefer disabling lock-screen content in settings before disabling this package."},
    {"package": "com.vivo.website", "app": "Vivo/iQOO: Official website app", "function": "OEM website/support portal on some builds.", "risk": "Review first — verify package", "impact": "Verify the installed label and package on your model; package name alone does not establish it is harmless."},
    {"package": "com.vivo.easyshare", "app": "Vivo/iQOO: EasyShare", "function": "Peer-to-peer transfer and device migration app.", "risk": "Low — optional app", "impact": "Removes EasyShare/migration features. Test your alternative transfer method before removing."},
    {"package": "com.vivo.gamecube", "app": "Vivo/iQOO: Ultra Game Mode / Game Cube (variant)", "function": "Gaming overlay or game tools on supported builds.", "risk": "Conditional — feature loss", "impact": "May remove in-game sidebar, game tools or performance controls. Keep if you use gaming features."},
    {"package": "com.vivo.assistant", "app": "Vivo/iQOO: Jovi assistant (variant)", "function": "Assistant and contextual features on some builds.", "risk": "Review first — device-dependent", "impact": "Jovi features vary by device and OS version. Disabling may affect smart scenes, assistant entry points or related features."},
    {"package": "com.android.bbklog", "app": "Vivo/iQOO: BBK log agent", "function": "OEM logging/diagnostics package on some builds.", "risk": "Review first — dependencies unclear", "impact": "Do not assume it only collects telemetry or that disabling it improves battery life; verify on the exact build."},
    {"package": "com.vivo.vtouch", "app": "Vivo/iQOO: V-Touch (variant)", "function": "Touch/gesture feature integration on some builds.", "risk": "Review first — feature loss", "impact": "May affect OEM gesture or shortcut behavior. Test navigation gestures and side-swipe shortcuts before changing."},
    {"package": "com.bbk.account", "app": "Vivo/iQOO: BBK account", "function": "Manufacturer account integration.", "risk": "Conditional — feature loss", "impact": "May affect Vivo/iQOO account sign-in, cloud sync, themes, or device-finding features. Keep if using the manufacturer account."},
    {"package": "com.bbk.cloud", "app": "Vivo/iQOO: BBK cloud", "function": "Manufacturer cloud sync and backup integration.", "risk": "Conditional — feature loss", "impact": "May affect cloud backups, gallery/notes sync or restore. Confirm exports and alternative backups before changing."},
    {"package": "com.vivo.gallery", "app": "Vivo/iQOO: Gallery", "function": "Stock photo gallery and media integration.", "risk": "Review first — feature loss", "impact": "Camera thumbnail previews, editing or album features may depend on it. Test camera previews and editing before disabling."},
    {"package": "com.android.calculator2", "app": "Vivo/iQOO: Calculator (package variant)", "function": "Calculator app on some builds.", "risk": "Low — optional app", "impact": "Package may belong to a different calculator app on some devices. Confirm the installed app label before acting."},
    {"package": "com.bbk.theme", "app": "Vivo/iQOO: Themes", "function": "Themes, fonts, wallpapers or icon-store integration.", "risk": "Conditional — feature loss", "impact": "May affect online themes, fonts, lock-screen assets or icon packs. Keep if you use these features."},
    {"package": "com.vivo.weather", "app": "Vivo/iQOO: Weather", "function": "Stock weather app and widgets.", "risk": "Low — optional app", "impact": "Remove only if you do not use its widgets or OEM weather shortcuts."},
    {"package": "com.vivo.email", "app": "Vivo/iQOO: Email", "function": "Stock email client on some builds.", "risk": "Low — optional app", "impact": "Confirm Gmail or another email app is installed and your accounts/messages are available before removing."},
    {"package": "com.iqoo.secure", "app": "Vivo/iQOO: iManager / security (variant) — KEEP", "function": "OEM security/device-management component on some builds.", "risk": "Critical — keep", "impact": "Do not disable based on generic debloat lists. Exact role varies by model; could affect device-management or security features."},
    {"package": "com.vivo.secure", "app": "Vivo/iQOO: iManager / security (variant) — KEEP", "function": "OEM security/device-management component on some builds.", "risk": "Critical — keep", "impact": "Do not disable based on generic debloat lists. Exact role varies by model; could affect device-management or security features."},
    {"package": "com.bbk.launcher2", "app": "Vivo/iQOO: Funtouch launcher (variant) — KEEP", "function": "Stock launcher on some Vivo/iQOO builds.", "risk": "Critical — keep", "impact": "Do not disable until a verified recovery path exists; launcher and system UI integrations can vary by version."},
    {"package": "com.iqoo.engineermode", "app": "Vivo/iQOO: Engineer mode (variant) — KEEP", "function": "OEM engineering/testing component on some builds.", "risk": "High — keep", "impact": "Do not remove using generic advice; package role is device-specific and may be required for service/testing functions."},
    {"package": "com.vivo.engineermode", "app": "Vivo/iQOO: Engineer mode (variant) — KEEP", "function": "OEM engineering/testing component on some builds.", "risk": "High — keep", "impact": "Do not remove using generic advice; package role is device-specific and may be required for service/testing functions."},
    {"package": "com.miui.home", "app": "POCO/MIUI/HyperOS: POCO Launcher — KEEP", "function": "Stock launcher on many Xiaomi/POCO builds.", "risk": "Critical — keep", "impact": "Do not disable unless you have verified device-specific replacement and recovery. Package varies by launcher/build."},
    {"package": "com.android.dreams.basic", "app": "Android Basic Daydreams", "function": "Screensaver / ambient display during charging or docking.", "risk": "Low — optional feature", "impact": "Only removes the basic screensaver provider; check whether your device uses it."},
    {"package": "com.android.nfc", "app": "Android NFC service", "function": "NFC hardware and tap-to-pay/tag features.", "risk": "Review first — feature dependency", "impact": "Disabling can stop NFC payments, tag reading and tap-to-pair. Keep if you use NFC."},
    {"package": "com.android.simappdialog", "app": "SIM App Dialog", "function": "Carrier SIM Toolkit configuration prompts.", "risk": "Conditional — feature loss", "impact": "May suppress carrier/SIM configuration prompts; behavior depends on carrier."},
    {"package": "com.android.wallpaper.livepicker", "app": "Live Wallpaper Picker", "function": "Selecting live wallpapers.", "risk": "Low — optional feature", "impact": "Live-wallpaper selection may stop working; ordinary static wallpapers should remain available."},
    {"package": "com.google.android.adservices.api", "app": "Android AdServices API", "function": "Android Privacy Sandbox ad services.", "risk": "Review first — verify build", "impact": "Disabling may affect ad-related APIs; privacy and performance effects vary by Android version."},
    {"package": "com.google.android.gms.location.history", "app": "Google Play Services Location History", "function": "Google Maps Timeline/location-history integration.", "risk": "Conditional — feature loss", "impact": "May affect location-history features; package availability varies."},
    {"package": "com.google.android.gms.supervision", "app": "Google supervision services", "function": "Family Link / supervised-device functions.", "risk": "Review first — account dependency", "impact": "Keep on supervised or parental-control-managed devices."},
    {"package": "com.google.android.onetimeinitializer", "app": "Google One Time Initializer", "function": "First-boot or update-time initialization.", "risk": "Review first — system setup", "impact": "May affect setup/restore flows on some builds. Avoid changing before a major update."},
    {"package": "com.oplus.bttestmode", "app": "OPlus Bluetooth Test Mode", "function": "Bluetooth hardware diagnostics.", "risk": "Review first — verify build", "impact": "Likely useful for diagnostics only, but confirm the installed label before changing."},
    {"package": "com.oplus.cast", "app": "OPlus Cast", "function": "OEM screen-mirroring / screencast feature.", "risk": "Conditional — feature loss", "impact": "May remove OEM Screencast integration; third-party casting behavior varies."},
    {"package": "com.oplus.customize.coreapp", "app": "OPlus Customization Core", "function": "Regional/carrier customization.", "risk": "Review first — carrier dependency", "impact": "Could affect regional or carrier-specific configuration; keep if unsure."},
    {"package": "com.oplus.encryption", "app": "OPlus Encryption", "function": "Encryption / secure storage-related component.", "risk": "Critical — security dependency", "impact": "Do not disable or uninstall; could affect security-related settings or protected data."},
    {"package": "com.oplus.locationproxy", "app": "OPlus Location Proxy", "function": "OEM location integration.", "risk": "Review first — location dependency", "impact": "May affect location integration or navigation on some firmware. Keep if unsure."},
    {"package": "com.android.apps.tag", "app": "Android NFC Tag", "function": "NFC tag reading app.", "risk": "Conditional — feature loss", "impact": "NFC tag workflows may stop working; not required if you never use tags."},
    {"package": "com.android.bluetoothmidiservice", "app": "Bluetooth MIDI Service", "function": "Bluetooth MIDI device support.", "risk": "Low — optional feature", "impact": "Wireless MIDI instruments may no longer connect."},
    {"package": "com.android.bookmarkprovider", "app": "Bookmark Provider", "function": "Legacy shared browser bookmark provider.", "risk": "Review first — verify build", "impact": "Legacy role varies; verify package label and browser behavior before changing."},
    {"package": "com.android.egg", "app": "Android Easter Egg", "function": "Hidden Android version Easter egg.", "risk": "Low — optional app", "impact": "Removes the Easter egg only on builds where this package serves that function."},
    {"package": "com.android.email.partnerprovider", "app": "Email Partner Provider", "function": "Legacy partner email setup configuration.", "risk": "Review first — verify build", "impact": "May be unused on newer devices, but verify the package role on your firmware."},
    {"package": "com.android.hotwordenrollment.okgoogle", "app": "OK Google Hotword Enrollment", "function": "Voice match enrollment.", "risk": "Conditional — feature loss", "impact": "May disable voice-match enrollment or hands-free activation."},
    {"package": "com.android.hotwordenrollment.xgoogle", "app": "Google Hotword Enrollment (variant)", "function": "Voice match enrollment variant.", "risk": "Conditional — feature loss", "impact": "May disable voice-match enrollment or hands-free activation."},
    {"package": "com.android.providers.partnerbookmarks", "app": "Partner Bookmarks Provider", "function": "Preloaded partner bookmarks.", "risk": "Low — optional feature", "impact": "Removes partner-provided bookmarks where used."},
    {"package": "com.android.stk", "app": "SIM Toolkit", "function": "Carrier SIM Toolkit menus and services.", "risk": "Critical — telephony dependency", "impact": "Do not disable blindly; can break carrier SIM menus and operator services."},
    {"package": "com.android.systemui.plugin.globalactions.wallet", "app": "System UI Wallet Power Menu Plugin", "function": "Wallet shortcuts in the power menu.", "risk": "Conditional — feature loss", "impact": "May remove wallet integration from the power menu."},
    {"package": "com.android.traceur", "app": "System Tracing", "function": "Developer/system performance tracing UI.", "risk": "Low — optional app", "impact": "Removes tracing UI; useful when diagnosing performance bugs."},
    {"package": "com.coloros.assistantscreen", "app": "ColorOS Assistant Screen", "function": "Home-screen smart assistant pane.", "risk": "Low — optional feature", "impact": "Removes the OEM assistant pane if present."},
    {"package": "com.coloros.ocs.opencapabilityservice", "app": "ColorOS Open Capability Service", "function": "OEM app-to-app capability bridge.", "risk": "Review first — dependencies unclear", "impact": "Could affect integrations among OEM apps or dependent third-party apps."},
    {"package": "com.coloros.oshare", "app": "OShare", "function": "OEM peer-to-peer file sharing.", "risk": "Conditional — feature loss", "impact": "Removes OShare; other sharing systems may remain available."},
    {"package": "com.coloros.phonemanager", "app": "ColorOS Phone Manager", "function": "Device security, permissions and storage management.", "risk": "Critical — security dependency", "impact": "Do not disable blindly; may affect security, permission and storage-management features."},
    {"package": "com.coloros.securepay", "app": "ColorOS Secure Pay", "function": "Payment environment/security checks.", "risk": "Review first — security dependency", "impact": "May affect payment or banking app security checks; do not remove without device-specific evidence."},
    {"package": "com.coloros.smartsidebar", "app": "ColorOS Smart Sidebar", "function": "Floating shortcuts and app tools.", "risk": "Low — optional feature", "impact": "Removes the sidebar if present; settings integration may vary."},
    {"package": "com.coloros.systemclone", "app": "ColorOS System Clone", "function": "Separate user/workspace feature.", "risk": "Conditional — feature loss", "impact": "May affect system-clone access or management; verify any cloned profile/data first."},
    {"package": "com.google.android.apps.googleassistant", "app": "Google Assistant", "function": "Assistant app and voice assistant entry points.", "risk": "Low — optional app", "impact": "Removes Assistant UI/shortcuts; other search features may be affected depending on integration."},
    {"package": "com.google.android.apps.nbu.files", "app": "Files by Google", "function": "File manager.", "risk": "Low — optional app", "impact": "Keep another working file manager before removing."},
    {"package": "com.google.android.as.oss", "app": "Android System Intelligence (OSS variant)", "function": "On-device intelligence component variant.", "risk": "Review first — system dependency", "impact": "May affect contextual system features; package usage varies by build."},
    {"package": "com.google.android.partnersetup", "app": "Google Partner Setup", "function": "Google/OEM integration setup component.", "risk": "Review first — dependencies unclear", "impact": "Could affect initialization or integrations on some builds."},
    {"package": "com.google.android.projection.gearhead", "app": "Android Auto", "function": "Android Auto vehicle integration.", "risk": "Conditional — feature loss", "impact": "Removes Android Auto support; keep if you connect to vehicle infotainment."},
    {"package": "com.mediatek.omacp", "app": "MediaTek OMACP", "function": "Carrier configuration provisioning on some MediaTek devices.", "risk": "Critical — carrier dependency", "impact": "Do not remove without confirming device chipset and carrier requirements; may affect SMS/data provisioning."},
    {"package": "com.oplus.aod", "app": "OPlus Always-On Display", "function": "Always-On Display feature.", "risk": "Low — optional feature", "impact": "Disables OEM Always-On Display if the device uses this package."},
    {"package": "com.oplus.apprecover", "app": "OPlus App Recovery", "function": "Restore/reinstall OEM utility apps.", "risk": "Low — optional feature", "impact": "May remove the OEM app-recovery path."},
    {"package": "com.oplus.healthservice", "app": "OPlus Health Service", "function": "OEM health/fitness integration.", "risk": "Conditional — feature loss", "impact": "May affect fitness tracking or connected accessory integration."},
    {"package": "com.oplus.location", "app": "OPlus Location", "function": "OEM location framework integration.", "risk": "Critical — location dependency", "impact": "Do not remove blindly; could impair location features on firmware that relies on it."},
    {"package": "com.oplus.multiapp", "app": "OPlus Multi-App / App Cloner", "function": "Dual-app cloning feature.", "risk": "Conditional — data/feature dependency", "impact": "Cloned apps or their data may become inaccessible; back up first and verify restore options."},
    {"package": "com.oplus.portrait", "app": "OPlus Portrait", "function": "Camera portrait processing integration.", "risk": "Conditional — camera dependency", "impact": "May affect stock-camera portrait mode on some builds."},
    {"package": "com.oplus.securitykeyboard", "app": "OPlus Security Keyboard", "function": "Secure input for protected fields.", "risk": "Critical — security/input dependency", "impact": "Do not remove; may affect secure password entry or banking app input."},
    {"package": "com.oplus.synergy", "app": "OPlus Synergy", "function": "Cross-device ecosystem integration.", "risk": "Conditional — feature loss", "impact": "May disable supported cross-device or smart-accessory features."},
    {"package": "com.oplus.themestore", "app": "OPlus Theme Store", "function": "Fonts, themes and icon customization.", "risk": "Low — optional app", "impact": "Removes OEM theme-store customization."},
    {"package": "com.oplus.viewtalk", "app": "OPlus ViewTalk", "function": "Carrier video-call integration on supported networks.", "risk": "Conditional — carrier feature", "impact": "May affect carrier-based video calling; depends on network and firmware."},
    {"package": "com.qualcomm.atfwd", "app": "Qualcomm ATFWD", "function": "Qualcomm wireless-display support component.", "risk": "Review first — hardware dependency", "impact": "May affect Miracast or wireless-display behavior on supported devices."},
    {"package": "com.qualcomm.qti.modemtestmode", "app": "Qualcomm Modem Test Mode", "function": "Radio/modem diagnostic component.", "risk": "Critical — telephony dependency", "impact": "Do not remove blindly; role varies by chipset/firmware and may affect radio diagnostics."},
    {"package": "com.qualcomm.qti.uim", "app": "Qualcomm UIM", "function": "Qualcomm User Identity Module integration.", "risk": "Critical — telephony dependency", "impact": "Do not disable; may affect SIM/radio functions on firmware that depends on it."},
    {"package": "com.tencent.soter.soterserver", "app": "Tencent Soter Server", "function": "Biometric authentication framework used by some apps.", "risk": "Review first — authentication dependency", "impact": "May affect fingerprint/face authentication in apps that rely on Soter."},
]

for _guide_entry in OEM_DEBLOAT_GUIDE:
    if not _guide_entry["risk"].startswith(("High", "Critical", "Review first")):
        DEBLOAT_RECOMMENDATIONS.setdefault(
            _guide_entry["package"],
            (_guide_entry["risk"], _guide_entry["impact"]),
        )


@dataclass
class Package:
    name: str
    kind: str
    recommendation: str = "Not listed"
    recommendation_note: str = ""
    label: str = ""
    icon_base64: str = ""


class Worker(QThread):
    done = Signal(object, str)

    def __init__(self, command: list[str], timeout: int = 40):
        super().__init__()
        self.command = command
        self.timeout = timeout

    def run(self) -> None:
        try:
            proc = subprocess.run(
                self.command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=_host_tool_env(),
            )
            output = (proc.stdout or "").strip()
            error = (proc.stderr or "").strip()
            if proc.returncode != 0:
                self.done.emit(None, error or output or f"Command failed with exit code {proc.returncode}")
            else:
                self.done.emit(output, "")
        except subprocess.TimeoutExpired:
            self.done.emit(None, "ADB command timed out. Check the phone connection and try again.")
        except OSError as exc:
            self.done.emit(None, str(exc))


class InventoryWorker(QThread):
    """Fetch AMBridge metadata over an ADB-forwarded loopback HTTP connection."""
    done = Signal(object, str)

    def __init__(self, adb: str, serial: str, timeout: int = 100):
        super().__init__()
        self.adb = adb
        self.serial = serial
        self.timeout = timeout

    def run(self) -> None:
        local_port = None
        prefix = [self.adb, "-s", self.serial]
        try:
            launch = subprocess.run(prefix + ["shell", "am", "start", "-n", "com.nightlab.ambridge/.MainActivity"], capture_output=True, text=True, timeout=30, env=_host_tool_env())
            if launch.returncode != 0 or "error" in (launch.stderr + launch.stdout).lower():
                raise RuntimeError((launch.stderr or launch.stdout or "Could not open NightLab AMBridge").strip())
            forward = subprocess.run(prefix + ["forward", "tcp:0", "tcp:39876"], capture_output=True, text=True, timeout=20, env=_host_tool_env())
            if forward.returncode != 0:
                raise RuntimeError((forward.stderr or forward.stdout or "ADB port forwarding failed").strip())
            try:
                local_port = int(forward.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                raise RuntimeError("ADB did not return a usable local port for AMBridge forwarding.")
            last_error = "AMBridge service did not become ready."
            for _ in range(24):
                try:
                    request = urllib.request.Request(f"http://127.0.0.1:{local_port}/v1/apps", headers={"Accept": "application/json", "Connection": "close"})
                    with urllib.request.urlopen(request, timeout=8) as response:
                        if response.status != 200:
                            raise RuntimeError(f"AMBridge returned HTTP {response.status}.")
                        payload = json.loads(response.read().decode("utf-8"))
                    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("applications"), list):
                        raise RuntimeError("AMBridge returned an unsupported inventory format.")
                    self.done.emit(payload, "")
                    return
                except Exception as exc:
                    reason = getattr(exc, "reason", None)
                    if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
                        raise RuntimeError("AMBridge took too long to build the app inventory. Keep the phone unlocked and retry.")
                    last_error = str(exc)
                    time.sleep(0.5)
            raise RuntimeError(last_error + " Keep the phone unlocked, reopen AMBridge, and retry.")
        except Exception as exc:
            self.done.emit(None, str(exc))
        finally:
            if local_port is not None:
                subprocess.run(prefix + ["forward", "--remove", f"tcp:{local_port}"], capture_output=True, text=True, timeout=15, env=_host_tool_env())


class ApkDropList(QListWidget):
    """List widget that accepts APK files dropped from the desktop file manager."""
    filesDropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        paths = [
            url.toLocalFile() for url in event.mimeData().urls()
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".apk")
        ]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1080, 720)
        self.setMinimumSize(760, 520)
        self.packages: list[Package] = []
        self.third_party_names: set[str] = set()
        self._ambridge_metadata: dict[str, dict] = {}
        self.device_id: str | None = None
        self._app_data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
        self._history_path = self._app_data_dir / "uninstall-history.json"
        self._ambridge_cache_path = self._app_data_dir / "ambridge-inventory-cache.json"
        self._ambridge_prompted_devices: set[str] = set()
        self._checked_packages: set[str] = set()
        self.worker: Worker | None = None
        self._build_ui()
        self._style_ui()
        self.refresh_devices()

    def _build_ui(self) -> None:
        central = QWidget()
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        # Compact top bar: product identity and connection controls.
        top = QFrame()
        top.setObjectName("topBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(24, 17, 24, 17)
        brand = QVBoxLayout()
        title = QLabel("ADB App Manager")
        title.setObjectName("title")
        subtitle = QLabel("Android device management, without the clutter")
        subtitle.setObjectName("subtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        top_layout.addLayout(brand)
        top_layout.addStretch(1)

        device_label = QLabel("DEVICE")
        device_label.setObjectName("eyebrow")
        top_layout.addWidget(device_label)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(240)
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        top_layout.addWidget(self.device_combo)
        self.connect_btn = QPushButton("Refresh")
        self.connect_btn.clicked.connect(self.refresh_devices)
        top_layout.addWidget(self.connect_btn)
        self.wifi_connect_btn = QPushButton("Connect Wi-Fi")
        self.wifi_connect_btn.clicked.connect(self.wireless_connect)
        top_layout.addWidget(self.wifi_connect_btn)
        self.wifi_pair_btn = QPushButton("Pair Wi-Fi")
        self.wifi_pair_btn.clicked.connect(self.wireless_pair)
        top_layout.addWidget(self.wifi_pair_btn)
        shell.addWidget(top)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(205)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(14, 22, 14, 18)
        nav.setSpacing(8)
        nav_label = QLabel("WORKSPACE")
        nav_label.setObjectName("eyebrow")
        nav.addWidget(nav_label)

        self.page_stack = QStackedWidget()
        self.nav_buttons = []
        for label, icon_text, page_index in [
            ("Overview", "⌂", 0), ("App library", "▦", 1), ("Device tools", "⚙", 2)
        ]:
            button = QPushButton(f"{icon_text}    {label}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, idx=page_index: self._show_page(idx))
            nav.addWidget(button)
            self.nav_buttons.append(button)
        nav.addStretch(1)
        side_note = QLabel("ADB POWER TOOLS\n\nUse only with devices you own or are authorized to manage.")
        side_note.setObjectName("sideNote")
        side_note.setWordWrap(True)
        nav.addWidget(side_note)
        body.addWidget(sidebar)

        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(24, 22, 24, 18)
        content_layout.setSpacing(16)

        # Overview page
        self.overview_page = QWidget()
        overview = QVBoxLayout(self.overview_page)
        overview.setContentsMargins(0, 0, 0, 0)
        overview.setSpacing(18)
        welcome = QLabel("Device overview")
        welcome.setObjectName("pageTitle")
        welcome_sub = QLabel("A quick look at your connection and installed packages.")
        welcome_sub.setObjectName("subtitle")
        overview.addWidget(welcome)
        overview.addWidget(welcome_sub)

        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.device_stat = QLabel("No device selected")
        self.package_stat = QLabel("Not loaded")
        self.third_party_stat = QLabel("—")
        for heading, value, name in [
            ("ACTIVE DEVICE", self.device_stat, "statDevice"),
            ("INSTALLED PACKAGES", self.package_stat, "statPackages"),
            ("THIRD-PARTY APPS", self.third_party_stat, "statThirdParty"),
        ]:
            card = QFrame()
            card.setObjectName("statCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(18, 16, 18, 16)
            cap = QLabel(heading)
            cap.setObjectName("eyebrow")
            value.setObjectName("statValue")
            value.setWordWrap(True)
            card_layout.addWidget(cap)
            card_layout.addWidget(value)
            cards.addWidget(card)
        overview.addLayout(cards)

        quick = QFrame()
        quick.setObjectName("panel")
        quick_layout = QVBoxLayout(quick)
        quick_layout.setContentsMargins(20, 18, 20, 18)
        quick_layout.setSpacing(12)
        quick_title = QLabel("Quick actions")
        quick_title.setObjectName("sectionTitle")
        quick_layout.addWidget(quick_title)
        quick_row = QHBoxLayout()
        self.overview_load_btn = QPushButton("Load app library")
        self.overview_load_btn.setObjectName("primaryButton")
        self.overview_load_btn.clicked.connect(self.load_packages)
        self.overview_apps_btn = QPushButton("Browse installed apps")
        self.overview_apps_btn.clicked.connect(lambda: self._show_page(1))
        self.overview_tools_btn = QPushButton("Open device tools")
        self.overview_tools_btn.clicked.connect(lambda: self._show_page(2))
        for button in (self.overview_load_btn, self.overview_apps_btn, self.overview_tools_btn):
            quick_row.addWidget(button)
        quick_layout.addLayout(quick_row)
        overview.addWidget(quick)

        connection_note = QLabel("Tip: Android 11+ uses Wireless Debugging pairing. Pairing and connection ports are different.")
        connection_note.setObjectName("infoNote")
        connection_note.setWordWrap(True)
        overview.addWidget(connection_note)
        overview.addStretch(1)
        self.page_stack.addWidget(self.overview_page)

        # App library page
        self.apps_page = QWidget()
        apps = QVBoxLayout(self.apps_page)
        apps.setContentsMargins(0, 0, 0, 0)
        apps.setSpacing(12)
        app_heading = QHBoxLayout()
        app_titles = QVBoxLayout()
        app_title = QLabel("App library")
        app_title.setObjectName("pageTitle")
        app_subtitle = QLabel("Search, classify, and manage packages on the selected device.")
        app_subtitle.setObjectName("subtitle")
        app_titles.addWidget(app_title)
        app_titles.addWidget(app_subtitle)
        app_heading.addLayout(app_titles)
        app_heading.addStretch(1)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self.export_csv)
        app_heading.addWidget(self.export_btn)
        self.disabled_apps_btn = QPushButton("Disabled apps")
        self.disabled_apps_btn.clicked.connect(self.show_disabled_apps)
        app_heading.addWidget(self.disabled_apps_btn)
        self.uninstall_history_btn = QPushButton("Uninstall history")
        self.uninstall_history_btn.clicked.connect(self.show_uninstall_history)
        app_heading.addWidget(self.uninstall_history_btn)
        apps.addLayout(app_heading)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by app name or package ID…")
        self.search.textChanged.connect(self.render_packages)
        toolbar.addWidget(self.search, 1)
        self.select_all_btn = QPushButton("Select all visible")
        self.select_all_btn.clicked.connect(lambda: self._set_visible_checked(True))
        toolbar.addWidget(self.select_all_btn)
        self.clear_selection_btn = QPushButton("Clear selection")
        self.clear_selection_btn.clicked.connect(self._clear_package_selection)
        toolbar.addWidget(self.clear_selection_btn)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All packages", "Third-party apps", "System apps", "Recommended (review first)"])
        self.filter_combo.currentIndexChanged.connect(self.render_packages)
        toolbar.addWidget(self.filter_combo)
        self.reload_btn = QPushButton("↻  Load packages")
        self.reload_btn.setObjectName("primaryButton")
        self.reload_btn.clicked.connect(self.load_packages)
        toolbar.addWidget(self.reload_btn)
        apps.addLayout(toolbar)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["☑ Select / app name / package", "Classification", "Debloat guidance"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemChanged.connect(self._table_item_changed)
        apps.addWidget(self.table, 1)

        actions_panel = QFrame()
        actions_panel.setObjectName("panel")
        actions = QHBoxLayout(actions_panel)
        actions.setContentsMargins(12, 10, 12, 10)
        actions.setSpacing(8)
        self.uninstall_btn = QPushButton("Uninstall for user")
        self.uninstall_btn.clicked.connect(self.uninstall_package)
        self.disable_btn = QPushButton("Disable")
        self.disable_btn.clicked.connect(self.disable_package)
        self.enable_btn = QPushButton("Enable / restore")
        self.enable_btn.clicked.connect(self.enable_package)
        self.install_btn = QPushButton("Install APK(s)")
        self.install_btn.clicked.connect(self.install_apks)
        self.clear_data_btn = QPushButton("Clear app data")
        self.clear_data_btn.clicked.connect(self.clear_app_data)
        self.ambridge_btn = QPushButton("AMBridge helper")
        self.ambridge_btn.clicked.connect(self.manage_ambridge)
        for btn in (self.uninstall_btn, self.disable_btn, self.enable_btn, self.install_btn, self.clear_data_btn, self.ambridge_btn):
            btn.setEnabled(False)
            actions.addWidget(btn)
        apps.addWidget(actions_panel)
        self.page_stack.addWidget(self.apps_page)

        # Device tools page
        self.tools_page = QWidget()
        tools_page_layout = QVBoxLayout(self.tools_page)
        tools_page_layout.setContentsMargins(0, 0, 0, 0)
        tools_page_layout.setSpacing(16)
        tools_title = QLabel("Device tools")
        tools_title.setObjectName("pageTitle")
        tools_subtitle = QLabel("Utilities for file transfer, troubleshooting, and device maintenance.")
        tools_subtitle.setObjectName("subtitle")
        tools_page_layout.addWidget(tools_title)
        tools_page_layout.addWidget(tools_subtitle)

        tools_grid = QHBoxLayout()
        tools_grid.setSpacing(12)
        for group_title, descriptions, entries in [
            ("ADB console", "Run a command or transfer files.", [
                ("Shell command", self.shell_command), ("Upload files", self.upload_files)
            ]),
            ("APK installer", "Install Android apps from APK files, including split APK bundles.", [
                ("Install APK(s)", self.install_apks),
                ("Install split APK set", self.install_split_apks),
            ]),
            ("App backup & restore", "Back up user-installed app APK files and restore them later.", [
                ("Back up user apps", self.backup_user_apps),
                ("Restore APK backup", self.restore_user_app_backup),
            ]),
            ("Connection", "Configure older TCP/IP debugging.", [
                ("Enable TCP/IP (USB)", self.enable_legacy_tcpip)
            ]),
            ("Device maintenance", "Restart Android into system, recovery, bootloader, or supported EDL mode.", [
                ("ADB reboot options", self.reboot_device),
                ("Fastboot reboot options", self.fastboot_reboot_device),
            ]),
            ("Package presets & debloat guide", "Save or restore selections, or review OxygenOS/ColorOS, HyperOS and Samsung One UI package functions, risks and dependency caveats.", [
                ("Save preset", self.save_preset), ("Load preset", self.load_preset),
                ("Open OEM debloat guide", self.show_oem_debloat_guide)
            ]),
        ]:
            card = QFrame()
            card.setObjectName("toolCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 16, 16, 16)
            card_layout.setSpacing(10)
            title_label = QLabel(group_title)
            title_label.setObjectName("sectionTitle")
            desc_label = QLabel(descriptions)
            desc_label.setObjectName("subtitle")
            desc_label.setWordWrap(True)
            card_layout.addWidget(title_label)
            card_layout.addWidget(desc_label)
            for label, callback in entries:
                button = QPushButton(label)
                button.clicked.connect(callback)
                card_layout.addWidget(button)
            card_layout.addStretch(1)
            tools_grid.addWidget(card)
        tools_page_layout.addLayout(tools_grid)
        tools_page_layout.addStretch(1)
        self.page_stack.addWidget(self.tools_page)

        content_layout.addWidget(self.page_stack, 1)
        body.addWidget(content_area, 1)
        shell.addLayout(body, 1)

        log_panel = QFrame()
        log_panel.setObjectName("logPanel")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(24, 10, 24, 10)
        log_layout.setSpacing(5)
        log_header = QHBoxLayout()
        log_title = QLabel("ACTIVITY")
        log_title.setObjectName("eyebrow")
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        log_hint = QLabel("Recent ADB operations")
        log_hint.setObjectName("subtitle")
        log_header.addWidget(log_hint)
        log_layout.addLayout(log_header)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(86)
        self.log.setPlaceholderText("Activity log — device actions and ADB responses appear here.")
        log_layout.addWidget(self.log)
        shell.addWidget(log_panel)

        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready. Connect an Android device with USB debugging enabled.")
        refresh_action = QAction("Refresh devices", self)
        refresh_action.triggered.connect(self.refresh_devices)
        self.menuBar().addMenu("Device").addAction(refresh_action)
        self._show_page(0)

    def _show_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def _style_ui(self) -> None:
        self.setStyleSheet("""
            * { font-family: "Inter", "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }
            QMainWindow, QWidget { background: #0b1020; color: #e7ecf5; }
            QMenuBar { background: #0b1020; color: #cbd5e1; padding: 5px 8px; }
            QMenuBar::item { padding: 7px 11px; border-radius: 6px; background: transparent; }
            QMenuBar::item:selected, QMenu { background: #172033; }
            QMenu { border: 1px solid #2b3850; padding: 5px; }
            QMenu::item { padding: 7px 24px; border-radius: 5px; }
            QMenu::item:selected { background: #263b60; }
            QFrame#topBar { background: #0e1728; border-bottom: 1px solid #243149; }
            QFrame#sidebar { background: #0d1525; border-right: 1px solid #243149; }
            QFrame#logPanel { background: #0e1728; border-top: 1px solid #243149; }
            QLabel { background: transparent; }
            QLabel#title { font-size: 25px; font-weight: 750; color: #f8fafc; }
            QLabel#pageTitle { font-size: 24px; font-weight: 700; color: #f8fafc; }
            QLabel#subtitle { color: #94a3b8; font-size: 12px; }
            QLabel#eyebrow { color: #7890b2; font-size: 10px; font-weight: 800; letter-spacing: 1px; }
            QLabel#sideNote { color: #71819b; font-size: 11px; padding: 10px 3px; }
            QLabel#statValue { color: #f1f5f9; font-size: 20px; font-weight: 700; }
            QLabel#sectionTitle { color: #f1f5f9; font-size: 15px; font-weight: 700; }
            QLabel#infoNote { color: #9bb8e6; background: #12213a; border: 1px solid #263f66; border-radius: 9px; padding: 13px; }
            QFrame#statCard, QFrame#panel, QFrame#toolCard { background: #111b2d; border: 1px solid #263650; border-radius: 12px; }
            QLineEdit, QComboBox, QTextEdit {
                background: #101a2b; color: #e7ecf5; border: 1px solid #293750;
                border-radius: 9px; padding: 9px 11px; selection-background-color: #315fbd;
            }
            QLineEdit:hover, QComboBox:hover, QTextEdit:hover { border-color: #3b4e70; }
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus { border: 1px solid #60a5fa; }
            QComboBox::drop-down { border: 0; width: 26px; }
            QComboBox QAbstractItemView { background: #111a2b; color: #e7ecf5; selection-background-color: #263f68; border: 1px solid #293750; }
            QTableWidget {
                background: #0f1727; alternate-background-color: #121d30;
                color: #e2e8f0; border: 1px solid #25324a; border-radius: 12px;
                gridline-color: #1e293b; padding: 5px; selection-background-color: #244777;
                selection-color: #ffffff; outline: 0;
            }
            QTableWidget::item { padding: 8px 10px; border-bottom: 1px solid #1d293d; }
            QTableWidget::item:hover { background: #192941; }
            QHeaderView { background: #131e31; }
            QHeaderView::section { background: #131e31; color: #9fb1ca; padding: 11px 10px; border: none; border-bottom: 1px solid #2b3952; font-weight: 700; }
            QTableCornerButton::section { background: #131e31; border: none; }
            QPushButton { background: #17243a; color: #dbe7f8; border: 1px solid #30415e; border-radius: 9px; padding: 9px 12px; font-weight: 600; }
            QPushButton:hover { background: #223653; border-color: #49678f; }
            QPushButton:pressed { background: #132037; }
            QPushButton:focus { border: 1px solid #60a5fa; }
            QPushButton:disabled { color: #64748b; background: #111827; border-color: #202b3d; }
            QPushButton#primaryButton { background: #2563eb; color: #ffffff; border: 1px solid #3b82f6; }
            QPushButton#primaryButton:hover { background: #3478f6; }
            QPushButton#navButton { text-align: left; padding: 12px 11px; background: transparent; border: 1px solid transparent; color: #9cabc2; }
            QPushButton#navButton:hover { background: #14213a; color: #e2e8f0; }
            QPushButton#navButton:checked { background: #1b3152; border: 1px solid #2c4e7d; color: #dbeafe; }
            QStatusBar { background: #0e1727; color: #a8b7cc; border-top: 1px solid #233149; }
            QStatusBar::item { border: none; }
            QScrollBar:vertical { background: #0f1727; width: 12px; margin: 2px; }
            QScrollBar::handle:vertical { background: #33445f; min-height: 24px; border-radius: 5px; }
            QScrollBar::handle:vertical:hover { background: #49658b; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setShowGrid(False)

    def log_message(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {message}")

    def adb_path(self) -> str | None:
        return shutil.which("adb")

    def run_async(self, command: list[str], on_success, timeout: int = 40, on_error=None) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, APP_NAME, "Another ADB operation is still running. Please wait.")
            return
        self._set_busy(True)
        self.worker = Worker(command, timeout)
        self.worker.done.connect(lambda result, error: self._finish_worker(result, error, on_success, on_error))
        self.worker.start()

    def _finish_worker(self, result, error: str, callback, on_error=None) -> None:
        self._set_busy(False)
        if error:
            self.log_message("Error: " + error)
            self.statusBar().showMessage("Operation failed", 6000)
            if on_error is not None:
                on_error(error)
            else:
                QMessageBox.warning(self, APP_NAME, error)
            return
        callback(result or "")

    def _set_busy(self, busy: bool) -> None:
        self.connect_btn.setEnabled(not busy)
        self.reload_btn.setEnabled(not busy)
        self.export_btn.setEnabled(not busy)
        self.statusBar().showMessage("Working with ADB…" if busy else "Ready")

    def refresh_devices(self) -> None:
        adb = self.adb_path()
        self.device_combo.clear()
        if not adb:
            self.device_combo.addItem("ADB not found on PATH", "")
            self.device_id = None
            self.statusBar().showMessage("Install Android SDK Platform-Tools and add adb to PATH.")
            self.log_message("ADB was not found. Install Android Platform-Tools and restart the app.")
            self._selection_changed()
            return
        self.run_async([adb, "devices", "-l"], self._devices_loaded)

    def _devices_loaded(self, output: str) -> None:
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("Select Android device…", "")
        for line in output.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serial = parts[0]
                detail = " ".join(parts[2:])
                self.device_combo.addItem(f"{serial}  {detail}".strip(), serial)
            elif len(parts) >= 2 and parts[1] in ("unauthorized", "offline"):
                self.device_combo.addItem(f"{parts[0]} ({parts[1]})", "")
        self.device_combo.blockSignals(False)
        self.device_id = self.device_combo.currentData()
        self.log_message(f"Device scan complete: {max(0, self.device_combo.count() - 1)} device entry/entries.")
        self.statusBar().showMessage("Select a device, then load packages.")
        self._selection_changed()

    def _device_changed(self) -> None:
        self.device_id = self.device_combo.currentData()
        self.device_stat.setText(self.device_id or "No device selected")
        self.packages = []
        self._checked_packages.clear()
        self._ambridge_metadata = self._read_ambridge_cache(self.device_id) if self.device_id else {}
        self.package_stat.setText("Not loaded")
        self.third_party_stat.setText("—")
        self.render_packages()
        self._selection_changed()
        if self.device_id and self.device_id not in self._ambridge_prompted_devices:
            self._ambridge_prompted_devices.add(self.device_id)
            self.check_ambridge(prompt_if_missing=True)

    def load_packages(self) -> None:
        adb = self.adb_path()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Select an authorized Android device first. Check the phone for the USB debugging prompt.")
            return
        serial = self.device_id
        self.run_async([adb, "-s", serial, "shell", "pm", "list", "packages"], self._packages_loaded, timeout=60)

    def _packages_loaded(self, output: str) -> None:
        self._all_package_names = parse_package_names(output)
        adb = self.adb_path()
        if not adb or not self.device_id:
            return
        self.run_async(
            [adb, "-s", self.device_id, "shell", "pm", "list", "packages", "-3"],
            self._third_party_loaded,
            timeout=60,
        )

    def _third_party_loaded(self, output: str) -> None:
        self.third_party_names = set(parse_package_names(output))
        self.packages = sorted(
            [
                Package(
                    name,
                    "Third-party" if name in self.third_party_names else "System / preinstalled",
                    *DEBLOAT_RECOMMENDATIONS.get(name, ("Not listed", "")),
                    label=self._ambridge_metadata.get(name, {}).get("label", ""),
                    icon_base64=self._ambridge_metadata.get(name, {}).get("iconPngBase64", ""),
                )
                for name in self._all_package_names
            ],
            key=lambda p: (p.label or p.name).casefold(),
        )
        self.render_packages()
        self.package_stat.setText(f"{len(self.packages):,}")
        self.third_party_stat.setText(f"{len(self.third_party_names):,}")
        self.device_stat.setText(self.device_id or "No device selected")
        self.log_message(f"Loaded {len(self.packages)} package names from {self.device_id}.")
        self.statusBar().showMessage(f"Loaded {len(self.packages)} packages", 5000)
        if "com.nightlab.ambridge" in self._all_package_names:
            self.load_ambridge_inventory(show_errors=False)

    def render_packages(self, *_args) -> None:
        needle = self.search.text().strip().casefold()
        mode = self.filter_combo.currentIndex()
        rows = []
        for package in self.packages:
            searchable = f"{package.label} {package.name}".casefold()
            if needle and needle not in searchable:
                continue
            is_third_party = package.name in self.third_party_names
            if mode == 1 and not is_third_party:
                continue
            if mode == 2 and is_third_party:
                continue
            if mode == 3 and package.recommendation == "Not listed":
                continue
            rows.append(package)
        self.table.setRowCount(len(rows))
        self.table.blockSignals(True)
        for index, package in enumerate(rows):
            name_item = QTableWidgetItem(package.label or package.name)
            name_item.setFlags(name_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            name_item.setCheckState(Qt.CheckState.Checked if package.name in self._checked_packages else Qt.CheckState.Unchecked)
            name_item.setData(Qt.ItemDataRole.UserRole, package.name)
            name_item.setToolTip(f"Package: {package.name}\n" + (package.recommendation_note or "No conservative recommendation is available for this package."))
            if package.icon_base64:
                try:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(base64.b64decode(package.icon_base64, validate=True)):
                        name_item.setIcon(QIcon(pixmap))
                except (ValueError, TypeError):
                    pass
            self.table.setItem(index, 0, name_item)
            self.table.setItem(index, 1, QTableWidgetItem(package.kind))
            recommendation_item = QTableWidgetItem(package.recommendation)
            recommendation_item.setToolTip(package.recommendation_note or "This package is not in the conservative recommendation list.")
            self.table.setItem(index, 2, recommendation_item)
        self.table.blockSignals(False)
        self.statusBar().showMessage(f"Showing {len(rows)} of {len(self.packages)} packages")
        self._selection_changed()

    def selected_packages(self) -> list[str]:
        """Return packages checked in the list plus rows explicitly selected with the mouse."""
        values = set(self._checked_packages)
        for index in self.table.selectionModel().selectedRows():
            item = self.table.item(index.row(), 0)
            if item:
                package = item.data(Qt.ItemDataRole.UserRole)
                if package:
                    values.add(package)
        if not values and self.table.currentRow() >= 0:
            item = self.table.item(self.table.currentRow(), 0)
            if item:
                package = item.data(Qt.ItemDataRole.UserRole)
                if package:
                    values.add(package)
        return sorted(values)

    def selected_package(self) -> str | None:
        selected = self.selected_packages()
        return selected[0] if selected else None

    def _table_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        package = item.data(Qt.ItemDataRole.UserRole)
        if not package:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._checked_packages.add(package)
        else:
            self._checked_packages.discard(package)
        self._selection_changed()

    def _set_visible_checked(self, checked: bool) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if not item:
                continue
            package = item.data(Qt.ItemDataRole.UserRole)
            if not package:
                continue
            if checked:
                self._checked_packages.add(package)
                item.setCheckState(Qt.CheckState.Checked)
            else:
                self._checked_packages.discard(package)
                item.setCheckState(Qt.CheckState.Unchecked)
        self._selection_changed()
        self.log_message(f"{'Checked' if checked else 'Unchecked'} visible package rows.")

    def _clear_package_selection(self) -> None:
        self._checked_packages.clear()
        self.table.clearSelection()
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._selection_changed()

    def _select_packages_in_library(self, package_names: set[str]) -> int:
        self._checked_packages.update(package_names)
        self.search.clear()
        self.filter_combo.setCurrentIndex(0)
        self.render_packages()
        self._show_page(1)
        return len(package_names.intersection({p.name for p in self.packages}))

    def _selection_changed(self) -> None:
        enabled = bool(self.device_id and self.selected_packages())
        self.uninstall_btn.setEnabled(enabled)
        self.disable_btn.setEnabled(enabled)
        self.enable_btn.setEnabled(enabled)

    def show_oem_debloat_guide(self) -> None:
        """Show a searchable, review-only OEM package guide; never execute actions from this dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Android OEM Debloat Guide")
        dialog.resize(1180, 650)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "This is a curated reference, not a universal complete list or a guarantee of safety. "
            "Package names and dependencies vary by model, region, Android version and OEM skin. "
            "Only packages actually installed on your phone can be selected in the App library. "
            "No package is removed automatically."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        search = QLineEdit()
        search.setPlaceholderText("Search package ID, app name, function, risk or dependency…")
        layout.addWidget(search)
        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Package ID", "App / function", "Risk", "Features affected / dependencies", "On connected phone"])
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        for col, mode in enumerate([
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.ResizeToContents,
            QHeaderView.ResizeMode.Stretch,
            QHeaderView.ResizeMode.ResizeToContents,
        ]):
            table.horizontalHeader().setSectionResizeMode(col, mode)
        layout.addWidget(table, 1)
        button_row = QHBoxLayout()
        select_btn = QPushButton("Select matching installed packages in App Library")
        close_btn = QPushButton("Close")
        button_row.addWidget(select_btn)
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        installed = {p.name for p in self.packages}
        def populate() -> None:
            needle = search.text().strip().casefold()
            table.setRowCount(0)
            for entry in OEM_DEBLOAT_GUIDE:
                searchable = " ".join(entry.values()).casefold()
                if needle and needle not in searchable:
                    continue
                row = table.rowCount()
                table.insertRow(row)
                values = [
                    entry["package"],
                    entry["app"] + "\\n" + entry["function"],
                    entry["risk"],
                    entry["impact"],
                    "Installed" if entry["package"] in installed else "Not detected / not loaded",
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, entry["package"])
                    table.setItem(row, col, item)
        search.textChanged.connect(populate)
        populate()

        def select_matching() -> None:
            chosen = {
                item.data(Qt.ItemDataRole.UserRole)
                for index in table.selectionModel().selectedRows()
                if (item := table.item(index.row(), 0)) is not None
            }
            if not chosen:
                QMessageBox.information(dialog, APP_NAME, "Select one or more guide rows first.")
                return
            if not self.packages:
                QMessageBox.information(dialog, APP_NAME, "Load the connected phone's App library first. The guide does not assume packages are installed.")
                return
            matches = chosen.intersection({p.name for p in self.packages})
            if not matches:
                QMessageBox.information(dialog, APP_NAME, "None of the selected package IDs were found in the loaded package list for this phone.")
                return
            self._select_packages_in_library(matches)
            self.log_message(f"Selected {len(matches)} guide package(s) in the App library for review only.")
            dialog.accept()

        select_btn.clicked.connect(select_matching)
        close_btn.clicked.connect(dialog.accept)
        dialog.exec()

    def _confirmed(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def _package_action(self, action: str) -> None:
        packages = self.selected_packages()
        adb = self.adb_path()
        if not packages or not adb or not self.device_id:
            return
        if len(packages) > 1:
            if not self._confirmed(f"Batch {action}?", f"{action.title()} {len(packages)} selected packages for user 0?\n\nReview every package carefully; system packages may be critical."):
                return
            def run_next(index: int = 0) -> None:
                if index >= len(packages):
                    self.log_message(f"Batch {action} queue finished.")
                    self.load_packages()
                    return
                package = packages[index]
                if action == "uninstall":
                    args = [adb, "-s", self.device_id, "shell", "pm", "uninstall", "--user", "0", package]
                elif action == "disable":
                    args = [adb, "-s", self.device_id, "shell", "pm", "disable-user", "--user", "0", package]
                else:
                    args = [adb, "-s", self.device_id, "shell", "pm", "enable", "--user", "0", package]
                serial = self.device_id
                def operation_finished(output: str) -> None:
                    self.log_message(f"{action.title()} {package}: {output}")
                    if action == "uninstall" and "Success" in output:
                        self._record_uninstall(serial, package)
                    run_next(index + 1)
                self.run_async(args, operation_finished, timeout=60)
            run_next()
            return
        package = packages[0]
        if action == "uninstall":
            title = "Uninstall for current user?"
            message = f"Run pm uninstall --user 0 for:\n\n{package}\n\nThe system APK usually remains on the device."
            args = [adb, "-s", self.device_id, "shell", "pm", "uninstall", "--user", "0", package]
        elif action == "disable":
            title = "Disable package?"
            message = f"Disable this package for the device user?\n\n{package}\n\nEssential packages may affect calling, setup, notifications, or system UI."
            args = [adb, "-s", self.device_id, "shell", "pm", "disable-user", "--user", "0", package]
        else:
            title = "Enable package?"
            message = f"Try to enable this package again?\n\n{package}"
            args = [adb, "-s", self.device_id, "shell", "pm", "enable", "--user", "0", package]
        if not self._confirmed(title, message):
            return
        self.log_message(f"Running {action} for {package}…")
        self.run_async(args, lambda output: self._action_finished(action, package, output), timeout=60)

    def _action_finished(self, action: str, package: str, output: str) -> None:
        self.log_message(f"{action.title()} result for {package}: {output or 'Command completed.'}")
        self.statusBar().showMessage(f"{action.title()} command completed; check the log for ADB's response.", 7000)
        if action == "uninstall" and "Success" in output:
            self._record_uninstall(self.device_id, package)
            self.packages = [p for p in self.packages if p.name != package]
            self.render_packages()


    def _read_uninstall_history(self) -> list[dict[str, str]]:
        """Read this app's local uninstall log; Android does not expose a complete historic list."""
        try:
            data = json.loads(self._history_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _record_uninstall(self, serial: str | None, package: str) -> None:
        if not serial or not package:
            return
        history = self._read_uninstall_history()
        history.append({
            "device": serial,
            "package": package,
            "uninstalled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        try:
            self._history_path.parent.mkdir(parents=True, exist_ok=True)
            self._history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
            self.log_message(f"Recorded uninstall history for {package} on {serial}.")
        except OSError as exc:
            self.log_message(f"Could not save uninstall history: {exc}")
            QMessageBox.warning(
                self, APP_NAME,
                "The uninstall succeeded, but its local history entry could not be saved. Check the app's user-data folder permissions."
            )

    def show_disabled_apps(self) -> None:
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Select an authorized Android device first.")
            return
        adb = self.adb_path()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        serial = self.device_id
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Disabled apps — {serial}")
        dialog.resize(720, 480)
        layout = QVBoxLayout(dialog)
        note = QLabel("Packages currently reported disabled by Android on this device. Select one and choose Enable.")
        note.setWordWrap(True)
        layout.addWidget(note)
        table = QTableWidget(0, 1)
        table.setHorizontalHeaderLabels(["Package name"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(table, 1)
        buttons = QHBoxLayout()
        enable_btn = QPushButton("Enable selected")
        close_btn = QPushButton("Close")
        buttons.addWidget(enable_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        def populate(output: str) -> None:
            table.setRowCount(0)
            for package in parse_package_names(output):
                row = table.rowCount()
                table.insertRow(row)
                item = QTableWidgetItem(package)
                item.setData(Qt.ItemDataRole.UserRole, package)
                table.setItem(row, 0, item)
            if table.rowCount() == 0:
                self.log_message(f"No disabled packages were reported for {serial}.")
                note.setText("No disabled packages were reported for this device.")
            else:
                note.setText(f"{table.rowCount()} disabled package(s) found on {serial}.")

        def refresh() -> None:
            self.run_async([adb, "-s", serial, "shell", "pm", "list", "packages", "-d"], populate, timeout=60)

        def enable_selected() -> None:
            row = table.currentRow()
            item = table.item(row, 0) if row >= 0 else None
            package = item.data(Qt.ItemDataRole.UserRole) if item else None
            if not package:
                QMessageBox.information(dialog, APP_NAME, "Select a disabled package first.")
                return
            if not self._confirmed("Enable package?", f"Try to enable this package for user 0?\\n\\n{package}"):
                return
            self.run_async(
                [adb, "-s", serial, "shell", "pm", "enable", "--user", "0", package],
                lambda output: (self.log_message(f"Enable {package}: {output}"), refresh(), self.load_packages()),
                timeout=60,
            )

        enable_btn.clicked.connect(enable_selected)
        close_btn.clicked.connect(dialog.accept)
        refresh()
        dialog.exec()

    def show_uninstall_history(self) -> None:
        history = self._read_uninstall_history()
        dialog = QDialog(self)
        dialog.setWindowTitle("Uninstall history")
        dialog.resize(780, 460)
        layout = QVBoxLayout(dialog)
        note = QLabel(
            "This list records successful uninstall commands issued by ADB App Manager on this computer. "
            "It cannot show uninstalls from before tracking began or actions performed elsewhere."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Device serial", "Package name", "Uninstalled at"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for entry in reversed(history):
            row = table.rowCount()
            table.insertRow(row)
            values = [entry.get("device", ""), entry.get("package", ""), entry.get("uninstalled_at", "")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setData(Qt.ItemDataRole.UserRole, entry.get("package", ""))
                table.setItem(row, column, item)
        layout.addWidget(table, 1)
        buttons = QHBoxLayout()
        restore_btn = QPushButton("Try restore selected")
        close_btn = QPushButton("Close")
        buttons.addWidget(restore_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        def restore_selected() -> None:
            row = table.currentRow()
            if row < 0:
                QMessageBox.information(dialog, APP_NAME, "Select a history entry first.")
                return
            serial = table.item(row, 0).text()
            package_item = table.item(row, 1)
            package = package_item.data(Qt.ItemDataRole.UserRole) if package_item else ""
            adb = self.adb_path()
            if not adb or not serial or not package:
                return
            if not self._confirmed(
                "Try to restore package?",
                f"Ask Android to restore {package} for user 0 on device {serial}?\\n\\n"
                "This works only when Android still has an installable system package. "
                "For a fully removed app, install its APK instead."
            ):
                return

            def restored(output: str) -> None:
                self.log_message(f"Restore attempt for {package} on {serial}: {output}")
                if "success" in output.casefold():
                    QMessageBox.information(dialog, APP_NAME, f"Android reports that {package} was restored.")
                    if self.device_id == serial:
                        self.load_packages()
                else:
                    QMessageBox.warning(
                        dialog, APP_NAME,
                        f"Android could not restore {package} with install-existing. If this was a regular APK that was fully removed, install the APK again.\\n\\n{output}"
                    )
            self.run_async(
                [adb, "-s", serial, "shell", "cmd", "package", "install-existing", "--user", "0", package],
                restored,
                timeout=60,
            )

        restore_btn.clicked.connect(restore_selected)
        close_btn.clicked.connect(dialog.accept)
        if not history:
            note.setText(note.text() + " No uninstall records have been saved yet.")
        dialog.exec()

    def uninstall_package(self) -> None:
        self._package_action("uninstall")

    def disable_package(self) -> None:
        self._package_action("disable")

    def enable_package(self) -> None:
        self._package_action("enable")


    def _valid_endpoint(self, value: str) -> bool:
        value = value.strip()
        if value.count(":") != 1:
            return False
        host, port_text = value.rsplit(":", 1)
        if not host or not port_text.isdigit():
            return False
        port = int(port_text)
        return 1 <= port <= 65535 and all(ch.isalnum() or ch in ".-_" for ch in host)

    def enable_legacy_tcpip(self) -> None:
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Select an authorized Android device connected by USB first.")
            return
        if ":" in self.device_id:
            QMessageBox.warning(
                self, APP_NAME,
                "Select the phone's USB connection first. This workflow switches ADB to TCP/IP on port 5555 and is intended mainly for Android 10 and older."
            )
            return
        if not self._confirmed(
            "Enable legacy TCP/IP debugging?",
            "This sends 'adb tcpip 5555' to the selected device. Connect your computer and phone to the same trusted Wi-Fi network. A reboot or disabling network debugging may be needed to turn it off.",
        ):
            return
        adb = self.adb_path()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        self.run_async(
            [adb, "-s", self.device_id, "tcpip", "5555"],
            self._legacy_tcpip_enabled,
            timeout=45,
        )

    def _legacy_tcpip_enabled(self, output: str) -> None:
        self.log_message("Legacy TCP/IP mode: " + (output or "ADB command completed."))
        QMessageBox.information(
            self, "TCP/IP mode enabled",
            "If ADB reports that it is restarting in TCP mode on port 5555, find your phone's Wi-Fi IP address in Android Settings. Then use Connect Wi-Fi and enter IP:5555. This legacy method is not the same as Android 11+ Wireless Debugging pairing."
        )

    def wireless_connect(self) -> None:
        endpoint, ok = QInputDialog.getText(
            self, "Connect over Wi-Fi", "Enter Android Wireless Debugging IP address and connection port (IP:port):"
        )
        if not ok or not endpoint.strip():
            return
        endpoint = endpoint.strip()
        if not self._valid_endpoint(endpoint):
            QMessageBox.warning(self, APP_NAME, "Enter a valid IP/host and port, for example 192.168.1.101:35555.")
            return
        if not self._confirmed(
            "Connect to wireless device?",
            f"Connect ADB to {endpoint} on your local network? Only connect to a device you own or are authorized to manage.",
        ):
            return
        adb = self.adb_path()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        self.run_async([adb, "connect", endpoint], lambda out: self._wireless_connected(endpoint, out), timeout=45)

    def _wireless_connected(self, endpoint: str, output: str) -> None:
        self.log_message(f"Wireless connection {endpoint}: {output or 'ADB command completed.'}")
        if "connected to" in output.lower() or "already connected" in output.lower():
            QMessageBox.information(
                self, "Wireless connection",
                f"ADB reports the connection to {endpoint} is ready. If the device is authorized, refresh devices and select it from the device list."
            )
        else:
            QMessageBox.warning(
                self, "Wireless connection result",
                f"ADB did not confirm a connection to {endpoint}. Check that the phone and computer are on the same network and that Wireless Debugging is enabled. The connection port may change.\n\n{output}"
            )
        self.refresh_devices()

    def wireless_pair(self) -> None:
        pairing_endpoint, ok = QInputDialog.getText(
            self, "Pair Android over Wi-Fi", "Enter the pairing IP address and pairing port shown by Android (IP:pairing-port):"
        )
        if not ok or not pairing_endpoint.strip():
            return
        pairing_endpoint = pairing_endpoint.strip()
        if not self._valid_endpoint(pairing_endpoint):
            QMessageBox.warning(self, APP_NAME, "Enter a valid pairing IP and port, for example 192.168.1.101:37123.")
            return
        code, ok = QInputDialog.getText(
            self, "Wireless pairing code", "Enter the six-digit pairing code shown on the Android device:"
        )
        if not ok or not code.strip():
            return
        code = code.strip()
        if not code.isdigit() or len(code) != 6:
            QMessageBox.warning(self, APP_NAME, "The pairing code should contain six digits.")
            return
        if not self._confirmed(
            "Pair Android device?",
            f"Pair this computer with {pairing_endpoint}? Keep the phone awake and the Wireless Debugging pairing-code screen open.",
        ):
            return
        adb = self.adb_path()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        self.run_async(
            [adb, "pair", pairing_endpoint, code],
            lambda out: self._wireless_paired(pairing_endpoint, out),
            timeout=60,
        )

    def _wireless_paired(self, endpoint: str, output: str) -> None:
        self.log_message(f"Wireless pairing {endpoint}: {output or 'ADB command completed.'}")
        if "successfully paired" not in output.lower():
            QMessageBox.warning(
                self, "Pairing result",
                f"ADB did not confirm pairing. Check the code and pairing port, which are different from the normal connection port.\n\n{output}"
            )
            return
        QMessageBox.information(
            self, "Pairing successful",
            "Pairing succeeded. Now enable Wireless Debugging on the phone and use Connect Wi-Fi with the separate IP address and connection port shown on the main Wireless Debugging screen."
        )
        self.wireless_connect()

    def check_ambridge(self, prompt_if_missing: bool = False) -> None:
        """Check for the optional NightLab AMBridge companion package."""
        cmd = self._device_adb("shell", "pm", "list", "packages", "com.nightlab.ambridge")
        if not cmd:
            return
        def checked(output: str) -> None:
            installed = "package:com.nightlab.ambridge" in output.splitlines()
            if installed:
                self.log_message("AMBridge companion detected on the selected device.")
                self.statusBar().showMessage("AMBridge is installed. Loading app names and icons…", 6000)
                self.load_packages()
            elif prompt_if_missing:
                answer = QMessageBox.question(
                    self, "AMBridge is not installed",
                    "NightLab AMBridge is an optional companion expected to use package ID com.nightlab.ambridge.\n\n"
                    "Choose only an APK you trust and have permission to use. This project does not include the companion APK. Would you like to select it and install it with ADB?\n\n"
                    "Requires Android 6 or newer. Keep the phone awake and unlocked during setup.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self.install_ambridge_apk()
            else:
                self.log_message("NightLab AMBridge is not installed. Use AMBridge helper to select a trusted companion APK.")
        self.run_async(cmd, checked, timeout=45)

    def _read_ambridge_cache(self, serial: str) -> dict[str, dict]:
        """Load the last locally cached inventory for this exact ADB device."""
        try:
            payload = json.loads(self._ambridge_cache_path.read_text(encoding="utf-8"))
            if payload.get("_deviceSerial") != serial or not isinstance(payload.get("applications"), list):
                return {}
            return {
                item.get("packageName"): item for item in payload["applications"]
                if isinstance(item, dict) and isinstance(item.get("packageName"), str)
            }
        except (OSError, ValueError, TypeError):
            return {}

    def load_ambridge_inventory(self, show_errors: bool = True) -> None:
        """Ask the Android companion for labels and icons using ADB port forwarding."""
        if not self.device_id:
            if show_errors:
                QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        if "com.nightlab.ambridge" not in getattr(self, "_all_package_names", []):
            if show_errors:
                QMessageBox.information(self, "NightLab AMBridge", "NightLab AMBridge is not installed. Use AMBridge helper to install the companion APK first.")
            return
        adb = self.adb_path()
        if not adb:
            if show_errors:
                QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        serial = self.device_id
        if self.worker is not None and self.worker.isRunning():
            if show_errors:
                QMessageBox.information(self, APP_NAME, "Another ADB operation is still running. Please wait.")
            return
        self._set_busy(True)
        self.log_message("Requesting app names and icons from NightLab AMBridge…")
        self.worker = InventoryWorker(adb, serial)
        self.worker.done.connect(lambda result, error: self._ambridge_inventory_finished(result, error, serial, show_errors))
        self.worker.start()

    def _ambridge_inventory_finished(self, result, error: str, serial: str, show_errors: bool) -> None:
        self._set_busy(False)
        if serial != self.device_id:
            return
        if error:
            self.log_message("AMBridge inventory unavailable: " + error)
            if show_errors:
                QMessageBox.warning(self, "NightLab AMBridge", "Could not retrieve app names and icons. Make sure the phone is unlocked and AMBridge can open, then retry.\n\n" + error)
            return
        apps = result.get("applications", []) if isinstance(result, dict) else []
        self._ambridge_metadata = {
            item.get("packageName"): item for item in apps
            if isinstance(item, dict) and isinstance(item.get("packageName"), str)
        }
        try:
            self._app_data_dir.mkdir(parents=True, exist_ok=True)
            cached_payload = dict(result)
            cached_payload["_deviceSerial"] = serial
            self._ambridge_cache_path.write_text(json.dumps(cached_payload), encoding="utf-8")
        except OSError as exc:
            self.log_message("Could not save AMBridge metadata cache: " + str(exc))
        for package in self.packages:
            item = self._ambridge_metadata.get(package.name, {})
            package.label = item.get("label", "") or package.name
            package.icon_base64 = item.get("iconPngBase64", "")
        self.render_packages()
        self.log_message(f"AMBridge supplied labels and icons for {len(self._ambridge_metadata)} apps.")
        self.statusBar().showMessage(f"Loaded app names and icons for {len(self._ambridge_metadata)} packages", 7000)
        if show_errors:
            QMessageBox.information(self, "NightLab AMBridge", f"Retrieved app names and icons for {len(self._ambridge_metadata)} installed packages.")

    def manage_ambridge(self) -> None:
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        answer = QMessageBox.question(
            self, "AMBridge companion",
            "Refresh app names and icons from NightLab AMBridge, or install the companion if it is missing.\n\n"
            "The companion communicates through a temporary ADB-forwarded local connection; it does not upload your inventory to a server.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.check_ambridge(prompt_if_missing=True)
        elif answer == QMessageBox.StandardButton.No:
            self.load_ambridge_inventory(show_errors=True)

    def install_ambridge_apk(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select NightLab AMBridge APK", "", "Android package (*.apk)"
        )
        if not path:
            return
        if Path(path).name.lower() != "com.nightlab.ambridge.apk":
            answer = QMessageBox.question(
                self, "Confirm AMBridge APK",
                "The selected file is not named com.nightlab.ambridge.apk. The filename alone does not prove its package ID or publisher. Only install an APK you trust and have permission to use.\n\nInstall this APK?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        cmd = self._device_adb("install", "-r", path)
        if not cmd:
            return
        if not self._confirmed(
            "Install AMBridge?",
            "Install the selected companion APK on the connected Android device?\n\n"
            "Android 10 or newer is required. This app does not verify the APK's publisher signature.",
        ):
            return
        self.run_async(cmd, lambda out: self._ambridge_install_finished(out), timeout=180)

    def _ambridge_install_finished(self, output: str) -> None:
        self.log_message("AMBridge install result: " + (output or "Command completed."))
        if "Success" in output:
            QMessageBox.information(
                self, "AMBridge installed",
                "The APK installer reported success. Confirm the installed package ID is com.nightlab.ambridge.\n\n"
                "The desktop app will load the package list and then request app names and icons. Keep the phone unlocked during the first connection."
            )
            self.load_packages()

    def _device_adb(self, *args: str) -> list[str] | None:
        adb = self.adb_path()
        if not adb or not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return None
        return [adb, "-s", self.device_id, *args]

    @staticmethod
    def _explain_adb_error(message: str) -> str:
        """Add plain-language help for common Android package installation failures."""
        lower = message.lower()
        hints = [
            (("insufficient_storage", "not enough space", "no space left"), "Free storage on the phone and retry."),
            (("version_downgrade", "downgrade detected", "install_failed_version_downgrade"), "Enable Allow downgrade if Android permits it, or install a newer version."),
            (("update_incompatible", "signatures do not match", "inconsistent certificates", "install_failed_update_incompatible"), "The installed app uses a different signing key. Uninstalling may erase its data, so do not do that unless you have a backup."),
            (("parse_failed", "failed to parse", "no certificates", "install_parse_failed"), "The APK may be incomplete, corrupt, or incompatible. Re-download it from a trusted source."),
            (("older sdk", "requires newer sdk", "install_failed_older_sdk"), "This APK requires a newer Android version than the phone provides."),
            (("no_matching_abis", "install_failed_no_matching_abis"), "The APK does not include a CPU architecture supported by this phone. Find the correct APK variant."),
            (("missing_split", "install_failed_missing_split", "missing base apk"), "The split set is incomplete. Add the base APK and every matching split from the same app version."),
            (("invalid_apk", "install_failed_invalid_apk"), "The APK or split set may be invalid, mixed from different versions, or incomplete."),
            (("test_only", "install_failed_test_only"), "This is marked as a test-only APK. Only proceed if you trust the source and understand the implications."),
            (("user_restricted", "install_failed_user_restricted"), "Android or device policy blocked installation. Check installation restrictions and work-profile policy."),
            (("unauthorized",), "Unlock the phone and approve the USB debugging prompt."),
            (("offline", "no devices/emulators found"), "Reconnect the phone and refresh the device list."),
        ]
        for tokens, hint in hints:
            if any(token in lower for token in tokens):
                return f"{message} | Hint: {hint}"
        return message

    def install_apks(self) -> None:
        """Open a batch APK queue supporting drag/drop, options, retry, and logs."""
        adb = self.adb_path()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        self._open_apk_queue(split_mode=False)

    def install_split_apks(self) -> None:
        """Install one app's split APK set together using install-multiple."""
        adb = self.adb_path()
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        self._open_apk_queue(split_mode=True)

    def _open_apk_queue(self, split_mode: bool = False, retry_paths: list[str] | None = None) -> None:
        """Queue UI for batch installs. Each standalone APK is installed separately."""
        adb = self.adb_path()
        if not adb or not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Split APK installer" if split_mode else "Batch APK installer")
        dialog.resize(700, 520)
        layout = QVBoxLayout(dialog)
        intro = QLabel(
            "Select every part of ONE app bundle (base.apk + matching config APKs)."
            if split_mode else
            "Add separate APK files to install them one after another. Drag files into the list or use Add APKs."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        queue = ApkDropList()
        queue.setToolTip("Drop .apk files here")
        layout.addWidget(queue, 1)
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        layout.addWidget(progress)
        status = QLabel("Ready")
        status.setWordWrap(True)
        layout.addWidget(status)

        options_row = QHBoxLayout()
        reinstall = QCheckBox("Reinstall / update (-r)")
        reinstall.setChecked(True)
        downgrade = QCheckBox("Allow downgrade (-d)")
        grant = QCheckBox("Grant runtime permissions (-g)")
        all_devices = QCheckBox("Install on all connected devices")
        options_row.addWidget(reinstall)
        options_row.addWidget(downgrade)
        options_row.addWidget(grant)
        options_row.addWidget(all_devices)
        layout.addLayout(options_row)

        buttons = QHBoxLayout()
        add_btn = QPushButton("Add APKs…")
        remove_btn = QPushButton("Remove selected")
        install_btn = QPushButton("Install queue")
        retry_btn = QPushButton("Retry failed")
        retry_btn.setEnabled(False)
        cancel_btn = QPushButton("Close")
        for b in (add_btn, remove_btn, retry_btn, install_btn, cancel_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)

        entries: list[dict] = []
        busy = {"value": False, "cancel": False, "split": split_mode}
        active_dialog = dialog

        def add_paths(paths: list[str]) -> None:
            existing = {item["path"] for item in entries}
            for raw in paths:
                path = str(Path(raw).expanduser().resolve())
                if Path(path).suffix.lower() != ".apk" or not Path(path).is_file() or path in existing:
                    continue
                existing.add(path)
                entries.append({"path": path, "status": "Queued", "detail": ""})
                details = f"{Path(path).stat().st_size / 1024 / 1024:.1f} MB"
                aapt = shutil.which("aapt") or shutil.which("aapt2")
                if aapt:
                    try:
                        meta = subprocess.run([aapt, "dump", "badging", path], capture_output=True, text=True, timeout=8)
                        for line in meta.stdout.splitlines():
                            if line.startswith("package:"):
                                fields = dict(part.split("=", 1) for part in line.replace("package:", "").split() if "=" in part)
                                package = fields.get("name", "").strip("'")
                                version = fields.get("versionName", "").strip("'")
                                if package:
                                    details += f" • {package}" + (f" • v{version}" if version else "")
                                break
                    except (OSError, subprocess.SubprocessError):
                        pass
                item = QListWidgetItem(f"Queued  •  {Path(path).name}  •  {details}")
                item.setData(Qt.ItemDataRole.UserRole, path)
                queue.addItem(item)
            if entries and split_mode:
                status.setText("Split mode: every queued file must belong to the same app and version.")
            elif entries:
                status.setText(f"{len(entries)} APK file(s) queued.")
            install_btn.setEnabled(bool(entries) and not busy["value"])

        # Keep the file picker available as a reliable fallback to desktop drag-and-drop.
        queue.filesDropped.connect(add_paths)

        def add_files() -> None:
            paths, _ = QFileDialog.getOpenFileNames(dialog, "Add APK files", "", "Android packages (*.apk)")
            add_paths(paths)

        def remove_selected() -> None:
            if busy["value"]:
                return
            selected = {item.data(Qt.ItemDataRole.UserRole) for item in queue.selectedItems()}
            if not selected:
                return
            entries[:] = [entry for entry in entries if entry["path"] not in selected]
            for row in reversed(range(queue.count())):
                if queue.item(row).data(Qt.ItemDataRole.UserRole) in selected:
                    queue.takeItem(row)
            install_btn.setEnabled(bool(entries))

        def update_item(path: str, state: str, detail: str = "") -> None:
            for index, entry in enumerate(entries):
                if entry["path"] == path:
                    entry["status"] = state
                    entry["detail"] = detail
                    queue.item(index).setText(f"{state}  •  {Path(path).name}" + (f"  —  {detail}" if detail else ""))
                    break

        def set_running(running: bool) -> None:
            busy["value"] = running
            add_btn.setEnabled(not running)
            remove_btn.setEnabled(not running)
            install_btn.setEnabled(not running and any(e["status"] in ("Queued", "Failed") for e in entries))
            retry_btn.setEnabled(not running and any(e["status"] == "Failed" for e in entries))
            cancel_btn.setText("Cancel pending" if running else "Close")

        def run_batch(only_failed: bool = False) -> None:
            if busy["value"]:
                return
            selected_entries = [e for e in entries if e["status"] == "Failed"] if only_failed else [
                e for e in entries if e["status"] in ("Queued", "Failed")
            ]
            if not selected_entries:
                QMessageBox.information(dialog, APP_NAME, "There are no queued or failed APKs to install.")
                return
            if split_mode and len(selected_entries) < 2:
                QMessageBox.information(dialog, APP_NAME, "Split install requires at least two APK files. For a normal APK, use the batch installer.")
                return
            serial = self.device_id
            if not serial:
                QMessageBox.warning(dialog, APP_NAME, "Select a connected Android device first.")
                return
            targets = [serial]
            if all_devices.isChecked():
                try:
                    scan = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=20, env=_host_tool_env())
                    targets = [line.split()[0] for line in scan.stdout.splitlines()[1:] if len(line.split()) >= 2 and line.split()[1] == "device"]
                except (OSError, subprocess.SubprocessError) as exc:
                    QMessageBox.warning(dialog, APP_NAME, f"Could not list connected devices: {exc}")
                    return
                if not targets:
                    QMessageBox.information(dialog, APP_NAME, "No authorized Android devices are connected.")
                    return
            if split_mode:
                # When Android SDK Build Tools are available, catch mixed app/version
                # selections before invoking adb install-multiple.
                aapt = shutil.which("aapt") or shutil.which("aapt2")
                if aapt:
                    split_identities: set[tuple[str, str]] = set()
                    unrecognized: list[str] = []
                    for item in selected_entries:
                        try:
                            meta = subprocess.run(
                                [aapt, "dump", "badging", item["path"]],
                                capture_output=True, text=True, timeout=10, env=_host_tool_env()
                            )
                            package_line = next(
                                (line for line in meta.stdout.splitlines() if line.startswith("package:")),
                                ""
                            )
                            fields = dict(
                                part.split("=", 1)
                                for part in package_line.replace("package:", "").split()
                                if "=" in part
                            )
                            package_name = fields.get("name", "").strip("'")
                            version_code = fields.get("versionCode", "").strip("'")
                            if meta.returncode != 0 or not package_name:
                                unrecognized.append(Path(item["path"]).name)
                            else:
                                split_identities.add((package_name, version_code))
                        except (OSError, subprocess.SubprocessError):
                            unrecognized.append(Path(item["path"]).name)
                    if len(split_identities) > 1:
                        QMessageBox.warning(
                            dialog, "Mixed split APK set",
                            "These files appear to belong to different apps or versions. "
                            "Select the base APK and matching splits from the same app version, then retry."
                        )
                        return
                    if unrecognized:
                        self.log_message(
                            "Split APK metadata could not be verified for: " + ", ".join(unrecognized)
                        )
            target_desc = f"{len(selected_entries)} APK file(s) on {len(targets)} device(s): {', '.join(targets)}"
            if not self._confirmed("Confirm APK installation", f"Install {target_desc}? Only install APKs you trust."):
                return
            busy["cancel"] = False
            set_running(True)
            results = {"success": 0, "failed": 0, "skipped": 0}
            for entry in selected_entries:
                entry["status"] = "Queued"
            current = {"index": 0}

            def next_item() -> None:
                if busy["cancel"]:
                    for entry in selected_entries[current["index"]:]:
                        update_item(entry["path"], "Skipped", "Cancelled before install")
                        results["skipped"] += 1
                    finish()
                    return
                if current["index"] >= len(selected_entries):
                    finish()
                    return
                entry = selected_entries[current["index"]]
                path = entry["path"]
                current["index"] += 1
                progress.setValue(int((current["index"] - 1) * 100 / max(1, len(selected_entries))))
                status.setText(f"Installing {current['index']} of {len(selected_entries)}: {Path(path).name}")
                args = ["install"]
                if reinstall.isChecked():
                    args.append("-r")
                if downgrade.isChecked():
                    args.append("-d")
                if grant.isChecked():
                    args.append("-g")

                if split_mode:
                    paths = [e["path"] for e in selected_entries]
                    split_args = ["install-multiple"]
                    if reinstall.isChecked():
                        split_args.append("-r")
                    if downgrade.isChecked():
                        split_args.append("-d")
                    if grant.isChecked():
                        split_args.append("-g")
                    for item in selected_entries:
                        update_item(item["path"], "Installing", "Split bundle")
                    device_index = {"value": 0}
                    device_results = {"ok": True, "messages": []}
                    def split_next_device() -> None:
                        if device_index["value"] >= len(targets):
                            result = " | ".join(device_results["messages"])
                            for item in selected_entries:
                                update_item(item["path"], "Installed" if device_results["ok"] else "Failed", result)
                            results["success" if device_results["ok"] else "failed"] += len(selected_entries)
                            current["index"] = len(selected_entries)
                            self.log_message("Split APK queue result: " + result)
                            finish()
                            return
                        target = targets[device_index["value"]]
                        device_index["value"] += 1
                        command = [adb, "-s", target, *split_args, *paths]
                        def split_done(output: str) -> None:
                            result = output.strip() or "(no output)"
                            ok = "success" in result.lower()
                            device_results["ok"] = device_results["ok"] and ok
                            device_results["messages"].append(f"{target}: {self._explain_adb_error(result)}")
                            split_next_device()
                        self.run_async(command, split_done, timeout=360, on_error=lambda err: split_done(err))
                    split_next_device()
                    return

                device_index = {"value": 0}
                device_results = {"ok": True, "messages": []}
                update_item(path, "Installing")
                def install_next_device() -> None:
                    if device_index["value"] >= len(targets):
                        result = " | ".join(device_results["messages"])
                        update_item(path, "Installed" if device_results["ok"] else "Failed", result)
                        results["success" if device_results["ok"] else "failed"] += 1
                        self.log_message(f"APK queue {Path(path).name}: {result}")
                        next_item()
                        return
                    target = targets[device_index["value"]]
                    device_index["value"] += 1
                    command = [adb, "-s", target, *args, path]
                    def install_done(output: str) -> None:
                        result = output.strip() or "(no output)"
                        ok = "success" in result.lower()
                        device_results["ok"] = device_results["ok"] and ok
                        device_results["messages"].append(f"{target}: {self._explain_adb_error(result)}")
                        install_next_device()
                    self.run_async(command, install_done, timeout=240, on_error=lambda err: install_done(err))
                install_next_device()

            def finish() -> None:
                progress.setValue(100 if not busy["cancel"] else progress.value())
                set_running(False)
                status.setText(
                    f"Finished — {results['success']} installed, {results['failed']} failed, {results['skipped']} skipped. "
                    "Use Retry failed to retry failed items."
                )
                self.log_message(
                    f"APK batch summary: {results['success']} installed, {results['failed']} failed, {results['skipped']} skipped."
                )
                retry_btn.setEnabled(any(e["status"] == "Failed" for e in entries))
                try:
                    self._app_data_dir.mkdir(parents=True, exist_ok=True)
                    report = self._app_data_dir / f"apk-install-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
                    report.write_text(
                        f"Devices: {', '.join(targets)}\nDate: {datetime.now().isoformat()}\n"
                        + "\n".join(f"{e['status']}: {e['path']} :: {e['detail']}" for e in entries),
                        encoding="utf-8",
                    )
                    self.log_message(f"Saved APK installation report: {report}")
                except OSError as exc:
                    self.log_message(f"Could not save APK installation report: {exc}")
                QMessageBox.information(dialog, "APK installation summary", status.text())

            next_item()

        def cancel_or_close() -> None:
            if busy["value"]:
                busy["cancel"] = True
                status.setText("Cancellation requested. The current ADB install will finish; pending files will be skipped.")
            else:
                dialog.accept()

        add_btn.clicked.connect(add_files)
        remove_btn.clicked.connect(remove_selected)
        install_btn.clicked.connect(lambda: run_batch(False))
        retry_btn.clicked.connect(lambda: run_batch(True))
        cancel_btn.clicked.connect(cancel_or_close)
        if retry_paths:
            add_paths(retry_paths)
        dialog.exec()

    def clear_app_data(self) -> None:
        package = self.selected_package()
        cmd = self._device_adb("shell", "pm", "clear", package) if package else None
        if cmd and self._confirmed("Clear app data?", f"This deletes the app's data and settings.\n\n{package}"):
            self.run_async(cmd, lambda out: self.log_message(f"Clear data for {package}: {out}"), timeout=90)

    def upload_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to upload to Downloads", "")
        if not paths:
            return
        adb = self.adb_path()
        if not adb or not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        def run_next(i: int = 0) -> None:
            if i >= len(paths):
                self.log_message("File upload queue finished.")
                return
            path = paths[i]
            self.run_async([adb, "-s", self.device_id, "push", path, "/sdcard/Download/" + Path(path).name],
                lambda out: (self.log_message(f"Uploaded {Path(path).name}: {out}"), run_next(i + 1)), timeout=180)
        run_next()

    def backup_user_apps(self) -> None:
        """Back up APK files for third-party apps; Android app-private data is not included."""
        adb = self.adb_path()
        serial = self.device_id
        if not adb:
            QMessageBox.warning(self, APP_NAME, "ADB is not installed or is not on PATH.")
            return
        if not serial:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        destination = QFileDialog.getExistingDirectory(self, "Choose backup destination folder")
        if not destination:
            return
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        root = Path(destination) / f"ADB-App-Manager-Backup-{stamp}"
        try:
            root.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not create backup folder:\n{exc}")
            return
        if not self._confirmed(
            "Back up user apps",
            f"Back up installable APK files for user-installed apps from {serial}?\n\n"
            "This does not include app-private data, logins, settings, or Android-protected files. "
            "Some apps may have no accessible APK path."
        ):
            try:
                root.rmdir()
            except OSError:
                pass
            return

        state = {"packages": [], "index": 0, "backed_up": [], "failed": [], "manifest": []}
        self.log_message(f"Starting user-app APK backup from {serial} to {root}")
        def list_done(output: str) -> None:
            state["packages"] = parse_package_names(output)
            if not state["packages"]:
                self.log_message("No user-installed packages were returned by Android.")
                QMessageBox.information(self, APP_NAME, "No user-installed apps were found to back up.")
                return
            self.log_message(f"Found {len(state['packages'])} user-installed app(s). Backing up APK files…")
            backup_next_package()
        def backup_next_package() -> None:
            if state["index"] >= len(state["packages"]):
                manifest = {
                    "format": "ADB-App-Manager APK backup",
                    "version": 1,
                    "device_serial": serial,
                    "created_at": datetime.now().isoformat(),
                    "backup_type": "APK files only; app-private data is not included",
                    "backed_up_packages": state["backed_up"],
                    "failed_packages": state["failed"],
                    "packages": state["manifest"],
                }
                try:
                    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                    summary = (
                        f"Backup finished.\n\nApps with APKs saved: {len(state['backed_up'])}\n"
                        f"Apps failed or unavailable: {len(state['failed'])}\n\n"
                        f"Backup folder:\n{root}\n\n"
                        "Only APK files and a manifest were saved. App data and accounts are not included."
                    )
                    self.log_message(f"User-app APK backup finished: {len(state['backed_up'])} backed up, {len(state['failed'])} failed.")
                    QMessageBox.information(self, "Backup complete", summary)
                except OSError as exc:
                    QMessageBox.warning(self, APP_NAME, f"Backup files were copied, but the manifest could not be saved:\n{exc}")
                return
            package = state["packages"][state["index"]]
            state["index"] += 1
            self.statusBar().showMessage(f"Backing up app {state['index']} of {len(state['packages'])}: {package}")
            def paths_done(output: str) -> None:
                remote_paths = [line.strip().removeprefix("package:") for line in output.splitlines() if line.strip().startswith("package:")]
                if not remote_paths:
                    state["failed"].append({"package": package, "reason": "Android returned no APK paths"})
                    state["manifest"].append({"package": package, "status": "unavailable", "apk_files": []})
                    backup_next_package()
                    return
                app_dir = root / package
                try:
                    app_dir.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    state["failed"].append({"package": package, "reason": str(exc)})
                    state["manifest"].append({"package": package, "status": "failed", "apk_files": []})
                    backup_next_package()
                    return
                paths_state = {"index": 0, "ok": True, "files": []}
                def pull_next() -> None:
                    if paths_state["index"] >= len(remote_paths):
                        if paths_state["ok"] and paths_state["files"]:
                            state["backed_up"].append(package)
                            state["manifest"].append({"package": package, "status": "backed_up", "apk_files": paths_state["files"]})
                        else:
                            state["failed"].append({"package": package, "reason": "One or more APK files could not be pulled"})
                            state["manifest"].append({"package": package, "status": "partial_or_failed", "apk_files": paths_state["files"]})
                        backup_next_package()
                        return
                    remote = remote_paths[paths_state["index"]]
                    paths_state["index"] += 1
                    filename = Path(remote).name or f"split-{paths_state['index']}.apk"
                    local = app_dir / filename
                    def pull_done(output: str) -> None:
                        if local.is_file() and local.stat().st_size > 0:
                            paths_state["files"].append(str(local.relative_to(root)))
                            self.log_message(f"Backed up {package}/{filename}")
                        else:
                            paths_state["ok"] = False
                            self.log_message(f"Could not back up {package}/{filename}: {output}")
                        pull_next()
                    def pull_failed(error: str) -> None:
                        paths_state["ok"] = False
                        self.log_message(f"Could not pull {remote}: {error}")
                        pull_next()
                    self.run_async([adb, "-s", serial, "pull", remote, str(local)], pull_done, timeout=240, on_error=pull_failed)
                pull_next()
            self.run_async([adb, "-s", serial, "shell", "pm", "path", package], paths_done, timeout=60,
                           on_error=lambda error: (state["failed"].append({"package": package, "reason": error}),
                                                   state["manifest"].append({"package": package, "status": "failed", "apk_files": []}),
                                                   backup_next_package()))
        self.run_async([adb, "-s", serial, "shell", "pm", "list", "packages", "-3"], list_done, timeout=60)

    def restore_user_app_backup(self) -> None:
        """Restore one app from a backup snapshot, supporting the snapshot or its parent folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Select backup snapshot folder (or the folder containing it)"
        )
        if not folder:
            return

        root = Path(folder)
        # Resolve the common case where the user selects the parent of a timestamped backup.
        if not (root / "manifest.json").is_file():
            snapshots = sorted(
                path for path in root.iterdir()
                if path.is_dir() and (path / "manifest.json").is_file()
            ) if root.is_dir() else []
            if len(snapshots) == 1:
                root = snapshots[0]
            elif len(snapshots) > 1:
                selected_snapshot, ok = QInputDialog.getItem(
                    self, "Choose backup snapshot", "Select the backup you want to restore:",
                    [path.name for path in snapshots], 0, False
                )
                if not ok or not selected_snapshot:
                    return
                root = root / selected_snapshot

        if not root.is_dir():
            QMessageBox.warning(self, APP_NAME, "The selected backup folder does not exist.")
            return

        manifest_path = root / "manifest.json"
        manifest_packages: dict[str, dict] = {}
        if manifest_path.is_file():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
                for item in manifest_data.get("packages", []):
                    if isinstance(item, dict) and item.get("package"):
                        manifest_packages[str(item["package"])] = item
            except (OSError, json.JSONDecodeError) as exc:
                QMessageBox.warning(
                    self, APP_NAME,
                    f"The backup manifest could not be read. APK files can still be checked manually.\n\n{exc}"
                )

        # Inspect only direct child app folders, never the whole snapshot as one split bundle.
        app_dirs = sorted(
            path for path in root.iterdir()
            if path.is_dir() and any(candidate.is_file() for candidate in path.rglob("*.apk"))
        )
        direct_apks = sorted(str(path) for path in root.glob("*.apk") if path.is_file())
        if not app_dirs and not direct_apks:
            QMessageBox.information(
                self, APP_NAME,
                "No APK files were found. Choose the backup snapshot folder (the folder containing manifest.json and app subfolders)."
            )
            return
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return

        if app_dirs:
            display_to_dir: dict[str, Path] = {}
            for app_dir in app_dirs:
                apk_count = sum(1 for path in app_dir.rglob("*.apk") if path.is_file())
                info = manifest_packages.get(app_dir.name, {})
                status_text = str(info.get("status", "backup found"))
                label = f"{app_dir.name} — {apk_count} APK file(s) — {status_text}"
                display_to_dir[label] = app_dir
            selected_label, ok = QInputDialog.getItem(
                self, "Restore app backup",
                "Choose ONE app to restore. Repeat this action for other apps:",
                list(display_to_dir), 0, False
            )
            if not ok or not selected_label:
                return
            app_dir = display_to_dir[selected_label]
            apk_paths = sorted(str(path) for path in app_dir.rglob("*.apk") if path.is_file())
            split_mode = len(apk_paths) > 1
            label = f"{app_dir.name} ({len(apk_paths)} APK file(s))"
        else:
            # A folder of ordinary APKs is a batch of separate apps, not one split bundle.
            apk_paths = direct_apks
            split_mode = False
            label = f"{len(apk_paths)} separate APK file(s)"

        if not apk_paths:
            QMessageBox.information(self, APP_NAME, "No APK files were found for the selected app.")
            return
        if not self._confirmed(
            "Restore app APK backup",
            f"Queue {label} for installation on {self.device_id}?\n\n"
            "A single APK uses normal install; split APKs for one app are installed together. "
            "Separate APK files in a folder are handled as a normal batch.\n\n"
            "This restores APK files only, not app-private data, accounts, logins, or settings. "
            "Restore can fail if the signing key, Android version, or device requirements do not match."
        ):
            return
        self._open_apk_queue(split_mode=split_mode, retry_paths=apk_paths)

    def shell_command(self) -> None:
        command, ok = QInputDialog.getText(self, "ADB shell", "Enter an Android shell command:")
        if not ok or not command.strip():
            return
        if not self._confirmed("Run shell command?", f"Run on the connected device?\n\n{command}\n\nOnly run commands you understand."):
            return
        cmd = self._device_adb("shell", "sh", "-c", command)
        if cmd:
            self.run_async(cmd, lambda out: self.log_message("Shell output:\n" + (out or "(no output)")), timeout=120)

    def reboot_device(self) -> None:
        """Use ADB to reboot an authorized Android device into a supported target."""
        modes = ["System", "Recovery", "Bootloader / Fastboot", "EDL (device-dependent)"]
        mode, ok = QInputDialog.getItem(self, "ADB reboot options", "Choose reboot target:", modes, 0, False)
        if not ok:
            return
        args = {
            "System": ["reboot"],
            "Recovery": ["reboot", "recovery"],
            "Bootloader / Fastboot": ["reboot", "bootloader"],
            "EDL (device-dependent)": ["reboot", "edl"],
        }[mode]
        cmd = self._device_adb(*args)
        if not cmd:
            return
        warning = ""
        if mode == "EDL (device-dependent)":
            warning = (
                "\n\nEDL is a low-level Qualcomm emergency download mode. This command is not supported "
                "on every phone; some devices may require authorized service access or a hardware key sequence. "
                "Entering EDL can leave the phone difficult to recover if you do not have the correct recovery tools."
            )
        if self._confirmed("Confirm device reboot", f"Send ADB reboot command for: {mode}?{warning}"):
            self.run_async(
                cmd,
                lambda out: self.log_message(f"ADB reboot command sent ({mode}). {out}".strip()),
                timeout=30,
            )

    def fastboot_reboot_device(self) -> None:
        """Run standard fastboot reboot commands after the phone is already in bootloader mode."""
        fastboot = shutil.which("fastboot")
        if not fastboot:
            QMessageBox.warning(
                self, APP_NAME,
                "The fastboot executable was not found on PATH. Install Android SDK Platform-Tools and try again."
            )
            return
        try:
            scan = subprocess.run(
                [fastboot, "devices"], capture_output=True, text=True, timeout=15, env=_host_tool_env()
            )
        except (OSError, subprocess.SubprocessError) as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not query fastboot devices:\n{exc}")
            return
        devices = [line.split()[0] for line in scan.stdout.splitlines() if len(line.split()) >= 2]
        if scan.returncode != 0 or not devices:
            QMessageBox.information(
                self, APP_NAME,
                "No fastboot device was detected.\n\nReboot the phone to Bootloader / Fastboot first, then check the USB connection and drivers."
            )
            if scan.stderr.strip():
                self.log_message("fastboot devices: " + scan.stderr.strip())
            return
        if len(devices) == 1:
            serial = devices[0]
        else:
            serial, ok = QInputDialog.getItem(
                self, "Select fastboot device", "Choose the target device:", devices, 0, False
            )
            if not ok or not serial:
                return
        actions = ["Reboot to Android", "Reboot to recovery", "Reboot to bootloader again"]
        action, ok = QInputDialog.getItem(self, "Fastboot reboot options", "Choose command:", actions, 0, False)
        if not ok:
            return
        command_args = {
            "Reboot to Android": ["reboot"],
            "Reboot to recovery": ["reboot", "recovery"],
            "Reboot to bootloader again": ["reboot-bootloader"],
        }[action]
        if not self._confirmed(
            "Confirm fastboot command",
            f"Run fastboot {' '.join(command_args)} on {serial}?\n\nThis only reboots the device; it does not flash or erase partitions."
        ):
            return
        command = [fastboot, "-s", serial, *command_args]
        self.run_async(
            command,
            lambda out: self.log_message(f"Fastboot command sent to {serial}: {action}. {out}".strip()),
            timeout=45,
        )

    def save_preset(self) -> None:
        selected = self.selected_packages()
        if not selected:
            QMessageBox.information(self, APP_NAME, "Select one or more packages first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save package preset", "preset.txt", "Preset files (*.txt)")
        if path:
            try:
                Path(path).write_text("\n".join(selected) + "\n", encoding="utf-8")
                self.log_message(f"Saved preset with {len(selected)} package(s) to {path}.")
            except OSError as exc:
                QMessageBox.warning(self, APP_NAME, f"Could not save preset: {exc}")

    def load_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load package preset", "", "Preset files (*.txt)")
        if not path:
            return
        try:
            names = {x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("#")}
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not load preset: {exc}")
            return
        matched_names = names.intersection({p.name for p in self.packages})
        self._checked_packages.update(matched_names)
        self.render_packages()
        self.log_message(f"Preset loaded: checked {len(matched_names)} matching package(s) out of {len(names)}. Review before running any batch action.")

    def export_csv(self) -> None:
        if not self.packages:
            QMessageBox.information(self, APP_NAME, "Load packages before exporting.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export package list", "android-packages.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["package_name", "classification"])
                writer.writerows((p.name, p.kind) for p in self.packages)
            self.log_message(f"Exported {len(self.packages)} packages to {path}.")
        except OSError as exc:
            QMessageBox.warning(self, APP_NAME, f"Could not export CSV:\n{exc}")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Noto Sans", 10))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
