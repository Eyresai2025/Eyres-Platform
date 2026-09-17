"""EyRes.AI operations dashboard."""
from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from db import MachineDB, ProjectDB


def _project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def _media(name: str) -> Path | None:
    path = _project_root() / "Media" / name
    return path if path.is_file() else None


class AccountPopup(QtWidgets.QFrame):
    """Application-styled account menu; avoids the native Windows QMenu look."""

    def __init__(self, dashboard, parent=None):
        super().__init__(parent, QtCore.Qt.Popup | QtCore.Qt.FramelessWindowHint)
        self.dashboard = dashboard
        self.setObjectName("AccountPopup")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setFixedWidth(238)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(5)

        identity = QtWidgets.QHBoxLayout()
        avatar = QtWidgets.QLabel(dashboard.username[:1].upper())
        avatar.setObjectName("PopupAvatar")
        avatar.setAlignment(QtCore.Qt.AlignCenter)
        avatar.setFixedSize(34, 34)
        copy = QtWidgets.QVBoxLayout()
        copy.setSpacing(0)
        name = QtWidgets.QLabel(dashboard.username, objectName="PopupName")
        role = QtWidgets.QLabel(dashboard.role_label, objectName="PopupRole")
        copy.addWidget(name)
        copy.addWidget(role)
        identity.addWidget(avatar)
        identity.addSpacing(8)
        identity.addLayout(copy, 1)
        status = QtWidgets.QLabel("●  Online", objectName="PopupOnline")
        identity.addWidget(status)
        layout.addLayout(identity)

        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setObjectName("PopupSeparator")
        layout.addWidget(separator)
        if dashboard.can_manage_users:
            users = QtWidgets.QPushButton("User Management", objectName="AccountAction")
            users.clicked.connect(lambda: self._open_page(9))
            layout.addWidget(users)
        sign_out = QtWidgets.QPushButton("Sign out", objectName="SignOutAction")
        sign_out.clicked.connect(self._sign_out)
        layout.addWidget(sign_out)

    def _open_page(self, index: int) -> None:
        self.close()
        self.dashboard._navigate(index)

    def _sign_out(self) -> None:
        self.close()
        self.dashboard._request_logout()


class DashboardPage(QtWidgets.QWidget):
    """Compact operational overview with live counts and workflow shortcuts."""

    def __init__(self, username: str | None = None, role_label: str = "Operator",
                 can_manage_users: bool = False, parent=None):
        super().__init__(parent)
        self.username = username or "User"
        self.role_label = role_label
        self.can_manage_users = can_manage_users
        self.machine_db = MachineDB()
        self.project_db = ProjectDB()
        self.machine_count = 0
        self.project_count = 0
        self.database_online = False
        self._movies: list[QtGui.QMovie] = []
        self.setObjectName("OperationsDashboard")
        self.setProperty("eyresLightSurface", True)
        self._build_ui()
        self.refresh_counts()

    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QWidget#OperationsDashboard { background:#F5F7FB; }
            QWidget#OperationsDashboard QLabel { background:transparent; border:0; }
            QFrame#Hero {
                background:#FFFFFF;
                border:1px solid #DCE5F2; border-radius:16px;
            }
            QLabel#HeroTitle { color:#14213D; font-size:20px; font-weight:700; }
            QLabel#HeroSubtitle { color:#64748B; font-size:12px; }
            QPushButton#AvatarButton {
                background:#2868E8; color:#FFFFFF; border-radius:18px;
                border:0; font-size:15px; font-weight:700;
            }
            QPushButton#AvatarButton:hover { background:#1F57C8; }
            QFrame#AccountPopup { background:#FFFFFF; border:1px solid #D6E0EE; border-radius:12px; }
            QLabel#PopupAvatar { background:#2868E8; color:#FFFFFF; border-radius:17px;
                font-size:13px; font-weight:700; }
            QLabel#PopupName { color:#172033; font-size:11px; font-weight:700; }
            QLabel#PopupRole { color:#718096; font-size:9px; }
            QLabel#PopupOnline { color:#159A67; font-size:9px; font-weight:700; }
            QFrame#PopupSeparator { color:#E5EBF4; background:#E5EBF4; max-height:1px; }
            QPushButton#AccountAction, QPushButton#SignOutAction { background:transparent; border:0;
                border-radius:7px; min-height:31px; padding:0 9px; text-align:left;
                color:#334155; font-size:10px; font-weight:600; }
            QPushButton#AccountAction:hover { background:#EEF4FF; color:#2868E8; }
            QPushButton#SignOutAction { color:#C93450; }
            QPushButton#SignOutAction:hover { background:#FFF1F3; }
            QFrame#KpiCard {
                background:#FFFFFF; border:1px solid #DCE5F2; border-radius:14px;
            }
            QFrame#KpiCard:hover { border:1px solid #AFC8FA; background:#FCFDFF; }
            QLabel#KpiTitle { color:#64748B; font-size:11px; font-weight:600; }
            QLabel#KpiValue { color:#14213D; font-size:25px; font-weight:700; }
            QLabel#KpiMeta { color:#7A8AA0; font-size:10px; }
            QFrame#IconWell {
                background:#F3F7FF; border:1px solid #D7E4FA; border-radius:11px;
            }
            QFrame#Panel {
                background:#FFFFFF; border:1px solid #DCE5F2; border-radius:14px;
            }
            QLabel#PanelTitle { color:#14213D; font-size:15px; font-weight:700; }
            QLabel#PanelSubtitle { color:#718096; font-size:11px; }
            QFrame#WorkflowStep {
                background:#F8FAFD; border:1px solid #E5EBF4; border-radius:10px;
            }
            QFrame#NextAction { background:#EEF5FF; border:1px solid #CFE0FF; border-radius:10px; }
            QLabel#NextLabel { color:#2868E8; font-size:9px; font-weight:700; }
            QLabel#NextTitle { color:#14213D; font-size:13px; font-weight:700; }
            QFrame#DetailBlock { background:#F8FAFD; border:1px solid #E5EBF4; border-radius:10px; }
            QLabel#StepNumber {
                background:#E8F0FF; color:#2868E8; border-radius:14px;
                font-size:11px; font-weight:700;
            }
            QLabel#StatusGood {
                background:#E9F8F1; color:#13845A; border-radius:9px;
                padding:3px 8px; font-size:10px; font-weight:700;
            }
            QLabel#StatusWarn {
                background:#FFF6DD; color:#9B6A00; border-radius:9px;
                padding:3px 8px; font-size:10px; font-weight:700;
            }
            QPushButton#QuickAction {
                background:#FFFFFF; color:#2868E8; border:1px solid #B9CDF4;
                border-radius:9px; padding:7px 13px; font-weight:600;
            }
            QPushButton#QuickAction:hover { background:#EEF4FF; border-color:#2868E8; }
        """)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(26, 20, 26, 22)
        root.setSpacing(14)
        root.addWidget(self._hero())

        metrics = QtWidgets.QHBoxLayout()
        metrics.setSpacing(12)
        self.machine_value, machine_card = self._kpi_card(
            "MACHINES", "0", "Inspection cells", "dashboard_machine.gif", "MC"
        )
        self.project_value, project_card = self._kpi_card(
            "PROJECTS", "0", "Active projects", "dashboard_projects.gif", "PR"
        )
        self.database_value, database_card = self._kpi_card(
            "DATABASE", "CHECKING", "Application records", "dashboard_database.gif", "DB"
        )
        self.pipeline_value, pipeline_card = self._kpi_card(
            "WORKFLOW", "4", "Inspection stages", "dashboard_ai_workflow.gif", "AI"
        )
        for card in (machine_card, project_card, database_card, pipeline_card):
            metrics.addWidget(card, 1)
        root.addLayout(metrics)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(12)
        content.setAlignment(QtCore.Qt.AlignTop)
        workflow_panel = self._workflow_panel()
        health_panel = self._readiness_panel()
        workflow_panel.setMaximumHeight(620)
        health_panel.setMaximumHeight(620)
        content.addWidget(workflow_panel, 5)
        content.addWidget(health_panel, 3)
        root.addLayout(content, 1)

    def _hero(self) -> QtWidgets.QFrame:
        frame = QtWidgets.QFrame()
        frame.setObjectName("Hero")
        frame.setFixedHeight(76)
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(18, 10, 18, 10)

        copy = QtWidgets.QVBoxLayout()
        copy.setSpacing(3)
        title = QtWidgets.QLabel("Dashboard")
        title.setObjectName("HeroTitle")
        subtitle = QtWidgets.QLabel(
            "Inspection operations and system readiness"
        )
        subtitle.setObjectName("HeroSubtitle")
        copy.addWidget(title)
        copy.addWidget(subtitle)
        layout.addLayout(copy)
        layout.addStretch(1)

        self.account_button = QtWidgets.QPushButton(self.username[:1].upper())
        self.account_button.setObjectName("AvatarButton")
        self.account_button.setFixedSize(36, 36)
        self.account_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.account_button.setToolTip(f"{self.username}\n{self.role_label} · Online")
        self.account_button.setAccessibleName("Open account menu")
        self.account_button.clicked.connect(self._show_account_menu)
        layout.addWidget(self.account_button, 0, QtCore.Qt.AlignVCenter)
        return frame

    def _show_account_menu(self) -> None:
        self._account_popup = AccountPopup(self, self)
        self._account_popup.adjustSize()
        anchor = self.account_button.mapToGlobal(QtCore.QPoint(self.account_button.width(), self.account_button.height() + 6))
        x = anchor.x() - self._account_popup.width()
        screen = QtWidgets.QApplication.screenAt(anchor)
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + 8, min(x, area.right() - self._account_popup.width() - 8))
        self._account_popup.move(x, anchor.y())
        self._account_popup.show()

    def _request_logout(self) -> None:
        window = self.window()
        if hasattr(window, "_on_logout_clicked"):
            window._on_logout_clicked()

    def _kpi_card(
        self, title: str, value: str, meta: str, asset: str | None, fallback: str
    ) -> tuple[QtWidgets.QLabel, QtWidgets.QFrame]:
        card = QtWidgets.QFrame()
        card.setObjectName("KpiCard")
        card.setMinimumHeight(112)
        layout = QtWidgets.QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 14, 14)
        layout.setSpacing(12)

        text = QtWidgets.QVBoxLayout()
        text.setSpacing(2)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("KpiTitle")
        value_label = QtWidgets.QLabel(value)
        value_label.setObjectName("KpiValue")
        meta_label = QtWidgets.QLabel(meta)
        meta_label.setObjectName("KpiMeta")
        meta_label.setWordWrap(True)
        text.addWidget(title_label)
        text.addWidget(value_label)
        text.addWidget(meta_label)
        layout.addLayout(text, 1)

        well = QtWidgets.QFrame()
        well.setObjectName("IconWell")
        well.setFixedSize(64, 64)
        well_layout = QtWidgets.QVBoxLayout(well)
        well_layout.setContentsMargins(7, 7, 7, 7)
        icon = QtWidgets.QLabel()
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setStyleSheet("color:#2868E8;font-size:13px;font-weight:700;")
        path = _media(asset) if asset else None
        if path and path.suffix.lower() == ".gif":
            movie = QtGui.QMovie(str(path))
            movie.setScaledSize(QtCore.QSize(50, 50))
            icon.setMovie(movie)
            self._movies.append(movie)
            movie.start()
        elif path:
            pixmap = QtGui.QPixmap(str(path))
            if not pixmap.isNull():
                icon.setPixmap(
                    pixmap.scaled(
                        46, 46, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                    )
                )
            else:
                icon.setText(fallback)
        else:
            icon.setText(fallback)
        well_layout.addWidget(icon)
        layout.addWidget(well)
        return value_label, card

    def _workflow_panel(self) -> QtWidgets.QFrame:
        panel = self._panel(
            "Inspection workflow",
            "Four controlled steps from acquisition to a trained model.",
        )
        body = panel.layout()
        callout = QtWidgets.QFrame()
        callout.setObjectName("NextAction")
        callout_layout = QtWidgets.QHBoxLayout(callout)
        callout_layout.setContentsMargins(12, 8, 10, 8)
        callout_copy = QtWidgets.QVBoxLayout()
        callout_copy.setSpacing(0)
        callout_copy.addWidget(QtWidgets.QLabel("RECOMMENDED NEXT ACTION", objectName="NextLabel"))
        self.next_action = QtWidgets.QLabel("Configure your first machine", objectName="NextTitle")
        callout_copy.addWidget(self.next_action)
        recommended = QtWidgets.QPushButton("Open  →", objectName="QuickAction")
        recommended.clicked.connect(self._open_recommended)
        callout_layout.addLayout(callout_copy, 1)
        callout_layout.addWidget(recommended)
        body.addWidget(callout)
        steps = (
            ("1", "Capture images", "Build the source dataset", 3),
            ("2", "Annotate dataset", "Create verified labels", 4),
            ("3", "Augment data", "Generate controlled variations", 5),
            ("4", "Train model", "Configure and run training", 6),
        )
        for number, title, detail, index in steps:
            row = QtWidgets.QFrame()
            row.setObjectName("WorkflowStep")
            row.setFixedHeight(74)
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(11, 8, 9, 8)
            row_layout.setSpacing(10)
            badge = QtWidgets.QLabel(number)
            badge.setObjectName("StepNumber")
            badge.setAlignment(QtCore.Qt.AlignCenter)
            badge.setFixedSize(28, 28)
            labels = QtWidgets.QVBoxLayout()
            labels.setSpacing(0)
            heading = QtWidgets.QLabel(title)
            heading.setStyleSheet("color:#172033;font-weight:650;")
            description = QtWidgets.QLabel(detail)
            description.setStyleSheet("color:#7A8AA0;font-size:10px;")
            labels.addWidget(heading)
            labels.addWidget(description)
            open_button = QtWidgets.QPushButton("Open  →")
            open_button.setObjectName("QuickAction")
            open_button.setCursor(QtCore.Qt.PointingHandCursor)
            open_button.clicked.connect(lambda _checked=False, i=index: self._navigate(i))
            row_layout.addWidget(badge)
            row_layout.addLayout(labels, 1)
            row_layout.addWidget(open_button)
            body.addWidget(row)
        body.addStretch(1)
        return panel

    def _readiness_panel(self) -> QtWidgets.QFrame:
        panel = self._panel(
            "System health",
            "Current workstation and platform readiness.",
        )
        body = panel.layout()
        self.database_status = self._status_row(
            "Database service", "CHECKING", "Secure application records"
        )
        body.addWidget(self.database_status)
        runtime = self._runtime_details()
        body.addWidget(self._status_row("AI runtime", runtime["runtime_status"], runtime["runtime_detail"]))
        body.addWidget(self._status_row("Storage", "HEALTHY", runtime["disk"]))
        details = QtWidgets.QFrame()
        details.setObjectName("DetailBlock")
        grid = QtWidgets.QGridLayout(details)
        grid.setContentsMargins(11, 9, 11, 9)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(5)
        rows = (("Operating system", runtime["os"]), ("Python", runtime["python"]),
                ("PyTorch", runtime["torch"]), ("Graphics", runtime["gpu"]))
        for row, (key, value) in enumerate(rows):
            key_label = QtWidgets.QLabel(key)
            key_label.setStyleSheet("color:#718096;font-size:9px;")
            value_label = QtWidgets.QLabel(value)
            value_label.setStyleSheet("color:#172033;font-size:9px;font-weight:600;")
            value_label.setAlignment(QtCore.Qt.AlignRight)
            value_label.setToolTip(value)
            grid.addWidget(key_label, row, 0)
            grid.addWidget(value_label, row, 1)
        body.addWidget(details)

        summary_title = QtWidgets.QLabel("OPERATIONAL SUMMARY")
        summary_title.setObjectName("KpiTitle")
        body.addWidget(summary_title)
        summary = QtWidgets.QFrame()
        summary.setObjectName("DetailBlock")
        summary_grid = QtWidgets.QGridLayout(summary)
        summary_grid.setContentsMargins(11, 9, 11, 9)
        summary_grid.setVerticalSpacing(6)
        self.configuration_value = QtWidgets.QLabel("Checking…")
        self.configuration_value.setStyleSheet("color:#172033;font-size:9px;font-weight:600;")
        self.configuration_value.setAlignment(QtCore.Qt.AlignRight)
        self.last_refresh_value = QtWidgets.QLabel("—")
        self.last_refresh_value.setStyleSheet("color:#172033;font-size:9px;font-weight:600;")
        self.last_refresh_value.setAlignment(QtCore.Qt.AlignRight)
        for row_index, (key, value) in enumerate((
            ("Application", "Ready"),
            ("Configuration", self.configuration_value),
            ("Last refreshed", self.last_refresh_value),
        )):
            key_label = QtWidgets.QLabel(key)
            key_label.setStyleSheet("color:#718096;font-size:9px;")
            value_label = value if isinstance(value, QtWidgets.QLabel) else QtWidgets.QLabel(value)
            if not isinstance(value, QtWidgets.QLabel):
                value_label.setStyleSheet("color:#159A67;font-size:9px;font-weight:700;")
                value_label.setAlignment(QtCore.Qt.AlignRight)
            summary_grid.addWidget(key_label, row_index, 0)
            summary_grid.addWidget(value_label, row_index, 1)
        body.addWidget(summary)

        actions_title = QtWidgets.QLabel("QUICK ACCESS")
        actions_title.setObjectName("KpiTitle")
        body.addWidget(actions_title)
        actions = QtWidgets.QHBoxLayout()
        for text, index in (("Machines", 1), ("Projects", 2), ("Diagnostics", 11)):
            button = QtWidgets.QPushButton(text)
            button.setObjectName("QuickAction")
            button.clicked.connect(lambda _checked=False, i=index: self._navigate(i))
            actions.addWidget(button)
        body.addLayout(actions)
        body.addStretch(1)
        return panel

    @staticmethod
    def _panel(title: str, subtitle: str) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame()
        panel.setObjectName("Panel")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(16, 15, 16, 16)
        layout.setSpacing(9)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("PanelTitle")
        subtitle_label = QtWidgets.QLabel(subtitle)
        subtitle_label.setObjectName("PanelSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return panel

    @staticmethod
    def _status_row(title: str, status: str, detail: str) -> QtWidgets.QFrame:
        row = QtWidgets.QFrame()
        row.setObjectName("WorkflowStep")
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(11, 9, 11, 9)
        labels = QtWidgets.QVBoxLayout()
        labels.setSpacing(0)
        heading = QtWidgets.QLabel(title)
        heading.setStyleSheet("font-weight:600;color:#172033;")
        description = QtWidgets.QLabel(detail)
        description.setStyleSheet("color:#7A8AA0;font-size:10px;")
        labels.addWidget(heading)
        labels.addWidget(description)
        badge = QtWidgets.QLabel(status)
        badge.setObjectName(
            "StatusGood" if status in {"READY", "ACTIVE", "ONLINE", "CUDA", "HEALTHY"}
            else "StatusWarn"
        )
        badge.setAlignment(QtCore.Qt.AlignCenter)
        layout.addLayout(labels, 1)
        layout.addWidget(badge)
        row.status_badge = badge
        return row

    @staticmethod
    def _runtime_details() -> dict[str, str]:
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
            free_gb = shutil.disk_usage(_project_root()).free / (1024 ** 3)
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

    def _open_recommended(self) -> None:
        self._navigate(1 if self.machine_count == 0 else 2 if self.project_count == 0 else 3)

    def _navigate(self, index: int) -> None:
        window = self.window()
        if hasattr(window, "switch_tool"):
            window.switch_tool(index)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        for movie in self._movies:
            movie.start()

    def hideEvent(self, event) -> None:
        for movie in self._movies:
            movie.setPaused(True)
        super().hideEvent(event)

    def refresh_counts(self) -> None:
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

        self.machine_value.setText(str(self.machine_count))
        self.project_value.setText(str(self.project_count))
        if hasattr(self, "configuration_value"):
            self.configuration_value.setText(
                f"{self.machine_count} machine{'s' if self.machine_count != 1 else ''} · "
                f"{self.project_count} project{'s' if self.project_count != 1 else ''}"
            )
        if hasattr(self, "last_refresh_value"):
            self.last_refresh_value.setText(QtCore.QTime.currentTime().toString("hh:mm:ss AP"))
        state = "ONLINE" if self.database_online else "ATTENTION"
        self.database_value.setText(state)
        self.database_value.setStyleSheet(
            "color:#159A67;" if self.database_online else "color:#D99000;"
        )
        badge = getattr(self.database_status, "status_badge", None)
        if badge is not None:
            badge.setText(state)
            badge.setObjectName("StatusGood" if self.database_online else "StatusWarn")
            badge.style().unpolish(badge)
            badge.style().polish(badge)
        if self.machine_count == 0:
            self.next_action.setText("Configure your first machine")
        elif self.project_count == 0:
            self.next_action.setText("Create an inspection project")
        else:
            self.next_action.setText("Continue with image capture")
