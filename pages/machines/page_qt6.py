"""PyQt6 Machines page for the EYRES AI Inspection Platform.

This is the Qt6 port of the existing Machines page.  It deliberately keeps the
existing MachineDB schema and PLC connectivity function instead of introducing
a second backend implementation.

Backend contracts kept:
- MachineDB.get_all_machines()
- MachineDB.add_machine(data)
- MachineDB.update_machine(machine_id, data)
- MachineDB.delete_machine(machine_id)
- check_plc_and_get_active(machine_config)

The UI is responsive, uses non-blocking QThread PLC checks, and follows the
approved EYRES Qt6 visual language.
"""
from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.qt6.icons import icon, icon_pixmap
from ui.qt6.widgets import AnimatedCard, IconBadge


# Keep compatibility with the current EYRES project layout and with the
# src/utils layout used by some newer project copies.
try:
    from db import MachineDB
except ImportError:  # pragma: no cover - project layout fallback
    try:
        from src.db import MachineDB
    except ImportError:
        from src.database.db import MachineDB

try:
    from plc_connection import check_plc_and_get_active
except ImportError:  # pragma: no cover - project layout fallback
    try:
        from src.utils.plc_connection import check_plc_and_get_active
    except ImportError:
        from utils.plc_connection import check_plc_and_get_active


PLC_DATA = {
    "Siemens": {
        "models": ["S7-200", "S7-300", "S7-400", "S7-1200", "S7-1500", "LOGO!"],
        "protocols": ["S7 TCP", "Modbus TCP"],
    },
    "Mitsubishi": {
        "models": ["FX Series", "Q Series", "L Series", "iQ-R"],
        "protocols": ["MC Protocol", "Modbus TCP"],
    },
    "Allen-Bradley": {
        "models": ["MicroLogix", "CompactLogix", "ControlLogix"],
        "protocols": ["EtherNet/IP", "CIP"],
    },
    "Omron": {
        "models": ["CP Series", "CJ Series", "NJ/NX Series"],
        "protocols": ["FINS", "EtherNet/IP"],
    },
    "Keyence": {
        "models": ["KV-3000", "KV-7000", "KV-Nano"],
        "protocols": ["KV Protocol", "Modbus TCP"],
    },
    "Delta": {
        "models": ["DVP Series", "AH Series", "AS Series"],
        "protocols": ["Modbus RTU", "Modbus TCP"],
    },
    "Schneider": {
        "models": ["Modicon M221", "Modicon M241", "Modicon M251"],
        "protocols": ["Modbus TCP", "Modbus RTU"],
    },
}


def _friendly_plc_message(message: Any) -> str:
    """Convert low-level driver failures into operator-friendly text."""
    text = str(message or "PLC connection could not be established.")
    lowered = text.lower()
    if "no module named" in lowered and "snap7" in lowered:
        return (
            "The Siemens PLC driver is not available in this environment. "
            "Install the approved python-snap7 dependency and retry."
        )
    if "timed out" in lowered or "timeout" in lowered:
        return "The PLC did not respond in time. Check power, network cable and IP address."
    if "connection refused" in lowered:
        return "The PLC rejected the connection. Confirm its IP address and communication settings."
    return text


def _machine_id(machine: dict) -> str:
    return str(machine.get("_id") or machine.get("id") or "")


def _machine_search_blob(machine: dict) -> str:
    keys = ("name", "plc_brand", "plc_model", "plc_protocol", "ip_address")
    return " ".join(str(machine.get(k, "")) for k in keys).lower()


def _fmt_last_check(value: Any) -> str:
    if not value:
        return "Not checked yet"
    text = str(value).replace("T", " ")
    if len(text) >= 19:
        text = text[:19]
    try:
        dt = datetime.fromisoformat(text)
        return dt.strftime("%b %d, %Y · %I:%M %p")
    except Exception:
        return text


class PlcCheckThread(QtCore.QThread):
    result_ready = pyqtSignal(bool, str)

    def __init__(self, machine_config: dict, parent=None):
        super().__init__(parent)
        self.machine_config = dict(machine_config)

    def run(self):
        try:
            connected, message = check_plc_and_get_active(self.machine_config)
            self.result_ready.emit(bool(connected), str(message))
        except Exception as exc:
            self.result_ready.emit(False, f"PLC connection check failed: {exc}")


class MetricCard(AnimatedCard):
    """Small responsive KPI card using the same hover language as Dashboard."""

    def __init__(
        self,
        title: str,
        value: str,
        meta: str,
        icon_name: str,
        *,
        icon_color: str = "#2868E8",
        icon_bg: str = "#EEF4FF",
        value_color: str = "#101A2D",
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 14, 14)
        row.setSpacing(10)

        copy = QVBoxLayout()
        copy.setSpacing(1)
        label = QLabel(title, objectName="MetricLabel")
        self.value_label = QLabel(value, objectName="MetricValue")
        self.value_label.setStyleSheet(f"color:{value_color};")
        sub = QLabel(meta, objectName="MetricMeta")
        copy.addWidget(label)
        copy.addSpacing(3)
        copy.addWidget(self.value_label)
        copy.addWidget(sub)
        copy.addStretch(1)

        self.badge = IconBadge(icon_name, icon_color, icon_bg)
        row.addLayout(copy, 1)
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)

    def set_value(self, value: Any):
        self.value_label.setText(str(value))


class MachineRecordCard(AnimatedCard):
    reconnect_requested = pyqtSignal(dict, object)
    edit_requested = pyqtSignal(dict)
    delete_requested = pyqtSignal(dict)

    def __init__(self, machine: dict, parent=None):
        super().__init__(parent)
        self.machine = machine
        self.setObjectName("MachineRecordCard")
        self.setMinimumHeight(132)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(15)

        self.machine_badge = IconBadge("machines", "#2868E8", "#EEF4FF")
        self.machine_badge.setFixedSize(54, 54)
        root.addWidget(self.machine_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        info = QVBoxLayout()
        info.setSpacing(5)
        info.setContentsMargins(0, 0, 0, 0)

        name = QLabel(str(machine.get("name") or "Unnamed machine"), objectName="MachineName")
        info.addWidget(name)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.setContentsMargins(0, 0, 0, 0)
        for value in (
            machine.get("plc_brand"),
            machine.get("plc_model"),
            machine.get("plc_protocol"),
        ):
            if value:
                chip = QLabel(str(value), objectName="ProtocolChip")
                chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                chips.addWidget(chip)
        chips.addStretch(1)
        info.addLayout(chips)

        ip_text = str(machine.get("ip_address") or "—")
        info.addWidget(QLabel(f"IP: {ip_text}", objectName="MachineMeta"))
        info.addWidget(
            QLabel(
                f"Last connection check: {_fmt_last_check(machine.get('last_connection_check'))}",
                objectName="MachineMetaSmall",
            )
        )
        root.addLayout(info, 1)

        actions = QVBoxLayout()
        actions.setSpacing(10)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        active = bool(machine.get("active"))
        status = QLabel("●  PLC ONLINE" if active else "●  PLC OFFLINE")
        status.setObjectName("StatusOnline" if active else "StatusOffline")
        status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        actions.addWidget(status, 0, Qt.AlignmentFlag.AlignRight)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.reconnect_button = QPushButton("Reconnect PLC", objectName="ReconnectButton")
        self.reconnect_button.setMinimumWidth(118)
        edit = QPushButton("Edit", objectName="SecondaryButton")
        delete = QPushButton("Delete", objectName="DeleteButton")
        for button in (self.reconnect_button, edit, delete):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(34)

        self.reconnect_button.clicked.connect(
            lambda: self.reconnect_requested.emit(self.machine, self.reconnect_button)
        )
        edit.clicked.connect(lambda: self.edit_requested.emit(self.machine))
        delete.clicked.connect(lambda: self.delete_requested.emit(self.machine))
        row.addWidget(self.reconnect_button)
        row.addWidget(edit)
        row.addWidget(delete)
        actions.addLayout(row)
        actions.addStretch(1)
        root.addLayout(actions)

    def enterEvent(self, event):
        self.machine_badge.animate_hover(True)
        self._animate_shadow(28.0, 7.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.machine_badge.animate_hover(False)
        self._animate_shadow(14.0, 4.0)
        super().leaveEvent(event)


class DeleteMachineDialog(QDialog):
    def __init__(self, machine: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("DeleteMachineDialog")
        self.setWindowTitle("Delete machine")
        self.setModal(True)
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        badge = QLabel("!", objectName="DeleteWarningBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(44, 44)
        root.addWidget(badge)

        name = str(machine.get("name") or "this machine")
        root.addWidget(QLabel(f"Delete {name}?", objectName="DeleteDialogTitle"))
        body = QLabel(
            "This removes the machine configuration from the application. "
            "Projects using it may require reconfiguration.",
            objectName="DeleteDialogBody",
        )
        body.setWordWrap(True)
        root.addWidget(body)
        root.addSpacing(5)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel", objectName="DialogSecondary")
        delete = QPushButton("Delete Machine", objectName="DialogDanger")
        for button in (cancel, delete):
            button.setFixedHeight(36)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        delete.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(delete)
        root.addLayout(buttons)

        self.setStyleSheet("""
        QDialog#DeleteMachineDialog { background:#FFFFFF; }
        QDialog#DeleteMachineDialog QLabel { background:transparent; }
        QLabel#DeleteWarningBadge {
            background:#FFF0F3; color:#D63C55; border:1px solid #F7D8DE;
            border-radius:13px; font-size:20px; font-weight:800;
        }
        QLabel#DeleteDialogTitle { color:#101A2D; font-size:17px; font-weight:800; }
        QLabel#DeleteDialogBody { color:#65758E; font-size:10.5px; }
        QPushButton#DialogSecondary, QPushButton#DialogDanger {
            background:#FFFFFF; color:#40516A; border:1px solid #C9D7E9;
            border-radius:9px; padding:0 14px; font-size:10.5px; font-weight:700;
        }
        QPushButton#DialogSecondary:hover { background:#F3F6FC; }
        QPushButton#DialogDanger { color:#C93450; border-color:#F0BEC8; }
        QPushButton#DialogDanger:hover { background:#FFF1F3; }
        """)


class MachineDialogQt6(QDialog):
    """Add/Edit machine dialog keeping the existing MachineDB + PLC logic."""

    def __init__(self, machine_db: MachineDB, machine: dict | None = None, parent=None):
        super().__init__(parent)
        self.machine_db = machine_db
        self.machine = machine
        self.connected = False
        self.connection_message = ""
        self._worker: PlcCheckThread | None = None
        self._pending_payload: dict | None = None

        self.setObjectName("MachineDialog")
        self.setWindowTitle("Edit Machine" if machine else "Add Machine")
        self.setModal(True)
        self.setMinimumSize(690, 500)
        self.resize(760, 540)
        self.setSizeGripEnabled(True)

        self._build()
        self._apply_style()
        if machine:
            self._populate(machine)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QFrame(objectName="DialogHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 16, 16, 14)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        title = QLabel("Edit Machine" if self.machine else "Add Machine", objectName="DialogTitle")
        sub = QLabel("Configure the inspection cell and its PLC endpoint.", objectName="DialogSubtitle")
        copy.addWidget(title)
        copy.addWidget(sub)
        hl.addLayout(copy, 1)
        close = QPushButton("×", objectName="DialogClose")
        close.setFixedSize(32, 32)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        hl.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(head)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(20, 18, 20, 18)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(0)

        identity = QFrame(objectName="FormCard")
        il = QVBoxLayout(identity)
        il.setContentsMargins(15, 14, 15, 14)
        il.setSpacing(8)
        il.addWidget(QLabel("MACHINE IDENTITY", objectName="SectionKicker"))
        self.name_input = self._field(il, "Machine Name", "Enter machine name")
        self.ip_input = self._field(il, "IP Address *", "e.g., 192.168.1.100")
        self.slot_input = self._field(
            il,
            "Slot / Rack (if applicable)",
            "e.g., 0 or 1",
            "Required for some PLC families such as Allen-Bradley.",
        )
        il.addStretch(1)

        connection = QFrame(objectName="FormCard")
        cl = QVBoxLayout(connection)
        cl.setContentsMargins(15, 14, 15, 14)
        cl.setSpacing(8)
        cl.addWidget(QLabel("PLC CONNECTION", objectName="SectionKicker"))

        cl.addWidget(QLabel("PLC Brand *", objectName="FieldLabel"))
        self.brand_combo = QComboBox(objectName="FormCombo")
        self.brand_combo.addItem("Select PLC Brand")
        self.brand_combo.addItems(PLC_DATA.keys())
        self.brand_combo.currentTextChanged.connect(self._brand_changed)
        cl.addWidget(self.brand_combo)

        cl.addWidget(QLabel("Model Series *", objectName="FieldLabel"))
        self.model_combo = QComboBox(objectName="FormCombo")
        self.model_combo.addItem("Select Model")
        self.model_combo.setEnabled(False)
        cl.addWidget(self.model_combo)

        cl.addWidget(QLabel("Communication Protocol *", objectName="FieldLabel"))
        self.protocol_combo = QComboBox(objectName="FormCombo")
        self.protocol_combo.addItem("Select Protocol")
        self.protocol_combo.setEnabled(False)
        cl.addWidget(self.protocol_combo)
        cl.addStretch(1)

        grid.addWidget(identity, 0, 0)
        grid.addWidget(connection, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addWidget(body, 1)

        foot = QFrame(objectName="DialogFooter")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(20, 12, 20, 14)
        fl.setSpacing(8)
        self.status_label = QLabel(
            "PLC connectivity is checked before the machine record is saved.",
            objectName="DialogStatus",
        )
        self.status_label.setWordWrap(True)
        fl.addWidget(self.status_label, 1)
        cancel = QPushButton("Cancel", objectName="DialogSecondary")
        self.save_button = QPushButton(
            "Save Machine" if not self.machine else "Update Machine",
            objectName="DialogPrimary",
        )
        for button in (cancel, self.save_button):
            button.setFixedHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save_clicked)
        fl.addWidget(cancel)
        fl.addWidget(self.save_button)
        root.addWidget(foot)

    @staticmethod
    def _field(layout, label_text: str, placeholder: str, helper: str | None = None) -> QLineEdit:
        layout.addWidget(QLabel(label_text, objectName="FieldLabel"))
        edit = QLineEdit(objectName="FormInput")
        edit.setPlaceholderText(placeholder)
        layout.addWidget(edit)
        if helper:
            layout.addWidget(QLabel(helper, objectName="FieldHelper"))
        return edit

    def _apply_style(self):
        self.setStyleSheet("""
        QDialog#MachineDialog { background:#FFFFFF; }
        QDialog#MachineDialog QLabel { background:transparent; border:0; }
        QFrame#DialogHeader, QFrame#DialogFooter { background:#FFFFFF; border:0; }
        QFrame#DialogHeader { border-bottom:1px solid #DDE5EF; }
        QFrame#DialogFooter { border-top:1px solid #DDE5EF; }
        QLabel#DialogTitle { color:#101A2D; font-size:19px; font-weight:800; }
        QLabel#DialogSubtitle { color:#6A7A91; font-size:10.5px; }
        QPushButton#DialogClose {
            background:#FFFFFF; color:#5E6D82; border:1px solid #D7E1EE;
            border-radius:9px; font-size:18px;
        }
        QPushButton#DialogClose:hover { background:#F2F6FC; }
        QFrame#FormCard { background:#F7F9FC; border:1px solid #D2DCE9; border-radius:13px; }
        QLabel#SectionKicker { color:#2868E8; font-size:9px; font-weight:800; letter-spacing:0.7px; }
        QLabel#FieldLabel { color:#42536A; font-size:10px; font-weight:700; margin-top:3px; }
        QLabel#FieldHelper { color:#8794A8; font-size:8.5px; }
        QLineEdit#FormInput, QComboBox#FormCombo {
            min-height:38px; background:#FFFFFF; color:#213047;
            border:1px solid #C9D7E9; border-radius:9px; padding:0 10px; font-size:10.5px;
        }
        QLineEdit#FormInput:focus, QComboBox#FormCombo:focus { border:1px solid #2868E8; }
        QLineEdit#FormInput:disabled, QComboBox#FormCombo:disabled {
            background:#F1F4F8; color:#9AA6B7;
        }
        QComboBox#FormCombo QAbstractItemView {
            background:#FFFFFF; color:#213047; border:1px solid #BFCDE0;
            selection-background-color:#EAF1FF; selection-color:#1D59CF; outline:0;
        }
        QLabel#DialogStatus { color:#708096; font-size:9.5px; }
        QPushButton#DialogPrimary, QPushButton#DialogSecondary {
            border-radius:9px; padding:0 15px; font-size:10.5px; font-weight:750;
        }
        QPushButton#DialogPrimary { background:#2868E8; color:#FFFFFF; border:1px solid #2868E8; }
        QPushButton#DialogPrimary:hover { background:#1F57C8; border-color:#1F57C8; }
        QPushButton#DialogPrimary:disabled { background:#AFC6EF; border-color:#AFC6EF; }
        QPushButton#DialogSecondary { background:#FFFFFF; color:#40516A; border:1px solid #C9D7E9; }
        QPushButton#DialogSecondary:hover { background:#F3F6FC; }
        """)

    def _populate(self, machine: dict):
        self.name_input.setText(str(machine.get("name") or ""))
        self.ip_input.setText(str(machine.get("ip_address") or ""))
        if machine.get("slot") is not None:
            self.slot_input.setText(str(machine.get("slot")))

        brand = str(machine.get("plc_brand") or "")
        idx = self.brand_combo.findText(brand)
        if idx >= 0:
            self.brand_combo.setCurrentIndex(idx)
            self._brand_changed(brand)

        model = str(machine.get("plc_model") or "")
        idx = self.model_combo.findText(model)
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)

        protocol = str(machine.get("plc_protocol") or "")
        idx = self.protocol_combo.findText(protocol)
        if idx >= 0:
            self.protocol_combo.setCurrentIndex(idx)

    def _brand_changed(self, brand: str):
        details = PLC_DATA.get(brand)

        self.model_combo.blockSignals(True)
        self.protocol_combo.blockSignals(True)
        self.model_combo.clear()
        self.protocol_combo.clear()
        self.model_combo.addItem("Select Model")
        self.protocol_combo.addItem("Select Protocol")
        if details:
            self.model_combo.addItems(details["models"])
            self.protocol_combo.addItems(details["protocols"])
            self.model_combo.setEnabled(True)
            self.protocol_combo.setEnabled(True)
        else:
            self.model_combo.setEnabled(False)
            self.protocol_combo.setEnabled(False)
        self.model_combo.blockSignals(False)
        self.protocol_combo.blockSignals(False)

    def _validation_error(self, message: str, widget: QWidget | None = None):
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color:#C93450; font-size:9.5px;")
        if widget is not None:
            widget.setFocus()

    def _payload(self) -> dict | None:
        name = self.name_input.text().strip()
        if not name:
            self._validation_error("Machine name cannot be empty.", self.name_input)
            return None

        ip_address = self.ip_input.text().strip()
        if not ip_address:
            self._validation_error("IP Address is mandatory.", self.ip_input)
            return None
        try:
            parsed = ipaddress.ip_address(ip_address)
            if parsed.version != 4:
                raise ValueError
        except ValueError:
            self._validation_error(
                "Enter a valid IPv4 address, for example 192.168.1.100.",
                self.ip_input,
            )
            self.ip_input.selectAll()
            return None

        brand = self.brand_combo.currentText()
        if brand == "Select PLC Brand":
            self._validation_error("Select the PLC manufacturer.", self.brand_combo)
            return None

        model = self.model_combo.currentText()
        if model == "Select Model":
            self._validation_error("Select the PLC model series.", self.model_combo)
            return None

        protocol = self.protocol_combo.currentText()
        if protocol == "Select Protocol":
            self._validation_error("Select the PLC communication protocol.", self.protocol_combo)
            return None

        slot_raw = self.slot_input.text().strip()
        slot = int(slot_raw) if slot_raw.isdigit() else None
        if "allen-bradley" in brand.lower() and slot is None:
            self._validation_error("Slot is required for Allen-Bradley PLCs.", self.slot_input)
            return None

        return {
            "name": name,
            "ip_address": ip_address,
            "slot": slot,
            "plc_brand": brand,
            "plc_model": model,
            "plc_protocol": protocol,
        }

    def _save_clicked(self):
        payload = self._payload()
        if payload is None:
            return

        self._pending_payload = payload
        config = {
            "plc_brand": payload["plc_brand"],
            "plc_protocol": payload["plc_protocol"],
            "ip_address": payload["ip_address"],
            "slot": payload["slot"],
        }

        self.save_button.setEnabled(False)
        self.save_button.setText("Checking PLC…")
        self.status_label.setStyleSheet("color:#2868E8; font-size:9.5px;")
        self.status_label.setText("Checking controller connectivity…")

        self._worker = PlcCheckThread(config, self)
        self._worker.result_ready.connect(self._plc_checked)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _plc_checked(self, connected: bool, message: str):
        payload = dict(self._pending_payload or {})
        payload["active"] = bool(connected)
        payload["last_connection_check"] = datetime.now().isoformat(timespec="seconds")

        try:
            if self.machine:
                machine_id = _machine_id(self.machine)
                ok = bool(self.machine_db.update_machine(machine_id, payload))
            else:
                ok = bool(self.machine_db.add_machine(payload))
        except Exception as exc:
            ok = False
            message = f"Machine record could not be saved: {exc}"

        if not ok:
            self.save_button.setEnabled(True)
            self.save_button.setText("Update Machine" if self.machine else "Save Machine")
            self._validation_error(message)
            return

        self.connected = bool(connected)
        self.connection_message = _friendly_plc_message(message)
        self.accept()


class MachinesPageQt6(QWidget):
    """Approved Qt6 Machines page."""

    toast_requested = pyqtSignal(str, str)

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.machine_db = MachineDB()
        self._machines: list[dict] = []
        self._reconnect_threads: set[PlcCheckThread] = set()
        self._summary_columns = None

        self.setObjectName("MachinesPageQt6")
        self._build()
        self._apply_style()
        self.refresh_data(animate=False)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(15)

        self.summary_host = QWidget()
        self.summary_grid = QGridLayout(self.summary_host)
        self.summary_grid.setContentsMargins(0, 0, 0, 0)
        self.summary_grid.setHorizontalSpacing(14)
        self.summary_grid.setVerticalSpacing(12)

        self.total_card = MetricCard(
            "TOTAL MACHINES", "0", "Configured inspection cells",
            "machines",
        )
        self.online_card = MetricCard(
            "PLC ONLINE", "0", "Reachable controllers",
            "live", icon_color="#07965D", icon_bg="#EAF9F2", value_color="#07965D",
        )
        self.offline_card = MetricCard(
            "PLC OFFLINE", "0", "Requires connection check",
            "diagnostics", icon_color="#D63C55", icon_bg="#FFF1F3", value_color="#D63C55",
        )
        self.brands_card = MetricCard(
            "PLC BRANDS", "0", "Configured manufacturers",
            "plc", icon_color="#6B40E5", icon_bg="#F2EDFF",
        )
        self.metric_cards = [
            self.total_card, self.online_card, self.offline_card, self.brands_card
        ]
        root.addWidget(self.summary_host)

        self.panel = AnimatedCard()
        self.panel.setObjectName("MachinePanel")
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setSpacing(0)

        head = QFrame(objectName="PanelHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(18, 15, 16, 14)
        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Inspection machines", objectName="PanelTitle"))
        copy.addWidget(
            QLabel(
                "Manage configured PLC endpoints and verify controller connectivity.",
                objectName="PanelSubtitle",
            )
        )
        hl.addLayout(copy, 1)
        add = QPushButton("+  Add Machine", objectName="PrimaryButton")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setFixedHeight(38)
        add.clicked.connect(self.open_add_dialog)
        hl.addWidget(add)
        panel.addWidget(head)

        toolbar = QFrame(objectName="FilterBar")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(15, 12, 15, 12)
        tl.setSpacing(9)

        self.search_input = QLineEdit(objectName="SearchInput")
        self.search_input.setPlaceholderText(
            "Search by machine, PLC brand, model or IP address"
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._render)
        tl.addWidget(self.search_input, 1)

        self.brand_filter = QComboBox(objectName="FilterCombo")
        self.brand_filter.addItem("All brands")
        self.brand_filter.addItems(PLC_DATA.keys())
        self.brand_filter.currentTextChanged.connect(self._render)
        self.brand_filter.setMinimumWidth(135)
        tl.addWidget(self.brand_filter)

        self.status_filter = QComboBox(objectName="FilterCombo")
        self.status_filter.addItems(["All status", "Online", "Offline"])
        self.status_filter.currentTextChanged.connect(self._render)
        self.status_filter.setMinimumWidth(120)
        tl.addWidget(self.status_filter)

        clear = QPushButton("Clear filters", objectName="SecondaryButton")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.setFixedHeight(36)
        clear.clicked.connect(self._clear_filters)
        tl.addWidget(clear)
        panel.addWidget(toolbar)

        self.scroll = QScrollArea(objectName="MachineScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.list_host = QWidget(objectName="MachineListHost")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(15, 14, 15, 18)
        self.list_layout.setSpacing(11)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_host)
        panel.addWidget(self.scroll, 1)

        foot = QFrame(objectName="PanelFooter")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(16, 9, 16, 9)
        note = QLabel("●  Machine configuration stored in the application database.", objectName="FooterNote")
        fl.addWidget(note)
        fl.addStretch(1)
        fl.addWidget(QLabel("PLC checks are performed only when requested.", objectName="FooterMeta"))
        panel.addWidget(foot)

        root.addWidget(self.panel, 1)
        self._reflow_summary(force=True)

    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#MachinesPageQt6 { background:transparent; color:#101A2D; }
        QWidget#MachinesPageQt6 QLabel { background:transparent; border:0; }

        QFrame#MetricCard {
            background:#FFFFFF; border:1px solid #C9D5E5; border-radius:16px;
        }
        QLabel#MetricLabel {
            color:#6A7A91; font-size:9px; font-weight:800; letter-spacing:0.7px;
        }
        QLabel#MetricValue { color:#101A2D; font-size:27px; font-weight:800; }
        QLabel#MetricMeta { color:#6F8097; font-size:9px; }

        QFrame#MachinePanel {
            background:#FFFFFF; border:1px solid #C9D5E5; border-radius:18px;
        }
        QFrame#PanelHeader { background:#FFFFFF; border:0; border-bottom:1px solid #DDE5EF; }
        QLabel#PanelTitle { color:#101A2D; font-size:15px; font-weight:800; }
        QLabel#PanelSubtitle { color:#68788F; font-size:9.5px; }

        QPushButton#PrimaryButton {
            background:#2868E8; color:#FFFFFF; border:1px solid #2868E8;
            border-radius:10px; padding:0 16px; font-size:10.5px; font-weight:800;
        }
        QPushButton#PrimaryButton:hover { background:#1F57C8; border-color:#1F57C8; }
        QPushButton#PrimaryButton:pressed { background:#184AAB; }

        QFrame#FilterBar { background:#F8FAFD; border:0; border-bottom:1px solid #DDE5EF; }
        QLineEdit#SearchInput, QComboBox#FilterCombo {
            min-height:36px; background:#FFFFFF; color:#213047;
            border:1px solid #BFCDE0; border-radius:10px;
            padding:0 11px; font-size:10.5px;
        }
        QLineEdit#SearchInput:focus, QComboBox#FilterCombo:focus { border:1px solid #2868E8; }
        QComboBox#FilterCombo QAbstractItemView {
            background:#FFFFFF; color:#213047; border:1px solid #BFCDE0;
            selection-background-color:#EAF1FF; selection-color:#1D59CF; outline:0;
        }

        QScrollArea#MachineScroll, QScrollArea#MachineScroll > QWidget > QWidget,
        QWidget#MachineListHost { background:#FFFFFF; border:0; }
        QScrollBar:vertical { background:transparent; width:7px; margin:2px; }
        QScrollBar::handle:vertical { background:#D3DDEA; border-radius:3px; min-height:28px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }

        QFrame#MachineRecordCard {
            background:#FFFFFF; border:1px solid #CDD9E7; border-radius:15px;
        }
        QLabel#MachineName { color:#101A2D; font-size:17px; font-weight:800; }
        QLabel#MachineMeta { color:#6A7A91; font-size:10px; }
        QLabel#MachineMetaSmall { color:#6E7F96; font-size:9px; }
        QLabel#ProtocolChip {
            background:#F1F5FA; color:#4F6078; border:0; border-radius:8px;
            padding:4px 8px; font-size:9px; font-weight:700;
        }
        QLabel#StatusOnline, QLabel#StatusOffline {
            border-radius:10px; padding:5px 10px; font-size:9px; font-weight:800;
        }
        QLabel#StatusOnline {
            background:#E8F8F1; color:#078A57; border:1px solid #D0EFDF;
        }
        QLabel#StatusOffline {
            background:#FFF0F3; color:#C93651; border:1px solid #F8D7DE;
        }

        QPushButton#ReconnectButton, QPushButton#SecondaryButton, QPushButton#DeleteButton {
            background:#FFFFFF; border:1px solid #C7D6EA; border-radius:9px;
            padding:0 13px; color:#2868E8; font-size:10px; font-weight:750;
        }
        QPushButton#ReconnectButton {
            background:#2868E8; color:#FFFFFF; border-color:#2868E8;
        }
        QPushButton#ReconnectButton:hover { background:#1F57C8; border-color:#1F57C8; }
        QPushButton#ReconnectButton:disabled {
            background:#AFC6EF; color:#FFFFFF; border-color:#AFC6EF;
        }
        QPushButton#SecondaryButton:hover { background:#F1F6FF; }
        QPushButton#DeleteButton { color:#C93450; border-color:#F0BEC8; }
        QPushButton#DeleteButton:hover { background:#FFF2F4; }

        QFrame#PanelFooter { background:#F7F9FC; border:0; border-top:1px solid #DDE5EF; }
        QLabel#FooterNote { color:#07965D; font-size:9px; }
        QLabel#FooterMeta { color:#77869B; font-size:9px; }

        QFrame#EmptyState {
            background:#F7F9FC; border:1px dashed #CAD8EA; border-radius:14px;
        }
        QLabel#EmptyTitle { color:#101A2D; font-size:15px; font-weight:800; }
        QLabel#EmptyText { color:#718096; font-size:10px; }
        """)

    # ------------------------------------------------------------------
    # Data / filters
    # ------------------------------------------------------------------
    def refresh_data(self, animate: bool = True):
        try:
            self._machines = list(self.machine_db.get_all_machines())
        except Exception as exc:
            self._machines = []
            self.toast_requested.emit(
                "Machine data unavailable",
                f"Machine records could not be loaded: {exc}",
            )
        self._update_metrics()
        self._render()
        if animate:
            for index, card in enumerate(self.metric_cards):
                QtCore.QTimer.singleShot(index * 45, card.animate_entrance)
            self.panel.animate_entrance()

    def _update_metrics(self):
        total = len(self._machines)
        online = sum(1 for m in self._machines if bool(m.get("active")))
        offline = total - online
        brands = {str(m.get("plc_brand") or "").strip() for m in self._machines}
        brands.discard("")

        self.total_card.set_value(total)
        self.online_card.set_value(online)
        self.offline_card.set_value(offline)
        self.brands_card.set_value(len(brands))

    def _matches(self, machine: dict) -> bool:
        query = self.search_input.text().strip().lower()
        if query and query not in _machine_search_blob(machine):
            return False

        brand = self.brand_filter.currentText()
        if brand != "All brands" and str(machine.get("plc_brand") or "") != brand:
            return False

        status = self.status_filter.currentText()
        active = bool(machine.get("active"))
        if status == "Online" and not active:
            return False
        if status == "Offline" and active:
            return False
        return True

    def _render(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        shown = [m for m in self._machines if self._matches(m)]
        if not shown:
            self._add_empty_state(bool(self._machines))
            return

        for index, machine in enumerate(shown):
            card = MachineRecordCard(machine)
            card.reconnect_requested.connect(self.reconnect_plc)
            card.edit_requested.connect(self.open_edit_dialog)
            card.delete_requested.connect(self.delete_machine)
            self.list_layout.addWidget(card)
            QtCore.QTimer.singleShot(35 * index, card.animate_entrance)
        self.list_layout.addStretch(1)

    def _add_empty_state(self, has_records: bool):
        card = QFrame(objectName="EmptyState")
        card.setMinimumHeight(210)
        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(26, 28, 26, 28)
        layout.setSpacing(8)

        badge = QLabel()
        badge.setPixmap(icon_pixmap("machines", "#2868E8", 34, prefer_legacy=True))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(58, 58)
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignCenter)

        title = QLabel(
            "No matching machines" if has_records else "Configure your first inspection machine",
            objectName="EmptyTitle",
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body = QLabel(
            "Clear the filters or search for another machine."
            if has_records
            else "Add the PLC connection details used by this inspection cell.",
            objectName="EmptyText",
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(body)

        if not has_records:
            button = QPushButton("+  Add Machine", objectName="PrimaryButton")
            button.setFixedHeight(38)
            button.clicked.connect(self.open_add_dialog)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)

        self.list_layout.addWidget(card)

    def _clear_filters(self):
        self.search_input.clear()
        self.brand_filter.setCurrentIndex(0)
        self.status_filter.setCurrentIndex(0)
        self._render()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def open_add_dialog(self):
        dialog = MachineDialogQt6(self.machine_db, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_data(animate=True)
            if dialog.connected:
                self.toast_requested.emit(
                    "Machine added",
                    "Machine saved and the PLC connection check passed.",
                )
            else:
                self.toast_requested.emit(
                    "Machine added",
                    "Machine saved. PLC is currently unavailable and is marked offline.",
                )

    def open_edit_dialog(self, machine: dict):
        dialog = MachineDialogQt6(self.machine_db, machine=machine, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_data(animate=True)
            self.toast_requested.emit(
                "Machine updated",
                "Machine configuration was saved successfully.",
            )

    def delete_machine(self, machine: dict):
        dialog = DeleteMachineDialog(machine, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            ok = bool(self.machine_db.delete_machine(_machine_id(machine)))
        except Exception as exc:
            ok = False
            error = str(exc)
        else:
            error = ""

        if ok:
            self.refresh_data(animate=True)
            self.toast_requested.emit("Machine deleted", "Machine configuration was removed.")
        else:
            self.toast_requested.emit(
                "Delete failed",
                error or "The machine configuration could not be removed.",
            )

    # ------------------------------------------------------------------
    # PLC reconnect
    # ------------------------------------------------------------------
    def reconnect_plc(self, machine: dict, button: QPushButton | None = None):
        if button is not None:
            button.setEnabled(False)
            button.setText("Connecting…")

        config = {
            "plc_brand": machine.get("plc_brand"),
            "plc_protocol": machine.get("plc_protocol"),
            "ip_address": machine.get("ip_address"),
            "slot": machine.get("slot"),
        }
        worker = PlcCheckThread(config, self)
        self._reconnect_threads.add(worker)

        def finished(connected: bool, message: str):
            try:
                self.machine_db.update_machine(
                    _machine_id(machine),
                    {
                        "active": bool(connected),
                        "last_connection_check": datetime.now().isoformat(timespec="seconds"),
                    },
                )
            except Exception as exc:
                connected = False
                message = f"PLC status could not be stored: {exc}"

            if button is not None:
                button.setEnabled(True)
                button.setText("Reconnect PLC")

            self.refresh_data(animate=True)
            self.toast_requested.emit(
                "PLC connected" if connected else "PLC unavailable",
                _friendly_plc_message(message),
            )

        def cleanup():
            self._reconnect_threads.discard(worker)

        worker.result_ready.connect(finished)
        worker.finished.connect(cleanup)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    # ------------------------------------------------------------------
    # Responsive reflow
    # ------------------------------------------------------------------
    def _reflow_summary(self, force: bool = False):
        width = max(1, self.width())
        columns = 4 if width >= 1180 else 2 if width >= 650 else 1
        if not force and columns == self._summary_columns:
            return
        self._summary_columns = columns

        while self.summary_grid.count():
            item = self.summary_grid.takeAt(0)
            # Widgets are intentionally kept alive and reinserted.
            _ = item

        for index, card in enumerate(self.metric_cards):
            row = index // columns
            col = index % columns
            self.summary_grid.addWidget(card, row, col)

        for col in range(columns):
            self.summary_grid.setColumnStretch(col, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_summary()
        # On compact widths the filter row stays usable instead of crushing text.
        if self.width() < 900:
            self.brand_filter.setVisible(False)
        else:
            self.brand_filter.setVisible(True)
