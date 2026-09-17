# src/views/pages/machine_page.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFrame, QScrollArea, QMessageBox, QGridLayout,
    QDialog, QComboBox, QSizePolicy, QApplication
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPixmap
from bson.objectid import ObjectId
from db import ProjectDB, MachineDB
from plc_connection import check_plc_and_get_active
import threading
import ipaddress
from datetime import datetime
from pathlib import Path
import sys
from functools import partial
from ui.theme import apply_light_surface


def _friendly_plc_message(message):
    """Keep driver details useful without exposing a raw Python exception to operators."""
    text = str(message or "PLC connection could not be established.")
    lowered = text.lower()
    if "no module named" in lowered and "snap7" in lowered:
        return (
            "The Siemens PLC driver is not available in this environment.\n\n"
            "Install the approved python-snap7 dependency, then retry the connection."
        )
    if "timed out" in lowered or "timeout" in lowered:
        return "The PLC did not respond in time. Check its power, network cable and IP address."
    if "connection refused" in lowered:
        return "The PLC rejected the connection. Confirm its IP address and communication settings."
    return text


def _machine_artwork():
    """Return the first frame of the Dashboard machine artwork when available."""
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS") \
        else Path(__file__).resolve().parents[2]
    for name in ("dashboard_machine.gif", "sidebar_machines.png"):
        candidate = root / "Media" / name
        if candidate.is_file():
            pixmap = QPixmap(str(candidate))
            if not pixmap.isNull():
                return pixmap
    return QPixmap()

class MachinePage(QWidget):
    reconnectFinished = pyqtSignal(bool, str)
    def __init__(self, user=None):
        super().__init__()
        self.user = user
        self.machine_db = MachineDB()
        apply_light_surface(self)
        self.setObjectName("MachinesPage")
        self.setup_ui()
        self.setStyleSheet(self.page_stylesheet())
        self.reconnectFinished.connect(self._on_reconnect_result)

    @staticmethod
    def page_stylesheet():
        return """
            QWidget#MachinesPage { background:#F5F7FB; color:#172033; }
            QWidget#MachinesPage QLabel { background:transparent; border:0; }
            QFrame#PageHeader, QFrame#Toolbar, QFrame#MachineCard, QFrame#EmptyState {
                background:#FFFFFF; border:1px solid #DCE5F2; border-radius:14px;
            }
            QLabel#PageTitle { color:#14213D; font-size:22px; font-weight:700; }
            QLabel#PageSubtitle { color:#64748B; font-size:11px; }
            QLabel#CountBadge { background:#EEF4FF; color:#2868E8; border-radius:10px;
                padding:3px 9px; font-size:10px; font-weight:700; }
            QPushButton#PrimaryButton { background:#2868E8; color:#FFFFFF; border:0;
                border-radius:9px; min-height:38px; padding:0 18px; font-weight:700; }
            QPushButton#PrimaryButton:hover { background:#1F57C8; }
            QLineEdit#SearchInput { background:#FFFFFF; border:1px solid #CBD7E7;
                border-radius:9px; min-height:36px; padding:0 12px; color:#172033; }
            QLineEdit#SearchInput:focus { border:1px solid #2868E8; }
            QLabel#MachineIcon { background:#EEF4FF; color:#2868E8; border-radius:20px;
                font-size:11px; font-weight:800; }
            QLabel#MachineName { color:#14213D; font-size:16px; font-weight:700; }
            QLabel#MachineMeta { color:#64748B; font-size:11px; }
            QLabel#ProtocolChip { background:#F2F6FC; color:#475569; border-radius:8px;
                padding:3px 8px; font-size:10px; font-weight:600; }
            QLabel#StatusActive { background:#E9F8F1; color:#13845A; border-radius:9px;
                padding:4px 10px; font-size:9px; font-weight:700; }
            QLabel#StatusDisabled { background:#FFF1F3; color:#C93450; border-radius:9px;
                padding:4px 10px; font-size:9px; font-weight:700; }
            QPushButton#ReconnectButton, QPushButton#SecondaryButton, QPushButton#DeleteButton {
                background:#FFFFFF; border:1px solid #B8C9E3; border-radius:8px;
                min-height:32px; padding:0 13px; color:#2868E8; font-size:10px; font-weight:700; }
            QPushButton#ReconnectButton { background:#2868E8; border-color:#2868E8; color:#FFFFFF; }
            QPushButton#ReconnectButton:hover { background:#1F57C8; }
            QPushButton#SecondaryButton:hover { background:#EEF4FF; border-color:#2868E8; }
            QPushButton#DeleteButton { color:#C93450; border-color:#F1B8C3; }
            QPushButton#DeleteButton:hover { background:#FFF1F3; border-color:#C93450; }
            QLabel#EmptyIcon { background:#EEF4FF; color:#2868E8; border-radius:32px;
                font-size:14px; font-weight:800; }
            QLabel#EmptyTitle { color:#14213D; font-size:16px; font-weight:700; }
            QLabel#EmptyText { color:#718096; font-size:10px; }
            QScrollArea { border:0; background:transparent; }
            QScrollArea > QWidget > QWidget { background:transparent; }
        """


    # ------------------------------------------------------------
    # MAIN PAGE SETUP
    # ------------------------------------------------------------
    def setup_ui(self):

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(26, 20, 26, 24)
        main_layout.setSpacing(14)

        # ---------- HEADER ROW: title + subtitle + button ----------
        header = QFrame()
        header.setObjectName("PageHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(18, 12, 14, 12)
        header_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(2)

        title = QLabel("Machines")
        title.setObjectName("PageTitle")

        subtitle = QLabel("Configure inspection cells, PLC connectivity and line endpoints.")
        subtitle.setObjectName("PageSubtitle")

        title_line = QHBoxLayout()
        title_line.setSpacing(8)
        title_line.addWidget(title)
        self.machine_count_label = QLabel("0 MACHINES")
        self.machine_count_label.setObjectName("CountBadge")
        title_line.addWidget(self.machine_count_label)
        title_line.addStretch(1)
        title_col.addLayout(title_line)
        title_col.addWidget(subtitle)
        header_row.addLayout(title_col)
        header_row.addStretch(1)

        # rounded / modern add button
        add_btn = QPushButton("+ Add Machine")
        add_btn.setObjectName("PrimaryButton")
        add_btn.setFixedHeight(36)
        add_btn.setMinimumWidth(150)
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self.open_add_form)
        header_row.addWidget(add_btn, 0, Qt.AlignRight | Qt.AlignVCenter)

        main_layout.addWidget(header)

        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(10)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("Search by machine, PLC brand, model or IP address")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._render_machines)
        toolbar_layout.addWidget(self.search_input, 1)
        main_layout.addWidget(toolbar)

        # ---------- SCROLL AREA (MACHINE LIST) ----------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 24)
        self.container_layout.setSpacing(12)
        # center cards horizontally, stack from top
        self.container_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

        self.container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        scroll.setWidget(self.container)
        main_layout.addWidget(scroll)

        self.refresh_list()

    def _on_reconnect_result(self, connected: bool, msg: str):
        """Runs on MAIN thread only."""
        if connected:
            QMessageBox.information(self, "PLC connected", _friendly_plc_message(msg))
        else:
            QMessageBox.warning(self, "PLC unavailable", _friendly_plc_message(msg))

        self.refresh_list()

    # ------------------------------------------------------------
    # RENDER MACHINE LIST
    # ------------------------------------------------------------
    def refresh_list(self):
        # -------- clear the layout completely (widgets + spacers) --------
        layout = self.container_layout
        while layout.count():
            item = layout.takeAt(0)

            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
                continue

            # if it's a nested layout, clear it too
            sub_layout = item.layout()
            if sub_layout is not None:
                while sub_layout.count():
                    sub_item = sub_layout.takeAt(0)
                    sub_w = sub_item.widget()
                    if sub_w is not None:
                        sub_w.setParent(None)
                        sub_w.deleteLater()
            # QSpacerItem is handled just by letting 'item' go out of scope

        # -------- rebuild the cards --------
        try:
            self._machines = list(self.machine_db.get_all_machines())
        except Exception as exc:
            self._machines = []
            self.show_error(f"Machine records could not be loaded.\n\n{exc}")
        self.machine_count_label.setText(
            f"{len(self._machines)} MACHINE{'S' if len(self._machines) != 1 else ''}"
        )
        self._render_machines()

    def _render_machines(self):
        layout = self.container_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        query = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        machines = [m for m in getattr(self, "_machines", []) if not query or query in " ".join(
            str(m.get(key, "")) for key in ("name", "plc_brand", "plc_model", "plc_protocol", "ip_address")
        ).lower()]
        if not machines:
            self._add_empty_state(no_match=bool(query))
            return
        for m in machines:
            layout.addWidget(self.machine_card(m))

    def _add_empty_state(self, no_match=False):
        empty = QFrame()
        empty.setObjectName("EmptyState")
        empty.setMinimumHeight(250)
        box = QVBoxLayout(empty)
        box.setContentsMargins(24, 30, 24, 30)
        box.setSpacing(8)
        box.setAlignment(Qt.AlignCenter)
        icon = QLabel("MC")
        icon.setObjectName("EmptyIcon")
        icon.setFixedSize(64, 64)
        icon.setAlignment(Qt.AlignCenter)
        title = QLabel("No matching machines" if no_match else "Configure your first inspection machine")
        title.setObjectName("EmptyTitle")
        text = QLabel(
            "Try another machine name, PLC model or IP address."
            if no_match else "Add the PLC connection details used by this inspection cell."
        )
        text.setObjectName("EmptyText")
        text.setAlignment(Qt.AlignCenter)
        box.addWidget(icon, 0, Qt.AlignCenter)
        box.addWidget(title, 0, Qt.AlignCenter)
        box.addWidget(text, 0, Qt.AlignCenter)
        if not no_match:
            button = QPushButton("Add Machine")
            button.setObjectName("PrimaryButton")
            button.clicked.connect(self.open_add_form)
            box.addWidget(button, 0, Qt.AlignCenter)
        self.container_layout.addWidget(empty)

    # ------------------------------------------------------------
    # ADD BUTTON STYLE (rounded / modern)
    # ------------------------------------------------------------
    def add_button_style(self):
        return """
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                              stop:0 #2563eb, stop:1 #38bdf8);
            color: #ffffff;
            border: none;
            border-radius: 18px;
            padding: 0 18px;
            font-size: 13px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        QPushButton:hover {
            background-color: #1d4ed8;
        }
        QPushButton:pressed {
            background-color: #1e40af;
        }
        """
    
    def card_reconnect_style(self):
        return """
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                              stop:0 #2563eb, stop:1 #38bdf8);
            color: #ffffff;
            border: none;
            border-radius: 16px;
            padding: 0 12px;   /* slightly tighter */
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }
        QPushButton:hover { background-color: #1d4ed8; }
        QPushButton:pressed { background-color: #1e40af; }
        """


    # keep old name if you use it anywhere else
    def button_style(self):
        return self.add_button_style()

    # ------------------------------------------------------------
    # MACHINE CARD WIDGET
    # ------------------------------------------------------------
    def machine_card(self, m):

        card = QFrame()
        card.setObjectName("MachineCard")
        card.setFixedHeight(116)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Main layout: Left (info) | Right (status + buttons)
        main_layout = QHBoxLayout(card)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(18)

        icon = QLabel("MC")
        icon.setObjectName("MachineIcon")
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignCenter)
        artwork = _machine_artwork()
        if not artwork.isNull():
            icon.setText("")
            icon.setPixmap(artwork.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        main_layout.addWidget(icon, 0, Qt.AlignVCenter)

        # LEFT SIDE: Machine Information
        left_layout = QVBoxLayout()
        left_layout.setSpacing(6)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setAlignment(Qt.AlignTop)

        # Machine Name
        name_label = QLabel(f"{m['name']}")
        name_label.setObjectName("MachineName")
        left_layout.addWidget(name_label)


        # PLC Information Section
        plc_container = QWidget()
        plc_layout = QVBoxLayout(plc_container)
        plc_layout.setContentsMargins(0, 0, 0, 0)
        plc_layout.setSpacing(2)

        # PLC Brand/Model/Protocol
        plc_info_parts = []
        if m.get("plc_brand"):
            plc_info_parts.append(m.get("plc_brand", ""))
        if m.get("plc_model"):
            plc_info_parts.append(m.get("plc_model", ""))
        if m.get("plc_protocol"):
            plc_info_parts.append(m.get("plc_protocol", ""))

        if plc_info_parts:
            plc_label = QLabel(" · ".join(plc_info_parts))
            plc_label.setObjectName("ProtocolChip")
            plc_layout.addWidget(plc_label)

        # IP Address
        if m.get("ip_address"):
            ip_label = QLabel(f"IP: {m.get('ip_address', '')}")
            ip_label.setObjectName("MachineMeta")
            plc_layout.addWidget(ip_label)

        if m.get("last_connection_check"):
            checked = str(m.get("last_connection_check", "")).replace("T", " ")[:19]
            checked_label = QLabel(f"Last connection check: {checked}")
            checked_label.setObjectName("MachineMeta")
            plc_layout.addWidget(checked_label)

        if plc_info_parts or m.get("ip_address"):
            left_layout.addWidget(plc_container)

        left_layout.addStretch()
        main_layout.addLayout(left_layout, 3)

        # RIGHT SIDE: Status and Actions
        right_layout = QVBoxLayout()
        right_layout.setSpacing(10)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setAlignment(Qt.AlignTop | Qt.AlignRight)

        # -------- modern status chip --------
        is_active = bool(m.get("active"))
        status_text = "PLC Online" if is_active else "PLC Offline"
        status_label = QLabel(("●  " if is_active else "●  ") + status_text.upper())
        status_label.setObjectName("StatusActive" if is_active else "StatusDisabled")
        right_layout.addWidget(status_label, 0, Qt.AlignRight | Qt.AlignTop)

        # -------- Action Buttons --------
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        btn_reconnect = QPushButton("Reconnect PLC")
        btn_edit = QPushButton("Edit")
        btn_delete = QPushButton("Delete")
        btn_reconnect.setObjectName("ReconnectButton")
        btn_edit.setObjectName("SecondaryButton")
        btn_delete.setObjectName("DeleteButton")

        # make them pill buttons like "+ Add Machine"
        for b in (btn_reconnect, btn_edit, btn_delete):
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)

        # ✅ make reconnect a bit wider than others
        btn_reconnect.setMinimumWidth(120)
        btn_edit.setMinimumWidth(72)
        btn_delete.setMinimumWidth(76)
        btn_reconnect.clicked.connect(
            lambda _checked=False, machine=m, button=btn_reconnect:
            self.reconnect_plc(machine, button)
        )
        btn_edit.clicked.connect(lambda _checked=False, machine=m: self.open_edit_form(machine))
        btn_delete.clicked.connect(lambda _checked=False, machine=m: self.delete_machine(machine))
        btn_layout.addWidget(btn_reconnect)
        btn_layout.addWidget(btn_edit)
        btn_layout.addWidget(btn_delete)
        right_layout.addLayout(btn_layout)
        right_layout.addStretch()

        main_layout.addLayout(right_layout, 1)

        return card

    def card_button(self):
        # gradient pill, matching Add Machine style (smaller)
        return """
        QPushButton {
            background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                              stop:0 #2563eb, stop:1 #38bdf8);
            color: #ffffff;
            border: none;
            border-radius: 16px;
            padding: 0 16px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }
        QPushButton:hover {
            background-color: #1d4ed8;
        }
        QPushButton:pressed {
            background-color: #1e40af;
        }
        """

    def card_delete_button(self):
        # red pill version for delete
        return """
        QPushButton {
            background-color: #ef4444;
            color: #ffffff;
            border: none;
            border-radius: 16px;
            padding: 0 16px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.3px;
        }
        QPushButton:hover {
            background-color: #f97373;
        }
        QPushButton:pressed {
            background-color: #b91c1c;
        }
        """

    # ------------------------------------------------------------
    # ADD FORM
    # ------------------------------------------------------------
    def open_add_form(self):
        """Open Add Machine dialog with PLC configuration."""
        dialog = AddMachineDialog(parent=self)
        if dialog.exec_() == QDialog.Accepted:
            self.refresh_list()

    # ------------------------------------------------------------
    # EDIT FORM
    # ------------------------------------------------------------
    def open_edit_form(self, machine):
        """Open Edit Machine dialog with PLC configuration."""
        dialog = AddMachineDialog(parent=self, machine=machine)
        if dialog.exec_() == QDialog.Accepted:
            self.refresh_list()

    # ------------------------------------------------------------
    # DELETE MACHINE
    # ------------------------------------------------------------
    def delete_machine(self, machine):

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Delete machine")
        box.setText(f"Delete {machine['name']}?")
        box.setInformativeText(
            "This removes the machine configuration from the application. "
            "Projects using it may require reconfiguration."
        )
        delete_button = box.addButton("Delete", QMessageBox.DestructiveRole)
        cancel_button = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(cancel_button)
        box.exec_()
        if box.clickedButton() is not delete_button:
            return

        machine_id = str(machine["_id"])
        success = self.machine_db.delete_machine(machine_id)
        if success:
            self.show_success("Machine deleted")
        else:
            self.show_error("Failed to delete machine")
        self.refresh_list()
    
    def reconnect_plc(self, machine: dict, button=None):

        if button is not None:
            button.setEnabled(False)
            button.setText("Connecting…")

        def _worker():
            try:
                plc_brand = machine.get("plc_brand")
                plc_protocol = machine.get("plc_protocol")
                ip = machine.get("ip_address")
                slot = machine.get("slot")

                temp_machine = {
                    "plc_brand": plc_brand,
                    "plc_protocol": plc_protocol,
                    "ip_address": ip,
                    "slot": slot,
                }

                connected, msg = check_plc_and_get_active(temp_machine)

                machine_id = str(machine["_id"])
                self.machine_db.update_machine(machine_id, {
                    "active": bool(connected),
                    "last_connection_check": datetime.now().isoformat(timespec="seconds"),
                })

                # ✅ popup + refresh via signal
                self.reconnectFinished.emit(bool(connected), str(msg))

            except Exception as e:
                self.reconnectFinished.emit(False, f"Reconnect failed: {e}")

        threading.Thread(target=_worker, daemon=True).start()




    # ------------------------------------------------------------
    def input_style(self):
        return """
            QLineEdit {
                background-color: #1a1a1a;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 10px;
                color: white;
            }
            QLineEdit:focus {
                border: 1px solid #2E86FF;
            }
        """

    def show_error(self, message):
        """Simple error message display"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("Error")
        msg.setText(message)
        msg.exec_()

    def show_success(self, message):
        """Simple success message display"""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Information)
        msg.setWindowTitle("Success")
        msg.setText(message)
        msg.exec_()


# ===================================================================
# Add Machine Dialog with PLC Configuration
# ===================================================================

PLC_DATA = {
    "Siemens": {
        "models": ["S7-200", "S7-300", "S7-400", "S7-1200", "S7-1500", "LOGO!"],
        "protocols": ["S7 TCP", "Modbus TCP"]
    },
    "Mitsubishi": {
        "models": ["FX Series", "Q Series", "L Series", "iQ-R"],
        "protocols": ["MC Protocol", "Modbus TCP"]
    },
    "Allen-Bradley": {
        "models": ["MicroLogix", "CompactLogix", "ControlLogix"],
        "protocols": ["EtherNet/IP", "CIP"]
    },
    "Omron": {
        "models": ["CP Series", "CJ Series", "NJ/NX Series"],
        "protocols": ["FINS", "EtherNet/IP"]
    },
    "Keyence": {
        "models": ["KV-3000", "KV-7000", "KV-Nano"],
        "protocols": ["KV Protocol", "Modbus TCP"]
    },
    "Delta": {
        "models": ["DVP Series", "AH Series", "AS Series"],
        "protocols": ["Modbus RTU", "Modbus TCP"]
    },
    "Schneider": {
        "models": ["Modicon M221", "Modicon M241", "Modicon M251"],
        "protocols": ["Modbus TCP", "Modbus RTU"]
    }
}


class AddMachineDialog(QDialog):
    """
    Dialog for adding a new machine with PLC configuration.
    """

    def __init__(self, parent=None, machine=None):
        super().__init__(parent)
        apply_light_surface(self)
        self.machine = machine
        self.machine_db = MachineDB()
        self.result = None

        self.setWindowTitle("Edit Machine" if machine else "Add Machine")

        self.setObjectName("MachineDialog")
        self.setFixedWidth(500)
        self.setStyleSheet("""
            QDialog#MachineDialog { background:#F7F9FC; }
            QLabel { color:#334155; font-size:11px; }
            QLabel#DialogTitle { color:#14213D; font-size:19px; font-weight:700; }
            QLabel#DialogSubtitle { color:#718096; font-size:10px; }
            QLabel#SectionTitle { color:#2868E8; font-size:9px; font-weight:700; }
            QLineEdit, QComboBox {
                background:#FFFFFF; border:1px solid #C9D5E5; border-radius:8px;
                padding:0 10px; color:#172033; min-height:36px; font-size:11px;
            }
            QLineEdit:focus, QComboBox:focus { border:1px solid #2868E8; }
            QLineEdit:disabled, QComboBox:disabled { background:#EDF1F6; color:#94A3B8; }
            QComboBox QAbstractItemView {
                background:#FFFFFF; color:#172033; selection-background-color:#E8F0FF;
                selection-color:#2868E8; border:1px solid #C9D5E5;
            }
            QPushButton#saveButton { background:#2868E8; color:#FFFFFF; border:0;
                border-radius:8px; min-height:36px; padding:0 18px; font-weight:700; }
            QPushButton#saveButton:hover { background:#1F57C8; }
            QPushButton#cancelButton { background:#FFFFFF; color:#475569;
                border:1px solid #C9D5E5; border-radius:8px; min-height:36px;
                padding:0 18px; font-weight:600; }
            QPushButton#cancelButton:hover { background:#F1F5F9; }
        """)

        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(24, 20, 24, 22)

        dialog_title = QLabel("Edit machine" if machine else "Add machine")
        dialog_title.setObjectName("DialogTitle")
        dialog_subtitle = QLabel("Configure the inspection cell and its PLC endpoint.")
        dialog_subtitle.setObjectName("DialogSubtitle")
        layout.addWidget(dialog_title)
        layout.addWidget(dialog_subtitle)
        layout.addSpacing(8)

        identity_section = QLabel("MACHINE IDENTITY")
        identity_section.setObjectName("SectionTitle")
        layout.addWidget(identity_section)

        # Machine Name
        layout.addWidget(QLabel("Machine Name"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter machine name")
        layout.addWidget(self.name_input)

        layout.addSpacing(6)
        plc_section = QLabel("PLC CONNECTION")
        plc_section.setObjectName("SectionTitle")
        layout.addWidget(plc_section)

        # PLC Brand
        layout.addWidget(QLabel("PLC Brand *"))
        self.plc_brand_combo = QComboBox()
        self.plc_brand_combo.addItem("Select PLC Brand", None)
        self.plc_brand_combo.addItems(list(PLC_DATA.keys()))
        self.plc_brand_combo.currentTextChanged.connect(self.on_brand_changed)
        layout.addWidget(self.plc_brand_combo)

        # Model
        layout.addWidget(QLabel("Model Series *"))
        self.plc_model_combo = QComboBox()
        self.plc_model_combo.addItem("Select Model", None)
        self.plc_model_combo.setEnabled(False)
        layout.addWidget(self.plc_model_combo)

        # Protocol
        layout.addWidget(QLabel("Communication Protocol *"))
        self.plc_protocol_combo = QComboBox()
        self.plc_protocol_combo.addItem("Select Protocol", None)
        self.plc_protocol_combo.setEnabled(False)
        layout.addWidget(self.plc_protocol_combo)

        # IP
        layout.addWidget(QLabel("IP Address *"))
        self.ip_input = QLineEdit()
        self.ip_input.setPlaceholderText("e.g., 192.168.1.100")
        layout.addWidget(self.ip_input)

        # Slot / Rack (needed for some PLCs like Allen-Bradley)
        layout.addWidget(QLabel("Slot / Rack (if applicable)"))
        self.slot_input = QLineEdit()
        self.slot_input.setPlaceholderText("e.g., 0 or 1 (Allen-Bradley usually 0)")
        layout.addWidget(self.slot_input)

        # Pre-fill when editing
        if self.machine:
            self.name_input.setText(self.machine.get("name", ""))
            self.ip_input.setText(self.machine.get("ip_address", ""))
            self.slot_input.setText(str(self.machine.get("slot", "")) if self.machine.get("slot") is not None else "")


            plc_brand = self.machine.get("plc_brand", "")
            if plc_brand:
                idx = self.plc_brand_combo.findText(plc_brand)
                if idx >= 0:
                    self.plc_brand_combo.setCurrentIndex(idx)
                    self.on_brand_changed(plc_brand)

                    plc_model = self.machine.get("plc_model", "")
                    if plc_model:
                        midx = self.plc_model_combo.findText(plc_model)
                        if midx >= 0:
                            self.plc_model_combo.setCurrentIndex(midx)

                    plc_protocol = self.machine.get("plc_protocol", "")
                    if plc_protocol:
                        pidx = self.plc_protocol_combo.findText(plc_protocol)
                        if pidx >= 0:
                            self.plc_protocol_combo.setCurrentIndex(pidx)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setObjectName("saveButton")
        save_btn.clicked.connect(self.save)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancelButton")
        cancel_btn.clicked.connect(self.reject)

        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addSpacing(8)
        layout.addLayout(btn_row)

        self.setLayout(layout)

    def on_brand_changed(self, brand):
        if not brand or brand == "Select PLC Brand":
            self.plc_model_combo.clear()
            self.plc_model_combo.addItem("Select Model", None)
            self.plc_model_combo.setEnabled(False)

            self.plc_protocol_combo.clear()
            self.plc_protocol_combo.addItem("Select Protocol", None)
            self.plc_protocol_combo.setEnabled(False)
            return

        plc_info = PLC_DATA.get(brand)
        if not plc_info:
            return

        self.plc_model_combo.clear()
        self.plc_model_combo.addItem("Select Model", None)
        self.plc_model_combo.addItems(plc_info["models"])
        self.plc_model_combo.setEnabled(True)

        self.plc_protocol_combo.clear()
        self.plc_protocol_combo.addItem("Select Protocol", None)
        self.plc_protocol_combo.addItems(plc_info["protocols"])
        self.plc_protocol_combo.setEnabled(True)

    def save(self):

        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing", "Machine name cannot be empty")
            return

        ip_address = self.ip_input.text().strip()
        if not ip_address:
            QMessageBox.warning(self, "Missing", "IP Address is mandatory.")
            return
        try:
            parsed_ip = ipaddress.ip_address(ip_address)
            if parsed_ip.version != 4:
                raise ValueError
        except ValueError:
            QMessageBox.warning(
                self, "Invalid IP address",
                "Enter a valid IPv4 address, for example 192.168.1.100."
            )
            self.ip_input.setFocus()
            self.ip_input.selectAll()
            return

        slot_raw = self.slot_input.text().strip()
        slot = int(slot_raw) if slot_raw.isdigit() else None

        plc_brand = self.plc_brand_combo.currentText()
        if plc_brand == "Select PLC Brand":
            QMessageBox.warning(self, "Missing PLC brand", "Select the PLC manufacturer.")
            self.plc_brand_combo.setFocus()
            return

        plc_model = self.plc_model_combo.currentText()
        if plc_model == "Select Model":
            QMessageBox.warning(self, "Missing PLC model", "Select the PLC model series.")
            self.plc_model_combo.setFocus()
            return

        plc_protocol = self.plc_protocol_combo.currentText()
        if plc_protocol == "Select Protocol":
            QMessageBox.warning(self, "Missing protocol", "Select the PLC communication protocol.")
            self.plc_protocol_combo.setFocus()
            return

        # ---- brand-specific requirement: AB usually needs slot ----
        if plc_brand and "allen-bradley" in plc_brand.lower() and slot is None:
            QMessageBox.warning(self, "Missing", "Slot is required for Allen-Bradley PLCs.")
            return

       # ---- REAL PLC CONNECTION TEST ----
        temp_machine = {
            "plc_brand": plc_brand,
            "plc_protocol": plc_protocol,
            "ip_address": ip_address,
            "slot": slot,
        }

        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            connected, msg = check_plc_and_get_active(temp_machine)
        finally:
            QApplication.restoreOverrideCursor()

        if connected:
            QMessageBox.information(self, "PLC connected", _friendly_plc_message(msg))
        else:
            QMessageBox.warning(self, "PLC unavailable", _friendly_plc_message(msg))


        active_status = bool(connected)

        try:
            if self.machine:
                machine_id = str(self.machine.get("_id") or self.machine.get("id"))
                update_data = {
                    "name": name,
                    "ip_address": ip_address,
                    "slot": slot,
                    "plc_brand": plc_brand,
                    "plc_model": plc_model,
                    "plc_protocol": plc_protocol,
                    "active": active_status,
                    "last_connection_check": datetime.now().isoformat(timespec="seconds"),
                }
                # keep None out
                update_data = {k: v for k, v in update_data.items() if v is not None}

                success = self.machine_db.update_machine(machine_id, update_data)
                if success:
                    QMessageBox.information(self, "Success", "Machine updated successfully.")
                    self.result = {"success": True}
                    self.accept()
                else:
                    QMessageBox.warning(self, "Error", "Failed to update machine.")
            else:
                data = {
                    "name": name,
                    "ip_address": ip_address,
                    "slot": slot,
                    "plc_brand": plc_brand,
                    "plc_model": plc_model,
                    "plc_protocol": plc_protocol,
                    "active": active_status,
                    "last_connection_check": datetime.now().isoformat(timespec="seconds"),
                }
                machine_id = self.machine_db.add_machine(data)
                if machine_id:
                    QMessageBox.information(
                        self, "Success",
                        "Machine added and PLC connected."
                        if active_status else
                        "Machine added but PLC not connected (marked Disabled)."
                    )
                    self.result = {"success": True}
                    self.accept()
                else:
                    QMessageBox.warning(self, "Error", "Failed to add machine.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error saving machine: {str(e)}")


    def get_result(self):
        return self.result
