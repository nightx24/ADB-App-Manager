from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QHeaderView, QInputDialog,
)

APP_NAME = "ADB App Manager"


@dataclass
class Package:
    name: str
    kind: str


class Worker(QThread):
    done = Signal(object, str)

    def __init__(self, command: list[str], timeout: int = 40):
        super().__init__()
        self.command = command
        self.timeout = timeout

    def run(self) -> None:
        try:
            proc = subprocess.run(self.command, capture_output=True, text=True, timeout=self.timeout)
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1080, 720)
        self.setMinimumSize(760, 520)
        self.packages: list[Package] = []
        self.third_party_names: set[str] = set()
        self.device_id: str | None = None
        self._ambridge_prompted_devices: set[str] = set()
        self.worker: Worker | None = None
        self._build_ui()
        self._style_ui()
        self.refresh_devices()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("ADB App Manager")
        title.setObjectName("title")
        subtitle = QLabel("Manage Android packages through Android Debug Bridge")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(240)
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        header.addWidget(self.device_combo)
        self.connect_btn = QPushButton("Refresh devices")
        self.connect_btn.clicked.connect(self.refresh_devices)
        header.addWidget(self.connect_btn)
        self.wifi_connect_btn = QPushButton("Connect Wi-Fi")
        self.wifi_connect_btn.clicked.connect(self.wireless_connect)
        header.addWidget(self.wifi_connect_btn)
        self.wifi_pair_btn = QPushButton("Pair Wi-Fi")
        self.wifi_pair_btn.clicked.connect(self.wireless_pair)
        header.addWidget(self.wifi_pair_btn)
        root.addLayout(header)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search package names…")
        self.search.textChanged.connect(self.render_packages)
        toolbar.addWidget(self.search, 1)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All packages", "Third-party apps", "System apps"])
        self.filter_combo.currentIndexChanged.connect(self.render_packages)
        toolbar.addWidget(self.filter_combo)
        self.reload_btn = QPushButton("Load packages")
        self.reload_btn.clicked.connect(self.load_packages)
        toolbar.addWidget(self.reload_btn)
        self.export_btn = QPushButton("Export CSV")
        self.export_btn.clicked.connect(self.export_csv)
        toolbar.addWidget(self.export_btn)
        root.addLayout(toolbar)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Package name", "Type"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
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
        actions.addStretch(1)
        root.addLayout(actions)
        tools = QHBoxLayout()
        for label, callback in [("Shell command", self.shell_command), ("Upload files", self.upload_files), ("Reboot", self.reboot_device), ("Enable TCP/IP (USB)", self.enable_legacy_tcpip), ("Save preset", self.save_preset), ("Load preset", self.load_preset)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            tools.addWidget(button)
        root.addLayout(tools)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(125)
        self.log.setPlaceholderText("Activity log")
        root.addWidget(self.log)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready. Connect an Android device with USB debugging enabled.")

        refresh_action = QAction("Refresh devices", self)
        refresh_action.triggered.connect(self.refresh_devices)
        self.menuBar().addMenu("Device").addAction(refresh_action)

    def _style_ui(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #11151c; color: #e8edf5; font-size: 13px; }
            QLabel#title { font-size: 25px; font-weight: 700; color: #ffffff; }
            QLabel#subtitle { color: #a4afc0; }
            QLineEdit, QComboBox, QTextEdit, QTableWidget { background: #191f29; border: 1px solid #303949; border-radius: 7px; padding: 7px; selection-background-color: #315eaa; }
            QHeaderView::section { background: #202837; color: #dce5f3; padding: 8px; border: none; }
            QTableWidget { gridline-color: #283140; alternate-background-color: #151b24; }
            QPushButton { background: #263244; border: 1px solid #3a485d; border-radius: 7px; padding: 9px 13px; font-weight: 600; }
            QPushButton:hover { background: #33445e; }
            QPushButton:disabled { color: #727d8c; background: #1a2029; }
            QStatusBar { color: #a4afc0; }
        """)

    def log_message(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {message}")

    def adb_path(self) -> str | None:
        return shutil.which("adb")

    def run_async(self, command: list[str], on_success, timeout: int = 40) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, APP_NAME, "Another ADB operation is still running. Please wait.")
            return
        self._set_busy(True)
        self.worker = Worker(command, timeout)
        self.worker.done.connect(lambda result, error: self._finish_worker(result, error, on_success))
        self.worker.start()

    def _finish_worker(self, result, error: str, callback) -> None:
        self._set_busy(False)
        if error:
            self.log_message("Error: " + error)
            self.statusBar().showMessage("Operation failed", 6000)
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
        self.packages = []
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
        names = []
        for line in output.splitlines():
            value = line.strip()
            if value.startswith("package:"):
                name = value[len("package:"):].strip()
                if name:
                    names.append(name)
        self._all_package_names = names
        adb = self.adb_path()
        if not adb or not self.device_id:
            return
        self.run_async(
            [adb, "-s", self.device_id, "shell", "pm", "list", "packages", "-3"],
            self._third_party_loaded,
            timeout=60,
        )

    def _third_party_loaded(self, output: str) -> None:
        self.third_party_names = {
            line.strip()[len("package:"):].strip()
            for line in output.splitlines()
            if line.strip().startswith("package:")
        }
        self.packages = sorted(
            [Package(name, "Third-party" if name in self.third_party_names else "System / preinstalled")
             for name in self._all_package_names],
            key=lambda p: p.name.casefold(),
        )
        self.render_packages()
        self.log_message(f"Loaded {len(self.packages)} package names from {self.device_id}.")
        self.statusBar().showMessage(f"Loaded {len(self.packages)} packages", 5000)

    def render_packages(self, *_args) -> None:
        needle = self.search.text().strip().casefold()
        mode = self.filter_combo.currentIndex()
        rows = []
        for package in self.packages:
            if needle and needle not in package.name.casefold():
                continue
            is_third_party = package.name in self.third_party_names
            if mode == 1 and not is_third_party:
                continue
            if mode == 2 and is_third_party:
                continue
            rows.append(package)
        self.table.setRowCount(len(rows))
        for index, package in enumerate(rows):
            name_item = QTableWidgetItem(package.name)
            name_item.setData(Qt.ItemDataRole.UserRole, package.name)
            self.table.setItem(index, 0, name_item)
            self.table.setItem(index, 1, QTableWidgetItem(package.kind))
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
                self.run_async(args, lambda output: (self.log_message(f"{action.title()} {package}: {output}"), run_next(index + 1)), timeout=60)
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
            self.packages = [p for p in self.packages if p.name != package]
            self.render_packages()

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
        """Check for the optional AMBridge companion without bundling its proprietary APK."""
        cmd = self._device_adb("shell", "pm", "list", "packages", "com.cybercat.ambridge")
        if not cmd:
            return
        def checked(output: str) -> None:
            installed = "package:com.cybercat.ambridge" in output.splitlines()
            if installed:
                self.log_message("AMBridge companion detected on the selected device.")
                self.statusBar().showMessage("AMBridge is installed. Use Load packages to refresh inventory.", 6000)
            elif prompt_if_missing:
                answer = QMessageBox.question(
                    self, "AMBridge is not installed",
                    "AMBridge is an optional Android companion that may provide richer app metadata to compatible tools.\n\n"
                    "This app does not bundle Cyber.Cat's proprietary APK. Would you like to select an AMBridge APK you obtained from its official source and install it with ADB?\n\n"
                    "Requires Android 6 or newer. Keep the phone awake and unlocked during setup.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer == QMessageBox.StandardButton.Yes:
                    self.install_ambridge_apk()
            else:
                self.log_message("AMBridge is not installed. Choose AMBridge helper to install an official APK.")
        self.run_async(cmd, checked, timeout=45)

    def manage_ambridge(self) -> None:
        if not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        answer = QMessageBox.question(
            self, "AMBridge companion",
            "Check whether com.cybercat.ambridge is installed on this device?\n\n"
            "If missing, you can choose an APK you obtained from the official AMBridge source. The APK is not bundled with this project.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.check_ambridge(prompt_if_missing=True)

    def install_ambridge_apk(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select official AMBridge APK", "", "Android package (*.apk)"
        )
        if not path:
            return
        if Path(path).name.lower() != "com.cybercat.ambridge.apk":
            answer = QMessageBox.question(
                self, "Confirm AMBridge APK",
                "The selected file is not named com.cybercat.ambridge.apk. Only continue if you verified it came from the official AMBridge source.\n\nInstall this APK?",
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
            "Android 6 or newer is required. This app does not verify the APK's publisher signature.",
        ):
            return
        self.run_async(cmd, lambda out: self._ambridge_install_finished(out), timeout=180)

    def _ambridge_install_finished(self, output: str) -> None:
        self.log_message("AMBridge install result: " + (output or "Command completed."))
        if "Success" in output:
            QMessageBox.information(
                self, "AMBridge installed",
                "AMBridge was installed. If the device requires it, open Android Settings → Apps → AMBridge and grant the requested storage/files access.\n\n"
                "Keep the phone awake and unlocked, then choose Load packages to refresh this app's inventory. AMBridge has no launcher UI."
            )

    def _device_adb(self, *args: str) -> list[str] | None:
        adb = self.adb_path()
        if not adb or not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return None
        return [adb, "-s", self.device_id, *args]

    def install_apks(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Select APK files", "", "Android packages (*.apk)")
        if not paths:
            return
        adb = self.adb_path()
        if not adb or not self.device_id:
            QMessageBox.information(self, APP_NAME, "Connect and select an authorized Android device first.")
            return
        if not self._confirmed("Install APK files?", f"Install {len(paths)} APK file(s) on {self.device_id}?"):
            return
        def run_next(i: int = 0) -> None:
            if i >= len(paths):
                self.log_message("APK installation queue finished.")
                return
            path = paths[i]
            self.run_async([adb, "-s", self.device_id, "install", "-r", path],
                lambda out: (self.log_message(f"{Path(path).name}: {out or 'Installed'}"), run_next(i + 1)), timeout=180)
        run_next()

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
