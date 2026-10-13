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
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QHeaderView,
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
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
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
        for btn in (self.uninstall_btn, self.disable_btn, self.enable_btn):
            btn.setEnabled(False)
            actions.addWidget(btn)
        actions.addStretch(1)
        root.addLayout(actions)

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

    def selected_package(self) -> str | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selection_changed(self) -> None:
        enabled = bool(self.device_id and self.selected_package())
        self.uninstall_btn.setEnabled(enabled)
        self.disable_btn.setEnabled(enabled)
        self.enable_btn.setEnabled(enabled)

    def _confirmed(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes

    def _package_action(self, action: str) -> None:
        package = self.selected_package()
        adb = self.adb_path()
        if not package or not adb or not self.device_id:
            return
        if action == "uninstall":
            title = "Uninstall for current user?"
            message = f"Run pm uninstall --user 0 for:\n\n{package}\n\nThis may disable phone features. The system image APK usually remains installed."
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
