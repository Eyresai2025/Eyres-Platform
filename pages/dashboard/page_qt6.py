"""PyQt6 Dashboard for the EYRES AI Inspection Platform.

This is the Phase-2 shell dashboard. It keeps the current MachineDB / ProjectDB
backend and runtime-health checks, while using the approved responsive Qt6 UI.
"""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QLabel, QPushButton, QFrame, QWidget

from db import MachineDB, ProjectDB
from ui.qt6.animations import fade_in
from ui.qt6.widgets import AnimatedCard, IconBadge


class ShimmerFrame(QFrame):
    """Very subtle low-frequency shimmer used only for the recommended action."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._phase = 0.0
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(4200)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutSine)
        self._anim.valueChanged.connect(self._phase_changed)
        self._anim.start()

    def _phase_changed(self, value):
        self._phase = float(value)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        # The first 65% of each cycle is visually still.
        if self._phase < 0.65:
            return
        local = (self._phase - 0.65) / 0.35
        width = max(70.0, self.width() * 0.16)
        x = -width + local * (self.width() + 2 * width)
        painter = QPainter(self)
        gradient = QLinearGradient(x, 0, x + width, 0)
        gradient.setColorAt(0.0, QColor(255, 255, 255, 0))
        gradient.setColorAt(0.5, QColor(255, 255, 255, 115))
        gradient.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(self.rect(), gradient)
        painter.end()


class DashboardPageQt6(QWidget):
    navigate_requested = pyqtSignal(str)
    toast_requested = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine_db = MachineDB()
        self.project_db = ProjectDB()
        self.machine_count = 0
        self.project_count = 0
        self.database_online = False
        self._metric_animations: list[QtCore.QVariantAnimation] = []
        self._animated_once = False
        self._narrow = None
        self.setObjectName("DashboardPageQt6")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build()
        self._apply_style()
        self.refresh_all(animate=False)

    # ------------------------------------------------------------------
    # BUILD
    # ------------------------------------------------------------------
    def _build(self):
        self.root = QtWidgets.QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(17)

        self.metrics_grid = QtWidgets.QGridLayout()
        self.metrics_grid.setHorizontalSpacing(15)
        self.metrics_grid.setVerticalSpacing(15)
        self.root.addLayout(self.metrics_grid)

        self.machine_value, self.machine_card = self._metric_card(
            "MACHINES", "0", "Inspection cell", "machine"
        )
        self.project_value, self.project_card = self._metric_card(
            "PROJECTS", "0", "Active project", "project"
        )
        self.database_value, self.database_card = self._metric_card(
            "DATABASE", "CHECKING", "Application records", "database", success=True
        )
        self.workflow_value, self.workflow_card = self._metric_card(
            "WORKFLOW", "4", "Inspection stages", "workflow"
        )
        self.metric_cards = [
            self.machine_card, self.project_card, self.database_card, self.workflow_card
        ]

        self.content_grid = QtWidgets.QGridLayout()
        self.content_grid.setHorizontalSpacing(17)
        self.content_grid.setVerticalSpacing(17)
        self.root.addLayout(self.content_grid, 1)

        self.workflow_panel = self._build_workflow_panel()
        self.health_panel = self._build_health_panel()

        self.root.addStretch(1)
        self._reflow(force=True)

    def _metric_card(self, label: str, value: str, meta: str, icon_name: str, success: bool = False):
        card = AnimatedCard()
        card.setObjectName("MetricCard")
        card.setMinimumHeight(116)
        layout = QtWidgets.QHBoxLayout(card)
        layout.setContentsMargins(17, 16, 16, 16)
        layout.setSpacing(12)

        copy = QtWidgets.QVBoxLayout()
        copy.setSpacing(2)
        title = QLabel(label)
        title.setObjectName("MetricLabel")
        value_label = QLabel(value)
        value_label.setObjectName("MetricValueSuccess" if success else "MetricValue")
        meta_label = QLabel(meta)
        meta_label.setObjectName("MetricMeta")
        copy.addWidget(title)
        copy.addSpacing(4)
        copy.addWidget(value_label)
        copy.addWidget(meta_label)
        copy.addStretch(1)
        layout.addLayout(copy, 1)

        if success:
            badge = IconBadge(icon_name, "#07965D", "#EAF9F2")
        else:
            badge = IconBadge(icon_name, "#2868E8", "#EEF4FF")
        layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        return value_label, card

    def _build_workflow_panel(self) -> QFrame:
        panel = AnimatedCard()
        panel.setObjectName("Panel")
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(objectName="PanelHeader")
        hh = QtWidgets.QHBoxLayout(header)
        hh.setContentsMargins(18, 15, 16, 13)
        copy = QtWidgets.QVBoxLayout(); copy.setSpacing(3)
        title = QLabel("Inspection workflow", objectName="PanelTitle")
        sub = QLabel("Four controlled steps from acquisition to a trained model.", objectName="PanelSubtitle")
        copy.addWidget(title); copy.addWidget(sub)
        hh.addLayout(copy, 1)
        view = QPushButton("View status", objectName="OutlineButton")
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        view.clicked.connect(lambda: self.toast_requested.emit(
            "Workflow status", "The controlled inspection workflow is ready."
        ))
        hh.addWidget(view)
        outer.addWidget(header)

        body = QWidget()
        bl = QtWidgets.QVBoxLayout(body)
        bl.setContentsMargins(13, 12, 13, 13)
        bl.setSpacing(8)

        self.recommended = ShimmerFrame()
        self.recommended.setObjectName("Recommended")
        rl = QtWidgets.QHBoxLayout(self.recommended)
        rl.setContentsMargins(13, 10, 10, 10)
        rc = QtWidgets.QVBoxLayout(); rc.setSpacing(2)
        kick = QLabel("RECOMMENDED NEXT ACTION", objectName="RecommendedKicker")
        self.next_action = QLabel("Continue with image capture", objectName="RecommendedTitle")
        rc.addWidget(kick); rc.addWidget(self.next_action)
        rl.addLayout(rc, 1)
        open_btn = QPushButton("Open  →", objectName="OutlineButton")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.clicked.connect(self._open_recommended)
        rl.addWidget(open_btn)
        bl.addWidget(self.recommended)

        rows = (
            ("1", "Capture images", "Build the source dataset", "capture"),
            ("2", "Annotate dataset", "Create verified labels", "annotation"),
            ("3", "Augment data", "Generate controlled variations", "augmentation"),
            ("4", "Train model", "Configure and run training", "training"),
        )
        self.workflow_rows = []
        for num, heading, detail, page_key in rows:
            row = QFrame(objectName="WorkflowRow")
            row.setMinimumHeight(64)
            l = QtWidgets.QHBoxLayout(row)
            l.setContentsMargins(12, 8, 10, 8)
            l.setSpacing(10)
            badge = QLabel(num, objectName="StepBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedSize(27, 27)
            text = QtWidgets.QVBoxLayout(); text.setSpacing(1)
            h = QLabel(heading, objectName="WorkflowTitle")
            d = QLabel(detail, objectName="WorkflowSub")
            text.addWidget(h); text.addWidget(d)
            btn = QPushButton("Open  →", objectName="OutlineButton")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked=False, key=page_key: self.navigate_requested.emit(key))
            l.addWidget(badge)
            l.addLayout(text, 1)
            l.addWidget(btn)
            bl.addWidget(row)
            self.workflow_rows.append(row)
        bl.addStretch(1)
        outer.addWidget(body, 1)
        return panel

    def _build_health_panel(self) -> QFrame:
        panel = AnimatedCard()
        panel.setObjectName("Panel")
        outer = QtWidgets.QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(objectName="PanelHeader")
        hh = QtWidgets.QVBoxLayout(header)
        hh.setContentsMargins(18, 15, 18, 13)
        hh.setSpacing(3)
        hh.addWidget(QLabel("System health", objectName="PanelTitle"))
        hh.addWidget(QLabel("Current workstation and platform readiness.", objectName="PanelSubtitle"))
        outer.addWidget(header)

        body = QWidget()
        bl = QtWidgets.QVBoxLayout(body)
        bl.setContentsMargins(13, 12, 13, 13)
        bl.setSpacing(8)

        self.database_status_badge, row = self._health_row(
            "Database service", "Secure application records", "CHECKING"
        )
        bl.addWidget(row)

        runtime = self._runtime_details()
        self.runtime_badge, row = self._health_row(
            "AI runtime", runtime["runtime_detail"], runtime["runtime_status"]
        )
        bl.addWidget(row)
        self.storage_badge, row = self._health_row("Storage", runtime["disk"], "HEALTHY")
        bl.addWidget(row)

        details = QFrame(objectName="SystemBox")
        grid = QtWidgets.QGridLayout(details)
        grid.setContentsMargins(11, 9, 11, 9)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(5)
        self.runtime_detail_labels = {}
        for i, (key, value) in enumerate((
            ("Operating system", runtime["os"]),
            ("Python", runtime["python"]),
            ("PyTorch", runtime["torch"]),
            ("Graphics", runtime["gpu"]),
        )):
            kl = QLabel(key, objectName="SystemKey")
            vl = QLabel(value, objectName="SystemValue")
            vl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            vl.setToolTip(value)
            grid.addWidget(kl, i, 0)
            grid.addWidget(vl, i, 1)
            self.runtime_detail_labels[key] = vl
        bl.addWidget(details)

        self.summary = QFrame(objectName="SystemBox")
        sg = QtWidgets.QGridLayout(self.summary)
        sg.setContentsMargins(11, 9, 11, 9)
        sg.setVerticalSpacing(5)
        self.configuration_value = QLabel("Checking…", objectName="SystemValue")
        self.configuration_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.last_refresh_value = QLabel("—", objectName="SystemValue")
        self.last_refresh_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        for i, (k, v) in enumerate((
            ("Application", "Ready"),
            ("Configuration", self.configuration_value),
            ("Last refreshed", self.last_refresh_value),
        )):
            key_label = QLabel(k, objectName="SystemKey")
            value_label = v if isinstance(v, QLabel) else QLabel(v, objectName="SystemValueGood")
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight)
            sg.addWidget(key_label, i, 0)
            sg.addWidget(value_label, i, 1)
        bl.addWidget(self.summary)

        quick_label = QLabel("QUICK ACCESS", objectName="QuickLabel")
        bl.addWidget(quick_label)
        quick = QtWidgets.QHBoxLayout(); quick.setSpacing(8)
        for text, key in (("Machines", "machines"), ("Projects", "projects"), ("Diagnostics", "diagnostics")):
            b = QPushButton(text, objectName="OutlineButton")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _checked=False, page_key=key: self.navigate_requested.emit(page_key))
            quick.addWidget(b)
        bl.addLayout(quick)
        bl.addStretch(1)
        outer.addWidget(body, 1)
        return panel

    def _health_row(self, title: str, detail: str, status: str):
        row = QFrame(objectName="HealthRow")
        l = QtWidgets.QHBoxLayout(row)
        l.setContentsMargins(11, 9, 11, 9)
        copy = QtWidgets.QVBoxLayout(); copy.setSpacing(1)
        copy.addWidget(QLabel(title, objectName="HealthTitle"))
        copy.addWidget(QLabel(detail, objectName="HealthSub"))
        badge = QLabel(status, objectName="HealthStatus")
        badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        l.addLayout(copy, 1); l.addWidget(badge)
        return badge, row

    # ------------------------------------------------------------------
    # DATA
    # ------------------------------------------------------------------
    @staticmethod
    def _project_root() -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)
        return Path(__file__).resolve().parents[2]

    @classmethod
    def _runtime_details(cls) -> dict[str, str]:
        torch = sys.modules.get("torch")
        torch_version = getattr(torch, "__version__", "Not loaded") if torch else "Not loaded"
        cuda_available = False
        cuda_version = ""
        gpu = "CPU mode"
        if torch:
            try:
                cuda_available = bool(torch.cuda.is_available())
                cuda_version = str(getattr(torch.version, "cuda", "") or "")
                if cuda_available:
                    gpu = torch.cuda.get_device_name(0)
            except Exception:
                pass
        try:
            free_gb = shutil.disk_usage(cls._project_root()).free / (1024 ** 3)
            disk = f"{free_gb:.1f} GB free"
        except OSError:
            disk = "Available"
        return {
            "runtime_status": "CUDA" if cuda_available else "CPU",
            "runtime_detail": f"CUDA {cuda_version}" if cuda_available else "Hardware acceleration unavailable",
            "disk": disk,
            "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "torch": torch_version,
            "gpu": gpu,
        }

    def refresh_all(self, animate: bool = True):
        self.database_online = True
        try:
            self.machine_count = len(self.machine_db.get_all_machines())
        except Exception:
            self.machine_count = 0
            self.database_online = False
        try:
            self.project_count = len(self.project_db.get_all_projects())
        except Exception:
            self.project_count = 0
            self.database_online = False

        if animate:
            self._animate_number(self.machine_value, self.machine_count)
            self._animate_number(self.project_value, self.project_count)
            self._animate_number(self.workflow_value, 4)
        else:
            self.machine_value.setText(str(self.machine_count))
            self.project_value.setText(str(self.project_count))
            self.workflow_value.setText("4")

        state = "ONLINE" if self.database_online else "ATTENTION"
        self.database_value.setText(state)
        self.database_value.setProperty("attention", not self.database_online)
        self.database_status_badge.setText(state)
        self.database_status_badge.setProperty("attention", not self.database_online)
        for w in (self.database_value, self.database_status_badge):
            w.style().unpolish(w); w.style().polish(w); w.update()

        self.configuration_value.setText(
            f"{self.machine_count} machine{'s' if self.machine_count != 1 else ''} · "
            f"{self.project_count} project{'s' if self.project_count != 1 else ''}"
        )
        self.last_refresh_value.setText(QtCore.QTime.currentTime().toString("hh:mm:ss AP"))

        if self.machine_count == 0:
            self.next_action.setText("Configure your first machine")
        elif self.project_count == 0:
            self.next_action.setText("Create an inspection project")
        else:
            self.next_action.setText("Continue with image capture")

        runtime = self._runtime_details()
        self.runtime_badge.setText(runtime["runtime_status"])
        self.storage_badge.setText("HEALTHY")
        for key, map_key in (("Operating system", "os"), ("Python", "python"), ("PyTorch", "torch"), ("Graphics", "gpu")):
            label = self.runtime_detail_labels.get(key)
            if label:
                label.setText(runtime[map_key]); label.setToolTip(runtime[map_key])

    def _animate_number(self, label: QLabel, target: int):
        anim = QtCore.QVariantAnimation(self)
        anim.setDuration(620)
        anim.setStartValue(0)
        anim.setEndValue(int(target))
        anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda value, target_label=label: target_label.setText(str(int(value))))
        self._metric_animations.append(anim)
        anim.finished.connect(lambda a=anim: self._metric_animations.remove(a) if a in self._metric_animations else None)
        anim.start()

    def _open_recommended(self):
        if self.machine_count == 0:
            self.navigate_requested.emit("machines")
        elif self.project_count == 0:
            self.navigate_requested.emit("projects")
        else:
            self.navigate_requested.emit("capture")

    # ------------------------------------------------------------------
    # RESPONSIVE / ANIMATION
    # ------------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        if not self._animated_once:
            self._animated_once = True
            for i, card in enumerate(self.metric_cards):
                QtCore.QTimer.singleShot(45 + i * 70, lambda w=card: fade_in(w, 260))
            QtCore.QTimer.singleShot(330, lambda: fade_in(self.workflow_panel, 300))
            QtCore.QTimer.singleShot(400, lambda: fade_in(self.health_panel, 300))
            QtCore.QTimer.singleShot(170, lambda: self.refresh_all(animate=True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, force: bool = False):
        narrow = self.width() < 1080
        if not force and narrow == self._narrow:
            return
        self._narrow = narrow

        while self.metrics_grid.count():
            item = self.metrics_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(self)
        if narrow:
            positions = ((0,0),(0,1),(1,0),(1,1))
        else:
            positions = ((0,0),(0,1),(0,2),(0,3))
        for card, (r,c) in zip(self.metric_cards, positions):
            self.metrics_grid.addWidget(card, r, c)
        for c in range(4):
            self.metrics_grid.setColumnStretch(c, 1 if (not narrow or c < 2) else 0)

        for widget in (self.workflow_panel, self.health_panel):
            self.content_grid.removeWidget(widget)
        if narrow:
            self.content_grid.addWidget(self.workflow_panel, 0, 0)
            self.content_grid.addWidget(self.health_panel, 1, 0)
            self.content_grid.setColumnStretch(0, 1)
            self.content_grid.setColumnStretch(1, 0)
        else:
            self.content_grid.addWidget(self.workflow_panel, 0, 0)
            self.content_grid.addWidget(self.health_panel, 0, 1)
            self.content_grid.setColumnStretch(0, 17)
            self.content_grid.setColumnStretch(1, 9)

    # ------------------------------------------------------------------
    # STYLE
    # ------------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#DashboardPageQt6 { background:transparent; }
        QWidget#DashboardPageQt6 QLabel { background:transparent; border:0; }

        QFrame#MetricCard, QFrame#Panel {
            background:#FFFFFF; border:1px solid #C9D5E5; border-radius:17px;
        }
        QFrame#MetricCard:hover { border-color:#CAD9ED; }
        QLabel#MetricLabel { color:#64748C; font-size:10px; font-weight:800; letter-spacing:.7px; }
        QLabel#MetricValue { color:#101A2D; font-size:29px; font-weight:800; }
        QLabel#MetricValueSuccess { color:#07965D; font-size:22px; font-weight:800; }
        QLabel#MetricValueSuccess[attention="true"] { color:#D78A00; }
        QLabel#MetricMeta { color:#6F8097; font-size:10px; }

        QFrame#PanelHeader { background:#FFFFFF; border:0; border-bottom:1px solid #DDE5EF; }
        QLabel#PanelTitle { color:#101A2D; font-size:15px; font-weight:800; }
        QLabel#PanelSubtitle { color:#65758E; font-size:10px; }

        QPushButton#OutlineButton {
            min-height:36px; padding:0 13px; background:#FFFFFF; color:#2868E8;
            border:1px solid #C9D8ED; border-radius:10px; font-size:10px; font-weight:750;
        }
        QPushButton#OutlineButton:hover { background:#F2F6FF; border-color:#AFC7EE; }
        QPushButton#OutlineButton:pressed { background:#E8F0FF; }

        QFrame#Recommended {
            background:#EFF4FF; border:1px solid #BCD2FF; border-radius:12px;
        }
        QLabel#RecommendedKicker { color:#2868E8; font-size:9px; font-weight:800; letter-spacing:.5px; }
        QLabel#RecommendedTitle { color:#101A2D; font-size:12px; font-weight:780; }

        QFrame#WorkflowRow, QFrame#HealthRow {
            background:#F8FAFD; border:1px solid #E2E8F1; border-radius:11px;
        }
        QFrame#WorkflowRow:hover, QFrame#HealthRow:hover {
            background:#FFFFFF; border-color:#C9D8EC;
        }
        QLabel#StepBadge {
            background:#EAF1FF; color:#2868E8; border-radius:8px; font-size:10px; font-weight:800;
        }
        QLabel#WorkflowTitle, QLabel#HealthTitle { color:#172033; font-size:12px; font-weight:760; }
        QLabel#WorkflowSub, QLabel#HealthSub { color:#8391A5; font-size:9px; }
        QLabel#HealthStatus { color:#07965D; font-size:9px; font-weight:850; }
        QLabel#HealthStatus[attention="true"] { color:#D78A00; }

        QFrame#SystemBox { background:#F6F8FC; border:1px solid #CCD8E7; border-radius:11px; }
        QLabel#SystemKey { color:#6D7B90; font-size:9px; }
        QLabel#SystemValue { color:#26354A; font-size:9px; font-weight:750; }
        QLabel#SystemValueGood { color:#07965D; font-size:9px; font-weight:800; }
        QLabel#QuickLabel { color:#6E7C91; font-size:9px; font-weight:800; letter-spacing:.5px; }
        """)


DashboardPage = DashboardPageQt6
