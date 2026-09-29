"""EYRES AI - PyQt6 Model Training page.

Final design:
- Current Project / Training Type / Dataset / Device context strip
- Icon-based Training Workflow rail
- Model Type cards
- Dataset
- Model Weights
- Hyperparameters
- Review & Run
- Detectron2 segmentation and detection configuration
- Run Dashboard

The training command generation logic is preserved from the existing
training_tool.py while the complete GUI is native PyQt6.
"""
from __future__ import annotations

import http.server
import json
import mimetypes
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import textwrap
import threading
import urllib.parse
from datetime import datetime
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtProperty, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from db import ProjectDB
except ImportError:  # pragma: no cover
    try:
        from src.db import ProjectDB
    except ImportError:
        from src.database.db import ProjectDB


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _project_root_path() -> Path:
    return Path(__file__).resolve().parents[2]


def _asset(name: str) -> str:
    return str(_project_root_path() / "ui" / "assets" / "training_icons" / name)


def fwd(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def _project_id(project: dict) -> str:
    return str(project.get("_id") or project.get("id") or "")


def _safe_name(value: str) -> str:
    value = "".join(
        c if c.isalnum() or c in "-_ " else "_"
        for c in str(value or "Project")
    )
    return value.strip().replace(" ", "_") or "Project"


def require_yaml(parent: QWidget | None = None):
    try:
        import yaml
        return yaml
    except Exception:
        answer = QMessageBox.question(
            parent,
            "Missing dependency",
            "PyYAML is required but is not installed.\n\nInstall it now using pip?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            raise ImportError("PyYAML is not available.")

        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml"])
            import yaml
            QMessageBox.information(parent, "Installed", "PyYAML was installed successfully.")
            return yaml
        except Exception as exc:
            QMessageBox.critical(
                parent,
                "Install failed",
                f"Could not install PyYAML.\n\n{exc}",
            )
            raise ImportError("PyYAML is not available.") from exc


def _candidate_weight_dirs() -> list[Path]:
    root = _project_root_path()
    cwd = Path.cwd()
    return [
        root,
        root / "models",
        root / "Models",
        root / "weights",
        root / "Weights",
        root / "assets",
        root / "ui" / "assets",
        cwd,
        cwd / "models",
        cwd / "weights",
        cwd / "assets",
    ]


def _find_weight(*names: str) -> str:
    for folder in _candidate_weight_dirs():
        for name in names:
            path = folder / name
            if path.is_file():
                return fwd(path)
    return ""


# -----------------------------------------------------------------------------
# Existing training dashboard server, migrated to the new page.
# -----------------------------------------------------------------------------
class _DashHandler(http.server.SimpleHTTPRequestHandler):
    base_dir: Path = Path(".")

    def _send_json(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)

        if url.path == "/index":
            base = self.base_dir
            runs = []
            if base.is_dir():
                for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                    if p.is_dir() and p.name.lower().startswith("train"):
                        files = []
                        for fp in p.rglob("*"):
                            if fp.is_file():
                                files.append(fp.relative_to(base).as_posix())
                        try:
                            mtime = p.stat().st_mtime
                        except Exception:
                            mtime = 0.0
                        runs.append({"name": p.name, "files": files, "mtime": mtime})
            return self._send_json({"base": str(base), "runs": runs})

        if url.path == "/file":
            query = urllib.parse.parse_qs(url.query)
            rel = (query.get("path", [""])[0]).replace("\\", "/").strip("/")
            fp = self.base_dir / rel
            if not fp.is_file():
                return self._send_json({"error": "not found"}, 404)
            ctype, _ = mimetypes.guess_type(fp.name)
            if not ctype:
                ctype = "application/octet-stream"
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if url.path == "/ui":
            root = _project_root_path()
            candidates = [
                root / "dashboard.html",
                root.parent / "dashboard.html",
                Path.cwd() / "dashboard.html",
            ]
            for p in candidates:
                if p.is_file():
                    data = p.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            return self._send_json({"error": "dashboard.html not found"}, 404)

        return super().do_GET()


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_dashboard_server(base_dir: str | Path):
    port = _pick_free_port()
    _DashHandler.base_dir = Path(base_dir)
    httpd = socketserver.TCPServer(("127.0.0.1", port), _DashHandler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}", httpd


# -----------------------------------------------------------------------------
# Controlled combo boxes: white popup, compact row height, no native Windows
# oversize dropdown behavior.
# -----------------------------------------------------------------------------
class ControlledComboBox(QComboBox):
    def __init__(self, parent=None, object_name="FieldCombo"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setMinimumHeight(35)
        self.setMaxVisibleItems(8)

        view = QListView(self)
        view.setObjectName("ControlledComboView")
        view.setUniformItemSizes(True)
        view.setSpacing(1)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setView(view)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(
            QtGui.QColor("#2868E8" if self.hasFocus() else "#526A86")
        )
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)

        cx = self.width() - 14.0
        cy = self.height() / 2.0 - 1.0
        painter.drawLine(
            QtCore.QPointF(cx - 4.0, cy - 2.0),
            QtCore.QPointF(cx, cy + 2.0),
        )
        painter.drawLine(
            QtCore.QPointF(cx, cy + 2.0),
            QtCore.QPointF(cx + 4.0, cy - 2.0),
        )
        painter.end()

    def showPopup(self):
        self.view().setMinimumWidth(self.width())
        self.view().setMaximumWidth(self.width())
        super().showPopup()
        QtCore.QTimer.singleShot(0, self._position_popup)

    def _position_popup(self):
        try:
            popup = self.view().window()
            visible_rows = min(max(1, self.count()), self.maxVisibleItems())
            row_h = 31
            popup.move(
                self.mapToGlobal(QtCore.QPoint(0, self.height() + 4))
            )
            popup.resize(
                max(150, self.width()),
                visible_rows * row_h + 12,
            )
        except Exception:
            pass


class ProjectComboBox(ControlledComboBox):
    def __init__(self, parent=None):
        super().__init__(parent, object_name="ProjectSelector")


# -----------------------------------------------------------------------------
# Animated rail icon button, matching the Augmentation and Annotation pages.
# -----------------------------------------------------------------------------
class RailNavButton(QPushButton):
    """Training rail button using the same padded icon motion as the shell."""

    def __init__(self, key: str, text: str, icon_name: str, parent=None):
        super().__init__(text, parent)
        self.key = key
        self._motion = 0.0
        self._hovered = False
        self._normal_icon = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._active_icon = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        self.setObjectName("TrainingRailButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(49)
        self.setIconSize(QtCore.QSize(34, 34))

        self._anim = QtCore.QPropertyAnimation(self, b"iconMotion", self)
        self._anim.setDuration(195)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        self.toggled.connect(lambda _checked: self._refresh_icon())
        self._refresh_icon()

    def get_motion(self):
        return self._motion

    def set_motion(self, value):
        self._motion = max(0.0, min(1.0, float(value)))
        self._refresh_icon()

    iconMotion = pyqtProperty(float, fget=get_motion, fset=set_motion)

    def _animate(self, target):
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(float(target))
        self._anim.start()

    def _refresh_icon(self):
        icon = self._active_icon if (self.isChecked() or self._hovered) else self._normal_icon
        base = icon.pixmap(QtCore.QSize(23, 23))

        canvas = QtGui.QPixmap(36, 36)
        canvas.fill(Qt.GlobalColor.transparent)
        p = QtGui.QPainter(canvas)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(18.0, 18.0 - self._motion)
        p.rotate(-5.0 * self._motion)
        scale = 1.0 + 0.055 * self._motion
        p.scale(scale, scale)
        p.drawPixmap(
            QtCore.QRectF(-11.5, -11.5, 23.0, 23.0),
            base,
            QtCore.QRectF(base.rect()),
        )
        p.end()
        self.setIcon(QtGui.QIcon(canvas))

    def enterEvent(self, event):
        self._hovered = True
        self._refresh_icon()
        self._animate(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._animate(0.0)
        self._refresh_icon()
        super().leaveEvent(event)



class TiltIconLabel(QLabel):
    def __init__(self, normal: str, active: str, parent=None):
        super().__init__(parent)
        self._normal_icon = QtGui.QIcon(normal)
        self._active_icon = QtGui.QIcon(active)
        self._active = False
        self._motion = 0.0
        self.setFixedSize(42, 42)

    def set_active(self, active: bool):
        self._active = bool(active)
        self.update()

    def set_motion(self, value: float):
        self._motion = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        color = QtGui.QColor("#2868E8" if self._active else "#EEF3FA")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect(), 10, 10)

        icon = self._active_icon if self._active else self._normal_icon
        pix = icon.pixmap(QtCore.QSize(24, 24))

        painter.save()
        painter.translate(
            self.width() / 2.0,
            self.height() / 2.0 - self._motion,
        )
        painter.rotate(-5.0 * self._motion)
        scale = 1.0 + 0.06 * self._motion
        painter.scale(scale, scale)

        if self._active:
            # Active card background is blue; paint icon white.
            image = pix.toImage().convertToFormat(QtGui.QImage.Format.Format_ARGB32)
            for y in range(image.height()):
                for x in range(image.width()):
                    c = image.pixelColor(x, y)
                    if c.alpha() > 0:
                        c.setRed(255)
                        c.setGreen(255)
                        c.setBlue(255)
                        image.setPixelColor(x, y, c)
            pix = QtGui.QPixmap.fromImage(image)

        painter.drawPixmap(
            QtCore.QRectF(-12, -12, 24, 24),
            pix,
            QtCore.QRectF(pix.rect()),
        )
        painter.restore()
        painter.end()


class ModelCard(QFrame):
    clicked = pyqtSignal(str)

    def __init__(
        self,
        mode: str,
        title: str,
        task: str,
        description: str,
        framework: str,
        chips: list[str],
        icon_name: str,
        parent=None,
    ):
        super().__init__(parent)
        self.mode = mode
        self._selected = False
        self._motion = 0.0

        self.setObjectName("ModelCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(140)

        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setDuration(180)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._on_anim_value)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(10)

        self.icon = TiltIconLabel(
            _asset(f"{icon_name}.svg"),
            _asset(f"{icon_name}_active.svg"),
        )
        head.addWidget(self.icon)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.title_label = QLabel(title, objectName="ModelCardTitle")
        self.task_label = QLabel(task, objectName="ModelCardTask")
        copy.addWidget(self.title_label)
        copy.addWidget(self.task_label)
        head.addLayout(copy, 1)

        self.check = QLabel("✓", objectName="ModelSelectedMark")
        self.check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.check.setFixedSize(23, 23)
        self.check.hide()
        head.addWidget(self.check, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(head)

        desc = QLabel(description, objectName="ModelCardDescription")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(5)
        for chip in chips:
            chip_row.addWidget(QLabel(chip, objectName="ModelChip"))
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        self.framework = framework
        self.task = task

    def _on_anim_value(self, value):
        self._motion = float(value)
        self.icon.set_motion(self._motion)

    def enterEvent(self, event):
        self._anim.setDirection(QtCore.QAbstractAnimation.Direction.Forward)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim.setDirection(QtCore.QAbstractAnimation.Direction.Backward)
        self._anim.start()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mode)
        super().mouseReleaseEvent(event)

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        self.icon.set_active(self._selected)
        self.check.setVisible(self._selected)

        for widget in (
            self,
            self.title_label,
            self.task_label,
        ):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()


class ContextCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ContextCard")
        self.setMinimumHeight(62)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(3)
        box.addWidget(QLabel(title, objectName="ContextKey"))
        self.box = box

    def add_value(self, text="—"):
        label = QLabel(text, objectName="ContextValue")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.box.addWidget(label)
        return label


class InnerCard(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("InnerCard")
        box = QVBoxLayout(self)
        box.setContentsMargins(13, 12, 13, 12)
        box.setSpacing(8)
        box.addWidget(QLabel(title, objectName="InnerTitle"))
        if subtitle:
            sub = QLabel(subtitle, objectName="InnerSubtitle")
            sub.setWordWrap(True)
            box.addWidget(sub)
        self.box = box


def _field(title: str, widget: QWidget, helper: str = "") -> QWidget:
    host = QWidget()
    box = QVBoxLayout(host)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(5)
    box.addWidget(QLabel(title, objectName="FieldLabel"))
    box.addWidget(widget)
    if helper:
        h = QLabel(helper, objectName="FieldHelper")
        h.setWordWrap(True)
        box.addWidget(h)
    return host


class DatasetMergeDialog(QDialog):
    """Qt6 port of the existing Merge / Update Dataset workflow."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge / Update Dataset")
        self.resize(780, 650)
        self.out_base_yaml = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        root.addWidget(QLabel("Merge / Update Dataset", objectName="DialogTitle"))
        root.addWidget(
            QLabel(
                "Merge class names, remap update labels and copy the update dataset into the base dataset.",
                objectName="DialogSubtitle",
            )
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        form = QGridLayout(content)
        form.setContentsMargins(2, 2, 2, 2)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)

        self.rows = {}
        specs = [
            ("base_yaml", "Base data.yaml", "file"),
            ("update_yaml", "Update data.yaml", "file"),
            ("src_train_images", "Update train/images", "folder"),
            ("src_train_labels", "Update train/labels", "folder"),
            ("src_test_images", "Update test/images", "folder"),
            ("src_test_labels", "Update test/labels", "folder"),
            ("dst_train_images", "Base train/images (dest)", "folder"),
            ("dst_train_labels", "Base train/labels (dest)", "folder"),
            ("dst_test_images", "Base test/images (dest)", "folder"),
            ("dst_test_labels", "Base test/labels (dest)", "folder"),
        ]

        for row, (key, title, kind) in enumerate(specs):
            label = QLabel(title, objectName="FieldLabel")
            edit = QLineEdit(objectName="PathEdit")
            button = QPushButton("Browse", objectName="SecondaryButton")
            button.setFixedWidth(82)
            button.clicked.connect(
                lambda checked=False, e=edit, k=kind: self._browse(e, k)
            )

            form.addWidget(label, row, 0)
            form.addWidget(edit, row, 1)
            form.addWidget(button, row, 2)
            self.rows[key] = edit

        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel", objectName="SecondaryButton")
        run = QPushButton("Run Merge", objectName="PrimaryButton")
        cancel.clicked.connect(self.reject)
        run.clicked.connect(self._run_merge)
        buttons.addWidget(cancel)
        buttons.addWidget(run)
        root.addLayout(buttons)

        self.setStyleSheet("""
        QDialog { background:#FFFFFF; color:#101A2D; }
        QLabel#DialogTitle { font-size:15px; font-weight:850; }
        QLabel#DialogSubtitle { color:#60728A; font-size:9.5px; }
        QLabel#FieldLabel { color:#405873; font-size:9px; font-weight:750; }
        QLineEdit#PathEdit {
            min-height:35px; background:#FFFFFF; color:#17263D;
            border:1px solid #B8C8DB; border-radius:8px; padding:0 8px;
            font-size:9.5px;
        }
        QPushButton#PrimaryButton, QPushButton#SecondaryButton {
            min-height:35px; border-radius:8px; padding:0 12px;
            font-size:9.2px; font-weight:780;
        }
        QPushButton#PrimaryButton {
            background:#2868E8; color:white; border:1px solid #2868E8;
        }
        QPushButton#SecondaryButton {
            background:#FFFFFF; color:#2868E8; border:1px solid #B8C8DB;
        }
        """)

    def _browse(self, edit: QLineEdit, kind: str):
        if kind == "file":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select YAML file",
                edit.text().strip() or str(Path.home()),
                "YAML Files (*.yaml *.yml);;All Files (*.*)",
            )
        else:
            path = QFileDialog.getExistingDirectory(
                self,
                "Select folder",
                edit.text().strip() or str(Path.home()),
            )
        if path:
            edit.setText(path)

    def _run_merge(self):
        yaml = require_yaml(self)

        values = {key: edit.text().strip() for key, edit in self.rows.items()}
        if not all(values.values()):
            QMessageBox.warning(self, "Missing", "Please fill all paths.")
            return

        for key in ("base_yaml", "update_yaml"):
            if not Path(values[key]).is_file():
                QMessageBox.warning(
                    self,
                    "Not found",
                    f"File not found:\n{values[key]}",
                )
                return

        folder_keys = [key for key in values if key not in {"base_yaml", "update_yaml"}]
        for key in folder_keys:
            if not Path(values[key]).is_dir():
                QMessageBox.warning(
                    self,
                    "Not a folder",
                    f"Folder not found:\n{values[key]}",
                )
                return

        try:
            with open(values["base_yaml"], "r", encoding="utf-8") as handle:
                base_data = yaml.safe_load(handle) or {}
            with open(values["update_yaml"], "r", encoding="utf-8") as handle:
                update_data = yaml.safe_load(handle) or {}

            base_names = base_data.get("names", [])
            update_names = update_data.get("names", [])

            if isinstance(base_names, dict):
                base_names = [base_names[k] for k in sorted(base_names)]
            if isinstance(update_names, dict):
                update_names = [update_names[k] for k in sorted(update_names)]

            base_names = list(base_names)
            for class_name in update_names:
                if class_name not in base_names:
                    base_names.append(class_name)

            base_data["names"] = base_names
            base_data["nc"] = len(base_names)

            with open(values["base_yaml"], "w", encoding="utf-8") as handle:
                yaml.safe_dump(base_data, handle, sort_keys=False)

            mapping = {
                index: base_names.index(class_name)
                for index, class_name in enumerate(update_names)
            }

            def update_labels(folder: str):
                for fp in Path(folder).glob("*.txt"):
                    rows = []
                    for line in fp.read_text(encoding="utf-8").splitlines():
                        parts = line.strip().split()
                        if not parts:
                            continue
                        if parts[0].isdigit():
                            old = int(parts[0])
                            parts[0] = str(mapping.get(old, old))
                        rows.append(parts)
                    fp.write_text(
                        "\n".join(" ".join(parts) for parts in rows)
                        + ("\n" if rows else ""),
                        encoding="utf-8",
                    )

            update_labels(values["src_train_labels"])
            update_labels(values["src_test_labels"])

            def copy_files(src: str, dst: str):
                Path(dst).mkdir(parents=True, exist_ok=True)
                for source in Path(src).iterdir():
                    if source.is_file():
                        shutil.copy2(source, Path(dst) / source.name)

            copy_files(values["src_train_images"], values["dst_train_images"])
            copy_files(values["src_train_labels"], values["dst_train_labels"])
            copy_files(values["src_test_images"], values["dst_test_images"])
            copy_files(values["src_test_labels"], values["dst_test_labels"])

            self.out_base_yaml = values["base_yaml"]
            self.accept()

        except Exception as exc:
            QMessageBox.critical(self, "Merge failed", str(exc))


class ModelTypePage(QWidget):
    mode_selected = pyqtSignal(str)

    MODES = {
        "seg": {
            "title": "YOLO Segmentation",
            "task": "Pixel-level masks",
            "description": "Ultralytics segmentation training for fast industrial defect masks.",
            "framework": "Ultralytics YOLO",
            "chips": ["Ultralytics", "Segmentation", "CUDA"],
            "icon": "yolo",
        },
        "det": {
            "title": "YOLO Detection",
            "task": "Bounding boxes",
            "description": "Fast object-detection training for discrete inspection defects.",
            "framework": "Ultralytics YOLO",
            "chips": ["Ultralytics", "Detection", "CUDA"],
            "icon": "yolo",
        },
        "dseg": {
            "title": "Detectron Segmentation",
            "task": "Mask R-CNN",
            "description": "Instance-segmentation workflow using Detectron2 configuration and datasets.",
            "framework": "Detectron2",
            "chips": ["Detectron2", "Mask R-CNN", "CUDA"],
            "icon": "detectron",
        },
        "ddet": {
            "title": "Detectron Detection",
            "task": "Faster R-CNN",
            "description": "Detectron2 object-detection workflow for Pascal VOC style training data.",
            "framework": "Detectron2",
            "chips": ["Detectron2", "Detection", "CUDA"],
            "icon": "detectron",
        },
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "seg"
        self.cards = {}
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 14, 15, 14)
        root.setSpacing(12)

        intro = QVBoxLayout()
        intro.setSpacing(3)
        intro.addWidget(QLabel("Model family", objectName="ModelFamilyTitle"))
        intro.addWidget(
            QLabel(
                "Choose the training path. The following stages adapt automatically to the selected framework and task.",
                objectName="PageSectionSubtitle",
            )
        )
        root.addLayout(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        order = ["seg", "det", "dseg", "ddet"]
        for index, mode in enumerate(order):
            spec = self.MODES[mode]
            card = ModelCard(
                mode=mode,
                title=spec["title"],
                task=spec["task"],
                description=spec["description"],
                framework=spec["framework"],
                chips=spec["chips"],
                icon_name=spec["icon"],
            )
            card.clicked.connect(self.set_mode)
            grid.addWidget(card, index // 2, index % 2)
            self.cards[mode] = card

        root.addLayout(grid)

        summary = QFrame(objectName="ModelSummaryStrip")
        row = QHBoxLayout(summary)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self.framework_value = self._summary_cell("FRAMEWORK", "Ultralytics YOLO")
        self.task_value = self._summary_cell("TASK", "Segmentation")
        self.compute_value = self._summary_cell("COMPUTE", "Detecting…")

        for cell in (
            self.framework_value[0],
            self.task_value[0],
            self.compute_value[0],
        ):
            row.addWidget(cell, 1)

        root.addWidget(summary)
        root.addStretch(1)

        self.set_mode("seg")

    def _summary_cell(self, title, value):
        host = QWidget(objectName="SummaryCell")
        box = QVBoxLayout(host)
        box.setContentsMargins(11, 8, 11, 8)
        box.setSpacing(3)
        box.addWidget(QLabel(title, objectName="SummaryCaption"))
        label = QLabel(value, objectName="SummaryValue")
        box.addWidget(label)
        return host, label

    def set_compute(self, text: str):
        self.compute_value[1].setText(text)

    def set_mode(self, mode: str):
        if mode not in self.MODES:
            return
        self.mode = mode
        for key, card in self.cards.items():
            card.set_selected(key == mode)

        spec = self.MODES[mode]
        self.framework_value[1].setText(spec["framework"])
        self.task_value[1].setText(
            "Segmentation" if "Segmentation" in spec["title"] else "Object Detection"
        )
        self.mode_selected.emit(mode)


class DatasetPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(15, 14, 15, 14)
        root.setSpacing(10)

        setup = InnerCard(
            "Dataset Setup",
            "Connect the dataset used for this training run.",
        )

        self.ver_combo = ControlledComboBox()
        self.ver_combo.addItems(["8", "10", "11", "12"])
        self.ver_combo.setCurrentText("11")

        self.data_edit = QLineEdit(objectName="PathEdit")
        self.data_edit.setPlaceholderText("Select data.yaml")

        yaml_row = QHBoxLayout()
        yaml_row.setSpacing(7)
        yaml_row.addWidget(self.data_edit, 1)
        browse = QPushButton("Browse", objectName="SecondaryButton")
        browse.setFixedHeight(36)
        browse.clicked.connect(self._browse)
        yaml_row.addWidget(browse)

        setup.box.addWidget(_field("Ultralytics version", self.ver_combo))
        setup.box.addWidget(QLabel("data.yaml", objectName="FieldLabel"))
        setup.box.addLayout(yaml_row)

        self.merge_btn = QPushButton("Merge / Update dataset", objectName="SecondaryButton")
        setup.box.addWidget(self.merge_btn, 0, Qt.AlignmentFlag.AlignLeft)
        setup.box.addStretch(1)

        validation = InnerCard(
            "Dataset Validation",
            "Quick checks before model configuration.",
        )
        stats = QHBoxLayout()
        self.classes_value = self._stat("CLASSES", "—")
        self.train_value = self._stat("TRAIN", "—")
        self.valid_value = self._stat("VALID", "—")
        for cell in (self.classes_value[0], self.train_value[0], self.valid_value[0]):
            stats.addWidget(cell, 1)
        validation.box.addLayout(stats)
        validation.box.addStretch(1)

        root.addWidget(setup, 1)
        root.addWidget(validation, 1)

        self.data_edit.textChanged.connect(self._update_stats)
        self.ver_combo.currentTextChanged.connect(self.changed.emit)

    def _stat(self, title, value):
        frame = QFrame(objectName="StatCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(3)
        box.addWidget(QLabel(title, objectName="SummaryCaption"))
        label = QLabel(value, objectName="SummaryValue")
        box.addWidget(label)
        return frame, label

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select data.yaml",
            self.data_edit.text().strip() or str(Path.home()),
            "YAML Files (*.yaml *.yml)",
        )
        if path:
            self.data_edit.setText(path)

    def _update_stats(self):
        path = Path(self.data_edit.text().strip())
        classes = train_count = val_count = None

        if path.is_file():
            try:
                import yaml
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

                names = data.get("names", [])
                classes = len(names) if hasattr(names, "__len__") else None

                base = path.parent
                dataset_root = data.get("path")
                if dataset_root:
                    root = Path(str(dataset_root))
                    if not root.is_absolute():
                        root = base / root
                else:
                    root = base

                def count_images(value):
                    if not value:
                        return None
                    target = Path(str(value))
                    if not target.is_absolute():
                        target = root / target
                    if target.is_dir():
                        return sum(
                            1
                            for p in target.rglob("*")
                            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
                        )
                    return None

                train_count = count_images(data.get("train"))
                val_count = count_images(data.get("val"))
            except Exception:
                pass

        self.classes_value[1].setText("—" if classes is None else str(classes))
        self.train_value[1].setText(
            "—" if train_count is None else f"{train_count:,} images"
        )
        self.valid_value[1].setText(
            "—" if val_count is None else f"{val_count:,} images"
        )
        self.changed.emit()


class WeightsPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "seg"
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(15, 14, 15, 14)
        root.setSpacing(10)

        selection = InnerCard(
            "Starting Weights",
            "Use the provided default or select a custom checkpoint.",
        )

        self.default_rb = QRadioButton("Use default weights", objectName="ChoiceRadio")
        self.custom_rb = QRadioButton("Use custom weights", objectName="ChoiceRadio")
        self.default_rb.setChecked(True)

        group = QButtonGroup(self)
        group.addButton(self.default_rb)
        group.addButton(self.custom_rb)

        selection.box.addWidget(self.default_rb)
        selection.box.addWidget(self.custom_rb)

        self.path_edit = QLineEdit(objectName="PathEdit")
        self.path_edit.setPlaceholderText("Select weights .pt")

        row = QHBoxLayout()
        row.setSpacing(7)
        row.addWidget(self.path_edit, 1)
        self.browse_btn = QPushButton("Browse", objectName="SecondaryButton")
        self.browse_btn.clicked.connect(self._browse)
        row.addWidget(self.browse_btn)
        selection.box.addWidget(QLabel("Weights path", objectName="FieldLabel"))
        selection.box.addLayout(row)
        selection.box.addStretch(1)

        summary = InnerCard(
            "Model Summary",
            "Current selected training route.",
        )
        stats = QHBoxLayout()
        self.mode_stat = self._stat("MODE", "YOLO Segmentation")
        self.start_stat = self._stat("START", "Default")
        self.device_stat = self._stat("DEVICE", "cuda")
        for cell in (self.mode_stat[0], self.start_stat[0], self.device_stat[0]):
            stats.addWidget(cell, 1)
        summary.box.addLayout(stats)
        summary.box.addStretch(1)

        root.addWidget(selection, 1)
        root.addWidget(summary, 1)

        self.default_rb.toggled.connect(self._state_changed)
        self.custom_rb.toggled.connect(self._state_changed)
        self.path_edit.textChanged.connect(self.changed.emit)
        self._state_changed()

    def _stat(self, title, value):
        frame = QFrame(objectName="StatCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(3)
        box.addWidget(QLabel(title, objectName="SummaryCaption"))
        label = QLabel(value, objectName="SummaryValue")
        box.addWidget(label)
        return frame, label

    def set_mode(self, mode: str, default_path: str):
        self.mode = mode
        title = "YOLO Segmentation" if mode == "seg" else "YOLO Detection"
        self.mode_stat[1].setText(title)
        if not self.custom_rb.isChecked():
            self.path_edit.setText(default_path)
        self._state_changed()

    def set_device(self, device: str):
        self.device_stat[1].setText(device)

    def _state_changed(self):
        custom = self.custom_rb.isChecked()
        self.path_edit.setEnabled(custom)
        self.browse_btn.setEnabled(custom)
        self.start_stat[1].setText("Custom" if custom else "Default")
        self.changed.emit()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select PyTorch weights",
            self.path_edit.text().strip() or str(Path.home()),
            "PyTorch Weights (*.pt);;All Files (*.*)",
        )
        if path:
            self.custom_rb.setChecked(True)
            self.path_edit.setText(path)


class HyperparametersPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 14, 15, 14)
        root.setSpacing(10)

        card = InnerCard(
            "Core Hyperparameters",
            "Set the compute and optimisation parameters for this run.",
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.device_combo = ControlledComboBox()
        self.epochs = QSpinBox(objectName="FieldSpin")
        self.epochs.setRange(1, 5000)
        self.epochs.setValue(400)

        self.imgsz = QSpinBox(objectName="FieldSpin")
        self.imgsz.setRange(32, 4096)
        self.imgsz.setSingleStep(32)
        self.imgsz.setValue(1024)

        self.opt = ControlledComboBox()
        self.opt.addItems(["Adam", "SGD", "AdamW"])
        self.opt.setCurrentText("Adam")

        self.batch = QSpinBox(objectName="FieldSpin")
        self.batch.setRange(1, 512)
        self.batch.setValue(16)

        self.project = QLineEdit("runs", objectName="PathEdit")

        self.lr0 = QDoubleSpinBox(objectName="FieldSpin")
        self.lr0.setDecimals(6)
        self.lr0.setRange(0.000001, 1.0)
        self.lr0.setSingleStep(0.0001)
        self.lr0.setValue(0.0001)

        fields = [
            ("Device", self.device_combo),
            ("Epochs", self.epochs),
            ("Image size", self.imgsz),
            ("Optimizer", self.opt),
            ("Batch size", self.batch),
            ("Output project", self.project),
            ("Learning rate", self.lr0),
        ]
        for index, (title, widget) in enumerate(fields):
            grid.addWidget(_field(title, widget), index // 2, index % 2)

        card.box.addLayout(grid)
        card.box.addStretch(1)
        root.addWidget(card, 1)

        for signal in (
            self.device_combo.currentTextChanged,
            self.epochs.valueChanged,
            self.imgsz.valueChanged,
            self.opt.currentTextChanged,
            self.batch.valueChanged,
            self.project.textChanged,
            self.lr0.valueChanged,
        ):
            signal.connect(self.changed.emit)


class DetectronSegPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 14, 15, 14)

        card = InnerCard(
            "Detectron Segmentation",
            "Configure the repository, dataset, model and runtime parameters.",
        )
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)

        self.d_repo_edit = QLineEdit("detectron2_repo", objectName="PathEdit")
        self.d_install_cb = QCheckBox(
            "Clone & install Detectron2 before training",
            objectName="FieldCheck",
        )

        self.d_data_edit = QLineEdit(objectName="PathEdit")
        self.d_train_edit = QLineEdit("train10", objectName="PathEdit")
        self.d_test_edit = QLineEdit("test10", objectName="PathEdit")
        self.d_classes_edit = QLineEdit("top_rectangle", objectName="PathEdit")

        self.d_model_combo = ControlledComboBox()
        self.d_model_combo.addItems(
            [
                "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml",
                "COCO-InstanceSegmentation/mask_rcnn_R_101_FPN_3x.yaml",
                "COCO-InstanceSegmentation/mask_rcnn_X_101_32x8d_FPN_3x.yaml",
            ]
        )

        self.d_ims_per_batch = QSpinBox(objectName="FieldSpin")
        self.d_ims_per_batch.setRange(1, 64)
        self.d_ims_per_batch.setValue(2)

        self.d_base_lr = QDoubleSpinBox(objectName="FieldSpin")
        self.d_base_lr.setDecimals(6)
        self.d_base_lr.setRange(0.000001, 1.0)
        self.d_base_lr.setValue(0.00025)

        self.d_max_iter = QSpinBox(objectName="FieldSpin")
        self.d_max_iter.setRange(10, 100000)
        self.d_max_iter.setValue(1000)

        self.d_workers = QSpinBox(objectName="FieldSpin")
        self.d_workers.setRange(0, 16)
        self.d_workers.setValue(2)

        self.d_device_combo = ControlledComboBox()
        self.d_output_edit = QLineEdit("detectron_runs", objectName="PathEdit")

        row = 0
        grid.addWidget(_field("Detectron2 repo", self._path_row(self.d_repo_edit, "folder")), row, 0, 1, 2)
        row += 1
        grid.addWidget(self.d_install_cb, row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Data root", self._path_row(self.d_data_edit, "folder")), row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Train folder", self.d_train_edit), row, 0)
        grid.addWidget(_field("Test folder", self.d_test_edit), row, 1)
        row += 1
        grid.addWidget(_field("Classes", self.d_classes_edit), row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Model config", self.d_model_combo), row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Images per batch", self.d_ims_per_batch), row, 0)
        grid.addWidget(_field("Base learning rate", self.d_base_lr), row, 1)
        row += 1
        grid.addWidget(_field("Maximum iterations", self.d_max_iter), row, 0)
        grid.addWidget(_field("Data workers", self.d_workers), row, 1)
        row += 1
        grid.addWidget(_field("Device", self.d_device_combo), row, 0)
        grid.addWidget(_field("Output dir", self._path_row(self.d_output_edit, "folder")), row, 1)

        card.box.addLayout(grid)
        root.addWidget(card, 1)

    def _path_row(self, edit, kind):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(edit, 1)
        btn = QPushButton("Browse", objectName="SecondaryButton")
        btn.clicked.connect(lambda: self._browse(edit, kind))
        row.addWidget(btn)
        return host

    def _browse(self, edit, kind):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select folder",
            edit.text().strip() or str(Path.home()),
        )
        if path:
            edit.setText(path)


class DetectronDetPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(15, 14, 15, 14)

        card = InnerCard(
            "Detectron Detection (Pascal VOC)",
            "Configure images, XML labels, model and runtime parameters.",
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(9)

        self.voc_images_root = QLineEdit(objectName="PathEdit")
        self.voc_labels_root = QLineEdit(objectName="PathEdit")
        self.voc_split_name = QLineEdit("train", objectName="PathEdit")
        self.voc_classes_edit = QLineEdit(
            "chip_mark,cut_piece,out_piece,curling_damage,bs,dent,dr",
            objectName="PathEdit",
        )

        self.d2det_model_combo = ControlledComboBox()
        self.d2det_model_combo.addItems(
            [
                "COCO-Detection/faster_rcnn_R_50_FPN_3x.yaml",
                "COCO-Detection/faster_rcnn_R_101_FPN_3x.yaml",
                "COCO-Detection/faster_rcnn_X_101_32x8d_FPN_3x.yaml",
            ]
        )

        self.d2det_weights_edit = QLineEdit(objectName="PathEdit")

        self.d2det_ims_per_batch = QSpinBox(objectName="FieldSpin")
        self.d2det_ims_per_batch.setRange(1, 64)
        self.d2det_ims_per_batch.setValue(6)

        self.d2det_max_iter = QSpinBox(objectName="FieldSpin")
        self.d2det_max_iter.setRange(10, 100000)
        self.d2det_max_iter.setValue(3000)

        self.d2det_steps_edit = QLineEdit(objectName="PathEdit")
        self.d2det_workers = QSpinBox(objectName="FieldSpin")
        self.d2det_workers.setRange(0, 32)
        self.d2det_workers.setValue(2)

        self.d2det_device_combo = ControlledComboBox()
        self.d2det_output_edit = QLineEdit("detectron_det_runs", objectName="PathEdit")

        row = 0
        grid.addWidget(_field("Images root (JPEGImages + ImageSets/Main)", self._folder_row(self.voc_images_root)), row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Labels root (.xml folder)", self._folder_row(self.voc_labels_root)), row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Split", self.voc_split_name), row, 0)
        grid.addWidget(_field("Classes", self.voc_classes_edit), row, 1)
        row += 1
        grid.addWidget(_field("Model config", self.d2det_model_combo), row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Start weights (.pth, optional)", self._weight_row()), row, 0, 1, 2)
        row += 1
        grid.addWidget(_field("Images per batch", self.d2det_ims_per_batch), row, 0)
        grid.addWidget(_field("Maximum iterations", self.d2det_max_iter), row, 1)
        row += 1
        grid.addWidget(_field("STEPS (comma)", self.d2det_steps_edit), row, 0)
        grid.addWidget(_field("Data workers", self.d2det_workers), row, 1)
        row += 1
        grid.addWidget(_field("Device", self.d2det_device_combo), row, 0)
        grid.addWidget(_field("Output dir", self._folder_row(self.d2det_output_edit)), row, 1)

        card.box.addLayout(grid)
        root.addWidget(card, 1)

    def _folder_row(self, edit):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(edit, 1)
        btn = QPushButton("Browse", objectName="SecondaryButton")
        btn.clicked.connect(lambda: self._browse_folder(edit))
        row.addWidget(btn)
        return host

    def _weight_row(self):
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.d2det_weights_edit, 1)
        btn = QPushButton("Browse", objectName="SecondaryButton")
        btn.clicked.connect(self._browse_weight)
        row.addWidget(btn)
        return host

    def _browse_folder(self, edit):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select folder",
            edit.text().strip() or str(Path.home()),
        )
        if path:
            edit.setText(path)

    def _browse_weight(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Detectron weights",
            self.d2det_weights_edit.text().strip() or str(Path.home()),
            "PyTorch Weights (*.pth *.pkl);;All Files (*.*)",
        )
        if path:
            self.d2det_weights_edit.setText(path)


class ReviewPage(QWidget):
    build_requested = pyqtSignal()
    start_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(15, 14, 15, 14)
        root.setSpacing(10)

        left = InnerCard(
            "Run Summary",
            "Review the final training configuration before starting.",
        )
        self.summary = QGridLayout()
        self.summary.setHorizontalSpacing(8)
        self.summary.setVerticalSpacing(8)

        self.mode_value = self._stat("MODEL", "YOLO Segmentation")
        self.device_value = self._stat("DEVICE", "cuda")
        self.epochs_value = self._stat("EPOCHS", "400")
        for idx, item in enumerate(
            (self.mode_value[0], self.device_value[0], self.epochs_value[0])
        ):
            self.summary.addWidget(item, 0, idx)
        left.box.addLayout(self.summary)

        self.command_preview = QLineEdit(objectName="CommandPreview")
        self.command_preview.setReadOnly(True)
        self.command_preview.setPlaceholderText(
            "Build command to preview the exact training process."
        )
        left.box.addWidget(QLabel("Generated command", objectName="FieldLabel"))
        left.box.addWidget(self.command_preview)

        buttons = QHBoxLayout()
        self.btn_build = QPushButton("Build Commands", objectName="SecondaryButton")
        self.btn_start = QPushButton("Start Training", objectName="PrimaryButton")
        buttons.addWidget(self.btn_build)
        buttons.addWidget(self.btn_start)
        buttons.addStretch(1)
        left.box.addLayout(buttons)
        left.box.addStretch(1)

        right = InnerCard(
            "Training Console",
            "Live process output and run status.",
        )
        self.console = QPlainTextEdit(objectName="TrainingConsole")
        self.console.setReadOnly(True)
        self.console.setPlaceholderText("Console output will appear here…")
        right.box.addWidget(self.console, 1)

        root.addWidget(left, 1)
        root.addWidget(right, 1)

        self.btn_build.clicked.connect(self.build_requested.emit)
        self.btn_start.clicked.connect(self.start_requested.emit)

    def _stat(self, title, value):
        frame = QFrame(objectName="StatCard")
        box = QVBoxLayout(frame)
        box.setContentsMargins(9, 8, 9, 8)
        box.setSpacing(3)
        box.addWidget(QLabel(title, objectName="SummaryCaption"))
        label = QLabel(value, objectName="SummaryValue")
        box.addWidget(label)
        return frame, label


class TrainingPageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)

    MODE_META = {
        "seg": ("YOLO Segmentation", "YOLO SEGMENTATION"),
        "det": ("YOLO Detection", "YOLO DETECTION"),
        "dseg": ("Detectron Segmentation", "DETECTRON SEGMENTATION"),
        "ddet": ("Detectron Detection", "DETECTRON DETECTION"),
    }

    DEFAULT_SEG_PATH = _find_weight(
        "yolo11s-seg.pt",
        "yolo11s-seg/yolo11s-seg.pt",
        "seg.pt",
    )
    DEFAULT_DET_PATH = _find_weight(
        "yolo11n.pt",
        "yolo11n/yolo11n.pt",
        "det.pt",
    )

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.mode = "seg"
        self.projects: list[dict] = []
        self.project_map: dict[str, dict] = {}
        self.selected_project_id = ""

        self._active_stage = "model"
        self._proc = None
        self._cmds = []
        self._idx = -1
        self._overall_start = None
        self._dash_httpd = None
        self._gpu_names = []

        self.setObjectName("TrainingPageQt6")
        self._build()
        self._apply_style()
        self._bind_backend_aliases()
        self._populate_devices()
        self.refresh_context()
        self._set_mode("seg", navigate=False)
        self._switch_stage("model")

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        context = QGridLayout()
        context.setContentsMargins(0, 0, 0, 0)
        context.setHorizontalSpacing(8)

        project_card = ContextCard("CURRENT PROJECT")
        self.project_selector = ProjectComboBox()
        self.project_selector.currentIndexChanged.connect(self._project_changed)
        project_card.box.addWidget(self.project_selector)
        context.addWidget(project_card, 0, 0)

        type_card = ContextCard("TRAINING TYPE")
        self.context_type = type_card.add_value("YOLO Segmentation")
        context.addWidget(type_card, 0, 1)

        dataset_card = ContextCard("DATASET")
        self.context_dataset = dataset_card.add_value("Not selected")
        context.addWidget(dataset_card, 0, 2)

        device_card = ContextCard("DEVICE")
        self.context_device = device_card.add_value("Detecting…")
        context.addWidget(device_card, 0, 3)

        context.setColumnStretch(0, 11)
        context.setColumnStretch(1, 14)
        context.setColumnStretch(2, 23)
        context.setColumnStretch(3, 10)
        root.addLayout(context)

        body = QHBoxLayout()
        body.setSpacing(10)

        rail = QFrame(objectName="TrainingRail")
        rail.setFixedWidth(220)
        rail_box = QVBoxLayout(rail)
        rail_box.setContentsMargins(12, 13, 12, 13)
        rail_box.setSpacing(7)

        rail_box.addWidget(QLabel("TRAINING WORKFLOW", objectName="RailEyebrow"))

        self.rail_buttons = {}
        for key, text, icon_name in (
            ("model", "Model Type", "model"),
            ("dataset", "Dataset", "dataset"),
            ("weights", "Model Weights", "weights"),
            ("hparams", "Hyperparameters", "hparams"),
            ("review", "Review & Run", "review"),
        ):
            button = RailNavButton(key, text, icon_name)
            button.clicked.connect(
                lambda checked=False, k=key: self._rail_clicked(k)
            )
            rail_box.addWidget(button)
            self.rail_buttons[key] = button

        divider = QFrame(objectName="RailDivider")
        divider.setFixedHeight(1)
        rail_box.addSpacing(4)
        rail_box.addWidget(divider)
        rail_box.addSpacing(4)
        rail_box.addWidget(QLabel("TOOLS", objectName="RailEyebrow"))

        dashboard_btn = RailNavButton("dashboard", "Run Dashboard", "dashboard")
        dashboard_btn.setCheckable(False)
        dashboard_btn.clicked.connect(self._open_dashboard)
        rail_box.addWidget(dashboard_btn)
        rail_box.addStretch(1)

        body.addWidget(rail)

        workspace = QFrame(objectName="TrainingWorkspace")
        workspace_box = QVBoxLayout(workspace)
        workspace_box.setContentsMargins(0, 0, 0, 0)
        workspace_box.setSpacing(0)

        head = QFrame(objectName="WorkspaceHeader")
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(15, 12, 15, 11)
        head_row.setSpacing(10)

        copy = QVBoxLayout()
        copy.setSpacing(2)
        self.workspace_title = QLabel(
            "Choose a Training Model",
            objectName="WorkspaceTitle",
        )
        self.workspace_subtitle = QLabel(
            "Select the model family and task for this training run.",
            objectName="WorkspaceSubtitle",
        )
        copy.addWidget(self.workspace_title)
        copy.addWidget(self.workspace_subtitle)
        head_row.addLayout(copy, 1)

        self.mode_badge = QLabel("YOLO SEGMENTATION", objectName="ModeBadge")
        head_row.addWidget(self.mode_badge, 0, Qt.AlignmentFlag.AlignTop)
        workspace_box.addWidget(head)

        self.stack = QStackedWidget()
        self.model_page = ModelTypePage()
        self.dataset_page = DatasetPage()
        self.weights_page = WeightsPage()
        self.hparams_page = HyperparametersPage()
        self.detectron_seg_page = DetectronSegPage()
        self.detectron_det_page = DetectronDetPage()
        self.review_page = ReviewPage()

        self.stage_widgets = {
            "model": self.model_page,
            "dataset": self.dataset_page,
            "weights": self.weights_page,
            "hparams": self.hparams_page,
            "dconfig_seg": self.detectron_seg_page,
            "dconfig_det": self.detectron_det_page,
            "review": self.review_page,
        }
        for page in self.stage_widgets.values():
            self.stack.addWidget(page)
        workspace_box.addWidget(self.stack, 1)

        footer = QFrame(objectName="TrainingFooter")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(14, 8, 14, 10)
        footer_row.setSpacing(7)

        self.footer_text = QLabel(
            "Select the model family and continue.",
            objectName="FooterText",
        )
        footer_row.addWidget(self.footer_text)
        footer_row.addStretch(1)

        self.back_btn = QPushButton("← Back", objectName="SecondaryButton")
        self.next_btn = QPushButton("Continue →", objectName="PrimaryButton")
        self.back_btn.clicked.connect(self._back)
        self.next_btn.clicked.connect(self._next)
        footer_row.addWidget(self.back_btn)
        footer_row.addWidget(self.next_btn)
        workspace_box.addWidget(footer)

        body.addWidget(workspace, 1)
        root.addLayout(body, 1)

        # Signals
        self.model_page.mode_selected.connect(
            lambda mode: self._set_mode(mode, navigate=False)
        )
        self.dataset_page.merge_btn.clicked.connect(self._open_merge_dialog)
        self.dataset_page.changed.connect(self._dataset_changed)
        self.hparams_page.changed.connect(self._hparams_changed)
        self.weights_page.changed.connect(self._sync_weights_backend)

        self.review_page.build_requested.connect(self._on_build)
        self.review_page.start_requested.connect(self._on_start)

    def _bind_backend_aliases(self):
        # Keep the legacy command-building attribute names.
        self.ver_combo = self.dataset_page.ver_combo
        self.data_edit = self.dataset_page.data_edit

        # Separate hidden radio states are unnecessary; expose the visible state.
        self.seg_default_rb = self.weights_page.default_rb
        self.seg_custom_rb = self.weights_page.custom_rb
        self.seg_path_edit = self.weights_page.path_edit

        self.det_default_rb = self.weights_page.default_rb
        self.det_custom_rb = self.weights_page.custom_rb
        self.det_path_edit = self.weights_page.path_edit

        self.device_combo = self.hparams_page.device_combo
        self.epochs = self.hparams_page.epochs
        self.imgsz = self.hparams_page.imgsz
        self.opt = self.hparams_page.opt
        self.batch = self.hparams_page.batch
        self.project = self.hparams_page.project
        self.lr0 = self.hparams_page.lr0

        # Detectron Segmentation
        d = self.detectron_seg_page
        self.d_repo_edit = d.d_repo_edit
        self.d_install_cb = d.d_install_cb
        self.d_data_edit = d.d_data_edit
        self.d_train_edit = d.d_train_edit
        self.d_test_edit = d.d_test_edit
        self.d_classes_edit = d.d_classes_edit
        self.d_model_combo = d.d_model_combo
        self.d_ims_per_batch = d.d_ims_per_batch
        self.d_base_lr = d.d_base_lr
        self.d_max_iter = d.d_max_iter
        self.d_workers = d.d_workers
        self.d_device_combo = d.d_device_combo
        self.d_output_edit = d.d_output_edit

        # Detectron Detection
        dd = self.detectron_det_page
        self.voc_images_root = dd.voc_images_root
        self.voc_labels_root = dd.voc_labels_root
        self.voc_split_name = dd.voc_split_name
        self.voc_classes_edit = dd.voc_classes_edit
        self.d2det_model_combo = dd.d2det_model_combo
        self.d2det_weights_edit = dd.d2det_weights_edit
        self.d2det_ims_per_batch = dd.d2det_ims_per_batch
        self.d2det_max_iter = dd.d2det_max_iter
        self.d2det_steps_edit = dd.d2det_steps_edit
        self.d2det_workers = dd.d2det_workers
        self.d2det_device_combo = dd.d2det_device_combo
        self.d2det_output_edit = dd.d2det_output_edit

        self.console = self.review_page.console
        self.btn_build = self.review_page.btn_build
        self.btn_start = self.review_page.btn_start

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------
    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#TrainingPageQt6 {
            background:transparent; color:#101A2D;
        }
        QWidget#TrainingPageQt6 QLabel {
            background:transparent; border:0;
        }

        QFrame#ContextCard {
            background:#FFFFFF; border:1px solid #C3D1E2; border-radius:12px;
        }
        QLabel#ContextKey {
            color:#60738B; font-size:8px; font-weight:850; letter-spacing:.65px;
        }
        QLabel#ContextValue {
            color:#15263D; font-size:10.4px; font-weight:800;
        }

        QComboBox#ProjectSelector, QComboBox#FieldCombo {
            min-height:35px; background:#FFFFFF; color:#17263D;
            border:1px solid #AEBFD5; border-radius:8px;
            padding:0 32px 0 9px; font-size:9.7px; font-weight:740;
        }
        QComboBox#ProjectSelector:hover, QComboBox#ProjectSelector:focus,
        QComboBox#FieldCombo:hover, QComboBox#FieldCombo:focus,
        QComboBox#FieldCombo:on {
            background:#FFFFFF; border:1px solid #2868E8;
        }
        QComboBox#ProjectSelector::drop-down,
        QComboBox#FieldCombo::drop-down {
            width:28px; border:0; border-left:1px solid #D8E1EC;
        }
        QComboBox#ProjectSelector::down-arrow,
        QComboBox#FieldCombo::down-arrow {
            image:none; width:0; height:0;
        }

        QListView#ControlledComboView {
            background:#FFFFFF; color:#17263D;
            border:1px solid #AEBFD5; border-radius:8px;
            padding:5px; outline:0; font-size:9.7px; font-weight:700;
        }
        QListView#ControlledComboView::item {
            background:#FFFFFF; color:#17263D;
            min-height:30px; padding:3px 8px; border-radius:5px;
        }
        QListView#ControlledComboView::item:hover {
            background:#F0F5FF; color:#1D5BD0;
        }
        QListView#ControlledComboView::item:selected {
            background:#E5EEFF; color:#1D5BD0; font-weight:800;
        }

        QFrame#TrainingRail {
            background:#FFFFFF; border:1px solid #BFCEDF; border-radius:15px;
        }
        QLabel#RailEyebrow {
            color:#60728A; font-size:8.4px; font-weight:850;
            letter-spacing:.75px; padding:3px 3px 4px;
        }
        QFrame#RailDivider { background:#DCE4EE; border:0; }

        QPushButton#TrainingRailButton {
            padding:0 12px; text-align:left;
            background:#FFFFFF; border:1px solid #C5D2E2; border-radius:10px;
        }
        QPushButton#TrainingRailButton:hover {
            background:#F0F5FF; border-color:#9DB7E2;
        }
        QPushButton#TrainingRailButton:checked {
            background:#E8F1FF; border:1px solid #2868E8;
        }

        QFrame#TrainingWorkspace {
            background:#FFFFFF; border:1px solid #BFCEDF; border-radius:15px;
        }
        QFrame#WorkspaceHeader {
            background:#FFFFFF; border:0; border-bottom:1px solid #DCE4EE;
        }
        QLabel#WorkspaceTitle {
            color:#101A2D; font-size:15px; font-weight:850;
        }
        QLabel#WorkspaceSubtitle {
            color:#60728A; font-size:9px; font-weight:600;
        }
        QLabel#ModeBadge {
            background:#F1F5FA; color:#566A82; border:1px solid #DCE4EE;
            border-radius:11px; padding:5px 8px;
            font-size:7.8px; font-weight:850;
        }

        QLabel#ModelFamilyTitle {
            color:#101A2D; font-size:17px; font-weight:850;
        }

        QFrame#ModelCard {
            background:#FFFFFF; border:1px solid #C7D4E4; border-radius:12px;
        }
        QFrame#ModelCard:hover {
            background:#FBFCFE; border-color:#9AB5E0;
        }
        QFrame#ModelCard[selected="true"] {
            background:#EAF2FF; border:2px solid #2868E8;
        }
        QLabel#ModelCardTitle {
            color:#17263D; font-size:11.4px; font-weight:850;
        }
        QLabel#ModelCardTask {
            color:#60728A; font-size:8.2px; font-weight:720;
        }
        QFrame#ModelCard[selected="true"] QLabel#ModelCardTask {
            color:#2868E8;
        }
        QLabel#ModelCardDescription {
            color:#66788E; font-size:8.8px; font-weight:580;
        }
        QLabel#ModelChip {
            background:#F2F5F9; color:#5E7188;
            border-radius:8px; padding:3px 6px;
            font-size:7.4px; font-weight:760;
        }
        QLabel#ModelSelectedMark {
            background:#2868E8; color:#FFFFFF; border-radius:11px;
            font-size:12px; font-weight:900;
        }

        QFrame#ModelSummaryStrip {
            background:#F7F9FC; border:1px solid #CFDAE7; border-radius:10px;
        }
        QWidget#SummaryCell {
            border-right:1px solid #DCE4EE;
        }
        QLabel#SummaryCaption {
            color:#718197; font-size:7.6px; font-weight:850; letter-spacing:.45px;
        }
        QLabel#SummaryValue {
            color:#17263D; font-size:9.5px; font-weight:820;
        }

        QFrame#InnerCard {
            background:#FBFCFE; border:1px solid #C8D5E5; border-radius:12px;
        }
        QLabel#InnerTitle {
            color:#17263D; font-size:11.3px; font-weight:830;
        }
        QLabel#InnerSubtitle, QLabel#PageSectionSubtitle {
            color:#62748B; font-size:8.7px; font-weight:600;
        }
        QLabel#FieldLabel {
            color:#405873; font-size:8.8px; font-weight:760;
        }
        QLabel#FieldHelper {
            color:#748399; font-size:7.8px;
        }

        QLineEdit#PathEdit, QLineEdit#CommandPreview,
        QSpinBox#FieldSpin, QDoubleSpinBox#FieldSpin {
            min-height:35px; background:#FFFFFF; color:#17263D;
            border:1px solid #B8C8DB; border-radius:8px;
            padding:0 8px; font-size:9.5px;
        }
        QLineEdit#PathEdit:focus, QLineEdit#CommandPreview:focus,
        QSpinBox#FieldSpin:focus, QDoubleSpinBox#FieldSpin:focus {
            border:1px solid #2868E8;
        }

        QRadioButton#ChoiceRadio, QCheckBox#FieldCheck {
            color:#405873; font-size:9.4px; font-weight:700;
            padding:4px;
        }

        QFrame#StatCard {
            background:#FFFFFF; border:1px solid #D0DBE8; border-radius:9px;
        }

        QPushButton#PrimaryButton, QPushButton#SecondaryButton {
            min-height:36px; border-radius:9px;
            padding:0 12px; font-size:9.4px; font-weight:780;
        }
        QPushButton#PrimaryButton {
            background:#2868E8; color:#FFFFFF; border:1px solid #2868E8;
        }
        QPushButton#PrimaryButton:hover { background:#1F58CC; }
        QPushButton#PrimaryButton:disabled {
            background:#AFC4E9; color:#FFFFFF; border-color:#AFC4E9;
        }
        QPushButton#SecondaryButton {
            background:#FFFFFF; color:#2868E8; border:1px solid #B8C8DB;
        }
        QPushButton#SecondaryButton:hover { background:#EEF4FF; }
        QPushButton#SecondaryButton:disabled {
            color:#A3AFBF; border-color:#D5DFEA; background:#F6F8FB;
        }

        QFrame#TrainingFooter {
            background:#FCFDFE; border:0; border-top:1px solid #DCE4EE;
        }
        QLabel#FooterText {
            color:#63758D; font-size:8.5px; font-weight:600;
        }

        QPlainTextEdit#TrainingConsole {
            background:#0F1724; color:#D9E8FF;
            border:1px solid #26354A; border-radius:9px;
            padding:8px; font-family:Consolas; font-size:8.7px;
        }

        QScrollBar:vertical {
            background:transparent; width:8px; margin:2px;
        }
        QScrollBar::handle:vertical {
            background:#C5D2E2; border-radius:4px; min-height:28px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height:0;
        }
        """)

    # ------------------------------------------------------------------
    # Project + device context
    # ------------------------------------------------------------------
    def refresh_context(self):
        previous = self.selected_project_id
        try:
            self.projects = list(ProjectDB().get_all_projects() or [])
        except Exception as exc:
            self.projects = []
            self.toast_requested.emit("Projects unavailable", str(exc))

        self.project_map = {
            _project_id(project): project
            for project in self.projects
            if _project_id(project)
        }

        self.project_selector.blockSignals(True)
        self.project_selector.clear()

        for project in self.projects:
            self.project_selector.addItem(
                str(project.get("name") or "Unnamed Project"),
                _project_id(project),
            )

        if self.projects:
            index = self.project_selector.findData(previous)
            self.project_selector.setCurrentIndex(index if index >= 0 else 0)
            self.project_selector.setEnabled(True)
        else:
            self.project_selector.addItem("No projects available", "")
            self.project_selector.setEnabled(False)

        self.project_selector.blockSignals(False)

        if self.projects:
            project = self.project_map.get(
                str(self.project_selector.currentData() or ""),
                self.projects[0],
            )
            self._apply_project(project)

        self._refresh_context_values()

    def _project_changed(self, _index):
        project = self.project_map.get(
            str(self.project_selector.currentData() or "")
        )
        if project:
            self._apply_project(project)

    def _apply_project(self, project: dict):
        self.selected_project_id = _project_id(project)

        project_root = self._resolve_project_root(project)
        data_yaml = self._find_project_data_yaml(project_root)

        if data_yaml:
            self.dataset_page.data_edit.setText(str(data_yaml))

        output_root = project_root / "Training_Runs"
        self.hparams_page.project.setText(str(output_root))
        self.detectron_seg_page.d_output_edit.setText(
            str(output_root / "detectron_seg")
        )
        self.detectron_det_page.d2det_output_edit.setText(
            str(output_root / "detectron_det")
        )

        # If this project already contains a likely Detectron data root, use it.
        self.detectron_seg_page.d_data_edit.setText(str(project_root))

        self._refresh_context_values()

    def _resolve_project_root(self, project: dict) -> Path:
        folder = str(project.get("folder_path") or "").strip()
        if folder:
            path = Path(folder)
            if path.suffix:
                path = path.parent
            return path

        name = _safe_name(str(project.get("name") or "Project"))
        candidates = [
            Path.home() / "Documents" / "EyresAiPlatform" / "Projects" / name,
            Path.cwd() / "Projects" / name,
            Path.cwd() / "media" / "Projects" / name,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def _find_project_data_yaml(self, project_root: Path) -> Path | None:
        preferred = [
            project_root / "Augmented_Dataset" / "data.yaml",
            project_root / "augmented_dataset" / "data.yaml",
            project_root / "data.yaml",
        ]
        for path in preferred:
            if path.is_file():
                return path

        if project_root.exists():
            found = list(project_root.rglob("data.yaml"))
            if found:
                return max(found, key=lambda p: p.stat().st_mtime)
        return None

    def _populate_devices(self):
        devices = ["cpu"]
        gpu_names = []
        cuda_available = False

        try:
            import torch
            if torch.cuda.is_available():
                cuda_available = True
                devices.append("cuda")
                for index in range(torch.cuda.device_count()):
                    devices.append(f"cuda:{index}")
                    try:
                        gpu_names.append(torch.cuda.get_device_name(index))
                    except Exception:
                        gpu_names.append(f"GPU {index}")
        except Exception:
            pass

        if not gpu_names and shutil.which("nvidia-smi"):
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=name",
                        "--format=csv,noheader",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                gpu_names = [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip()
                ]
            except Exception:
                pass

        self._gpu_names = gpu_names

        for combo in (
            self.hparams_page.device_combo,
            self.detectron_seg_page.d_device_combo,
            self.detectron_det_page.d2det_device_combo,
        ):
            combo.clear()
            combo.addItems(devices)
            combo.setCurrentText("cuda" if cuda_available else "cpu")

        if cuda_available:
            self.model_page.set_compute("CUDA available")
        elif gpu_names:
            self.model_page.set_compute("NVIDIA driver detected")
        else:
            self.model_page.set_compute("CPU")

        self._refresh_context_values()

    def _device_description(self) -> str:
        device = self.hparams_page.device_combo.currentText().strip() or "cpu"
        if device.startswith("cuda"):
            if self._gpu_names:
                return f"{device.upper()} · {self._gpu_names[0]}"
            return f"{device.upper()} · NVIDIA GPU"
        return "CPU"

    # ------------------------------------------------------------------
    # Navigation + mode
    # ------------------------------------------------------------------
    def _path_for_mode(self) -> list[str]:
        if self.mode in {"seg", "det"}:
            return ["model", "dataset", "weights", "hparams", "review"]
        return [
            "model",
            "dconfig_seg" if self.mode == "dseg" else "dconfig_det",
            "review",
        ]

    def _set_mode(self, mode: str, navigate: bool = False):
        if mode not in self.MODE_META:
            return

        self.mode = mode
        title, badge = self.MODE_META[mode]
        self.context_type.setText(title)
        self.mode_badge.setText(badge)

        if mode == "seg":
            self.weights_page.set_mode("seg", self.DEFAULT_SEG_PATH)
        elif mode == "det":
            self.weights_page.set_mode("det", self.DEFAULT_DET_PATH)

        # Rail adapts exactly like the original training workflow.
        if mode in {"seg", "det"}:
            self.rail_buttons["dataset"].setText("Dataset")
            self.rail_buttons["weights"].setVisible(True)
            self.rail_buttons["hparams"].setVisible(True)
        else:
            self.rail_buttons["dataset"].setText("Configuration")
            self.rail_buttons["weights"].setVisible(False)
            self.rail_buttons["hparams"].setVisible(False)

        if navigate:
            self._switch_stage(self._path_for_mode()[1])

        self._refresh_context_values()
        self._update_review_summary()

    def _rail_clicked(self, key: str):
        if key == "dataset" and self.mode in {"dseg", "ddet"}:
            key = "dconfig_seg" if self.mode == "dseg" else "dconfig_det"

        if key not in self._path_for_mode():
            return

        if key != "model" and self.mode in {"seg", "det"}:
            if key in {"weights", "hparams", "review"} and not self._valid_dataset():
                return

        self._switch_stage(key)

    def _switch_stage(self, key: str):
        if key not in self.stage_widgets:
            return

        self._active_stage = key
        page = self.stage_widgets[key]
        self.stack.setCurrentWidget(page)

        visible_key = key
        if key in {"dconfig_seg", "dconfig_det"}:
            visible_key = "dataset"

        for rail_key, button in self.rail_buttons.items():
            button.setChecked(rail_key == visible_key)

        headings = {
            "model": (
                "Choose a Training Model",
                "Select the model family and task for this training run.",
            ),
            "dataset": (
                "Dataset Setup",
                "Connect and validate the dataset used for this run.",
            ),
            "weights": (
                "Model Weights",
                "Choose default or custom starting weights.",
            ),
            "hparams": (
                "Hyperparameters",
                "Set the core compute and optimisation parameters.",
            ),
            "dconfig_seg": (
                "Detectron Configuration",
                "Configure the repository, dataset, model and runtime parameters.",
            ),
            "dconfig_det": (
                "Detectron Configuration",
                "Configure Pascal VOC input, model and runtime parameters.",
            ),
            "review": (
                "Review & Run",
                "Build the command, verify configuration and start training.",
            ),
        }

        title, subtitle = headings[key]
        self.workspace_title.setText(title)
        self.workspace_subtitle.setText(subtitle)

        path = self._path_for_mode()
        index = path.index(key)

        self.back_btn.setVisible(index > 0)
        self.next_btn.setVisible(key != "review")

        if key == "model":
            self.footer_text.setText("Select the model family and continue.")
        elif key == "review":
            self.footer_text.setText(
                "Review the training configuration before starting."
            )
        else:
            self.footer_text.setText("Complete this section and continue.")

        if key == "review":
            self._update_review_summary()

    def _next(self):
        path = self._path_for_mode()
        if self._active_stage not in path:
            self._switch_stage(path[0])
            return

        index = path.index(self._active_stage)
        if self._active_stage == "dataset" and not self._valid_dataset():
            return

        if index + 1 < len(path):
            self._switch_stage(path[index + 1])

    def _back(self):
        path = self._path_for_mode()
        if self._active_stage not in path:
            return
        index = path.index(self._active_stage)
        if index > 0:
            self._switch_stage(path[index - 1])

    def _valid_dataset(self) -> bool:
        if self.mode not in {"seg", "det"}:
            return True
        path = Path(self.data_edit.text().strip())
        if not path.is_file():
            self.toast_requested.emit(
                "Dataset required",
                "Select a valid data.yaml before continuing.",
            )
            return False
        return True

    # ------------------------------------------------------------------
    # UI sync
    # ------------------------------------------------------------------
    def _dataset_changed(self):
        self._refresh_context_values()
        self._update_review_summary()

    def _hparams_changed(self):
        self.weights_page.set_device(
            self.hparams_page.device_combo.currentText()
        )
        self._refresh_context_values()
        self._update_review_summary()

    def _sync_weights_backend(self):
        # The same visible page is used for seg/det, while aliases are already
        # mapped to the backend names.
        self._update_review_summary()

    def _refresh_context_values(self):
        if hasattr(self, "data_edit"):
            value = self.data_edit.text().strip()
            self.context_dataset.setText(value or "Not selected")
        self.context_device.setText(self._device_description())

    def _update_review_summary(self):
        title = self.MODE_META[self.mode][0]
        self.review_page.mode_value[1].setText(title)

        if self.mode in {"seg", "det"}:
            self.review_page.device_value[1].setText(
                self.device_combo.currentText()
            )
            self.review_page.epochs_value[1].setText(
                str(self.epochs.value())
            )
        elif self.mode == "dseg":
            self.review_page.device_value[1].setText(
                self.d_device_combo.currentText()
            )
            self.review_page.epochs_value[1].setText(
                f"{self.d_max_iter.value()} iters"
            )
        else:
            self.review_page.device_value[1].setText(
                self.d2det_device_combo.currentText()
            )
            self.review_page.epochs_value[1].setText(
                f"{self.d2det_max_iter.value()} iters"
            )

    # ------------------------------------------------------------------
    # Dataset merge
    # ------------------------------------------------------------------
    def _open_merge_dialog(self):
        dialog = DatasetMergeDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if dialog.out_base_yaml:
                self.data_edit.setText(dialog.out_base_yaml)
            self.toast_requested.emit(
                "Dataset updated",
                "Dataset merge completed successfully.",
            )

    # ------------------------------------------------------------------
    # Existing backend methods follow below.
    # ------------------------------------------------------------------

    def _get_seg_weights(self) -> str:
        return self.seg_path_edit.text().strip() if self.seg_custom_rb.isChecked() else self.DEFAULT_SEG_PATH

    def _get_det_weights(self) -> str:
        return self.det_path_edit.text().strip() if self.det_custom_rb.isChecked() else self.DEFAULT_DET_PATH

    def _fix_and_stage_data_yaml(self, data_yaml_path: str) -> str:
        yaml = require_yaml(self)
        src = Path(data_yaml_path).resolve()
        if not src.is_file():
            raise FileNotFoundError(f"data.yaml not found: {src}")

        with open(src, "r", encoding="utf-8") as f:
            data = (yaml.safe_load(f) or {})

        base = src.parent
        dataset_root = data.get("path", "")
        train = data.get("train", ""); val = data.get("val", ""); test = data.get("test", "")

        def _abs(candidate: str) -> Path:
            c = str(candidate or "").strip()
            if not c: return Path("")
            p = Path(c)
            return p if p.is_absolute() else (base / p)

        path_hint = _abs(dataset_root) if dataset_root else base

        def _resolve_dir(p: str | Path) -> Path:
            if not p: return Path("")
            p = Path(p)
            if not p.is_absolute():
                p = (path_hint / p) if dataset_root else (base / p)
            if p.is_dir(): return p
            for guess in [p.parent, base / p.name, path_hint / p.name]:
                if guess.is_dir(): return guess
            return p

        train_dir = _resolve_dir(train)
        val_dir = _resolve_dir(val)
        test_dir = _resolve_dir(test) if test else Path("")

        def _ensure_dir(label: str, p: Path) -> Path:
            if p and p.is_dir(): return p
            dn = QtWidgets.QFileDialog.getExistingDirectory(self, f"Select {label}", str(base))
            if not dn: raise FileNotFoundError(f"{label} not found and no folder selected.")
            return Path(dn)

        train_dir = _ensure_dir("train images folder", train_dir)
        val_dir = _ensure_dir("val images folder", val_dir)
        if test:
            test_dir = _ensure_dir("test images folder", test_dir)

        fixed = dict(data)
        fixed.pop("path", None)
        fixed["train"] = fwd(train_dir)
        fixed["val"] = fwd(val_dir)
        if test:
            fixed["test"] = fwd(test_dir)

        cache_dir = base / ".cache_wizard"
        cache_dir.mkdir(exist_ok=True)
        out = cache_dir / f"{src.stem}_fixed.yaml"

        with open(out, "w", encoding="utf-8") as f:
            yaml.safe_dump(fixed, f, sort_keys=False)

        return fwd(out)

    def build_commands(self) -> tuple[str, list]:
        if self.mode == "dseg":
            data_root = (self.d_data_edit.text() or "").strip()
            train_dir = (self.d_train_edit.text() or "train10").strip()
            test_dir  = (self.d_test_edit.text() or "test10").strip()
            classes_s = (self.d_classes_edit.text() or "").strip()
            repo_dir  = (self.d_repo_edit.text() or "detectron2_repo").strip()
            model_key = self.d_model_combo.currentText().strip()
            ims       = int(self.d_ims_per_batch.value())
            base_lr   = float(self.d_base_lr.value())
            max_iter  = int(self.d_max_iter.value())
            nworkers  = int(self.d_workers.value())
            device    = self.d_device_combo.currentText().strip()
            out_dir   = (self.d_output_edit.text() or "detectron_runs").strip()

            if not data_root or not os.path.isdir(data_root):
                raise ValueError("Please choose a valid Data root folder (Detectron → Data root).")
            if not classes_s:
                raise ValueError("Please enter at least one class name (Detectron → Classes).")

            info = "[info] Detectron2 training (Instance Segmentation)"
            cmds = []

            if self.d_install_cb.isChecked():
                if not os.path.isdir(repo_dir):
                    cmds.append(("git", ["clone", "https://github.com/facebookresearch/detectron2", repo_dir]))
                cmds.append((sys.executable, ["-m", "pip", "install", "git+https://github.com/facebookresearch/fvcore.git"]))
                cmds.append((sys.executable, ["-m", "pip", "install", "-e", repo_dir]))

            runner = textwrap.dedent(r"""
                import argparse, os, json, glob, cv2, numpy as np
                from detectron2.structures import BoxMode
                from detectron2.data import DatasetCatalog, MetadataCatalog
                from detectron2 import model_zoo
                from detectron2.config import get_cfg
                from detectron2.engine import DefaultTrainer

                def get_data_dicts(directory, classes):
                    dicts = []
                    for jf in glob.glob(os.path.join(directory, "*.json")):
                        with open(jf, "r") as f:
                            img_anns = json.load(f)
                        img_path = os.path.join(directory, img_anns.get("imagePath",""))
                        if not os.path.isfile(img_path):
                            base = os.path.splitext(jf)[0]
                            for ext in (".jpg",".jpeg",".png",".bmp"):
                                if os.path.isfile(base+ext):
                                    img_path = base+ext; break
                        h, w = img_anns.get("imageHeight", 0), img_anns.get("imageWidth", 0)
                        if (h == 0 or w == 0) and os.path.isfile(img_path):
                            im = cv2.imread(img_path); h, w = im.shape[:2]
                        rec = {"file_name": img_path, "image_id": os.path.basename(img_path), "height": int(h), "width": int(w), "annotations": []}
                        objs = []
                        for s in img_anns.get("shapes", []):
                            lbl = s.get("label","")
                            if lbl not in classes: continue
                            pts = s.get("points", [])
                            if len(pts) < 3: continue
                            px = [float(p[0]) for p in pts]; py = [float(p[1]) for p in pts]
                            poly = [v for xy in pts for v in xy]
                            bbox = [float(np.min(px)), float(np.min(py)), float(np.max(px)), float(np.max(py))]
                            objs.append({"bbox": bbox, "bbox_mode": BoxMode.XYXY_ABS, "segmentation": [poly], "category_id": int(classes.index(lbl)), "iscrowd": 0})
                        rec["annotations"] = objs
                        dicts.append(rec)
                    return dicts

                def main():
                    ap = argparse.ArgumentParser()
                    ap.add_argument("--data", required=True)
                    ap.add_argument("--train", required=True)
                    ap.add_argument("--test", required=True)
                    ap.add_argument("--classes", required=True)
                    ap.add_argument("--model", required=True)
                    ap.add_argument("--ims-per-batch", type=int, default=2)
                    ap.add_argument("--base-lr", type=float, default=2.5e-4)
                    ap.add_argument("--max-iter", type=int, default=1000)
                    ap.add_argument("--num-workers", type=int, default=2)
                    ap.add_argument("--device", default="cuda")
                    ap.add_argument("--output-dir", default="detectron_runs")
                    args = ap.parse_args()

                    classes = [c.strip() for c in args.classes.split(",") if c.strip()]
                    train_dir = os.path.join(args.data, args.train)

                    train_name = "category_train_gui"
                    DatasetCatalog.register(train_name, lambda: get_data_dicts(train_dir, classes))
                    MetadataCatalog.get(train_name).set(thing_classes=classes)

                    cfg = get_cfg()
                    cfg.merge_from_file(model_zoo.get_config_file(args.model))
                    cfg.DATASETS.TRAIN = (train_name,)
                    cfg.DATASETS.TEST = ()
                    cfg.DATALOADER.NUM_WORKERS = int(args.num_workers)
                    cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(args.model)
                    cfg.SOLVER.IMS_PER_BATCH = int(args.ims_per_batch)
                    cfg.SOLVER.BASE_LR = float(args.base_lr)
                    cfg.SOLVER.MAX_ITER = int(args.max_iter)
                    cfg.MODEL.ROI_HEADS.NUM_CLASSES = len(classes)
                    cfg.MODEL.DEVICE = args.device
                    cfg.OUTPUT_DIR = args.output_dir
                    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

                    print("[Detectron] Starting training...")
                    print(f"[Detectron] Classes: {classes}")
                    print(f"[Detectron] Output: {cfg.OUTPUT_DIR}")
                    trainer = DefaultTrainer(cfg)
                    trainer.resume_or_load(resume=False)
                    trainer.train()

                if __name__ == "__main__":
                    main()
            """).strip("\n")

            tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
            tmp.write(runner); tmp.close()

            args = [
                tmp.name,
                "--data", data_root,
                "--train", train_dir,
                "--test",  test_dir,
                "--classes", classes_s,
                "--model", model_key,
                "--ims-per-batch", str(ims),
                "--base-lr", str(base_lr),
                "--max-iter", str(max_iter),
                "--num-workers", str(nworkers),
                "--device", device,
                "--output-dir", out_dir,
            ]
            return info, [(sys.executable, args)]

        if self.mode == "ddet":
            images_root = (self.voc_images_root.text() or "").strip()
            labels_root = (self.voc_labels_root.text() or "").strip()
            split       = (self.voc_split_name.text() or "train").strip()
            classes_s   = (self.voc_classes_edit.text() or "").strip()
            model_key   = self.d2det_model_combo.currentText().strip()
            ims         = int(self.d2det_ims_per_batch.value())
            max_iter    = int(self.d2det_max_iter.value())
            steps_s     = (self.d2det_steps_edit.text() or "").strip()
            workers     = int(self.d2det_workers.value())
            device      = self.d2det_device_combo.currentText().strip()
            out_dir     = (self.d2det_output_edit.text() or "detectron_det_runs").strip()
            start_w     = (self.d2det_weights_edit.text() or "").strip()

            if not images_root or not os.path.isdir(images_root):
                raise ValueError("Select a valid Images root (contains JPEGImages and ImageSets/Main).")
            if not labels_root or not os.path.isdir(labels_root):
                raise ValueError("Select a valid Labels root (folder with .xml).")
            if not classes_s:
                raise ValueError("Enter at least one class in Classes.")

            info = "[info] Detectron2 Detection (Pascal VOC) training"
            steps_py = "[" + ",".join([s.strip() for s in steps_s.split(",") if s.strip().isdigit()]) + "]" if steps_s else "[]"

            runner = textwrap.dedent(f"""
                import os, json, numpy as np, xml.etree.ElementTree as ET
                from typing import List, Tuple, Union
                from detectron2.structures import BoxMode
                from detectron2.data import DatasetCatalog, MetadataCatalog
                from detectron2.utils.file_io import PathManager
                from detectron2.engine import DefaultTrainer
                from detectron2.config import get_cfg
                from detectron2 import model_zoo

                CLASS_NAMES = [c.strip() for c in {classes_s!r}.split(",") if c.strip()]
                IMAGES_ROOT = r"{images_root}"
                LABELS_ROOT = r"{labels_root}"
                SPLIT_NAME  = r"{split}"
                MODEL_KEY   = r"{model_key}"
                IMS_PER_BATCH = int({ims})
                MAX_ITER      = int({max_iter})
                STEPS         = {steps_py}
                NUM_WORKERS   = int({workers})
                DEVICE        = r"{device}"
                OUT_DIR       = r"{out_dir}"
                START_WEIGHTS = r"{start_w}"

                def load_voc_instances(dirname: str, split: str, class_names: Union[List[str], Tuple[str, ...]]):
                    with PathManager.open(os.path.join(dirname, "ImageSets", "Main", split + ".txt")) as f:
                        fileids = np.loadtxt(f, dtype=str)

                    annotation_dirname = PathManager.get_local_path(LABELS_ROOT)
                    dicts = []
                    for fileid in fileids:
                        anno_file = os.path.join(annotation_dirname, fileid + ".xml")
                        jpeg_file = os.path.join(dirname, "JPEGImages", fileid + ".jpg")

                        with PathManager.open(anno_file) as f:
                            tree = ET.parse(f)

                        r = {{
                            "file_name": jpeg_file,
                            "image_id": fileid,
                            "height": int(tree.findall("./size/height")[0].text),
                            "width":  int(tree.findall("./size/width")[0].text),
                        }}
                        instances = []
                        for obj in tree.findall("object"):
                            cls = obj.find("name").text
                            if cls not in class_names:
                                continue
                            bbox = obj.find("bndbox")
                            bbox = [float(bbox.find(x).text) for x in ["xmin","ymin","xmax","ymax"]]
                            bbox[0] -= 1.0; bbox[1] -= 1.0
                            instances.append({{
                                "category_id": class_names.index(cls),
                                "bbox": bbox,
                                "bbox_mode": BoxMode.XYXY_ABS
                            }})
                        r["annotations"] = instances
                        dicts.append(r)
                    return dicts

                def register_voc(name, images_root, split, class_names=CLASS_NAMES):
                    DatasetCatalog.register(name, lambda: load_voc_instances(images_root, split, class_names))
                    MetadataCatalog.get(name).set(thing_classes=list(class_names), dirname=images_root, year=2023, split=split)

                def main():
                    train_name = "voc_train_gui"
                    register_voc(train_name, IMAGES_ROOT, SPLIT_NAME, CLASS_NAMES)

                    cfg = get_cfg()
                    cfg.merge_from_file(model_zoo.get_config_file(MODEL_KEY))
                    cfg.DATASETS.TRAIN = (train_name,)
                    cfg.DATASETS.TEST  = ()
                    cfg.DATALOADER.NUM_WORKERS = NUM_WORKERS
                    cfg.SOLVER.IMS_PER_BATCH = IMS_PER_BATCH
                    cfg.SOLVER.MAX_ITER = MAX_ITER
                    cfg.SOLVER.STEPS = STEPS
                    cfg.MODEL.ROI_HEADS.NUM_CLASSES = len(CLASS_NAMES)
                    cfg.MODEL.DEVICE = DEVICE
                    cfg.OUTPUT_DIR = OUT_DIR
                    os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

                    if START_WEIGHTS:
                        cfg.MODEL.WEIGHTS = START_WEIGHTS
                    else:
                        cfg.MODEL.WEIGHTS = model_zoo.get_checkpoint_url(MODEL_KEY)

                    print("[Detectron-Det] Classes:", CLASS_NAMES)
                    print("[Detectron-Det] Output:", cfg.OUTPUT_DIR)
                    trainer = DefaultTrainer(cfg)
                    trainer.resume_or_load(resume=False)
                    trainer.train()

                if __name__ == "__main__":
                    import numpy as np
                    main()
            """).strip("\n")

            tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
            tmp.write(runner); tmp.close()

            return info, [(sys.executable, [tmp.name])]

        if self.mode in ("seg", "det"):
            data_yaml = (self.data_edit.text() or "").strip()
            if not data_yaml or not os.path.isfile(data_yaml):
                raise ValueError("Please choose a valid data.yaml (Dataset → Browse…).")

            ver = self.ver_combo.currentText()
            info = f"[info] Requested Ultralytics major version: {ver} (ensure your environment has this installed)"

            if self.mode == "seg":
                weights = self._get_seg_weights()
            elif self.mode == "det":
                weights = self._get_det_weights()

            if not weights or not os.path.isfile(weights):
                raise FileNotFoundError(
                    "Weights not found. Either select a custom .pt file or place a default\n"
                    "model in one of these folders next to the app: models/, weights/, assets/."
                )

            fixed_yaml = self._fix_and_stage_data_yaml(data_yaml)

            if shutil.which("yolo"):
                program = "yolo"; prefix = []
            else:
                program = sys.executable; prefix = ["-m", "ultralytics"]

            if self.mode == "seg":
                args = prefix + self._build_args("segment", weights.replace("\\", "/"), fixed_yaml)
            else:
                args = prefix + self._build_args("detect", weights.replace("\\", "/"), fixed_yaml)

            return info, [(program, args)]

        raise ValueError("Unknown mode")

    def _build_args(self, task: str, w: str, y: str) -> list:
        device_val = self.device_combo.currentText().strip() if hasattr(self, "device_combo") else "cpu"
        return [
            "train", task, f"model={w}", f"data={y}",
            f"epochs={self.epochs.value()}", f"imgsz={self.imgsz.value()}",
            f"optimizer={self.opt.currentText()}", f"device={device_val}",
            "patience=0", f"batch={self.batch.value()}",
            f"project={self.project.text().strip()}", f"lr0={self.lr0.value()}",
        ]

    def _fmt_cmd(self, program: str, args: list[str]) -> str:
        return program + " " + " ".join(args)

    def _format_td(self, td):
        try:
            total = int(td.total_seconds())
            ms = int(td.microseconds / 1000)
            hh, rem = divmod(total, 3600)
            mm, ss = divmod(rem, 60)
            if hh:
                return f"{hh:d}:{mm:02d}:{ss:02d}.{ms:03d}"
            return f"{mm:d}:{ss:02d}.{ms:03d}"
        except Exception:
            return str(td)


    # ------------------------------------------------------------------
    # Review / process execution
    # ------------------------------------------------------------------
    def _on_build(self):
        try:
            info, commands = self.build_commands()
        except Exception as exc:
            QMessageBox.warning(self, "Build error", str(exc))
            return

        self.console.appendPlainText("\n=== Built Command(s) ===")
        self.console.appendPlainText(info)

        formatted = []
        for program, args in commands:
            command = self._fmt_cmd(program, args)
            formatted.append(command)
            self.console.appendPlainText(command)

        self.review_page.command_preview.setText(
            "  &&  ".join(formatted)
        )
        self._switch_stage("review")
        self.toast_requested.emit(
            "Command built",
            f"{len(commands)} training command(s) ready.",
        )

    def _on_start(self):
        try:
            info, commands = self.build_commands()
        except Exception as exc:
            QMessageBox.warning(self, "Cannot start", str(exc))
            return

        if self._proc is not None and self._proc.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.toast_requested.emit(
                "Training already running",
                "Wait for the current training process to finish.",
            )
            return

        device = (
            self.device_combo.currentText()
            if self.mode in {"seg", "det"}
            else self.d_device_combo.currentText()
            if self.mode == "dseg"
            else self.d2det_device_combo.currentText()
        )

        self.console.appendPlainText(
            f"\n=== Starting Training ({device.upper()}) ==="
        )
        self.console.appendPlainText(info)

        formatted = []
        for program, args in commands:
            command = self._fmt_cmd(program, args)
            formatted.append(command)
            self.console.appendPlainText(command)

        self.review_page.command_preview.setText(
            "  &&  ".join(formatted)
        )
        self._switch_stage("review")

        self._overall_start = datetime.now()
        self.console.appendPlainText(
            f"[benchmark] Overall start: {self._overall_start.isoformat()}"
        )

        self._run_commands_sequential(commands)
        self.toast_requested.emit(
            "Training started",
            f"{self.MODE_META[self.mode][0]} is running.",
        )

    def _pipe(self, data: QtCore.QByteArray):
        try:
            text = bytes(data).decode("utf-8", errors="ignore")
            if text:
                self.console.appendPlainText(text.rstrip())
            scrollbar = self.console.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception:
            pass

    def _run_commands_sequential(self, commands: list):
        self.btn_start.setEnabled(False)
        self.btn_build.setEnabled(False)
        self.project_selector.setEnabled(False)

        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(
            QtCore.QProcess.ProcessChannelMode.MergedChannels
        )
        self._proc.readyRead.connect(
            lambda: self._pipe(self._proc.readAll())
        )
        self._proc.finished.connect(self._next_or_done)

        self._cmds = commands
        self._idx = -1
        self._next_or_done()

    def _next_or_done(self, *_):
        self._idx += 1

        if self._idx >= len(self._cmds):
            end = datetime.now()
            self.console.appendPlainText("\n=== All trainings finished ===")

            if self._overall_start is not None:
                self.console.appendPlainText(
                    "[benchmark] Overall end: "
                    f"{end.isoformat()} — total duration "
                    f"{self._format_td(end - self._overall_start)}"
                )
            else:
                self.console.appendPlainText(
                    f"[benchmark] Overall end: {end.isoformat()}"
                )

            self.btn_start.setEnabled(True)
            self.btn_build.setEnabled(True)
            self.project_selector.setEnabled(bool(self.projects))
            self.toast_requested.emit(
                "Training completed",
                f"{self.MODE_META[self.mode][0]} process finished.",
            )
            return

        program, args = self._cmds[self._idx]
        self.console.appendPlainText(
            f"\n[Running {self._idx + 1}/{len(self._cmds)}] -> "
            + program
            + " "
            + " ".join(args)
        )
        self._proc.start(program, args)

    # ------------------------------------------------------------------
    # Run dashboard
    # ------------------------------------------------------------------
    def _open_dashboard(self):
        base = Path(self.project.text().strip() or "runs")
        try:
            base.mkdir(parents=True, exist_ok=True)
            api_url, self._dash_httpd = start_dashboard_server(base)
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl(f"{api_url}/ui?theme=dark")
            )
            self.toast_requested.emit(
                "Training Dashboard",
                f"Dashboard opened for {base}",
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Dashboard",
                f"Could not open training dashboard.\n\n{exc}",
            )

    def shutdown(self):
        try:
            if self._proc is not None and self._proc.state() != QtCore.QProcess.ProcessState.NotRunning:
                self._proc.terminate()
                if not self._proc.waitForFinished(1500):
                    self._proc.kill()
        except Exception:
            pass

        try:
            if self._dash_httpd is not None:
                self._dash_httpd.shutdown()
                self._dash_httpd.server_close()
                self._dash_httpd = None
        except Exception:
            pass


TrainingTool = TrainingPageQt6
