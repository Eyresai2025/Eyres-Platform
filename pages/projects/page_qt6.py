"""Responsive PyQt6 Projects page for the EYRES AI Inspection Platform.

This is a UI migration of the existing Projects page. It deliberately keeps
the existing ProjectDB / MachineDB backend contracts and project field names.

Preserved backend fields:
    name
    machine_id
    description
    type
    folder_path

Preserved inspection types:
    Anomaly
    Classification
    Anomaly + Classification
    Dimension
"""
from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
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

from ui.qt6.icons import icon_pixmap
from ui.qt6.widgets import AnimatedCard, IconBadge


# Keep compatibility with the current project layout and newer src layouts.
try:
    from db import MachineDB, ProjectDB
except ImportError:  # pragma: no cover
    try:
        from src.db import MachineDB, ProjectDB
    except ImportError:
        from src.database.db import MachineDB, ProjectDB


INSPECTION_TYPES = (
    "Anomaly",
    "Classification",
    "Anomaly + Classification",
    "Dimension",
)


def _record_id(record: dict | None) -> str:
    record = record or {}
    return str(record.get("_id") or record.get("id") or "")


def _machine_name(machine: dict | None) -> str:
    if not machine:
        return "Machine unavailable"
    raw = machine.get("name", "Unnamed machine")
    if isinstance(raw, dict):
        return str(
            raw.get("name")
            or raw.get("machine_name")
            or raw.get("label")
            or "Unnamed machine"
        )
    return str(raw)


def _project_type(project: dict) -> str:
    value = str(project.get("type") or "Not configured").strip()
    return value or "Not configured"


def _folder_path_for_project(project_name: str) -> str | None:
    """Reuse the existing project-path helper when the application provides it."""
    try:
        from utils.project_paths import get_project_folder
    except Exception:
        try:
            from src.utils.project_paths import get_project_folder
        except Exception:
            return None
    try:
        return str(get_project_folder(project_name))
    except Exception:
        return None


class MetricCard(AnimatedCard):
    """Projects KPI card using the Dashboard/Machines hover language."""

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
        meta_label = QLabel(meta, objectName="MetricMeta")

        copy.addWidget(label)
        copy.addSpacing(3)
        copy.addWidget(self.value_label)
        copy.addWidget(meta_label)
        copy.addStretch(1)

        self.badge = IconBadge(icon_name, icon_color, icon_bg)

        row.addLayout(copy, 1)
        row.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)

    def set_value(self, value: Any):
        self.value_label.setText(str(value))


class ProjectRecordCard(AnimatedCard):
    edit_requested = pyqtSignal(dict)
    delete_requested = pyqtSignal(dict)

    def __init__(self, project: dict, machine: dict | None, parent=None):
        super().__init__(parent)
        self.project = project
        self.machine = machine

        self.setObjectName("ProjectRecordCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(18, 16, 18, 16)
        self.grid.setHorizontalSpacing(15)
        self.grid.setVerticalSpacing(9)

        self.project_badge = IconBadge("projects", "#2868E8", "#EEF4FF")
        self.project_badge.setFixedSize(54, 54)

        self.info_widget = QWidget()
        info = QVBoxLayout(self.info_widget)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(5)

        name = QLabel(
            str(project.get("name") or "Unnamed project"),
            objectName="ProjectName",
        )
        info.addWidget(name)

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(7)

        type_chip = QLabel(_project_type(project).upper(), objectName="ProjectTypeChip")
        type_chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        chips.addWidget(type_chip)

        if machine:
            machine_chip = QLabel(
                f"Machine · {_machine_name(machine)}",
                objectName="MachineChip",
            )
            machine_chip.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            chips.addWidget(machine_chip)

        chips.addStretch(1)
        info.addLayout(chips)

        plc_parts = []
        if machine:
            for key in ("plc_brand", "plc_model"):
                value = machine.get(key)
                if value:
                    plc_parts.append(str(value))
        plc_text = " · ".join(plc_parts) if plc_parts else "Not configured"

        info.addWidget(QLabel(f"PLC: {plc_text}", objectName="ProjectMeta"))
        info.addWidget(
            QLabel(
                "Inspection workflow is linked to the configured production machine."
                if machine
                else "The assigned machine is unavailable. Reassign this project.",
                objectName="ProjectMetaSmall",
            )
        )

        self.actions_widget = QWidget()
        actions = QVBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(10)
        actions.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)

        status = QLabel(
            "●  LINKED" if machine else "●  MACHINE UNAVAILABLE",
            objectName="LinkedStatus" if machine else "UnlinkedStatus",
        )
        status.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        actions.addWidget(status, 0, Qt.AlignmentFlag.AlignRight)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        edit = QPushButton("Edit", objectName="SecondaryButton")
        delete = QPushButton("Delete", objectName="DeleteButton")

        for button in (edit, delete):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(34)

        edit.clicked.connect(lambda: self.edit_requested.emit(self.project))
        delete.clicked.connect(lambda: self.delete_requested.emit(self.project))

        buttons.addWidget(edit)
        buttons.addWidget(delete)
        actions.addLayout(buttons)
        actions.addStretch(1)

        self._compact = None
        self._reflow(force=True)

    def _clear_grid(self):
        while self.grid.count():
            self.grid.takeAt(0)

    def _reflow(self, force: bool = False):
        compact = self.width() < 740
        if not force and compact == self._compact:
            return
        self._compact = compact
        self._clear_grid()

        if compact:
            self.setMinimumHeight(190)
            self.grid.addWidget(
                self.project_badge,
                0,
                0,
                1,
                1,
                Qt.AlignmentFlag.AlignTop,
            )
            self.grid.addWidget(self.info_widget, 0, 1, 1, 1)
            self.grid.addWidget(self.actions_widget, 1, 0, 1, 2)
            self.grid.setColumnStretch(0, 0)
            self.grid.setColumnStretch(1, 1)
        else:
            self.setMinimumHeight(132)
            self.grid.addWidget(
                self.project_badge,
                0,
                0,
                1,
                1,
                Qt.AlignmentFlag.AlignVCenter,
            )
            self.grid.addWidget(self.info_widget, 0, 1, 1, 1)
            self.grid.addWidget(self.actions_widget, 0, 2, 1, 1)
            self.grid.setColumnStretch(0, 0)
            self.grid.setColumnStretch(1, 1)
            self.grid.setColumnStretch(2, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def enterEvent(self, event):
        self.project_badge.animate_hover(True)
        self._animate_shadow(28.0, 7.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.project_badge.animate_hover(False)
        self._animate_shadow(14.0, 4.0)
        super().leaveEvent(event)


class DeleteProjectDialog(QDialog):
    def __init__(self, project: dict, parent=None):
        super().__init__(parent)

        self.setObjectName("DeleteProjectDialog")
        self.setWindowTitle("Delete Project")
        self.setModal(True)
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(10)

        badge = QLabel("!", objectName="DeleteWarningBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(44, 44)
        root.addWidget(badge)

        name = str(project.get("name") or "this project")
        root.addWidget(QLabel(f"Delete {name}?", objectName="DeleteDialogTitle"))

        body = QLabel(
            "This removes the project record. Inspection data associated with it "
            "may no longer be accessible.",
            objectName="DeleteDialogBody",
        )
        body.setWordWrap(True)
        root.addWidget(body)
        root.addSpacing(5)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        cancel = QPushButton("Cancel", objectName="DialogSecondary")
        delete = QPushButton("Delete Project", objectName="DialogDanger")

        for button in (cancel, delete):
            button.setFixedHeight(36)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        cancel.clicked.connect(self.reject)
        delete.clicked.connect(self.accept)

        buttons.addWidget(cancel)
        buttons.addWidget(delete)
        root.addLayout(buttons)

        self.setStyleSheet("""
        QDialog#DeleteProjectDialog { background:#FFFFFF; }
        QDialog#DeleteProjectDialog QLabel { background:transparent; border:0; }

        QLabel#DeleteWarningBadge {
            background:#FFF0F3; color:#D63C55;
            border:1px solid #F7D8DE; border-radius:13px;
            font-size:20px; font-weight:800;
        }
        QLabel#DeleteDialogTitle {
            color:#101A2D; font-size:17px; font-weight:800;
        }
        QLabel#DeleteDialogBody {
            color:#65758E; font-size:10.5px;
        }

        QPushButton#DialogSecondary, QPushButton#DialogDanger {
            background:#FFFFFF; color:#40516A;
            border:1px solid #C9D7E9; border-radius:9px;
            padding:0 14px; font-size:10.5px; font-weight:700;
        }
        QPushButton#DialogSecondary:hover { background:#F3F6FC; }
        QPushButton#DialogDanger {
            color:#C93450; border-color:#F0BEC8;
        }
        QPushButton#DialogDanger:hover { background:#FFF1F3; }
        """)


class ProjectDialogQt6(QDialog):
    """Create/Edit Project dialog using the existing database schema."""

    def __init__(
        self,
        project_db: ProjectDB,
        machine_db: MachineDB,
        project: dict | None = None,
        parent=None,
    ):
        super().__init__(parent)

        self.project_db = project_db
        self.machine_db = machine_db
        self.project = project
        self._machines: list[dict] = []

        self.setObjectName("ProjectDialog")
        self.setWindowTitle("Edit Project" if project else "Create Project")
        self.setModal(True)
        self.setMinimumSize(640, 500)
        self.resize(720, 520)
        self.setSizeGripEnabled(True)

        self._build()
        self._apply_style()
        self._load_machines()

        if project:
            self._populate(project)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(objectName="DialogHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 16, 16, 14)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(
            QLabel(
                "Edit Project" if self.project else "Create Project",
                objectName="DialogTitle",
            )
        )
        copy.addWidget(
            QLabel(
                "Define the inspection workflow and assign its production machine.",
                objectName="DialogSubtitle",
            )
        )
        hl.addLayout(copy, 1)

        close = QPushButton("×", objectName="DialogClose")
        close.setFixedSize(32, 32)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        hl.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        root.addWidget(header)

        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(20, 18, 20, 18)
        grid.setHorizontalSpacing(16)

        details = QFrame(objectName="FormCard")
        dl = QVBoxLayout(details)
        dl.setContentsMargins(15, 14, 15, 14)
        dl.setSpacing(8)
        dl.addWidget(QLabel("PROJECT DETAILS", objectName="SectionKicker"))

        dl.addWidget(QLabel("Project Name *", objectName="FieldLabel"))
        self.name_input = QLineEdit(objectName="FormInput")
        self.name_input.setPlaceholderText("e.g., Cap seal inspection")
        self.name_input.setClearButtonEnabled(True)
        dl.addWidget(self.name_input)

        dl.addWidget(QLabel("Inspection Type *", objectName="FieldLabel"))
        self.type_combo = QComboBox(objectName="FormCombo")
        self.type_combo.addItems(INSPECTION_TYPES)
        dl.addWidget(self.type_combo)

        workflow_box = QFrame(objectName="InfoBox")
        workflow_layout = QVBoxLayout(workflow_box)
        workflow_layout.setContentsMargins(11, 9, 11, 9)
        workflow_layout.setSpacing(2)
        workflow_layout.addWidget(QLabel("Workflow type", objectName="InfoTitle"))
        workflow_layout.addWidget(
            QLabel(
                "Select the same inspection workflow type used by the existing project configuration.",
                objectName="InfoText",
            )
        )
        dl.addWidget(workflow_box)
        dl.addStretch(1)

        assignment = QFrame(objectName="FormCard")
        al = QVBoxLayout(assignment)
        al.setContentsMargins(15, 14, 15, 14)
        al.setSpacing(8)
        al.addWidget(QLabel("MACHINE ASSIGNMENT", objectName="SectionKicker"))

        al.addWidget(QLabel("Machine *", objectName="FieldLabel"))
        self.machine_combo = QComboBox(objectName="FormCombo")
        self.machine_combo.addItem("Select machine", None)
        self.machine_combo.currentIndexChanged.connect(self._update_machine_info)
        al.addWidget(self.machine_combo)

        self.machine_info = QFrame(objectName="InfoBox")
        mil = QVBoxLayout(self.machine_info)
        mil.setContentsMargins(11, 9, 11, 9)
        mil.setSpacing(2)
        self.machine_info_title = QLabel("Selected machine", objectName="InfoTitle")
        self.machine_info_text = QLabel(
            "Select a machine to view its PLC configuration.",
            objectName="InfoText",
        )
        self.machine_info_text.setWordWrap(True)
        mil.addWidget(self.machine_info_title)
        mil.addWidget(self.machine_info_text)
        al.addWidget(self.machine_info)
        al.addStretch(1)

        grid.addWidget(details, 0, 0)
        grid.addWidget(assignment, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        root.addWidget(body, 1)

        footer = QFrame(objectName="DialogFooter")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 12, 20, 14)
        fl.setSpacing(8)

        self.status_label = QLabel(
            "A configured machine is required for an inspection project.",
            objectName="DialogStatus",
        )
        self.status_label.setWordWrap(True)
        fl.addWidget(self.status_label, 1)

        cancel = QPushButton("Cancel", objectName="DialogSecondary")
        self.save_button = QPushButton(
            "Update Project" if self.project else "Save Project",
            objectName="DialogPrimary",
        )
        for button in (cancel, self.save_button):
            button.setFixedHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        cancel.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)

        fl.addWidget(cancel)
        fl.addWidget(self.save_button)
        root.addWidget(footer)

        self.name_input.returnPressed.connect(self._save)

    def _load_machines(self):
        try:
            self._machines = list(self.machine_db.get_all_machines() or [])
        except Exception as exc:
            self._machines = []
            self.status_label.setText(f"Machines could not be loaded: {exc}")
            self.status_label.setStyleSheet("color:#C93450; font-size:9.5px;")

        for machine in self._machines:
            self.machine_combo.addItem(
                _machine_name(machine),
                _record_id(machine),
            )

        has_machines = bool(self._machines)
        self.machine_combo.setEnabled(has_machines)
        self.save_button.setEnabled(has_machines)

        if not has_machines:
            self.machine_info_text.setText(
                "Create a machine before configuring an inspection project."
            )

    def _populate(self, project: dict):
        self.name_input.setText(str(project.get("name") or ""))

        current_type = str(project.get("type") or "")
        index = self.type_combo.findText(current_type)
        if index >= 0:
            self.type_combo.setCurrentIndex(index)

        machine_id = str(project.get("machine_id") or "")
        index = self.machine_combo.findData(machine_id)
        if index >= 0:
            self.machine_combo.setCurrentIndex(index)

    def _machine_by_id(self, machine_id: str) -> dict | None:
        for machine in self._machines:
            if _record_id(machine) == str(machine_id):
                return machine
        return None

    def _update_machine_info(self):
        machine_id = self.machine_combo.currentData()
        machine = self._machine_by_id(machine_id) if machine_id else None

        if not machine:
            self.machine_info_text.setText(
                "Select a machine to view its PLC configuration."
            )
            return

        lines = [_machine_name(machine)]
        plc = " · ".join(
            str(machine.get(key))
            for key in ("plc_brand", "plc_model")
            if machine.get(key)
        )
        if plc:
            lines.append(plc)

        protocol = machine.get("plc_protocol")
        if protocol:
            lines.append(str(protocol))

        ip_address = machine.get("ip_address")
        if ip_address:
            lines.append(f"IP {ip_address}")

        self.machine_info_text.setText("\n".join(lines))

    def _validation_error(self, message: str, widget: QWidget | None = None):
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color:#C93450; font-size:9.5px;")
        if widget is not None:
            widget.setFocus()

    def _save(self):
        name = self.name_input.text().strip()
        machine_id = self.machine_combo.currentData()

        if not name:
            self._validation_error("Enter a name for this project.", self.name_input)
            return

        if not machine_id:
            self._validation_error(
                "Select the machine used by this project.",
                self.machine_combo,
            )
            return

        project_type = self.type_combo.currentText()

        try:
            if self.project:
                project_id = _record_id(self.project)
                kwargs = {
                    "name": name,
                    "machine_id": machine_id,
                    "description": "",
                    "type": project_type,
                }

                folder_path = _folder_path_for_project(name)
                if folder_path is not None:
                    kwargs["folder_path"] = folder_path

                result = self.project_db.update_project(project_id, **kwargs)
                if not result:
                    raise RuntimeError("The database did not update the project.")
            else:
                result = self.project_db.add_project(
                    name=name,
                    machine_id=machine_id,
                    description="",
                    type=project_type,
                )
                if not result:
                    raise RuntimeError("The database did not create the project.")
        except Exception as exc:
            self._validation_error(str(exc))
            return

        self.accept()

    def _apply_style(self):
        self.setStyleSheet("""
        QDialog#ProjectDialog { background:#FFFFFF; }
        QDialog#ProjectDialog QLabel { background:transparent; border:0; }

        QFrame#DialogHeader, QFrame#DialogFooter {
            background:#FFFFFF; border:0;
        }
        QFrame#DialogHeader { border-bottom:1px solid #DDE5EF; }
        QFrame#DialogFooter { border-top:1px solid #DDE5EF; }

        QLabel#DialogTitle {
            color:#101A2D; font-size:19px; font-weight:800;
        }
        QLabel#DialogSubtitle {
            color:#6A7A91; font-size:10.5px;
        }

        QPushButton#DialogClose {
            background:#FFFFFF; color:#5E6D82;
            border:1px solid #D7E1EE; border-radius:9px; font-size:18px;
        }
        QPushButton#DialogClose:hover { background:#F2F6FC; }

        QFrame#FormCard {
            background:#F7F9FC; border:1px solid #D2DCE9; border-radius:13px;
        }
        QLabel#SectionKicker {
            color:#2868E8; font-size:9px; font-weight:800; letter-spacing:0.7px;
        }
        QLabel#FieldLabel {
            color:#42536A; font-size:10px; font-weight:700; margin-top:3px;
        }

        QLineEdit#FormInput, QComboBox#FormCombo {
            min-height:38px; background:#FFFFFF; color:#213047;
            border:1px solid #C9D7E9; border-radius:9px;
            padding:0 10px; font-size:10.5px;
        }
        QLineEdit#FormInput:focus, QComboBox#FormCombo:focus {
            border:1px solid #2868E8;
        }
        QComboBox#FormCombo:disabled {
            background:#F1F4F8; color:#9AA6B7;
        }
        QComboBox#FormCombo QAbstractItemView {
            background:#FFFFFF; color:#213047;
            border:1px solid #BFCDE0;
            selection-background-color:#EAF1FF;
            selection-color:#2868E8;
            outline:0;
        }

        QFrame#InfoBox {
            background:#FFFFFF; border:1px solid #DFE7F2; border-radius:10px;
        }
        QLabel#InfoTitle {
            color:#223047; font-size:9.5px; font-weight:750;
        }
        QLabel#InfoText {
            color:#6F7E92; font-size:9px;
        }

        QLabel#DialogStatus {
            color:#708096; font-size:9.5px;
        }

        QPushButton#DialogPrimary, QPushButton#DialogSecondary {
            border-radius:9px; padding:0 15px;
            font-size:10.5px; font-weight:750;
        }
        QPushButton#DialogPrimary {
            background:#2868E8; color:#FFFFFF; border:1px solid #2868E8;
        }
        QPushButton#DialogPrimary:hover {
            background:#1F57C8; border-color:#1F57C8;
        }
        QPushButton#DialogPrimary:disabled {
            background:#AFC6EF; border-color:#AFC6EF;
        }
        QPushButton#DialogSecondary {
            background:#FFFFFF; color:#40516A; border:1px solid #C9D7E9;
        }
        QPushButton#DialogSecondary:hover { background:#F3F6FC; }
        """)


class ProjectsPageQt6(QWidget):
    """Approved Projects page integrated with the existing backend."""

    toast_requested = pyqtSignal(str, str)

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)

        self.user = user or {}
        self.project_db = ProjectDB()
        self.machine_db = MachineDB()

        self._projects: list[dict] = []
        self._machines: list[dict] = []
        self._machine_cache: dict[str, dict] = {}
        self._summary_columns: int | None = None
        self._toolbar_mode: int | None = None

        self.setObjectName("ProjectsPageQt6")

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
            "TOTAL PROJECTS",
            "0",
            "Configured inspection projects",
            "projects",
        )
        self.linked_card = MetricCard(
            "MACHINE LINKED",
            "0",
            "Projects with assigned machines",
            "machines",
            icon_color="#07965D",
            icon_bg="#EAF9F2",
            value_color="#07965D",
        )
        self.types_card = MetricCard(
            "INSPECTION TYPES",
            "0",
            "Configured workflow types",
            "training",
            icon_color="#6B40E5",
            icon_bg="#F2EDFF",
        )
        self.attention_card = MetricCard(
            "NEEDS ATTENTION",
            "0",
            "Projects without a machine",
            "diagnostics",
            icon_color="#B86A00",
            icon_bg="#FFF6E2",
            value_color="#B86A00",
        )

        self.metric_cards = [
            self.total_card,
            self.linked_card,
            self.types_card,
            self.attention_card,
        ]
        root.addWidget(self.summary_host)

        self.panel = AnimatedCard()
        self.panel.setObjectName("ProjectPanel")
        panel = QVBoxLayout(self.panel)
        panel.setContentsMargins(0, 0, 0, 0)
        panel.setSpacing(0)

        header = QFrame(objectName="PanelHeader")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 15, 16, 14)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Inspection projects", objectName="PanelTitle"))
        copy.addWidget(
            QLabel(
                "Manage inspection workflows and their assigned production machines.",
                objectName="PanelSubtitle",
            )
        )
        hl.addLayout(copy, 1)

        add = QPushButton("+  Create Project", objectName="PrimaryButton")
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setFixedHeight(38)
        add.clicked.connect(self.open_add_dialog)
        hl.addWidget(add)
        panel.addWidget(header)

        self.toolbar = QFrame(objectName="FilterBar")
        self.toolbar_grid = QGridLayout(self.toolbar)
        self.toolbar_grid.setContentsMargins(15, 12, 15, 12)
        self.toolbar_grid.setHorizontalSpacing(9)
        self.toolbar_grid.setVerticalSpacing(9)

        self.search_input = QLineEdit(objectName="SearchInput")
        self.search_input.setPlaceholderText(
            "Search by project, inspection type, machine or PLC"
        )
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._render)

        self.type_filter = QComboBox(objectName="FilterCombo")
        self.type_filter.addItem("All inspection types")
        self.type_filter.addItems(INSPECTION_TYPES)
        self.type_filter.currentTextChanged.connect(self._render)

        self.machine_filter = QComboBox(objectName="FilterCombo")
        self.machine_filter.addItems(
            ["All machine status", "Linked", "Unlinked"]
        )
        self.machine_filter.currentTextChanged.connect(self._render)

        self.clear_button = QPushButton(
            "Clear filters",
            objectName="SecondaryButton",
        )
        self.clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_button.setFixedHeight(36)
        self.clear_button.clicked.connect(self._clear_filters)

        panel.addWidget(self.toolbar)

        self.scroll = QScrollArea(objectName="ProjectScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.list_host = QWidget(objectName="ProjectListHost")
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(15, 14, 15, 18)
        self.list_layout.setSpacing(11)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll.setWidget(self.list_host)
        panel.addWidget(self.scroll, 1)

        # Intentionally no bottom footer / design-preview text.
        # The user finalized the page without those lines.
        root.addWidget(self.panel, 1)

        self._reflow_summary(force=True)
        self._reflow_toolbar(force=True)

    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#ProjectsPageQt6 {
            background:transparent; color:#101A2D;
        }
        QWidget#ProjectsPageQt6 QLabel {
            background:transparent; border:0;
        }

        QFrame#MetricCard {
            background:#FFFFFF;
            border:1px solid #C9D5E5;
            border-radius:16px;
        }
        QLabel#MetricLabel {
            color:#6A7A91; font-size:9px; font-weight:800;
            letter-spacing:0.7px;
        }
        QLabel#MetricValue {
            color:#101A2D; font-size:27px; font-weight:800;
        }
        QLabel#MetricMeta {
            color:#6F8097; font-size:9px;
        }

        QFrame#ProjectPanel {
            background:#FFFFFF;
            border:1px solid #C9D5E5;
            border-radius:18px;
        }
        QFrame#PanelHeader {
            background:#FFFFFF;
            border:0;
            border-bottom:1px solid #DDE5EF;
        }
        QLabel#PanelTitle {
            color:#101A2D; font-size:15px; font-weight:800;
        }
        QLabel#PanelSubtitle {
            color:#68788F; font-size:9.5px;
        }

        QPushButton#PrimaryButton {
            background:#2868E8; color:#FFFFFF;
            border:1px solid #2868E8; border-radius:10px;
            padding:0 16px; font-size:10.5px; font-weight:800;
        }
        QPushButton#PrimaryButton:hover {
            background:#1F57C8; border-color:#1F57C8;
        }
        QPushButton#PrimaryButton:pressed {
            background:#184AAB;
        }

        QFrame#FilterBar {
            background:#F8FAFD;
            border:0;
            border-bottom:1px solid #DDE5EF;
        }
        QLineEdit#SearchInput, QComboBox#FilterCombo {
            min-height:36px;
            background:#FFFFFF; color:#213047;
            border:1px solid #BFCDE0;
            border-radius:10px;
            padding:0 11px;
            font-size:10.5px;
        }
        QLineEdit#SearchInput:focus, QComboBox#FilterCombo:focus {
            border:1px solid #2868E8;
        }
        QComboBox#FilterCombo QAbstractItemView {
            background:#FFFFFF; color:#213047;
            border:1px solid #BFCDE0;
            selection-background-color:#EAF1FF;
            selection-color:#2868E8;
            outline:0;
        }

        QScrollArea#ProjectScroll,
        QScrollArea#ProjectScroll > QWidget > QWidget,
        QWidget#ProjectListHost {
            background:#FFFFFF; border:0;
        }
        QScrollBar:vertical {
            background:transparent; width:7px; margin:2px;
        }
        QScrollBar::handle:vertical {
            background:#D3DDEA; border-radius:3px; min-height:28px;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height:0;
        }

        QFrame#ProjectRecordCard {
            background:#FFFFFF;
            border:1px solid #CDD9E7;
            border-radius:15px;
        }
        QLabel#ProjectName {
            color:#101A2D; font-size:17px; font-weight:800;
        }
        QLabel#ProjectTypeChip {
            background:#EEF4FF; color:#2868E8;
            border:0; border-radius:8px;
            padding:4px 8px; font-size:9px; font-weight:800;
        }
        QLabel#MachineChip {
            background:#F1F5FA; color:#526279;
            border:0; border-radius:8px;
            padding:4px 8px; font-size:9px; font-weight:700;
        }
        QLabel#ProjectMeta {
            color:#6A7A91; font-size:10px;
        }
        QLabel#ProjectMetaSmall {
            color:#6E7F96; font-size:9px;
        }

        QLabel#LinkedStatus, QLabel#UnlinkedStatus {
            border-radius:10px;
            padding:5px 10px;
            font-size:9px;
            font-weight:800;
        }
        QLabel#LinkedStatus {
            background:#E8F8F1; color:#078A57;
            border:1px solid #D0EFDF;
        }
        QLabel#UnlinkedStatus {
            background:#FFF6E2; color:#A75F00;
            border:1px solid #F0DEAF;
        }

        QPushButton#SecondaryButton, QPushButton#DeleteButton {
            background:#FFFFFF;
            border:1px solid #C7D6EA;
            border-radius:9px;
            padding:0 13px;
            color:#2868E8;
            font-size:10px;
            font-weight:750;
        }
        QPushButton#SecondaryButton:hover {
            background:#F1F6FF;
        }
        QPushButton#DeleteButton {
            color:#C93450;
            border-color:#F0BEC8;
        }
        QPushButton#DeleteButton:hover {
            background:#FFF2F4;
        }

        QFrame#EmptyState {
            background:#F7F9FC;
            border:1px dashed #CAD8EA;
            border-radius:14px;
        }
        QLabel#EmptyTitle {
            color:#101A2D; font-size:15px; font-weight:800;
        }
        QLabel#EmptyText {
            color:#718096; font-size:10px;
        }
        """)

    # ------------------------------------------------------------------
    # Backend refresh / filtering
    # ------------------------------------------------------------------
    def refresh_data(self, animate: bool = True):
        errors = []

        try:
            self._projects = list(self.project_db.get_all_projects() or [])
        except Exception as exc:
            self._projects = []
            errors.append(f"Projects could not be loaded: {exc}")

        try:
            self._machines = list(self.machine_db.get_all_machines() or [])
        except Exception as exc:
            self._machines = []
            errors.append(f"Machines could not be loaded: {exc}")

        self._machine_cache = {
            _record_id(machine): machine
            for machine in self._machines
            if _record_id(machine)
        }

        self._update_metrics()
        self._render()

        if errors:
            self.toast_requested.emit(
                "Project data unavailable",
                " ".join(errors),
            )

        if animate:
            for index, card in enumerate(self.metric_cards):
                QtCore.QTimer.singleShot(
                    index * 45,
                    card.animate_entrance,
                )
            self.panel.animate_entrance()

    def _machine_for(self, project: dict) -> dict | None:
        machine_id = str(project.get("machine_id") or "")
        if not machine_id:
            return None
        return self._machine_cache.get(machine_id)

    def _update_metrics(self):
        total = len(self._projects)
        linked = sum(
            1
            for project in self._projects
            if self._machine_for(project) is not None
        )
        types = {
            _project_type(project)
            for project in self._projects
            if _project_type(project) != "Not configured"
        }
        attention = total - linked

        self.total_card.set_value(total)
        self.linked_card.set_value(linked)
        self.types_card.set_value(len(types))
        self.attention_card.set_value(attention)

    def _matches(self, project: dict) -> bool:
        machine = self._machine_for(project)

        query = self.search_input.text().strip().casefold()
        if query:
            values = [
                project.get("name", ""),
                project.get("type", ""),
                _machine_name(machine),
            ]
            if machine:
                values.extend(
                    [
                        machine.get("plc_brand", ""),
                        machine.get("plc_model", ""),
                        machine.get("plc_protocol", ""),
                    ]
                )
            blob = " ".join(map(str, values)).casefold()
            if query not in blob:
                return False

        selected_type = self.type_filter.currentText()
        if (
            selected_type != "All inspection types"
            and _project_type(project) != selected_type
        ):
            return False

        linked_filter = self.machine_filter.currentText()
        linked = machine is not None

        if linked_filter == "Linked" and not linked:
            return False
        if linked_filter == "Unlinked" and linked:
            return False

        return True

    def _render(self):
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        visible = [
            project
            for project in self._projects
            if self._matches(project)
        ]

        if not visible:
            filtered = bool(
                self.search_input.text().strip()
                or self.type_filter.currentIndex() > 0
                or self.machine_filter.currentIndex() > 0
            )
            self._add_empty_state(filtered)
            return

        for index, project in enumerate(visible):
            card = ProjectRecordCard(
                project,
                self._machine_for(project),
            )
            card.edit_requested.connect(self.open_edit_dialog)
            card.delete_requested.connect(self.delete_project)

            self.list_layout.addWidget(card)
            QtCore.QTimer.singleShot(
                index * 35,
                card.animate_entrance,
            )

        self.list_layout.addStretch(1)

    def _add_empty_state(self, filtered: bool):
        card = QFrame(objectName="EmptyState")
        card.setMinimumHeight(210)

        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(26, 28, 26, 28)
        layout.setSpacing(8)

        badge = QLabel()
        badge.setPixmap(
            icon_pixmap(
                "projects",
                "#2868E8",
                34,
                prefer_legacy=True,
            )
        )
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(58, 58)

        title = QLabel(
            "No matching projects"
            if filtered
            else "No inspection projects yet",
            objectName="EmptyTitle",
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        body = QLabel(
            "Clear the filters or search for another project."
            if filtered
            else "Create a project to connect a machine with an inspection workflow.",
            objectName="EmptyText",
        )
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setWordWrap(True)

        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addWidget(body)

        if not filtered:
            button = QPushButton(
                "+  Create Project",
                objectName="PrimaryButton",
            )
            button.setFixedHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(self.open_add_dialog)
            layout.addWidget(
                button,
                0,
                Qt.AlignmentFlag.AlignCenter,
            )

        self.list_layout.addWidget(card)

    def _clear_filters(self):
        self.search_input.clear()
        self.type_filter.setCurrentIndex(0)
        self.machine_filter.setCurrentIndex(0)
        self._render()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def open_add_dialog(self):
        dialog = ProjectDialogQt6(
            self.project_db,
            self.machine_db,
            parent=self,
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_data(animate=True)
            self.toast_requested.emit(
                "Project created",
                "The inspection project was saved successfully.",
            )

    def open_edit_dialog(self, project: dict):
        dialog = ProjectDialogQt6(
            self.project_db,
            self.machine_db,
            project=project,
            parent=self,
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh_data(animate=True)
            self.toast_requested.emit(
                "Project updated",
                "The inspection project was updated successfully.",
            )

    def delete_project(self, project: dict):
        dialog = DeleteProjectDialog(project, self)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        project_id = _record_id(project)

        try:
            success = bool(
                self.project_db.delete_project(project_id)
            )
        except Exception as exc:
            self.toast_requested.emit(
                "Delete failed",
                f"Project could not be deleted: {exc}",
            )
            return

        if not success:
            self.toast_requested.emit(
                "Delete failed",
                "The database did not delete the project.",
            )
            return

        self.refresh_data(animate=True)
        self.toast_requested.emit(
            "Project deleted",
            "The project record was removed.",
        )

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
            self.summary_grid.takeAt(0)

        for index, card in enumerate(self.metric_cards):
            row = index // columns
            col = index % columns
            self.summary_grid.addWidget(card, row, col)

        for column in range(columns):
            self.summary_grid.setColumnStretch(column, 1)

    def _reflow_toolbar(self, force: bool = False):
        width = max(1, self.width())

        if width >= 1050:
            mode = 0
        elif width >= 720:
            mode = 1
        else:
            mode = 2

        if not force and mode == self._toolbar_mode:
            return

        self._toolbar_mode = mode

        while self.toolbar_grid.count():
            self.toolbar_grid.takeAt(0)

        if mode == 0:
            self.toolbar_grid.addWidget(self.search_input, 0, 0)
            self.toolbar_grid.addWidget(self.type_filter, 0, 1)
            self.toolbar_grid.addWidget(self.machine_filter, 0, 2)
            self.toolbar_grid.addWidget(self.clear_button, 0, 3)

            self.toolbar_grid.setColumnStretch(0, 1)
            self.toolbar_grid.setColumnStretch(1, 0)
            self.toolbar_grid.setColumnStretch(2, 0)
            self.toolbar_grid.setColumnStretch(3, 0)

        elif mode == 1:
            self.toolbar_grid.addWidget(
                self.search_input,
                0,
                0,
                1,
                3,
            )
            self.toolbar_grid.addWidget(self.type_filter, 1, 0)
            self.toolbar_grid.addWidget(self.machine_filter, 1, 1)
            self.toolbar_grid.addWidget(self.clear_button, 1, 2)

            self.toolbar_grid.setColumnStretch(0, 1)
            self.toolbar_grid.setColumnStretch(1, 1)
            self.toolbar_grid.setColumnStretch(2, 0)

        else:
            self.toolbar_grid.addWidget(self.search_input, 0, 0)
            self.toolbar_grid.addWidget(self.type_filter, 1, 0)
            self.toolbar_grid.addWidget(self.machine_filter, 2, 0)
            self.toolbar_grid.addWidget(self.clear_button, 3, 0)
            self.toolbar_grid.setColumnStretch(0, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_summary()
        self._reflow_toolbar()
