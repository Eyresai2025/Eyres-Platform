"""Modern Projects page for the EyRes.AI inspection platform."""
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette, QPixmap
from PyQt5.QtWidgets import (QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListView, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget)

from db import MachineDB, ProjectDB
from ui.theme import apply_light_surface


PAGE_STYLE = """
QWidget#ProjectsPage { background:#f5f7fb; color:#0f172a; }
QWidget#ProjectsPage QLabel { background-color:transparent; }
QFrame#PageHeader,QFrame#SearchBar,QFrame#ProjectCard,QFrame#EmptyCard {
 background:#fff; border:1px solid #d8e2f0; border-radius:14px; }
QFrame#ProjectCard:hover { border-color:#9dbcfb; background:#fbfdff; }
QLabel#PageTitle { color:#0f172a; background:transparent; font-size:23px; font-weight:800; }
QLabel#PageSubtitle,QLabel#MutedText { color:#64748b; background:transparent; font-size:11px; }
QLabel#CountBadge,QLabel#ProjectType { color:#2563eb; background:#eef4ff;
 border-radius:9px; padding:3px 8px; font-size:10px; font-weight:700; }
QLabel#ProjectName { color:#0f172a; background:transparent; font-size:17px; font-weight:750; }
QLabel#LinkedStatus { color:#087f5b; background:#ecfdf5; border-radius:9px;
 padding:3px 9px; font-size:10px; font-weight:700; }
QLabel#UnlinkedStatus { color:#b45309; background:#fff7ed; border-radius:9px;
 padding:3px 9px; font-size:10px; font-weight:700; }
QLineEdit#ProjectSearch { background:#fff; color:#0f172a; border:1px solid #cbd8ea;
 border-radius:9px; padding:0 14px; font-size:12px; }
QLineEdit#ProjectSearch:focus { border-color:#2563eb; }
QPushButton#PrimaryButton { background:#2868e8; color:white; border:1px solid #2868e8;
 border-radius:9px; padding:0 18px; font-weight:700; }
QPushButton#PrimaryButton:hover { background:#1d57ca; }
QPushButton#SecondaryButton { background:#fff; color:#2563eb; border:1px solid #b7cdfb;
 border-radius:8px; padding:0 16px; font-weight:650; }
QPushButton#SecondaryButton:hover { background:#eef4ff; }
QPushButton#DangerButton { background:#fff; color:#dc263f; border:1px solid #f2b6be;
 border-radius:8px; padding:0 16px; font-weight:650; }
QPushButton#DangerButton:hover { background:#fff1f2; }
QScrollArea { border:none; background:transparent; }
QScrollArea > QWidget > QWidget { background:transparent; }
"""

DIALOG_STYLE = """
QDialog#ProjectDialog { background:#f7f9fc; color:#0f172a; }
QDialog#ProjectDialog QLabel { background-color:transparent; }
QLabel#DialogTitle { color:#0f172a; font-size:20px; font-weight:800; }
QLabel#DialogSubtitle { color:#64748b; font-size:11px; }
QLabel#SectionLabel { color:#2563eb; font-size:10px; font-weight:750; }
QLabel#FieldLabel { color:#24324a; font-size:11px; font-weight:600; }
QLabel#HelperText { color:#b45309; font-size:10px; }
QLineEdit,QComboBox { background:#fff; color:#0f172a; border:1px solid #c5d2e5;
 border-radius:8px; padding:0 11px; min-height:36px; }
QLineEdit:focus,QComboBox:focus { border-color:#2563eb; }
QComboBox:disabled { background:#eef2f7; color:#94a3b8; }
QComboBox QAbstractItemView { background:#fff; color:#0f172a; border:1px solid #c5d2e5;
 selection-background-color:#eaf1ff; selection-color:#1d4ed8; }
QPushButton#DialogPrimary { background:#2868e8; color:white; border:none; border-radius:8px;
 padding:0 18px; font-weight:700; min-height:36px; }
QPushButton#DialogPrimary:hover { background:#1d57ca; }
QPushButton#DialogPrimary:disabled { background:#aebbd0; }
QPushButton#DialogCancel { background:#fff; color:#334155; border:1px solid #c5d2e5;
 border-radius:8px; padding:0 18px; font-weight:650; min-height:36px; }
QPushButton#DialogCancel:hover { background:#f1f5f9; }
"""


class ProjectPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectsPage")
        self.setWindowTitle("Projects")
        self.main_window = None
        self.project_db, self.machine_db = ProjectDB(), MachineDB()
        self._projects, self._machine_cache = [], {}
        apply_light_surface(self)  # Run compatibility styling before page-specific QSS.
        self.setup_ui()
        self.setStyleSheet(PAGE_STYLE)

    def set_main_window(self, main_window): self.main_window = main_window

    def setup_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(28,20,28,24); root.setSpacing(14)
        header = QFrame(objectName="PageHeader"); header.setFixedHeight(72)
        row = QHBoxLayout(header); row.setContentsMargins(18,10,14,10)
        titles = QVBoxLayout(); titles.setSpacing(2)
        title_row = QHBoxLayout()
        title = QLabel("Projects", objectName="PageTitle")
        self.count_badge = QLabel("0 PROJECTS", objectName="CountBadge")
        title_row.addWidget(title); title_row.addWidget(self.count_badge,0,Qt.AlignVCenter); title_row.addStretch()
        titles.addLayout(title_row)
        titles.addWidget(QLabel("Organize inspection recipes, training pipelines and machine assignments.", objectName="PageSubtitle"))
        add = QPushButton("+  Create Project", objectName="PrimaryButton"); add.setFixedSize(150,38)
        add.setCursor(Qt.PointingHandCursor); add.clicked.connect(self.open_add_form)
        row.addLayout(titles,1); row.addWidget(add); root.addWidget(header)

        toolbar = QFrame(objectName="SearchBar"); tb = QHBoxLayout(toolbar); tb.setContentsMargins(12,8,12,8)
        self.search = QLineEdit(objectName="ProjectSearch")
        self.search.setPlaceholderText("Search by project, inspection type, machine or PLC")
        self.search.setClearButtonEnabled(True); self.search.setFixedHeight(38)
        self.search.textChanged.connect(self._render_projects); tb.addWidget(self.search); root.addWidget(toolbar)

        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        self.container = QWidget(); self.container.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Minimum)
        self.container_layout = QVBoxLayout(self.container); self.container_layout.setContentsMargins(0,0,0,20)
        self.container_layout.setSpacing(12); self.container_layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.container); root.addWidget(scroll,1); self.refresh_list()

    @staticmethod
    def _id(record): return str(record.get("_id") or record.get("id") or "")

    @staticmethod
    def _machine_name(machine):
        if not machine: return "Machine unavailable"
        raw = machine.get("name", "Unnamed machine")
        if isinstance(raw, dict): return str(raw.get("name") or raw.get("machine_name") or "Unnamed machine")
        return str(raw)

    def _machine_for(self, project):
        ident = str(project.get("machine_id") or "")
        if ident in self._machine_cache: return self._machine_cache[ident]
        try: return self.machine_db.get_machine(ident) if ident else None
        except Exception: return None

    def _clear(self):
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

    def refresh_list(self):
        try:
            self._projects = list(self.project_db.get_all_projects() or [])
            machines = list(self.machine_db.get_all_machines() or [])
            self._machine_cache = {self._id(m):m for m in machines}
        except Exception as exc:
            self._projects, self._machine_cache = [], {}
            self.show_error(f"Projects could not be loaded.\n\n{exc}")
        n = len(self._projects); self.count_badge.setText(f"{n} PROJECT" if n == 1 else f"{n} PROJECTS")
        self._render_projects()

    def _render_projects(self, _text=None):
        self._clear(); query = self.search.text().strip().casefold(); visible = []
        for project in self._projects:
            machine = self._machine_for(project)
            values = [project.get("name",""),project.get("type",""),self._machine_name(machine)]
            if machine: values += [machine.get("plc_brand",""),machine.get("plc_model","")]
            if not query or query in " ".join(map(str,values)).casefold(): visible.append(project)
        if not visible: self.container_layout.addWidget(self._empty_state(bool(query))); return
        for project in visible: self.container_layout.addWidget(self.project_card(project))
        self.container_layout.addStretch(1)

    def _art(self, size, fallback="PR"):
        label = QLabel(fallback); label.setAlignment(Qt.AlignCenter); label.setFixedSize(size,size)
        label.setStyleSheet("background:#eef4ff;color:#2563eb;border-radius:12px;font-size:12px;font-weight:800;")
        asset = Path(__file__).resolve().parents[2]/"Media"/"dashboard_projects.gif"
        pix = QPixmap(str(asset))
        if not pix.isNull():
            label.setText(""); label.setPixmap(pix.scaled(size-10,size-10,Qt.KeepAspectRatio,Qt.SmoothTransformation))
        return label

    def _empty_state(self, filtered):
        card = QFrame(objectName="EmptyCard"); box = QVBoxLayout(card)
        box.setContentsMargins(24,42,24,42); box.setSpacing(8); box.setAlignment(Qt.AlignCenter)
        art = self._art(64); art.setStyleSheet("background:#eef4ff;color:#2563eb;border-radius:16px;font-size:16px;font-weight:800;")
        heading = QLabel("No matching projects" if filtered else "No inspection projects yet")
        heading.setStyleSheet("color:#0f172a;font-size:16px;font-weight:750;background:transparent;")
        detail = QLabel("Try another search term." if filtered else "Create a project to connect a machine with an inspection workflow.", objectName="MutedText")
        box.addWidget(art,0,Qt.AlignCenter); box.addWidget(heading,0,Qt.AlignCenter); box.addWidget(detail,0,Qt.AlignCenter)
        if not filtered:
            button = QPushButton("+  Create Project", objectName="PrimaryButton"); button.setFixedSize(146,36)
            button.clicked.connect(self.open_add_form); box.addSpacing(6); box.addWidget(button,0,Qt.AlignCenter)
        return card

    def project_card(self, project):
        card = QFrame(objectName="ProjectCard"); card.setFixedHeight(116)
        row = QHBoxLayout(card); row.setContentsMargins(18,15,16,15); row.setSpacing(16)
        row.addWidget(self._art(48),0,Qt.AlignVCenter)
        detail = QVBoxLayout(); detail.setSpacing(4); heading = QHBoxLayout()
        heading.addWidget(QLabel(str(project.get("name") or "Unnamed project"),objectName="ProjectName"))
        heading.addWidget(QLabel(str(project.get("type") or "Not configured").upper(),objectName="ProjectType"),0,Qt.AlignVCenter)
        heading.addStretch(); detail.addLayout(heading)
        machine = self._machine_for(project)
        detail.addWidget(QLabel(f"Machine  {self._machine_name(machine)}",objectName="MutedText"))
        plc = [str(machine.get(k)) for k in ("plc_brand","plc_model") if machine and machine.get(k)]
        detail.addWidget(QLabel("PLC  "+(" · ".join(plc) if plc else "Not configured"),objectName="MutedText"))
        row.addLayout(detail,1)
        status = QLabel("LINKED" if machine else "MACHINE UNAVAILABLE", objectName="LinkedStatus" if machine else "UnlinkedStatus")
        row.addWidget(status,0,Qt.AlignTop)
        edit = QPushButton("Edit",objectName="SecondaryButton"); delete = QPushButton("Delete",objectName="DangerButton")
        for b in (edit,delete): b.setFixedHeight(34); b.setCursor(Qt.PointingHandCursor)
        edit.setFixedWidth(72); delete.setFixedWidth(76)
        edit.clicked.connect(lambda _=False,p=project:self.open_edit_form(p))
        delete.clicked.connect(lambda _=False,p=project:self.delete_project(p))
        row.addWidget(edit,0,Qt.AlignVCenter); row.addWidget(delete,0,Qt.AlignVCenter); return card

    def open_add_form(self): self.project_form("add")
    def open_edit_form(self, project): self.project_form("edit",project)

    @staticmethod
    def _field(layout, title, widget):
        layout.addWidget(QLabel(title,objectName="FieldLabel")); layout.addWidget(widget)

    @staticmethod
    def _style_combo_popup(combo):
        """Use a fully controlled light list instead of Windows' inherited native popup."""
        view = QListView(combo)
        view.setObjectName("LightComboPopup")
        view.setFrameShape(QFrame.NoFrame)
        view.setAutoFillBackground(True)
        view.viewport().setAutoFillBackground(True)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        palette = view.palette()
        palette.setColor(QPalette.Window, QColor("#ffffff"))
        palette.setColor(QPalette.Base, QColor("#ffffff"))
        palette.setColor(QPalette.AlternateBase, QColor("#ffffff"))
        palette.setColor(QPalette.Text, QColor("#0f172a"))
        palette.setColor(QPalette.WindowText, QColor("#0f172a"))
        palette.setColor(QPalette.Highlight, QColor("#eaf1ff"))
        palette.setColor(QPalette.HighlightedText, QColor("#1d4ed8"))
        view.setPalette(palette)
        view.viewport().setPalette(palette)
        combo.setView(view)

        combo.setStyleSheet(combo.styleSheet() + """
            QComboBox { background:#ffffff; color:#0f172a; }
            QComboBox QAbstractItemView {
                background-color:#ffffff;
                color:#0f172a;
                border:1px solid #c5d2e5;
                outline:0;
                selection-background-color:#eaf1ff;
                selection-color:#1d4ed8;
            }
        """)
        view.setStyleSheet("""
            QListView#LightComboPopup,
            QListView#LightComboPopup QAbstractScrollArea,
            QListView#LightComboPopup QWidget,
            QListView#LightComboPopup::viewport {
                background-color:#ffffff;
                color:#0f172a;
            }
            QListView#LightComboPopup {
                border:1px solid #c5d2e5;
                outline:0;
                padding:0;
            }
            QListView#LightComboPopup::item {
                background-color:#ffffff;
                color:#0f172a;
                min-height:30px;
                padding:3px 10px;
                border:0;
            }
            QListView#LightComboPopup::item:hover,
            QListView#LightComboPopup::item:selected {
                background-color:#eaf1ff;
                color:#1d4ed8;
            }
        """)

    def project_form(self, mode="add", project=None):
        dialog = QDialog(self); dialog.setObjectName("ProjectDialog")
        dialog.setWindowTitle("Create Project" if mode == "add" else "Edit Project")
        dialog.setModal(True); dialog.setFixedSize(520,520); apply_light_surface(dialog); dialog.setStyleSheet(DIALOG_STYLE)
        form = QVBoxLayout(dialog); form.setContentsMargins(24,20,24,20); form.setSpacing(8)
        form.addWidget(QLabel("Create project" if mode == "add" else "Edit project",objectName="DialogTitle"))
        form.addWidget(QLabel("Define the inspection workflow and assign its production machine.",objectName="DialogSubtitle")); form.addSpacing(10)
        form.addWidget(QLabel("PROJECT DETAILS",objectName="SectionLabel"))
        name = QLineEdit(); name.setPlaceholderText("e.g., Cap seal inspection"); name.setClearButtonEnabled(True)
        self._field(form,"Project Name *",name)
        kind = QComboBox(); kind.addItems(["Anomaly","Classification","Anomaly + Classification","Dimension"])
        self._style_combo_popup(kind)
        self._field(form,"Inspection Type *",kind); form.addSpacing(9)
        form.addWidget(QLabel("MACHINE ASSIGNMENT",objectName="SectionLabel"))
        machine_box = QComboBox(); machine_box.addItem("Select machine",None)
        self._style_combo_popup(machine_box)
        try: machines = list(self.machine_db.get_all_machines() or [])
        except Exception: machines = []
        for m in machines: machine_box.addItem(self._machine_name(m),self._id(m))
        self._field(form,"Machine *",machine_box)
        helper = QLabel("",objectName="HelperText")
        if not machines:
            helper.setText("Create a machine before configuring an inspection project."); machine_box.setEnabled(False)
        form.addWidget(helper); form.addStretch(1)
        footer = QHBoxLayout(); footer.addStretch(1)
        cancel = QPushButton("Cancel",objectName="DialogCancel"); save = QPushButton("Save Project",objectName="DialogPrimary")
        save.setEnabled(bool(machines)); cancel.clicked.connect(dialog.reject); footer.addWidget(cancel); footer.addWidget(save); form.addLayout(footer)
        if mode == "edit" and project:
            name.setText(str(project.get("name") or ""))
            i = kind.findText(str(project.get("type") or "")); kind.setCurrentIndex(i if i >= 0 else 0)
            i = machine_box.findData(str(project.get("machine_id") or "")); machine_box.setCurrentIndex(i if i >= 0 else 0)

        def save_action():
            project_name, machine_id = name.text().strip(), machine_box.currentData()
            if not project_name:
                QMessageBox.warning(dialog,"Project name required","Enter a name for this project."); name.setFocus(); return
            if not machine_id:
                QMessageBox.warning(dialog,"Machine required","Select the machine used by this project."); return
            try:
                if mode == "add":
                    result = self.project_db.add_project(name=project_name,machine_id=machine_id,description="",type=kind.currentText())
                    if not result: raise RuntimeError("The database did not create the project.")
                else:
                    from utils.project_paths import get_project_folder
                    result = self.project_db.update_project(str(project["_id"]),name=project_name,machine_id=machine_id,
                        description="",type=kind.currentText(),folder_path=str(get_project_folder(project_name)))
                    if not result: raise RuntimeError("The database did not update the project.")
            except Exception as exc:
                QMessageBox.critical(dialog,"Project not saved",str(exc)); return
            dialog.accept(); self.refresh_list()
        save.clicked.connect(save_action); name.returnPressed.connect(save_action); name.setFocus(); dialog.exec_()

    def delete_project(self, project):
        box = QMessageBox(self); box.setIcon(QMessageBox.Warning); box.setWindowTitle("Delete Project")
        box.setText(f"Delete ‘{project.get('name','this project')}’?")
        box.setInformativeText("This removes the project record. Inspection data associated with it may no longer be accessible.")
        delete = box.addButton("Delete",QMessageBox.DestructiveRole); cancel = box.addButton("Cancel",QMessageBox.RejectRole)
        box.setDefaultButton(cancel); box.exec_()
        if box.clickedButton() is not delete: return
        try: success = self.project_db.delete_project(str(project["_id"]))
        except Exception as exc: self.show_error(f"Project could not be deleted.\n\n{exc}"); return
        if not success: self.show_error("The database did not delete the project."); return
        self.refresh_list()

    def show_error(self,message): QMessageBox.warning(self,"Projects",message)
    def show_success(self,message): QMessageBox.information(self,"Projects",message)
    def show_info(self,message): QMessageBox.information(self,"Projects",message)
