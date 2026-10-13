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
        self.table.setHorizontalHeaderLabels(["App name / package", "Classification", "Debloat guidance"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
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
            ("Connection", "Configure older TCP/IP debugging.", [
                ("Enable TCP/IP (USB)", self.enable_legacy_tcpip)
            ]),
            ("Device maintenance", "Restart the selected device.", [
                ("Reboot device", self.reboot_device)
            ]),
            ("Package presets", "Save or restore package selections.", [
                ("Save preset", self.save_preset), ("Load preset", self.load_preset)
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
        for index, package in enumerate(rows):
            name_item = QTableWidgetItem(package.label or package.name)
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
        self.statusBar().showMessage(f"Showing {len(rows)} of {len(self.packages)} packages")
        self._selection_changed()

    def selected_packages(self) -> list[str]:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        values = []
        for row in rows:
            item = self.table.item(row, 0)
            if item:
                values.append(item.data(Qt.ItemDataRole.UserRole))
        if not values and self.table.currentRow() >= 0:
            item = self.table.item(self.table.currentRow(), 0)
            if item:
                values.append(item.data(Qt.ItemDataRole.UserRole))
        return values

    def selected_package(self) -> str | None:
        selected = self.selected_packages()
        return selected[0] if selected else None

    def _selection_changed(self) -> None:
        enabled = bool(self.device_id and self.selected_packages())
        self.uninstall_btn.setEnabled(enabled)
        self.disable_btn.setEnabled(enabled)
        self.enable_btn.setEnabled(enabled)

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
        options_row.addWidget(reinstall)
        options_row.addWidget(downgrade)
        options_row.addWidget(grant)
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
            target_desc = f"{len(selected_entries)} APK file(s) on {serial}"
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
                    remaining = selected_entries[current["index"]:]
                    for entry in remaining:
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
                update_item(path, "Installing")
                progress.setValue(int((current["index"] - 1) * 100 / max(1, len(selected_entries))))
                status.setText(f"Installing {current['index']} of {len(selected_entries)}: {Path(path).name}")
                self.log_message(f"APK queue: installing {Path(path).name} on {serial}")
                args = ["install"]
                if reinstall.isChecked():
                    args.append("-r")
                if downgrade.isChecked():
                    args.append("-d")
                if grant.isChecked():
                    args.append("-g")
                if split_mode:
                    # Split bundles are submitted together in a single ADB command below.
                    install_split()
                    return
                command = [adb, "-s", serial, *args, path]

                def completed(output: str) -> None:
                    result = output.strip() or "(no output)"
                    ok = "success" in result.lower()
                    update_item(path, "Installed" if ok else "Failed", result)
                    results["success" if ok else "failed"] += 1
                    self.log_message(f"APK queue {Path(path).name}: {result}")
                    next_item()
                self.run_async(command, completed, timeout=240, on_error=lambda err: completed('ADB error: ' + err))

            def install_split() -> None:
                paths = [e["path"] for e in selected_entries]
                args = ["install-multiple"]
                if reinstall.isChecked():
                    args.append("-r")
                if downgrade.isChecked():
                    args.append("-d")
                if grant.isChecked():
                    args.append("-g")
                for entry in selected_entries:
                    update_item(entry["path"], "Installing", "Part of split bundle")
                progress.setValue(20)
                command = [adb, "-s", serial, *args, *paths]
                def completed(output: str) -> None:
                    result = output.strip() or "(no output)"
                    ok = "success" in result.lower()
                    for entry in selected_entries:
                        update_item(entry["path"], "Installed" if ok else "Failed", result)
                    results["success" if ok else "failed"] += len(selected_entries)
                    self.log_message("Split APK queue result: " + result)
                    current["index"] = len(selected_entries)
                    finish()
                self.run_async(command, completed, timeout=360, on_error=lambda err: completed('ADB error: ' + err))

            def finish() -> None:
                progress.setValue(100 if not busy["cancel"] else progress.value())
                set_running(False)
                status.setText(
                    f"Finished — {results['success']} installed, {results['failed']} failed, {results['skipped']} skipped. "
                    "Select a failed row and use Retry failed to retry failures."
                )
                self.log_message(
                    f"APK batch summary: {results['success']} installed, {results['failed']} failed, {results['skipped']} skipped."
                )
                retry_btn.setEnabled(any(e["status"] == "Failed" for e in entries))
                try:
                    self._app_data_dir.mkdir(parents=True, exist_ok=True)
                    report = self._app_data_dir / f"apk-install-log-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
                    report.write_text(
                        f"Device: {serial}\nDate: {datetime.now().isoformat()}\n"
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
        mode, ok = QInputDialog.getItem(self, "Reboot device", "Choose target:", ["System", "Bootloader / Fastboot", "Recovery"], 0, False)
        if not ok:
            return
        args = {"System": ["reboot"], "Bootloader / Fastboot": ["reboot", "bootloader"], "Recovery": ["reboot", "recovery"]}[mode]
        cmd = self._device_adb(*args)
        if cmd and self._confirmed("Reboot device?", f"Reboot the connected device into {mode}?"):
            self.run_async(cmd, lambda out: self.log_message(f"Reboot command sent ({mode})."), timeout=30)

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
        self.table.clearSelection()
        matched = 0
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) in names:
                self.table.selectRow(row)
                matched += 1
        self.log_message(f"Preset loaded: selected {matched} matching package(s) out of {len(names)}.")

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
