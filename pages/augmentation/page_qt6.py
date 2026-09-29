"""EYRES AI - PyQt6 Augmentation Tool.

Final UI based on the approved modern augmentation preview:
- no top Capture -> Annotation -> Augmentation -> Training indicator
- project/dataset/status context strip
- icon-based internal navigation
- Dataset Setup
- Settings with Original vs Augmented preview
- Review & Run
- Preprocessing
- Gamma Correction

The production augmentation, LabelMe -> YOLO segmentation, preprocessing and
gamma algorithms are preserved from the existing augmentation_tool.py, while
all widgets in this page are PyQt6.
"""
from __future__ import annotations

import json
import os
import random
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt, pyqtSignal, pyqtProperty
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
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

try:
    from preprocessing_functions import process_folder_with_params
except Exception:
    process_folder_with_params = None


# Compatibility aliases used by the preserved worker classes below.
QThread = QtCore.QThread
pyqtSignal = QtCore.pyqtSignal

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


def _asset(name: str) -> str:
    root = Path(__file__).resolve().parents[2]
    return str(root / "ui" / "assets" / "augmentation_icons" / name)


def _project_id(project: dict) -> str:
    return str(project.get("_id") or project.get("id") or "")


def _safe_name(value: str) -> str:
    value = "".join(
        c if c.isalnum() or c in "-_ " else "_"
        for c in str(value or "Project")
    )
    return value.strip().replace(" ", "_") or "Project"


def _cv_to_pixmap(image: np.ndarray | None, width: int, height: int) -> QtGui.QPixmap:
    if image is None:
        return QtGui.QPixmap()

    frame = np.asarray(image)
    if frame.ndim == 2:
        frame = np.ascontiguousarray(frame)
        qimg = QtGui.QImage(
            frame.data,
            frame.shape[1],
            frame.shape[0],
            int(frame.strides[0]),
            QtGui.QImage.Format.Format_Grayscale8,
        ).copy()
    else:
        if frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
        else:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = np.ascontiguousarray(frame)
        qimg = QtGui.QImage(
            frame.data,
            frame.shape[1],
            frame.shape[0],
            int(frame.strides[0]),
            QtGui.QImage.Format.Format_RGB888,
        ).copy()

    return QtGui.QPixmap.fromImage(qimg).scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class ProjectComboBox(QComboBox):
    """White non-native popup so Windows dark popup palettes cannot leak in."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectSelector")
        self.setMinimumHeight(33)
        view = QListView(self)
        view.setObjectName("ProjectSelectorView")
        view.setUniformItemSizes(True)
        view.setSpacing(1)
        self.setView(view)
        self.setMaxVisibleItems(8)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("#2868E8" if self.hasFocus() else "#526A86"))
        pen.setWidthF(1.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        cx = self.width() - 14.0
        cy = self.height() / 2.0 - 1.0
        painter.drawLine(QtCore.QPointF(cx - 4, cy - 2), QtCore.QPointF(cx, cy + 2))
        painter.drawLine(QtCore.QPointF(cx, cy + 2), QtCore.QPointF(cx + 4, cy - 2))
        painter.end()

    def showPopup(self):
        self.view().setMinimumWidth(max(260, self.width()))
        super().showPopup()
        QtCore.QTimer.singleShot(0, self._position_popup)

    def _position_popup(self):
        try:
            popup = self.view().window()
            popup.move(self.mapToGlobal(QtCore.QPoint(0, self.height() + 4)))
            popup.resize(max(260, self.width()), popup.height())
        except Exception:
            pass


class FieldComboBox(QComboBox):
    """Controlled white popup for form dropdowns in the Augmentation page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FieldCombo")
        self.setMinimumHeight(35)
        self.setMaxVisibleItems(7)

        view = QListView(self)
        view.setObjectName("FieldComboView")
        view.setUniformItemSizes(True)
        view.setSpacing(1)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setView(view)

    def paintEvent(self, event):
        # Draw the normal combo first, then replace the Windows/native arrow
        # with the same clean chevron used elsewhere in the EYRES Qt6 UI.
        super().paintEvent(event)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)

        color = QtGui.QColor("#2868E8" if self.hasFocus() else "#526A86")
        pen = QtGui.QPen(color)
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

            visible_rows = min(
                max(1, self.count()),
                max(1, self.maxVisibleItems()),
            )
            row_height = 32
            popup_height = visible_rows * row_height + 12
            popup_width = max(self.width(), 150)

            pos = self.mapToGlobal(
                QtCore.QPoint(0, self.height() + 4)
            )
            popup.move(pos)
            popup.resize(popup_width, popup_height)

            current = self.view().currentIndex()
            if current.isValid():
                self.view().scrollTo(
                    current,
                    QtWidgets.QAbstractItemView.ScrollHint.PositionAtCenter,
                )
        except Exception:
            pass


class RailNavButton(QPushButton):
    """Augmentation rail button with a padded, non-clipping icon animation."""

    def __init__(self, key: str, text: str, icon_name: str, parent=None):
        super().__init__(text, parent)
        self.key = key
        self._motion = 0.0
        self._hovered = False
        self._normal_icon = QtGui.QIcon(_asset(f"{icon_name}.svg"))
        self._active_icon = QtGui.QIcon(_asset(f"{icon_name}_active.svg"))

        self.setObjectName("AugRailButton")
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

    def _animate(self, value):
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(float(value))
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



class SwitchButton(QPushButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setFixedSize(42, 23)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self.update)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        rect = QtCore.QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QColor("#2868E8" if self.isChecked() else "#CAD5E2"))
        painter.drawRoundedRect(rect, 11, 11)
        x = self.width() - 12 if self.isChecked() else 12
        painter.setBrush(QtGui.QColor("#FFFFFF"))
        painter.drawEllipse(QtCore.QPointF(x, self.height() / 2), 8.2, 8.2)
        painter.end()


class ContextCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("ContextCard")
        self.setMinimumHeight(65)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(10, 8, 10, 8)
        self.layout_box.setSpacing(3)
        self.layout_box.addWidget(QLabel(title, objectName="ContextKey"))

    def add_value(self, value="—"):
        label = QLabel(value, objectName="ContextValue")
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.layout_box.addWidget(label)
        return label


class InnerCard(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("InnerCard")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(14, 13, 14, 13)
        self.box.setSpacing(8)
        self.box.addWidget(QLabel(title, objectName="CardTitle"))
        if subtitle:
            sub = QLabel(subtitle, objectName="CardSubtitle")
            sub.setWordWrap(True)
            self.box.addWidget(sub)


class FieldBlock(QWidget):
    def __init__(self, title: str, widget: QWidget, helper: str = "", parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)
        box.addWidget(QLabel(title, objectName="FieldLabel"))
        box.addWidget(widget)
        if helper:
            label = QLabel(helper, objectName="FieldHelper")
            label.setWordWrap(True)
            box.addWidget(label)




# ================================================================
# Preserved production worker implementations from augmentation_tool.py
# ================================================================

class GammaWorker(QThread):
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished_signal = pyqtSignal(tuple)  # (processed_count, output_dir)
    error = pyqtSignal(str)

    def __init__(self, input_dir: str, gamma_exponent: float):
        super().__init__()
        self.input_dir = input_dir
        self.gamma_exponent = gamma_exponent

    def run(self):
        try:
            in_dir = self.input_dir
            out_dir = os.path.join(in_dir, "Gamma_corrected")
            os.makedirs(out_dir, exist_ok=True)

            files = [f for f in os.listdir(in_dir) if os.path.isfile(os.path.join(in_dir, f))]
            exts = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
            img_files = [f for f in files if os.path.splitext(f)[1].lower() in exts]

            total = len(img_files)
            if total == 0:
                self.error.emit("No images found in the selected folder.")
                return

            processed = 0
            self.message.emit(f"Gamma exponent = {self.gamma_exponent:.3f}")
            self.message.emit(f"Output folder = {out_dir}")

            for i, img_file in enumerate(img_files, 1):
                src = os.path.join(in_dir, img_file)
                dst = os.path.join(out_dir, img_file)

                gray = cv2.imread(src, cv2.IMREAD_GRAYSCALE)
                if gray is None:
                    self.message.emit(f"[SKIP] Failed to read {img_file}")
                    continue

                norm = gray.astype(np.float32) / 255.0
                gamma_corrected = np.power(norm, self.gamma_exponent)
                out = np.clip(gamma_corrected * 255.0, 0, 255).astype(np.uint8)

                ok = cv2.imwrite(dst, out)
                if ok:
                    self.message.emit(f"[OK] Saved {img_file}")
                else:
                    self.message.emit(f"[ERR] Could not save {img_file}")

                processed += 1
                self.progress.emit(int(i * 100 / total))

            self.finished_signal.emit((processed, out_dir))
        except Exception as e:
            self.error.emit(str(e))

class AugmentationWorker(QThread):
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished_signal = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config

    def run(self):
        try:
            self.perform_augmentation()
        except Exception as e:
            self.error.emit(str(e))

    def perform_augmentation(self):
        random.seed(self.config['seed'])
        input_dir = Path(self.config['input_dir'])
        root = Path(self.config['output_dir'])
        self.make_dataset_dirs(root)

        pairs = self.collect_pairs(input_dir)
        if not pairs:
            self.error.emit("No (image, json) pairs found.")
            return

        class_names = self.collect_labels_from_jsons(pairs)
        if not class_names:
            self.error.emit("No labels found in JSONs.")
            return

        class_map = self.class_map_from_names(class_names)
        self.message.emit(f"Detected {len(class_names)} classes: {class_names}")

        stems = [p[0].stem for p in pairs]
        random.shuffle(stems)
        cutoff = int(len(stems) * self.config['train_ratio'])
        train_stems = set(stems[:cutoff])
        valid_stems = set(stems[cutoff:])

        total_files = len(pairs)
        processed = 0

        for img_path, json_path in pairs:
            stem = img_path.stem
            split = "train" if stem in train_stems else "valid"

            img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
            if img is None:
                self.message.emit(f"Skipping unreadable image: {img_path}")
                continue

            _, shapes, W_json, H_json, _ = self.load_labelme(json_path)
            H_img, W_img = img.shape[:2]
            W, H = (W_img, H_img) if (W_img, H_img) != (W_json, H_json) else (W_json, H_json)

            img_dir = root / split / "images"
            lbl_dir = root / split / "labels"

            out_img = img_dir / f"{stem}.jpg"
            out_txt = lbl_dir / f"{stem}.txt"
            self.save_image(out_img, img)
            self.write_yolo_txt(out_txt, shapes, W, H, class_map)

            # flips
            if self.config['flip_horizontal']:
                img_h = cv2.flip(img, 1)
                shapes_h = self.flipped_shapes(shapes, W, H, horizontal=True, vertical=False)
                self.save_image(img_dir / f"{stem}_flipH.jpg", img_h)
                self.write_yolo_txt(lbl_dir / f"{stem}_flipH.txt", shapes_h, W, H, class_map)

            if self.config['flip_vertical']:
                img_v = cv2.flip(img, 0)
                shapes_v = self.flipped_shapes(shapes, W, H, horizontal=False, vertical=True)
                self.save_image(img_dir / f"{stem}_flipV.jpg", img_v)
                self.write_yolo_txt(lbl_dir / f"{stem}_flipV.txt", shapes_v, W, H, class_map)

            # brightness
            if self.config['brightness_pct'] != 0:
                pct = int(abs(self.config['brightness_pct']))
                img_bp = self.adjust_brightness(img, +self.config['brightness_pct'])
                img_bm = self.adjust_brightness(img, -self.config['brightness_pct'])
                self.save_image(img_dir / f"{stem}_bplus{pct}.jpg", img_bp)
                self.save_image(img_dir / f"{stem}_bminus{pct}.jpg", img_bm)
                self.write_yolo_txt(lbl_dir / f"{stem}_bplus{pct}.txt", shapes, W, H, class_map)
                self.write_yolo_txt(lbl_dir / f"{stem}_bminus{pct}.txt", shapes, W, H, class_map)

            # saturation
            if self.config['saturation_pct'] != 0:
                pct = int(abs(self.config['saturation_pct']))
                img_sp = self.adjust_saturation(img, +self.config['saturation_pct'])
                img_sm = self.adjust_saturation(img, -self.config['saturation_pct'])
                self.save_image(img_dir / f"{stem}_splus{pct}.jpg", img_sp)
                self.save_image(img_dir / f"{stem}_sminus{pct}.jpg", img_sm)
                self.write_yolo_txt(lbl_dir / f"{stem}_splus{pct}.txt", shapes, W, H, class_map)
                self.write_yolo_txt(lbl_dir / f"{stem}_sminus{pct}.txt", shapes, W, H, class_map)

            processed += 1
            self.progress.emit(int((processed / total_files) * 100))
            self.message.emit(f"Processed {stem}")

        self.write_yaml(root, class_names)
        self.finished_signal.emit(
            f"Augmentation completed! Processed {total_files} image pairs.\nClasses: {class_names}"
        )

    # ---- helpers ----
    def make_dataset_dirs(self, root: Path):
        for split in ["train", "valid"]:
            self.ensure_dir(root / split / "images")
            self.ensure_dir(root / split / "labels")

    def ensure_dir(self, p: Path):
        p.mkdir(parents=True, exist_ok=True)

    def is_image_file(self, p: Path):
        return p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

    def collect_pairs(self, input_dir: Path):
        images = [p for p in input_dir.rglob("*") if self.is_image_file(p)]
        pairs = []
        for img in images:
            json_path = img.with_suffix(".json")
            if json_path.exists():
                pairs.append((img, json_path))
        return pairs

    def load_labelme(self, json_path: Path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            W = int(data["imageWidth"])
            H = int(data["imageHeight"])
            shapes = data.get("shapes", [])
            stem = Path(data.get("imagePath", json_path.stem)).stem

            self.message.emit(f"Loaded JSON: {json_path.name}")
            self.message.emit(f"Image dimensions: {W}x{H}")
            self.message.emit(f"Number of shapes: {len(shapes)}")
            for i, shape in enumerate(shapes):
                self.message.emit(
                    f"Shape {i}: label='{shape.get('label')}', type='{shape.get('shape_type')}', points={len(shape.get('points', []))}"
                )
            return data, shapes, W, H, stem
        except Exception as e:
            self.message.emit(f"Error loading {json_path}: {str(e)}")
            raise

    def collect_labels_from_jsons(self, pairs):
        labels, seen = [], set()
        for _, jpath in pairs:
            try:
                _, shapes, _, _, _ = self.load_labelme(jpath)
            except Exception:
                continue
            for sh in shapes:
                lbl = str(sh.get("label", "unknown"))
                if lbl not in seen:
                    seen.add(lbl)
                    labels.append(lbl)
        return sorted(labels)

    def class_map_from_names(self, names):
        return {name: idx for idx, name in enumerate(names)}

    def yolo_seg_txt_lines(self, shapes, W, H, class_map):
        lines = []
        for sh in shapes:
            label = str(sh.get("label", "unknown"))
            if label not in class_map:
                continue

            pts = sh.get("points", [])
            shape_type = sh.get("shape_type", "polygon")

            if shape_type == "rectangle" and len(pts) == 2:
                x1, y1 = float(pts[0][0]), float(pts[0][1])
                x2, y2 = float(pts[1][0]), float(pts[1][1])
                pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
            elif shape_type != "polygon":
                continue

            if len(pts) < 3:
                continue

            cls_id = class_map[label]
            flat_norm = []
            for x, y in pts:
                nx = min(1.0, max(0.0, float(x) / float(W)))
                ny = min(1.0, max(0.0, float(y) / float(H)))
                flat_norm.extend([nx, ny])

            formatted_points = []
            for v in flat_norm:
                s = f"{v:.{self.config['float_precision']}f}"
                if '.' in s:
                    s = s.rstrip('0').rstrip('.')
                formatted_points.append(s)

            lines.append(str(cls_id) + " " + " ".join(formatted_points))
        return lines

    def write_yolo_txt(self, out_txt: Path, shapes, W, H, class_map):
        out_txt.parent.mkdir(parents=True, exist_ok=True)
        lines = self.yolo_seg_txt_lines(shapes, W, H, class_map)
        with open(out_txt, "w", encoding="utf-8") as f:
            if lines:
                f.write("\n".join(lines) + "\n")

    def save_image(self, out_img: Path, img):
        out_img.parent.mkdir(parents=True, exist_ok=True)
        if out_img.suffix.lower() in {".jpg", ".jpeg"}:
            cv2.imwrite(str(out_img), img, [int(cv2.IMWRITE_JPEG_QUALITY), self.config['jpeg_quality']])
        else:
            cv2.imwrite(str(out_img), img)

    def flip_points_horizontal(self, points, W):
        return [[(W - 1 - float(x)), float(y)] for (x, y) in points]

    def flip_points_vertical(self, points, H):
        return [[float(x), (H - 1 - float(y))] for (x, y) in points]

    def flipped_shapes(self, shapes, W, H, horizontal=False, vertical=False):
        new_shapes = []
        for sh in shapes:
            pts = sh.get("points", [])
            new_pts = [list(p) for p in pts]
            if horizontal:
                new_pts = self.flip_points_horizontal(new_pts, W)
            if vertical:
                new_pts = self.flip_points_vertical(new_pts, H)
            nsh = dict(sh)
            nsh["points"] = new_pts
            new_shapes.append(nsh)
        return new_shapes

    def adjust_brightness(self, img, percent):
        beta = float(percent) * 255.0 / 100.0
        return cv2.convertScaleAbs(img, alpha=1.0, beta=beta)

    def adjust_saturation(self, img, percent):
        factor = 1.0 + float(percent) / 100.0
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        s = np.clip(s.astype(np.float32) * factor, 0, 255).astype(np.uint8)
        hsv2 = cv2.merge([h, s, v])
        return cv2.cvtColor(hsv2, cv2.COLOR_HSV2BGR)

    def write_yaml(self, root: Path, class_names):
        yaml_text = f"""train: train/images
val: valid/images

nc: {len(class_names)}
names: [{", ".join("'" + n.replace("'", "''") + "'" for n in class_names)}]
"""
        (root / "data.yaml").write_text(yaml_text, encoding="utf-8")

class PreprocessingThread(QThread):
    finished = pyqtSignal(tuple)

    def __init__(self, input_folder, dpi_value, denoise_h, denoise_hcolor, kernel_size, iterations):
        super().__init__()
        self.input_folder = input_folder
        self.dpi_value = dpi_value
        self.denoise_h = denoise_h
        self.denoise_hcolor = denoise_hcolor
        self.kernel_size = kernel_size
        self.iterations = iterations

    def run(self):
        try:
            if process_folder_with_params is None:
                raise RuntimeError("preprocessing_functions.py is not available in the project environment.")
            processed_count, output_folder = process_folder_with_params(
                self.input_folder, self.dpi_value, self.denoise_h, self.denoise_hcolor,
                7, 15, self.kernel_size, self.iterations
            )
            self.finished.emit((processed_count, output_folder))
        except Exception as e:
            print(f"Error in preprocessing: {e}")
            self.finished.emit((0, ""))



class DatasetSetupPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Dataset Setup", objectName="PageSectionTitle"))
        copy.addWidget(
            QLabel(
                "Select source/output folders and configure how the augmented dataset will be written.",
                objectName="PageSectionSubtitle",
            )
        )
        header.addLayout(copy, 1)
        badge = QLabel("Dataset Setup", objectName="NeutralBadge")
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(11)

        locations = InnerCard(
            "Dataset Locations",
            "Choose where images are read from and where generated data is saved.",
        )
        self.input_edit = QLineEdit(objectName="PathEdit")
        self.input_edit.setPlaceholderText("Select source folder...")
        self.output_edit = QLineEdit(objectName="PathEdit")
        self.output_edit.setPlaceholderText("Select destination folder...")

        for title, edit, callback, helper in (
            (
                "Input directory",
                self.input_edit,
                self._browse_input,
                "Source images and matching LabelMe JSON files.",
            ),
            (
                "Output directory",
                self.output_edit,
                self._browse_output,
                "Generated train/validation images, labels and data.yaml.",
            ),
        ):
            locations.box.addWidget(QLabel(title, objectName="FieldLabel"))
            row = QHBoxLayout()
            row.setSpacing(7)
            row.addWidget(edit, 1)
            browse = QPushButton("Browse", objectName="SecondaryButton")
            browse.setFixedHeight(36)
            browse.clicked.connect(callback)
            row.addWidget(browse)
            locations.box.addLayout(row)
            help_label = QLabel(helper, objectName="FieldHelper")
            locations.box.addWidget(help_label)

        output = InnerCard(
            "Output Configuration",
            "Control split reproducibility and generated image format.",
        )

        self.train_ratio = FieldComboBox()
        self.train_ratio.addItems(["90 / 10", "85 / 15", "80 / 20", "75 / 25", "70 / 30"])
        self.train_ratio.setCurrentText("80 / 20")

        self.quality = QSpinBox(objectName="FieldSpin")
        self.quality.setRange(1, 100)
        self.quality.setValue(95)
        self.quality.setSuffix(" %")

        self.seed = QSpinBox(objectName="FieldSpin")
        self.seed.setRange(0, 999999)
        self.seed.setValue(42)

        self.float_precision = FieldComboBox()
        self.float_precision.addItems(["4", "6", "8", "10", "12", "16"])
        self.float_precision.setCurrentText("16")

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(FieldBlock("Train / validation split", self.train_ratio), 0, 0)
        grid.addWidget(FieldBlock("JPEG quality", self.quality), 0, 1)
        grid.addWidget(FieldBlock("Random seed", self.seed), 1, 0)
        grid.addWidget(FieldBlock("Float precision", self.float_precision), 1, 1)
        output.box.addLayout(grid)
        output.box.addStretch(1)

        cards.addWidget(locations, 1)
        cards.addWidget(output, 1)
        root.addLayout(cards)

        self.validation = QLabel("", objectName="ValidationMessage")
        self.validation.hide()
        root.addWidget(self.validation)

        summary = QFrame(objectName="ReadinessStrip")
        sr = QHBoxLayout(summary)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.setSpacing(0)
        self.input_summary = self._summary("INPUT DATASET", "Not selected")
        self.output_summary = self._summary("OUTPUT DATASET", "Not selected")
        self.split_summary = self._summary("SPLIT", "80 / 20")
        self.seed_summary = self._summary("REPRODUCIBILITY", "Seed 42", success=True)
        for cell in (
            self.input_summary,
            self.output_summary,
            self.split_summary,
            self.seed_summary,
        ):
            sr.addWidget(cell, 1)
        root.addWidget(summary)
        root.addStretch(1)

        for signal in (
            self.input_edit.textChanged,
            self.output_edit.textChanged,
            self.train_ratio.currentTextChanged,
            self.seed.valueChanged,
            self.quality.valueChanged,
            self.float_precision.currentTextChanged,
        ):
            signal.connect(self._changed)
        self._changed()

    def _summary(self, title, value, success=False):
        host = QWidget(objectName="SummaryCell")
        box = QVBoxLayout(host)
        box.setContentsMargins(12, 9, 12, 9)
        box.setSpacing(3)
        box.addWidget(QLabel(title, objectName="SummaryCaption"))
        label = QLabel(value, objectName="SummaryValueSuccess" if success else "SummaryValue")
        box.addWidget(label)
        host.value_label = label
        return host

    def _changed(self):
        inp = self.input_edit.text().strip()
        out = self.output_edit.text().strip()
        self.input_summary.value_label.setText("Selected" if inp else "Not selected")
        self.output_summary.value_label.setText("Selected" if out else "Not selected")
        self.split_summary.value_label.setText(self.train_ratio.currentText())
        self.seed_summary.value_label.setText(f"Seed {self.seed.value()}")
        self.changed.emit()

    def _browse_input(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Input Dataset",
            self.input_edit.text().strip() or str(Path.home()),
        )
        if folder:
            self.input_edit.setText(folder)

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Dataset",
            self.output_edit.text().strip() or str(Path.home()),
        )
        if folder:
            self.output_edit.setText(folder)

    def get_config(self) -> dict:
        train = int(self.train_ratio.currentText().split("/")[0].strip()) / 100.0
        return {
            "input_dir": self.input_edit.text().strip(),
            "output_dir": self.output_edit.text().strip(),
            "train_ratio": train,
            "seed": int(self.seed.value()),
            "jpeg_quality": int(self.quality.value()),
            "float_precision": int(self.float_precision.currentText()),
        }

    def set_paths(self, input_dir: str = "", output_dir: str = ""):
        if input_dir:
            self.input_edit.setText(input_dir)
        if output_dir:
            self.output_edit.setText(output_dir)


class TransformCard(QFrame):
    changed = pyqtSignal()

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.setObjectName("TransformCard")
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(13, 12, 13, 12)
        self.box.setSpacing(8)
        self.box.addWidget(QLabel(title, objectName="TransformTitle"))
        desc = QLabel(subtitle, objectName="TransformSubtitle")
        desc.setWordWrap(True)
        self.box.addWidget(desc)


class SettingsPage(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_image = None
        self._source_name = ""
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Augmentation Settings", objectName="PageSectionTitle"))
        copy.addWidget(
            QLabel(
                "Choose controlled transformations and verify them before running the dataset job.",
                objectName="PageSectionSubtitle",
            )
        )
        header.addLayout(copy, 1)
        self.selected_badge = QLabel("3 selected", objectName="NeutralBadge")
        header.addWidget(self.selected_badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(10)

        flip = TransformCard(
            "Flip",
            "Mirror samples while keeping annotation coordinates aligned.",
        )
        self.flip_h = SwitchButton(True)
        self.flip_v = SwitchButton(False)
        flip.box.addLayout(self._switch_row("Horizontal flip", self.flip_h))
        flip.box.addLayout(self._switch_row("Vertical flip", self.flip_v))
        flip.box.addStretch(1)

        brightness = TransformCard(
            "Brightness",
            "Create brighter and darker variations around each source image.",
        )
        self.brightness_enabled = SwitchButton(True)
        brightness.box.addLayout(
            self._switch_row("Enable brightness", self.brightness_enabled)
        )
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.setValue(20)
        self.brightness_spin = QDoubleSpinBox(objectName="SmallSpin")
        self.brightness_spin.setRange(0, 100)
        self.brightness_spin.setValue(20)
        self.brightness_spin.setSuffix(" %")
        self.brightness_spin.setFixedWidth(84)
        brightness.box.addWidget(QLabel("Variation", objectName="FieldLabel"))
        row = QHBoxLayout()
        row.addWidget(self.brightness_slider, 1)
        row.addWidget(self.brightness_spin)
        brightness.box.addLayout(row)
        brightness.box.addStretch(1)

        saturation = TransformCard(
            "Saturation",
            "Create lower and higher colour-intensity variants.",
        )
        self.saturation_enabled = SwitchButton(True)
        saturation.box.addLayout(
            self._switch_row("Enable saturation", self.saturation_enabled)
        )
        self.saturation_slider = QSlider(Qt.Orientation.Horizontal)
        self.saturation_slider.setRange(0, 100)
        self.saturation_slider.setValue(20)
        self.saturation_spin = QDoubleSpinBox(objectName="SmallSpin")
        self.saturation_spin.setRange(0, 100)
        self.saturation_spin.setValue(20)
        self.saturation_spin.setSuffix(" %")
        self.saturation_spin.setFixedWidth(84)
        saturation.box.addWidget(QLabel("Variation", objectName="FieldLabel"))
        row2 = QHBoxLayout()
        row2.addWidget(self.saturation_slider, 1)
        row2.addWidget(self.saturation_spin)
        saturation.box.addLayout(row2)
        saturation.box.addStretch(1)

        for card in (flip, brightness, saturation):
            cards.addWidget(card, 1)
        root.addLayout(cards)

        # Approved modern original vs augmented preview.
        preview = QFrame(objectName="PreviewWorkbench")
        pv = QVBoxLayout(preview)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        phead = QFrame(objectName="PreviewHeader")
        ph = QHBoxLayout(phead)
        ph.setContentsMargins(13, 10, 13, 10)
        pcopy = QVBoxLayout()
        pcopy.setSpacing(2)
        pcopy.addWidget(QLabel("Augmentation Preview", objectName="CardTitle"))
        pcopy.addWidget(
            QLabel(
                "Compare the source image against the current configuration.",
                objectName="CardSubtitle",
            )
        )
        ph.addLayout(pcopy, 1)
        self.preview_badge = QLabel("3 transforms", objectName="NeutralBadge")
        ph.addWidget(self.preview_badge)
        pv.addWidget(phead)

        grid = QHBoxLayout()
        grid.setContentsMargins(10, 10, 10, 10)
        grid.setSpacing(10)

        self.original_host, self.original_image, self.original_name = self._preview_pane(
            "ORIGINAL"
        )
        self.aug_host, self.aug_image, self.aug_name = self._preview_pane(
            "AUGMENTED PREVIEW"
        )
        grid.addWidget(self.original_host, 1)
        grid.addWidget(self.aug_host, 1)

        holder = QWidget()
        holder.setLayout(grid)
        pv.addWidget(holder)
        root.addWidget(preview, 1)

        summary = InnerCard(
            "Transformation Summary",
            "The run creates annotation-safe image variants using the settings above.",
        )
        self.summary_label = QLabel("", objectName="SummaryText")
        self.summary_label.setWordWrap(True)
        summary.box.addWidget(self.summary_label)
        root.addWidget(summary)

        self.brightness_slider.valueChanged.connect(self.brightness_spin.setValue)
        self.brightness_spin.valueChanged.connect(
            lambda v: self.brightness_slider.setValue(int(v))
        )
        self.saturation_slider.valueChanged.connect(self.saturation_spin.setValue)
        self.saturation_spin.valueChanged.connect(
            lambda v: self.saturation_slider.setValue(int(v))
        )

        for signal in (
            self.flip_h.toggled,
            self.flip_v.toggled,
            self.brightness_enabled.toggled,
            self.saturation_enabled.toggled,
            self.brightness_spin.valueChanged,
            self.saturation_spin.valueChanged,
        ):
            signal.connect(self._settings_changed)
        self._settings_changed()

    def _preview_pane(self, title):
        frame = QFrame(objectName="PreviewPane")
        box = QVBoxLayout(frame)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)

        head = QFrame(objectName="PreviewPaneHeader")
        row = QHBoxLayout(head)
        row.setContentsMargins(9, 0, 9, 0)
        row.addWidget(QLabel(title, objectName="PreviewPaneTitle"))
        row.addStretch(1)
        name = QLabel("No image", objectName="PreviewPaneName")
        row.addWidget(name)
        box.addWidget(head)

        image = QLabel("Select a dataset to preview", objectName="PreviewImage")
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image.setMinimumHeight(190)
        image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        box.addWidget(image, 1)
        return frame, image, name

    def _switch_row(self, text, switch):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel(text, objectName="SwitchLabel"))
        row.addStretch(1)
        row.addWidget(switch)
        return row

    def get_config(self) -> dict:
        return {
            "flip_horizontal": self.flip_h.isChecked(),
            "flip_vertical": self.flip_v.isChecked(),
            "brightness_pct": (
                float(self.brightness_spin.value())
                if self.brightness_enabled.isChecked()
                else 0.0
            ),
            "saturation_pct": (
                float(self.saturation_spin.value())
                if self.saturation_enabled.isChecked()
                else 0.0
            ),
        }

    def set_source_image(self, path: str | None):
        self._source_image = None
        self._source_name = ""
        if path:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is not None:
                self._source_image = image
                self._source_name = Path(path).name
        self._render_preview()

    def _settings_changed(self, *_):
        count = 0
        if self.flip_h.isChecked():
            count += 1
        if self.flip_v.isChecked():
            count += 1
        if self.brightness_enabled.isChecked() and self.brightness_spin.value() > 0:
            count += 1
        if self.saturation_enabled.isChecked() and self.saturation_spin.value() > 0:
            count += 1
        self.selected_badge.setText(f"{count} selected")
        self.preview_badge.setText(f"{count} transform{'s' if count != 1 else ''}")

        parts = []
        if self.flip_h.isChecked():
            parts.append("Horizontal flip")
        if self.flip_v.isChecked():
            parts.append("Vertical flip")
        if self.brightness_enabled.isChecked():
            parts.append(f"Brightness ±{self.brightness_spin.value():.0f}%")
        if self.saturation_enabled.isChecked():
            parts.append(f"Saturation ±{self.saturation_spin.value():.0f}%")
        self.summary_label.setText("  •  ".join(parts) if parts else "No transformations selected.")
        self._render_preview()
        self.changed.emit()

    def _render_preview(self):
        if self._source_image is None:
            self.original_image.setPixmap(QtGui.QPixmap())
            self.aug_image.setPixmap(QtGui.QPixmap())
            self.original_image.setText("Select a dataset to preview")
            self.aug_image.setText("Preview unavailable")
            self.original_name.setText("No image")
            self.aug_name.setText("No image")
            return

        original = self._source_image.copy()
        augmented = original.copy()

        if self.flip_h.isChecked():
            augmented = cv2.flip(augmented, 1)
        if self.flip_v.isChecked():
            augmented = cv2.flip(augmented, 0)

        if self.brightness_enabled.isChecked() and self.brightness_spin.value():
            beta = float(self.brightness_spin.value()) * 255.0 / 100.0
            augmented = cv2.convertScaleAbs(augmented, alpha=1.0, beta=beta)

        if self.saturation_enabled.isChecked() and self.saturation_spin.value():
            factor = 1.0 + float(self.saturation_spin.value()) / 100.0
            hsv = cv2.cvtColor(augmented, cv2.COLOR_BGR2HSV)
            h, s, v = cv2.split(hsv)
            s = np.clip(s.astype(np.float32) * factor, 0, 255).astype(np.uint8)
            augmented = cv2.cvtColor(cv2.merge([h, s, v]), cv2.COLOR_HSV2BGR)

        self.original_image.setText("")
        self.aug_image.setText("")
        self.original_image.setPixmap(_cv_to_pixmap(original, 520, 230))
        self.aug_image.setPixmap(_cv_to_pixmap(augmented, 520, 230))
        self.original_name.setText(self._source_name)
        self.aug_name.setText(self._source_name)


class ReviewPage(QWidget):
    start_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Review & Run", objectName="PageSectionTitle"))
        copy.addWidget(
            QLabel(
                "Verify the dataset plan, then run augmentation in the background.",
                objectName="PageSectionSubtitle",
            )
        )
        header.addLayout(copy, 1)
        self.ready_badge = QLabel("Ready", objectName="ReadyBadge")
        header.addWidget(self.ready_badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        top = QHBoxLayout()
        top.setSpacing(10)

        summary = InnerCard("Run Summary", "The final configuration used by the worker.")
        self.summary_grid = QGridLayout()
        self.summary_grid.setHorizontalSpacing(12)
        self.summary_grid.setVerticalSpacing(8)
        self.summary_labels = {}
        for row, (key, title) in enumerate(
            (
                ("input", "Input dataset"),
                ("output", "Output dataset"),
                ("split", "Train / validation"),
                ("seed", "Random seed"),
                ("transforms", "Transformations"),
                ("estimate", "Estimated images"),
            )
        ):
            self.summary_grid.addWidget(QLabel(title, objectName="ReviewKey"), row, 0)
            value = QLabel("—", objectName="ReviewValue")
            value.setWordWrap(True)
            self.summary_grid.addWidget(value, row, 1)
            self.summary_labels[key] = value
        summary.box.addLayout(self.summary_grid)

        structure = InnerCard("Output Structure", "YOLO segmentation dataset layout.")
        structure_label = QLabel(
            "output/\n"
            "  train/\n"
            "    images/\n"
            "    labels/\n"
            "  valid/\n"
            "    images/\n"
            "    labels/\n"
            "  data.yaml",
            objectName="CodeBlock",
        )
        structure_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        structure.box.addWidget(structure_label)
        structure.box.addStretch(1)

        top.addWidget(summary, 1)
        top.addWidget(structure, 1)
        root.addLayout(top)

        run = InnerCard("Processing", "Live progress and worker messages.")
        self.progress = QProgressBar(objectName="RunProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)

        status_row = QHBoxLayout()
        self.progress_text = QLabel("0% complete", objectName="RunStatus")
        self.run_status = QLabel("Ready to run", objectName="RunStatusGood")
        status_row.addWidget(self.progress_text)
        status_row.addStretch(1)
        status_row.addWidget(self.run_status)

        self.log = QPlainTextEdit(objectName="RunLog")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(190)

        run.box.addWidget(self.progress)
        run.box.addLayout(status_row)
        run.box.addWidget(self.log, 1)
        root.addWidget(run, 1)

    def set_summary(self, config: dict, source_pairs: int):
        split = int(round(float(config.get("train_ratio", 0.8)) * 100))
        transforms = []
        if config.get("flip_horizontal"):
            transforms.append("Horizontal flip")
        if config.get("flip_vertical"):
            transforms.append("Vertical flip")
        if config.get("brightness_pct"):
            transforms.append(f"Brightness ±{config['brightness_pct']:.0f}%")
        if config.get("saturation_pct"):
            transforms.append(f"Saturation ±{config['saturation_pct']:.0f}%")

        variants = 1
        variants += 1 if config.get("flip_horizontal") else 0
        variants += 1 if config.get("flip_vertical") else 0
        variants += 2 if config.get("brightness_pct") else 0
        variants += 2 if config.get("saturation_pct") else 0

        self.summary_labels["input"].setText(config.get("input_dir", "—"))
        self.summary_labels["output"].setText(config.get("output_dir", "—"))
        self.summary_labels["split"].setText(f"{split} / {100 - split}")
        self.summary_labels["seed"].setText(str(config.get("seed", 42)))
        self.summary_labels["transforms"].setText(", ".join(transforms) or "Original only")
        self.summary_labels["estimate"].setText(
            f"{source_pairs} source pair(s) × {variants} = about {source_pairs * variants} images"
        )

    def reset_run(self):
        self.progress.setValue(0)
        self.progress_text.setText("0% complete")
        self.run_status.setText("Ready to run")
        self.run_status.setObjectName("RunStatusGood")
        self.log.clear()

    def update_progress(self, value: int):
        self.progress.setValue(int(value))
        self.progress_text.setText(f"{int(value)}% complete")

    def append_log(self, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {message}")
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_running(self, running: bool, success: bool | None = None):
        if running:
            self.run_status.setText("Running")
        elif success is True:
            self.run_status.setText("Completed")
        elif success is False:
            self.run_status.setText("Failed")
        else:
            self.run_status.setText("Ready to run")


class PreprocessingPage(QWidget):
    back_requested = pyqtSignal()
    finished = pyqtSignal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Image Preprocessing", objectName="PageSectionTitle"))
        copy.addWidget(
            QLabel(
                "Apply the existing preprocessing pipeline before augmentation.",
                objectName="PageSectionSubtitle",
            )
        )
        header.addLayout(copy, 1)
        root.addLayout(header)

        location = InnerCard("Input Folder", "Choose the images to preprocess.")
        self.folder = QLineEdit(objectName="PathEdit")
        self.folder.setPlaceholderText("Select input folder containing images...")
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        browse = QPushButton("Browse", objectName="SecondaryButton")
        browse.setFixedHeight(36)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        location.box.addLayout(row)
        root.addWidget(location)

        params = InnerCard("Preprocessing Parameters")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.dpi = QSpinBox(objectName="FieldSpin")
        self.dpi.setRange(72, 600)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" DPI")

        self.denoise_h = QSpinBox(objectName="FieldSpin")
        self.denoise_h.setRange(1, 50)
        self.denoise_h.setValue(10)

        self.denoise_color = QSpinBox(objectName="FieldSpin")
        self.denoise_color.setRange(1, 50)
        self.denoise_color.setValue(10)

        self.kernel = QSpinBox(objectName="FieldSpin")
        self.kernel.setRange(1, 15)
        self.kernel.setValue(5)

        self.iterations = QSpinBox(objectName="FieldSpin")
        self.iterations.setRange(1, 10)
        self.iterations.setValue(1)

        widgets = (
            ("DPI Scaling", self.dpi),
            ("Denoise Strength (h)", self.denoise_h),
            ("Denoise Color (hColor)", self.denoise_color),
            ("Kernel Size", self.kernel),
            ("Iterations", self.iterations),
        )
        for index, (title, widget) in enumerate(widgets):
            grid.addWidget(FieldBlock(title, widget), index // 2, index % 2)
        params.box.addLayout(grid)
        root.addWidget(params)

        progress = InnerCard("Progress")
        self.progress = QProgressBar(objectName="RunProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.status = QLabel("Select a folder and run preprocessing.", objectName="RunStatus")
        progress.box.addWidget(self.progress)
        progress.box.addWidget(self.status)
        root.addWidget(progress)

        actions = QHBoxLayout()
        back = QPushButton("← Back", objectName="SecondaryButton")
        run = QPushButton("Run Preprocessing", objectName="PrimaryButton")
        self.run_btn = run
        back.clicked.connect(self.back_requested.emit)
        run.clicked.connect(self._run)
        actions.addWidget(back)
        actions.addStretch(1)
        actions.addWidget(run)
        root.addLayout(actions)
        root.addStretch(1)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Preprocessing Input",
            self.folder.text().strip() or str(Path.home()),
        )
        if path:
            self.folder.setText(path)

    def _run(self):
        folder = self.folder.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, "Preprocessing", "Select a valid input folder.")
            return
        if self.worker and self.worker.isRunning():
            return

        self.progress.setRange(0, 0)
        self.status.setText("Processing images…")
        self.run_btn.setEnabled(False)

        self.worker = PreprocessingThread(
            folder,
            self.dpi.value(),
            self.denoise_h.value(),
            self.denoise_color.value(),
            self.kernel.value(),
            self.iterations.value(),
        )
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _finished(self, result):
        count, output = result
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if count else 0)
        self.run_btn.setEnabled(True)
        if count:
            self.status.setText(f"Processed {count} image(s) · {output}")
        else:
            self.status.setText("No images were processed.")
        self.finished.emit(result)


class GammaPage(QWidget):
    back_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        copy = QVBoxLayout()
        copy.setSpacing(3)
        copy.addWidget(QLabel("Gamma Correction", objectName="PageSectionTitle"))
        copy.addWidget(
            QLabel(
                "Apply grayscale gamma correction using the existing processing worker.",
                objectName="PageSectionSubtitle",
            )
        )
        root.addLayout(copy)

        location = InnerCard("Input Folder")
        self.folder = QLineEdit(objectName="PathEdit")
        self.folder.setPlaceholderText("Select input folder containing images...")
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        browse = QPushButton("Browse", objectName="SecondaryButton")
        browse.setFixedHeight(36)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        location.box.addLayout(row)
        root.addWidget(location)

        params = InnerCard("Parameters")
        self.gamma = QDoubleSpinBox(objectName="FieldSpin")
        self.gamma.setRange(0.05, 5.0)
        self.gamma.setSingleStep(0.05)
        self.gamma.setValue(0.5)
        self.gamma.setDecimals(2)
        params.box.addWidget(
            FieldBlock(
                "Gamma exponent",
                self.gamma,
                "Values below 1.0 brighten; values above 1.0 darken.",
            )
        )
        root.addWidget(params)

        progress = InnerCard("Progress")
        self.progress = QProgressBar(objectName="RunProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.status = QLabel("Ready", objectName="RunStatus")
        self.log = QPlainTextEdit(objectName="RunLog")
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(175)
        progress.box.addWidget(self.progress)
        progress.box.addWidget(self.status)
        progress.box.addWidget(self.log)
        root.addWidget(progress, 1)

        actions = QHBoxLayout()
        back = QPushButton("← Back", objectName="SecondaryButton")
        self.run_btn = QPushButton("Run Gamma Correction", objectName="PrimaryButton")
        back.clicked.connect(self.back_requested.emit)
        self.run_btn.clicked.connect(self._run)
        actions.addWidget(back)
        actions.addStretch(1)
        actions.addWidget(self.run_btn)
        root.addLayout(actions)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(
            self,
            "Select Gamma Input",
            self.folder.text().strip() or str(Path.home()),
        )
        if path:
            self.folder.setText(path)

    def _run(self):
        folder = self.folder.text().strip()
        if not folder or not Path(folder).is_dir():
            QMessageBox.warning(self, "Gamma Correction", "Select a valid input folder.")
            return
        if self.worker and self.worker.isRunning():
            return

        self.progress.setValue(0)
        self.log.clear()
        self.status.setText("Running…")
        self.run_btn.setEnabled(False)

        self.worker = GammaWorker(folder, self.gamma.value())
        self.worker.progress.connect(self.progress.setValue)
        self.worker.message.connect(self.log.appendPlainText)
        self.worker.finished_signal.connect(self._done)
        self.worker.error.connect(self._error)
        self.worker.finished.connect(lambda: self.run_btn.setEnabled(True))
        self.worker.start()

    def _done(self, result):
        count, output = result
        self.status.setText(f"Completed · {count} image(s)")
        self.log.appendPlainText(f"Output: {output}")

    def _error(self, message):
        self.status.setText("Failed")
        self.log.appendPlainText(f"ERROR: {message}")


class AugmentationPageQt6(QWidget):
    toast_requested = pyqtSignal(str, str)

    PAGE_DATASET = 0
    PAGE_SETTINGS = 1
    PAGE_REVIEW = 2
    PAGE_PREPROCESS = 3
    PAGE_GAMMA = 4

    def __init__(self, user: dict | None = None, parent=None):
        super().__init__(parent)
        self.user = user or {}
        self.projects: list[dict] = []
        self.project_map: dict[str, dict] = {}
        self.selected_project_id = ""
        self.current_section = "dataset"
        self.worker = None
        self.augmentation_completed = False
        self._input_pair_count = 0
        self._first_image = None

        self.setObjectName("AugmentationPageQt6")
        self._build()
        self._apply_style()
        self.refresh_context()
        self._switch("dataset")

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # Context strip
        context = QGridLayout()
        context.setContentsMargins(0, 0, 0, 0)
        context.setHorizontalSpacing(8)
        context.setVerticalSpacing(8)

        project_card = ContextCard("CURRENT PROJECT")
        self.project_selector = ProjectComboBox()
        self.project_selector.currentIndexChanged.connect(self._project_changed)
        project_card.layout_box.addWidget(self.project_selector)
        context.addWidget(project_card, 0, 0)

        input_card = ContextCard("INPUT DATASET")
        self.context_input = input_card.add_value("Not selected")
        context.addWidget(input_card, 0, 1)

        count_card = ContextCard("SOURCE IMAGES")
        self.context_count = count_card.add_value("0")
        context.addWidget(count_card, 0, 2)

        output_card = ContextCard("OUTPUT DATASET")
        self.context_output = output_card.add_value("Not selected")
        context.addWidget(output_card, 0, 3)

        # Final approved context strip:
        # Current Project / Input Dataset / Source Images / Output Dataset only.
        context.setColumnStretch(0, 13)
        context.setColumnStretch(1, 22)
        context.setColumnStretch(2, 8)
        context.setColumnStretch(3, 22)
        root.addLayout(context)

        body = QHBoxLayout()
        body.setSpacing(11)

        rail = QFrame(objectName="WorkflowRail")
        rail.setFixedWidth(218)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(12, 13, 12, 13)
        rl.setSpacing(7)

        rl.addWidget(QLabel("AUGMENTATION", objectName="RailEyebrow"))

        self.rail_buttons = {}
        for key, text, icon_name in (
            ("dataset", "Dataset Setup", "dataset"),
            ("settings", "Settings", "settings"),
            ("review", "Review & Run", "review"),
        ):
            button = RailNavButton(key, text, icon_name)
            button.clicked.connect(
                lambda checked=False, k=key: self._rail_clicked(k)
            )
            rl.addWidget(button)
            self.rail_buttons[key] = button

        divider = QFrame(objectName="RailDivider")
        divider.setFixedHeight(1)
        rl.addSpacing(5)
        rl.addWidget(divider)
        rl.addSpacing(4)
        rl.addWidget(QLabel("IMAGE PROCESSING", objectName="RailEyebrow"))

        for key, text, icon_name in (
            ("preprocess", "Preprocessing", "preprocess"),
            ("gamma", "Gamma Correction", "gamma"),
        ):
            button = RailNavButton(key, text, icon_name)
            button.clicked.connect(
                lambda checked=False, k=key: self._rail_clicked(k)
            )
            rl.addWidget(button)
            self.rail_buttons[key] = button

        rl.addStretch(1)
        body.addWidget(rail)

        workspace = QFrame(objectName="WorkspaceCard")
        wl = QVBoxLayout(workspace)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)

        self.stack = QStackedWidget()
        self.dataset_page = DatasetSetupPage()
        self.settings_page = SettingsPage()
        self.review_page = ReviewPage()
        self.preprocessing_page = PreprocessingPage()
        self.gamma_page = GammaPage()

        for page in (
            self.dataset_page,
            self.settings_page,
            self.review_page,
            self.preprocessing_page,
            self.gamma_page,
        ):
            self.stack.addWidget(page)
        wl.addWidget(self.stack, 1)

        self.footer = QFrame(objectName="WorkspaceFooter")
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(14, 9, 14, 11)
        fl.setSpacing(7)

        self.back_btn = QPushButton("← Back", objectName="SecondaryButton")
        self.back_btn.clicked.connect(self._back)
        self.footer_status = QLabel("", objectName="FooterStatus")
        self.next_btn = QPushButton("Continue →", objectName="PrimaryButton")
        self.next_btn.clicked.connect(self._next)
        self.start_btn = QPushButton("Start Augmentation", objectName="PrimaryButton")
        self.start_btn.clicked.connect(self.start_augmentation)
        self.finish_btn = QPushButton("Finish", objectName="PrimaryButton")
        self.finish_btn.clicked.connect(self.reset_session)

        fl.addWidget(self.back_btn)
        fl.addWidget(self.footer_status)
        fl.addStretch(1)
        fl.addWidget(self.finish_btn)
        fl.addWidget(self.start_btn)
        fl.addWidget(self.next_btn)
        wl.addWidget(self.footer)

        body.addWidget(workspace, 1)
        root.addLayout(body, 1)

        self.dataset_page.changed.connect(self._dataset_changed)
        self.settings_page.changed.connect(self._settings_changed)
        self.preprocessing_page.back_requested.connect(
            lambda: self._switch("dataset")
        )
        self.gamma_page.back_requested.connect(
            lambda: self._switch("dataset")
        )
        self.preprocessing_page.finished.connect(self._preprocessing_done)

    def _apply_style(self):
        self.setStyleSheet("""
        QWidget#AugmentationPageQt6 { background:transparent; color:#101A2D; }
        QWidget#AugmentationPageQt6 QLabel { background:transparent; border:0; }

        QFrame#ContextCard {
            background:#FFFFFF; border:1px solid #C3D1E2;
            border-radius:13px;
        }
        QLabel#ContextKey {
            color:#60738B; font-size:8px; font-weight:850; letter-spacing:.65px;
        }
        QLabel#ContextValue {
            color:#15263D; font-size:10.4px; font-weight:800;
        }
        QComboBox#ProjectSelector {
            min-height:33px; background:#FFFFFF; color:#17263D;
            border:1px solid #AEBFD5; border-radius:8px;
            padding:0 32px 0 9px; font-size:10px; font-weight:780;
        }
        QComboBox#ProjectSelector:hover,
        QComboBox#ProjectSelector:focus { border:1px solid #2868E8; }
        QComboBox#ProjectSelector::drop-down {
            width:28px; border:0; border-left:1px solid #D8E1EC;
        }
        QComboBox#ProjectSelector::down-arrow { image:none; width:0; height:0; }
        QListView#ProjectSelectorView {
            background:#FFFFFF; color:#17263D; border:1px solid #AEBFD5;
            border-radius:8px; padding:4px; outline:0;
            font-size:10px; font-weight:700;
        }
        QListView#ProjectSelectorView::item {
            min-height:30px; padding:3px 7px; border-radius:5px;
        }
        QListView#ProjectSelectorView::item:hover { background:#F0F5FF; color:#1D5BD0; }
        QListView#ProjectSelectorView::item:selected { background:#E5EEFF; color:#1D5BD0; }


        QFrame#WorkflowRail {
            background:#FFFFFF; border:1px solid #BFCEDF; border-radius:15px;
        }
        QLabel#RailEyebrow {
            color:#60728A; font-size:8.4px; font-weight:850;
            letter-spacing:.75px; padding:3px 3px 4px;
        }
        QFrame#RailDivider { background:#DCE4EE; border:0; }

        QPushButton#AugRailButton {
            padding:0 12px; text-align:left;
            background:#FFFFFF; border:1px solid #C5D2E2;
            border-radius:10px; text-align:left;
        }
        QPushButton#AugRailButton:hover {
            background:#F0F5FF; border-color:#9DB7E2;
        }
        QPushButton#AugRailButton:checked {
            background:#E8F1FF; border:1px solid #2868E8;
        }

        QFrame#WorkspaceCard {
            background:#FFFFFF; border:1px solid #BFCEDF; border-radius:15px;
        }
        QFrame#WorkspaceFooter {
            background:#FCFDFE; border:0; border-top:1px solid #DCE4EE;
        }
        QLabel#FooterStatus { color:#5B6E86; font-size:9px; }

        QLabel#PageSectionTitle {
            color:#101A2D; font-size:16px; font-weight:850;
        }
        QLabel#PageSectionSubtitle {
            color:#5C6F87; font-size:9.5px; font-weight:600;
        }
        QLabel#NeutralBadge {
            background:#F1F5FA; color:#566A82; border:1px solid #DCE4EE;
            border-radius:12px; padding:5px 8px;
            font-size:8px; font-weight:800;
        }
        QLabel#ReadyBadge {
            background:#E9F8F1; color:#078A57; border:1px solid #D1EBDF;
            border-radius:12px; padding:5px 8px;
            font-size:8px; font-weight:800;
        }

        QFrame#InnerCard, QFrame#TransformCard {
            background:#FBFCFE; border:1px solid #C8D5E5; border-radius:12px;
        }
        QLabel#CardTitle, QLabel#TransformTitle {
            color:#17263D; font-size:11.5px; font-weight:820;
        }
        QLabel#CardSubtitle, QLabel#TransformSubtitle {
            color:#62748B; font-size:8.8px; font-weight:600;
        }
        QLabel#FieldLabel { color:#3E536D; font-size:9px; font-weight:760; }
        QLabel#FieldHelper { color:#728198; font-size:8px; }
        QLabel#SwitchLabel { color:#405873; font-size:9.4px; font-weight:700; }

        QLineEdit#PathEdit,
        QComboBox#FieldCombo,
        QSpinBox#FieldSpin,
        QDoubleSpinBox#FieldSpin,
        QDoubleSpinBox#SmallSpin {
            min-height:35px; background:#FFFFFF; color:#17263D;
            border:1px solid #B8C8DB; border-radius:8px;
            padding:0 8px; font-size:9.5px;
        }
        QLineEdit#PathEdit:focus,
        QComboBox#FieldCombo:focus,
        QComboBox#FieldCombo:on,
        QSpinBox#FieldSpin:focus,
        QDoubleSpinBox#FieldSpin:focus,
        QDoubleSpinBox#SmallSpin:focus {
            border:1px solid #2868E8;
            background:#FFFFFF;
        }

        QComboBox#FieldCombo {
            padding:0 32px 0 9px;
        }
        QComboBox#FieldCombo::drop-down {
            subcontrol-origin:padding;
            subcontrol-position:top right;
            width:28px;
            border:0;
            border-left:1px solid #D8E1EC;
        }
        QComboBox#FieldCombo::down-arrow {
            image:none;
            width:0px;
            height:0px;
        }

        QListView#FieldComboView {
            background:#FFFFFF;
            color:#17263D;
            border:1px solid #AEBFD5;
            border-radius:8px;
            padding:5px;
            outline:0;
            font-size:9.8px;
            font-weight:700;
        }
        QListView#FieldComboView::item {
            background:#FFFFFF;
            color:#17263D;
            min-height:30px;
            padding:3px 8px;
            border-radius:5px;
        }
        QListView#FieldComboView::item:hover {
            background:#F0F5FF;
            color:#1D5BD0;
        }
        QListView#FieldComboView::item:selected {
            background:#E5EEFF;
            color:#1D5BD0;
            font-weight:800;
        }

        QPushButton#PrimaryButton, QPushButton#SecondaryButton {
            min-height:36px; border-radius:9px;
            padding:0 12px; font-size:9.5px; font-weight:780;
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

        QLabel#ValidationMessage {
            background:#FFF5E4; color:#A66000; border:1px solid #F0DBB3;
            border-radius:8px; padding:8px; font-size:9px; font-weight:700;
        }

        QFrame#ReadinessStrip {
            background:#F6F9FD; border:1px solid #C9D6E6; border-radius:10px;
        }
        QWidget#SummaryCell { border-right:1px solid #DCE4EE; }
        QLabel#SummaryCaption {
            color:#6C7D92; font-size:7.7px; font-weight:850; letter-spacing:.5px;
        }
        QLabel#SummaryValue { color:#17263D; font-size:9.5px; font-weight:800; }
        QLabel#SummaryValueSuccess { color:#078A57; font-size:9.5px; font-weight:800; }

        QSlider::groove:horizontal {
            height:5px; background:#DDE5EF; border-radius:2px;
        }
        QSlider::handle:horizontal {
            width:15px; margin:-5px 0; background:#2868E8;
            border:2px solid #FFFFFF; border-radius:7px;
        }

        QFrame#PreviewWorkbench {
            background:#FFFFFF; border:1px solid #C8D5E5; border-radius:12px;
        }
        QFrame#PreviewHeader {
            background:#FCFDFE; border:0; border-bottom:1px solid #DCE4EE;
        }
        QFrame#PreviewPane {
            background:#FFFFFF; border:1px solid #C5D2E2; border-radius:9px;
        }
        QFrame#PreviewPaneHeader {
            background:#FBFCFE; border:0; border-bottom:1px solid #DFE6EF;
            min-height:32px;
        }
        QLabel#PreviewPaneTitle {
            color:#596C84; font-size:8px; font-weight:850; letter-spacing:.4px;
        }
        QLabel#PreviewPaneName {
            color:#748399; font-size:8px; font-family:Consolas;
        }
        QLabel#PreviewImage {
            background:#F7F9FC; color:#7A899B; border:0;
        }
        QLabel#SummaryText {
            color:#405873; font-size:9.3px; font-weight:650;
        }

        QLabel#ReviewKey { color:#61738A; font-size:8.8px; font-weight:760; }
        QLabel#ReviewValue { color:#17263D; font-size:9px; font-weight:760; }
        QLabel#CodeBlock {
            background:#111827; color:#D8E7FA; border-radius:8px;
            padding:9px; font-family:Consolas; font-size:8.5px;
        }

        QProgressBar#RunProgress {
            min-height:10px; max-height:10px; background:#E0E7F0;
            border:0; border-radius:5px;
        }
        QProgressBar#RunProgress::chunk {
            background:#2868E8; border-radius:5px;
        }
        QLabel#RunStatus { color:#60728A; font-size:8.8px; font-weight:650; }
        QLabel#RunStatusGood { color:#078A57; font-size:8.8px; font-weight:780; }
        QPlainTextEdit#RunLog {
            background:#0F1724; color:#D9E8FF;
            border:1px solid #26354A; border-radius:9px;
            padding:7px; font-family:Consolas; font-size:8.8px;
        }

        QScrollBar:vertical { background:transparent; width:8px; margin:2px; }
        QScrollBar::handle:vertical {
            background:#C5D2E2; border-radius:4px; min-height:28px;
        }
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical { height:0; }
        """)

    # ------------------------------------------------------------------
    # Project / dataset context
    # ------------------------------------------------------------------
    def refresh_context(self):
        previous = self.selected_project_id
        try:
            self.projects = list(ProjectDB().get_all_projects() or [])
        except Exception as exc:
            self.projects = []
            self.toast_requested.emit("Projects unavailable", str(exc))

        self.project_map = {
            _project_id(p): p for p in self.projects if _project_id(p)
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

    def _project_changed(self, _index):
        if self.worker and self.worker.isRunning():
            self.toast_requested.emit(
                "Augmentation running",
                "Project selection is locked while processing.",
            )
            return
        project = self.project_map.get(
            str(self.project_selector.currentData() or "")
        )
        if project:
            self._apply_project(project)

    def _apply_project(self, project: dict):
        self.selected_project_id = _project_id(project)
        project_name = str(project.get("name") or "Project")

        dataset = self._find_annotation_dataset(project)
        project_root = self._project_root(project)
        default_output = project_root / "Augmented_Dataset"

        self.dataset_page.set_paths(
            str(dataset) if dataset else "",
            str(default_output),
        )
        self.preprocessing_page.folder.setText(str(dataset) if dataset else "")
        self.gamma_page.folder.setText(str(dataset) if dataset else "")
        self._refresh_dataset_state()

        if dataset:
            self.toast_requested.emit(
                "Augmentation dataset ready",
                f"{project_name}: {dataset.name}",
            )

    def _project_root(self, project: dict) -> Path:
        folder = str(project.get("folder_path") or "").strip()
        if folder:
            root = Path(folder)
            if root.suffix:
                root = root.parent
            return root

        name = _safe_name(str(project.get("name") or "Project"))
        root = Path.home() / "Documents" / "EyresAiPlatform" / "Projects" / name
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _find_annotation_dataset(self, project: dict) -> Path | None:
        roots: list[Path] = []
        project_root = self._project_root(project)
        roots.append(project_root)

        name = str(project.get("name") or "")
        cwd = Path.cwd()
        roots.extend(
            [
                cwd / "media" / "Capture_Input" / name,
                cwd / "Media" / "Capture_Input" / name,
            ]
        )

        candidates: list[tuple[int, float, Path]] = []
        seen = set()

        for root in roots:
            if not root.exists():
                continue

            dirs = [root]
            try:
                dirs.extend(p for p in root.rglob("*") if p.is_dir())
            except Exception:
                pass

            for folder in dirs:
                key = str(folder.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)

                try:
                    image_stems = {
                        p.stem.lower()
                        for p in folder.iterdir()
                        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
                    }
                    json_stems = {
                        p.stem.lower()
                        for p in folder.iterdir()
                        if p.is_file() and p.suffix.lower() == ".json"
                    }
                except Exception:
                    continue

                pairs = len(image_stems & json_stems)
                if pairs:
                    try:
                        mtime = folder.stat().st_mtime
                    except Exception:
                        mtime = 0
                    candidates.append((pairs, mtime, folder))

        if not candidates:
            return None

        # Prefer newest useful annotation dataset; pair count breaks ties.
        candidates.sort(key=lambda item: (item[1], item[0]), reverse=True)
        return candidates[0][2]

    def _dataset_changed(self):
        self._refresh_dataset_state()

    def _settings_changed(self):
        self._update_review()

    def _refresh_dataset_state(self):
        config = self.dataset_page.get_config()
        input_dir = Path(config["input_dir"]) if config["input_dir"] else None
        output_dir = config["output_dir"]

        self._input_pair_count = 0
        self._first_image = None

        if input_dir and input_dir.exists():
            for path in sorted(input_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                    json_path = path.with_suffix(".json")
                    if json_path.exists():
                        self._input_pair_count += 1
                        if self._first_image is None:
                            self._first_image = path

        self.context_input.setText(
            config["input_dir"] if config["input_dir"] else "Not selected"
        )
        self.context_output.setText(output_dir or "Not selected")
        self.context_count.setText(str(self._input_pair_count))
        self.settings_page.set_source_image(
            str(self._first_image) if self._first_image else None
        )
        self._update_review()

    def _full_config(self):
        config = {}
        config.update(self.dataset_page.get_config())
        config.update(self.settings_page.get_config())
        return config

    def _update_review(self):
        self.review_page.set_summary(
            self._full_config(),
            self._input_pair_count,
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _rail_clicked(self, key: str):
        if key == "settings" and not self._validate_dataset():
            return
        if key == "review":
            if not self._validate_dataset():
                return
            self._update_review()
        self._switch(key)

    def _switch(self, key: str):
        mapping = {
            "dataset": self.PAGE_DATASET,
            "settings": self.PAGE_SETTINGS,
            "review": self.PAGE_REVIEW,
            "preprocess": self.PAGE_PREPROCESS,
            "gamma": self.PAGE_GAMMA,
        }
        self.current_section = key
        self.stack.setCurrentIndex(mapping[key])

        for name, button in self.rail_buttons.items():
            button.setChecked(name == key)

        is_main = key in {"dataset", "settings", "review"}
        self.footer.setVisible(is_main)

        self.back_btn.setVisible(key in {"settings", "review"})
        self.next_btn.setVisible(key in {"dataset", "settings"})
        self.start_btn.setVisible(key == "review" and not self.augmentation_completed)
        self.finish_btn.setVisible(key == "review" and self.augmentation_completed)

        if key == "dataset":
            self.next_btn.setText("Continue →")
        elif key == "settings":
            self.next_btn.setText("Review & Run →")
        elif key == "review":
            self._update_review()


    def _next(self):
        if self.current_section == "dataset":
            if self._validate_dataset():
                self._switch("settings")
        elif self.current_section == "settings":
            if self._validate_dataset():
                self._switch("review")

    def _back(self):
        if self.current_section == "settings":
            self._switch("dataset")
        elif self.current_section == "review":
            self._switch("settings")

    def _validate_dataset(self) -> bool:
        config = self.dataset_page.get_config()
        self.dataset_page.validation.hide()

        if not config["input_dir"]:
            self.dataset_page.validation.setText(
                "Select an input dataset containing image + LabelMe JSON pairs."
            )
            self.dataset_page.validation.show()
            self.toast_requested.emit("Input dataset required", "Choose the annotation dataset first.")
            return False

        if not Path(config["input_dir"]).is_dir():
            self.dataset_page.validation.setText("The selected input directory does not exist.")
            self.dataset_page.validation.show()
            return False

        if self._input_pair_count <= 0:
            self.dataset_page.validation.setText(
                "No matching image + LabelMe JSON pairs were found in this folder."
            )
            self.dataset_page.validation.show()
            self.toast_requested.emit("No annotation pairs", "Images and JSON files must share the same stem.")
            return False

        if not config["output_dir"]:
            self.dataset_page.validation.setText("Select an output directory.")
            self.dataset_page.validation.show()
            return False

        return True

    # ------------------------------------------------------------------
    # Augmentation run
    # ------------------------------------------------------------------
    def start_augmentation(self):
        if not self._validate_dataset():
            return
        if self.worker and self.worker.isRunning():
            return

        config = self._full_config()
        try:
            Path(config["output_dir"]).mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self.toast_requested.emit("Output unavailable", str(exc))
            return

        self.augmentation_completed = False
        self.review_page.reset_run()
        self.review_page.set_running(True)
        self.start_btn.setEnabled(False)
        self.project_selector.setEnabled(False)

        self.worker = AugmentationWorker(config)
        self.worker.progress.connect(self.review_page.update_progress)
        self.worker.message.connect(self.review_page.append_log)
        self.worker.finished_signal.connect(self._augmentation_done)
        self.worker.error.connect(self._augmentation_error)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

        self.toast_requested.emit(
            "Augmentation started",
            f"Processing {self._input_pair_count} annotated image pair(s).",
        )

    def _augmentation_done(self, message: str):
        self.augmentation_completed = True
        self.review_page.append_log(message)
        self.review_page.set_running(False, True)
        self.toast_requested.emit("Augmentation completed", "Dataset generation finished successfully.")

    def _augmentation_error(self, message: str):
        self.review_page.append_log(f"ERROR: {message}")
        self.review_page.set_running(False, False)
        self.toast_requested.emit("Augmentation failed", message)

    def _worker_finished(self):
        self.start_btn.setEnabled(True)
        self.project_selector.setEnabled(bool(self.projects))
        self.start_btn.setVisible(not self.augmentation_completed)
        self.finish_btn.setVisible(self.augmentation_completed)

    def _preprocessing_done(self, result):
        count, output = result
        if count:
            self.toast_requested.emit(
                "Preprocessing completed",
                f"{count} image(s) processed to {output}",
            )
        else:
            self.toast_requested.emit("Preprocessing", "No images were processed.")

    # ------------------------------------------------------------------
    # Reset / shutdown
    # ------------------------------------------------------------------
    def reset_session(self):
        if self.worker and self.worker.isRunning():
            self.toast_requested.emit(
                "Augmentation running",
                "Wait for the current augmentation job to finish before resetting.",
            )
            return

        self.augmentation_completed = False
        self.settings_page.flip_h.setChecked(True)
        self.settings_page.flip_v.setChecked(False)
        self.settings_page.brightness_enabled.setChecked(True)
        self.settings_page.brightness_spin.setValue(20)
        self.settings_page.saturation_enabled.setChecked(True)
        self.settings_page.saturation_spin.setValue(20)
        self.dataset_page.train_ratio.setCurrentText("80 / 20")
        self.dataset_page.quality.setValue(95)
        self.dataset_page.seed.setValue(42)
        self.dataset_page.float_precision.setCurrentText("16")
        self.review_page.reset_run()

        if self.projects:
            project = self.project_map.get(
                str(self.project_selector.currentData() or ""),
                self.projects[0],
            )
            self._apply_project(project)
        self._switch("dataset")
        self.toast_requested.emit("Augmentation reset", "Ready for a new dataset job.")

    def shutdown(self):
        # Do not terminate workers unsafely. They are finite jobs; simply keep
        # references alive and prevent the GUI from deleting them mid-run.
        try:
            if self.worker and self.worker.isRunning():
                self.worker.wait(1200)
        except Exception:
            pass
        try:
            if self.preprocessing_page.worker and self.preprocessing_page.worker.isRunning():
                self.preprocessing_page.worker.wait(800)
        except Exception:
            pass
        try:
            if self.gamma_page.worker and self.gamma_page.worker.isRunning():
                self.gamma_page.worker.wait(800)
        except Exception:
            pass


AugmentationTool = AugmentationPageQt6
