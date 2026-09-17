import os, json, random, shutil
from pathlib import Path
import cv2
import numpy as np
from toasts import ToastManager

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox,
    QDoubleSpinBox, QSpinBox, QGroupBox, QFileDialog,
    QProgressBar, QMessageBox, QWidget, QSplitter,
    QListWidget, QProxyStyle, QStyle, QTabWidget, QFormLayout, QComboBox,
    QStackedWidget, QGraphicsDropShadowEffect, QFrame, QGridLayout, QSizePolicy,
    QLayout, QDialog, QScrollArea, QGraphicsBlurEffect, QSlider
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDateTime, QPoint, QTimer, QRectF, QSize, QEvent
from PyQt5.QtGui import QPainter, QPolygon, QFont, QPalette, QColor, QIcon, QPixmap, QFontMetrics

# ⬇️ bring in your preprocessing function
from preprocessing_functions import process_folder_with_params
from ui.theme.augmentation import AUGMENTATION_QSS


def apply_drop_shadow(widget, blur=28, xoff=0, yoff=10, alpha=130):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(xoff, yoff)
    eff.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(eff)


# ========================== Gamma worker ============================
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


# ====================== Augmentation Worker ========================
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


# ====================== Help Guide Dialog ===========================
class HelpGuideDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Augumentation Tool- Help Guide")
        self.setGeometry(150, 150, 800, 600)
        self.setup_ui()
        self.center_on_screen()

    def center_on_screen(self):
        screen_geometry = QApplication.desktop().screenGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        title = QLabel("Image Augmentation Suite Guide")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #007acc; padding: 10px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea { background-color: #252525; border: 1px solid #333; border-radius: 8px; }
            QScrollBar:vertical { background-color: #2d2d2d; width: 12px; border-radius: 6px; }
            QScrollBar::handle:vertical { background-color: #404040; border-radius: 6px; min-height: 20px; }
        """)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(25, 25, 25, 25)
        content_layout.setSpacing(20)

        sections = [
            {
                "title": "📋 Overview",
                "content": """
                <p>The Image Augmentation Suite is designed to help you preprocess and augment your image datasets for machine learning projects, specifically for YOLO segmentation models.</p>
                <p><b>Key Features:</b></p>
                <ul>
                <li>Convert LabelMe JSON annotations to YOLO segmentation format</li>
                <li>Apply various image augmentations</li>
                <li>Split dataset into training and validation sets</li>
                <li>Generate YAML configuration files for YOLO</li>
                </ul>
                """
            },
            {
                "title": "🚀 Getting Started",
                "content": """
                <p><b>Step 1: Dataset Configuration</b></p>
                <ul>
                <li><b>Input Directory:</b> Select folder containing your images and corresponding LabelMe JSON files</li>
                <li><b>Output Directory:</b> Choose where to save the augmented dataset</li>
                <li><b>Train/Validation Ratio:</b> Set the split ratio (default: 80% training, 20% validation)</li>
                <li><b>Random Seed:</b> For reproducible dataset splitting</li>
                <li><b>JPEG Quality:</b> Output image quality (1-100)</li>
                <li><b>Float Precision:</b> Decimal precision for coordinate values</li>
                </ul>
                <p><b>Step 2: Augmentation Settings</b></p>
                <ul>
                <li><b>Flip Augmentations:</b> Horizontal and/or vertical flipping</li>
                <li><b>Brightness Augmentations:</b> Adjust brightness by percentage</li>
                <li><b>Saturation Augmentations:</b> Adjust color saturation by percentage</li>
                </ul>
                <p><b>Step 3: Progress & Results</b></p>
                <ul>
                <li>Monitor processing progress with real-time logs</li>
                <li>View generated class mappings</li>
                <li>Check output directory structure</li>
                </ul>
                """
            },
            {
                "title": "📁 Input Requirements",
                "content": """
                <p><b>Supported Image Formats:</b> JPG, JPEG, PNG, BMP, TIF, TIFF</p>
                <p><b>Annotation Format:</b> LabelMe JSON files</p>
                <pre style="background: #2d2d2d; padding: 10px; border-radius: 5px;">
input_directory/
├── image1.jpg
├── image1.json
├── image2.png
├── image2.json
└── ...</pre>
                <p><b>JSON Structure Requirements:</b></p>
                <ul>
                <li>Each JSON file should correspond to an image file</li>
                <li>JSON must contain "shapes" array with polygon annotations</li>
                <li>Each shape should have "label" and "points" properties</li>
                </ul>
                """
            },
            {
                "title": "🔄 Output Structure",
                "content": """
                <pre style="background: #2d2d2d; padding: 10px; border-radius: 5px;">
output_directory/
├── train/
│   ├── images/
│   └── labels/
├── valid/
│   ├── images/
│   └── labels/
└── data.yaml</pre>
                <p><b>YOLO Format:</b> Each line: <code>class_id x1 y1 x2 y2 ...</code> with normalized coordinates.</p>
                """
            },
            {
                "title": "⚙️ Augmentation Details",
                "content": """
                <p><b>Flip:</b> horizontal/vertical with coordinates adjusted.</p>
                <p><b>Brightness/Saturation:</b> +/- percentage, 0–100% ranges.</p>
                """
            },
            {
                "title": "❓ Troubleshooting",
                "content": """
                <ul>
                <li><b>No pairs found:</b> image & JSON names must match</li>
                <li><b>Missing labels:</b> check 'shapes' arrays</li>
                <li><b>Permission errors:</b> ensure output dir writeable</li>
                </ul>
                """
            }
        ]

        for section in sections:
            section_title = QLabel(section["title"])
            section_title.setFont(QFont("Arial", 13, QFont.Bold))
            section_title.setStyleSheet("color: #8ecaff; margin-bottom: 5px;")
            content_layout.addWidget(section_title)

            section_content = QLabel(section["content"])
            section_content.setFont(QFont("Arial", 10))
            section_content.setStyleSheet("color: #ffffff; margin-left: 10px;")
            section_content.setWordWrap(True
            )
            section_content.setTextFormat(Qt.RichText)
            content_layout.addWidget(section_content)

            if section != sections[-1]:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setStyleSheet("background-color: #404040; margin: 10px 0px;")
                content_layout.addWidget(sep)

        content_layout.addStretch()
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)

        close_btn = QPushButton("Close Guide")
        close_btn.setFont(QFont("Arial", 10, QFont.Bold))
        close_btn.setFixedSize(120, 35)
        close_btn.setStyleSheet("""
            QPushButton { background-color: #007acc; color: white; border: none; border-radius: 5px; }
            QPushButton:hover { background-color: #005a9e; }
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)


# ========================= Sidebar =================================
class SidebarWidget(QWidget):
    # 🔔 NEW: signals the main window will listen to
    open_preprocessing = pyqtSignal()
    open_gamma = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(280)
        self.step_widgets = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("""
            SidebarWidget { background-color: #2d2d2d; border: none; border-radius: 0px; }
        """)

        self.setup_navigation_steps(layout)
        self.setup_tools_section(layout)
        layout.addStretch()

    def setup_navigation_steps(self, layout):
        steps_frame = QFrame()
        steps_frame.setStyleSheet("QFrame { background-color: transparent; border: none; padding: 0px; }")
        steps_layout = QVBoxLayout(steps_frame)
        steps_layout.setSpacing(15)
        steps_layout.setContentsMargins(0, 0, 0, 0)

        steps_title = QLabel("Augmentation Steps")
        steps_title.setAlignment(Qt.AlignCenter)
        steps_title.setStyleSheet("""
            QLabel { color: #8ecaff; background: transparent; font-size: 16px; font-weight: bold; padding: 10px 0; margin-bottom: 15px; }
        """)
        steps_layout.addWidget(steps_title)

        s1, w1 = self.create_step_item(1, "Dataset Configuration", "#007acc", False); steps_layout.addLayout(s1); self.step_widgets[1] = w1
        s2, w2 = self.create_step_item(2, "Augmentation Settings", "#007acc", False); steps_layout.addLayout(s2); self.step_widgets[2] = w2
        s3, w3 = self.create_step_item(3, "Progress", "#007acc", False); steps_layout.addLayout(s3); self.step_widgets[3] = w3
        steps_layout.addSpacing(30)
        layout.addWidget(steps_frame)

    def create_step_item(self, step_number, step_text, circle_color, is_completed):
        step_layout = QHBoxLayout()
        step_layout.setSpacing(12)
        step_layout.setContentsMargins(10, 5, 10, 5)

        circle_label = QLabel(str(step_number))
        circle_label.setFixedSize(30, 30)
        circle_label.setAlignment(Qt.AlignCenter)
        if is_completed:
            circle_style = """
                QLabel { background-color: #27ae60; color: white; border: 2px solid #27ae60;
                         border-radius: 15px; font-weight: bold; font-size: 12px; }
            """
        else:
            circle_style = f"""
                QLabel {{ background-color: {circle_color}; color: white; border: 2px solid {circle_color};
                         border-radius: 15px; font-weight: bold; font-size: 12px; }}
            """
        circle_label.setStyleSheet(circle_style)

        text_label = QLabel(step_text)
        text_label.setStyleSheet("QLabel { color:#fff; background:transparent; font-size:14px; }")

        step_layout.addWidget(circle_label)
        step_layout.addWidget(text_label)
        step_layout.addStretch()
        return step_layout, circle_label

    def setup_tools_section(self, layout):
        tools_frame = QFrame()
        tools_frame.setStyleSheet("QFrame { background-color: transparent; border: none; padding: 0px; }")
        tools_layout = QVBoxLayout(tools_frame)
        tools_layout.setSpacing(15)
        tools_layout.setContentsMargins(0, 0, 0, 0)

        tools_title = QLabel("Image Processing Tools")
        tools_title.setAlignment(Qt.AlignCenter)
        tools_title.setStyleSheet("""
            QLabel { color: #8ecaff; background: transparent; font-size: 16px; font-weight: bold;
                     padding: 20px 0 10px 0; margin-bottom: 10px; }
        """)
        tools_layout.addWidget(tools_title)

        for text, tip in [("Preprocessing", "Apply various image preprocessing techniques"),
                          ("Gamma Correction", "Modify gamma to enhance image brightness/contrast")]:
            btn = self.create_blue_button(text, tip)
            tools_layout.addWidget(btn)

        layout.addWidget(tools_frame)

    def create_blue_button(self, text, tooltip):
        button = QPushButton(text)
        button.setFixedSize(180, 40)
        button.setCursor(Qt.PointingHandCursor)
        button.setStyleSheet("""
            QPushButton { background:#007acc; color:white; border:none; border-radius:8px; font-size:14px; font-weight:bold; padding:8px 16px; }
            QPushButton:hover { background:#005a9e; }
            QPushButton:pressed { background:#004a80; }
        """)
        button.setToolTip(tooltip)
        button.clicked.connect(lambda _, t=text: self.on_tool_clicked(t))
        return button

    def on_tool_clicked(self, tool_name):
        # 🔁 NEW: emit signals; do NOT open new windows
        if "Preprocessing" in tool_name:
            self.open_preprocessing.emit()
        elif "Gamma" in tool_name:
            self.open_gamma.emit()


    def show_help_guide(self):
        HelpGuideDialog(self).exec_()

    def update_step_status(self, step_number, is_completed):
        if step_number in self.step_widgets:
            circle_label = self.step_widgets[step_number]
            if is_completed:
                circle_label.setStyleSheet(
                    "QLabel { background:#27ae60; color:white; border:2px solid #27ae60; border-radius:15px; font-weight:bold; font-size:12px; }"
                )
            else:
                circle_label.setStyleSheet(
                    "QLabel { background:#007acc; color:white; border:2px solid #007acc; border-radius:15px; font-weight:bold; font-size:12px; }"
                )


# ========================= BasePage + Pages =========================
class BasePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet("QWidget { background-color: #1e1e1e; color: #ffffff; }")


class DatasetSetupPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(parent)

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 20)
        root.setSpacing(18)

        header = QVBoxLayout()
        header.setContentsMargins(80, 0, 0, 0)
        title = QLabel("Dataset Configuration")
        title.setFont(QFont("Arial", 19, QFont.Bold))
        title.setStyleSheet("color:#007acc;")
        header.addWidget(title)
        root.addLayout(header)
        header.addSpacing(20)

        card = QFrame()
        card.setStyleSheet("QFrame { background-color:#252525; border:1px solid #333; border-radius:10px; padding:16px; }")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(6, 6, 6, 6)
        card_l.setSpacing(14)

        dir_panel = QFrame()
        dir_panel.setObjectName("panel")
        dir_panel.setStyleSheet("""QFrame#panel { background-color:#303233; border:1px solid #3b3d3e; border-radius:8px; padding:10px; }""")
        dir_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        dir_panel_l = QVBoxLayout(dir_panel)
        dir_panel_l.setContentsMargins(10, 10, 10, 10)
        dir_panel_l.setSpacing(10)
        dir_panel_l.addLayout(self.create_directory_section())

        params_panel = QFrame()
        params_panel.setObjectName("panel")
        params_panel.setStyleSheet(dir_panel.styleSheet())
        params_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        params_panel_l = QVBoxLayout(params_panel)
        params_panel_l.setContentsMargins(10, 10, 10, 10)
        params_panel_l.setSpacing(10)
        params_panel_l.addLayout(self.create_parameters_section())

        card_l.addWidget(dir_panel)
        card_l.addWidget(params_panel)
        root.addWidget(card, alignment=Qt.AlignCenter)
        root.addStretch()

    def create_directory_section(self):
        lay = QVBoxLayout()
        lay.setSpacing(10)
        title = QLabel("Directory Configuration")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet("color:#8ecaff;")
        lay.addWidget(title)

        LABEL_W = 185
        EDIT_H = 32
        BTN_W, BTN_H = 86, 32

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        grid.setContentsMargins(0, 0, 0, 0)

        lbl_in = QLabel("Input Directory")
        lbl_in.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_in.setStyleSheet("color:#fff;")
        lbl_in.setFixedWidth(LABEL_W)

        self.input_dir_edit = QLineEdit()
        self.input_dir_edit.setPlaceholderText("Select directory containing images and JSON files...")
        self.input_dir_edit.setFont(QFont("Arial", 10))
        self.input_dir_edit.setFixedHeight(EDIT_H)
        self.input_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.input_dir_edit.setStyleSheet("""
            QLineEdit{background:#2d2d2d;color:#fff;border:2px solid #404040;border-radius:6px;padding:6px 10px;font-size:11px;}
            QLineEdit:focus{border-color:#007acc;}
        """)

        btn_in = QPushButton("Browse")
        btn_in.setFont(QFont("Arial", 10, QFont.Bold))
        btn_in.setFixedSize(BTN_W, BTN_H)
        btn_in.setStyleSheet("""
            QPushButton{background:#007acc;color:#fff;border:none;border-radius:6px;}
            QPushButton:hover{background:#0a66b2;}
        """)
        btn_in.clicked.connect(self.browse_input_dir)

        lbl_out = QLabel("Output Directory")
        lbl_out.setFont(QFont("Arial", 11, QFont.Bold))
        lbl_out.setStyleSheet("color:#fff;")
        lbl_out.setFixedWidth(LABEL_W)

        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("Select output directory for augmented dataset...")
        self.output_dir_edit.setFont(QFont("Arial", 10))
        self.output_dir_edit.setFixedHeight(EDIT_H)
        self.output_dir_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.output_dir_edit.setStyleSheet("""
            QLineEdit{background:#2d2d2d;color:#fff;border:2px solid #404040;border-radius:6px;padding:6px 10px;font-size:11px;}
            QLineEdit:focus{border-color:#007acc;}
        """)

        btn_out = QPushButton("Browse")
        btn_out.setFont(QFont("Arial", 10, QFont.Bold))
        btn_out.setFixedSize(BTN_W, BTN_H)
        btn_out.setStyleSheet("""
            QPushButton{background:#007acc;color:#fff;border:none;border-radius:6px;}
            QPushButton:hover{background:#0a66b2;}
        """)
        btn_out.clicked.connect(self.browse_output_dir)

        grid.addWidget(lbl_in,               0, 0, alignment=Qt.AlignVCenter | Qt.AlignLeft)
        grid.addWidget(self.input_dir_edit,  0, 1)
        grid.addWidget(btn_in,               0, 2)
        grid.addWidget(lbl_out,              1, 0, alignment=Qt.AlignVCenter | Qt.AlignLeft)
        grid.addWidget(self.output_dir_edit, 1, 1)
        grid.addWidget(btn_out,              1, 2)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)

        lay.addLayout(grid)
        return lay

    def create_parameters_section(self):
        lay = QVBoxLayout()
        lay.setSpacing(8)
        title = QLabel("Augmentation Parameters")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet("color:#8ecaff;")
        lay.addWidget(title)

        COMMON_H = 32
        LABEL_W = 170

        self.train_ratio_spin = QDoubleSpinBox()
        self.train_ratio_spin.setRange(0.1, 0.9)
        self.train_ratio_spin.setSingleStep(0.1)
        self.train_ratio_spin.setValue(0.8)
        self._style_double_spin_grey(self.train_ratio_spin, COMMON_H)

        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 9999)
        self.seed_spin.setValue(42)
        self._style_spin_grey(self.seed_spin, COMMON_H)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(95)
        self._style_spin_grey(self.quality_spin, COMMON_H)

        self.float_precision_combo = QComboBox()
        self.float_precision_combo.addItems(["4", "6", "8", "10", "12", "16"])
        self.float_precision_combo.setCurrentText("16")
        self.float_precision_combo.setFixedHeight(COMMON_H)
        self.float_precision_combo.setFixedWidth(140)
        self.float_precision_combo.setStyleSheet("""
            QComboBox{ background:#e7e7e7; color:#000; border:1px solid #bdbdbd; border-radius:4px; padding:4px 8px; }
            QComboBox::drop-down{ border:none; width:22px; background:#ffffff; border-top-right-radius:4px; border-bottom-right-radius:4px; }
            QComboBox QAbstractItemView{ background:#ffffff; color:#000; border:1px solid #bdbdbd; selection-background-color:#e5f1fb; }
        """)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        lbl_tr = QLabel("Train/Validation"); lbl_tr.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold;"); lbl_tr.setFixedWidth(LABEL_W)
        grid.addWidget(lbl_tr, 0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.train_ratio_spin, 0, 1, alignment=Qt.AlignVCenter)

        lbl_q = QLabel("JPEG Quality"); lbl_q.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold;"); lbl_q.setFixedWidth(LABEL_W)
        grid.addWidget(lbl_q, 0, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.quality_spin, 0, 3, alignment=Qt.AlignVCenter)

        lbl_seed = QLabel("Random Seed"); lbl_seed.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold;"); lbl_seed.setFixedWidth(LABEL_W)
        grid.addWidget(lbl_seed, 1, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.seed_spin, 1, 1, alignment=Qt.AlignVCenter)

        lbl_fp = QLabel("Float Precision"); lbl_fp.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold;"); lbl_fp.setFixedWidth(LABEL_W)
        grid.addWidget(lbl_fp, 1, 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.float_precision_combo, 1, 3, alignment=Qt.AlignVCenter)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 0)
        grid.setColumnStretch(3, 1)

        lay.addLayout(grid)
        return lay

    def _style_spin_grey(self, sb: QSpinBox, h: int):
        sb.setFixedHeight(h)
        sb.setFixedWidth(140)
        sb.setStyleSheet("QSpinBox { font-size: 12px; selection-background-color: #2d2d2d; selection-color: #ffffff; }")

    def _style_double_spin_grey(self, dsb: QDoubleSpinBox, h: int):
        dsb.setFixedHeight(h)
        dsb.setFixedWidth(140)
        dsb.setDecimals(2)
        dsb.setStyleSheet("QDoubleSpinBox { font-size: 12px; selection-background-color: #2d2d2d; selection-color: #ffffff; }")

    def browse_input_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Input Directory")
        if d:
            self.input_dir_edit.setText(d)

    def browse_output_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_dir_edit.setText(d)

    def get_config(self):
        return {
            "input_dir": self.input_dir_edit.text(),
            "output_dir": self.output_dir_edit.text(),
            "train_ratio": self.train_ratio_spin.value(),
            "seed": self.seed_spin.value(),
            "jpeg_quality": self.quality_spin.value(),
            "float_precision": int(self.float_precision_combo.currentText()),
        }


class AugmentationSettingsPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(parent)

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 20)
        root.setSpacing(18)

        header = QVBoxLayout()
        header.setContentsMargins(80, 0, 0, 0)
        title = QLabel("Augmentation Settings")
        title.setFont(QFont("Arial", 19, QFont.Bold))
        title.setStyleSheet("color:#007acc;")
        header.addWidget(title)
        root.addLayout(header)
        header.addSpacing(20)

        card = QFrame()
        card.setStyleSheet("QFrame { background-color:#252525; border:1px solid #333; border-radius:10px; padding:16px; }")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(6, 6, 6, 6)
        card_l.setSpacing(14)

        panel_qss = """
            QFrame#panel { background-color:#303233; border:1px solid #3b3d3e; border-radius:8px; padding:10px; }
        """

        flip_panel = QFrame(); flip_panel.setObjectName("panel"); flip_panel.setStyleSheet(panel_qss); flip_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        brightness_panel = QFrame(); brightness_panel.setObjectName("panel"); brightness_panel.setStyleSheet(panel_qss); brightness_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        saturation_panel = QFrame(); saturation_panel.setObjectName("panel"); saturation_panel.setStyleSheet(panel_qss); saturation_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        flip_panel_l = QVBoxLayout(flip_panel); flip_panel_l.setContentsMargins(10,10,10,10); flip_panel_l.setSpacing(10)
        brightness_panel_l = QVBoxLayout(brightness_panel); brightness_panel_l.setContentsMargins(10,10,10,10); brightness_panel_l.setSpacing(10)
        saturation_panel_l = QVBoxLayout(saturation_panel); saturation_panel_l.setContentsMargins(10,10,10,10); saturation_panel_l.setSpacing(10)

        flip_panel_l.addLayout(self.create_flip_section())
        brightness_panel_l.addLayout(self.create_brightness_section())
        saturation_panel_l.addLayout(self.create_saturation_section())

        card_l.addWidget(flip_panel)
        card_l.addWidget(brightness_panel)
        card_l.addWidget(saturation_panel)
        root.addWidget(card, alignment=Qt.AlignCenter)
        root.addStretch()

        self._refresh_enabled_states()

    def create_flip_section(self):
        lay = QVBoxLayout()
        lay.setSpacing(10)
        title = QLabel("Flip Augmentations")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet("color:#8ecaff;")
        lay.addWidget(title)

        LABEL_W = 170
        LABEL_H = 30

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(20)
        grid.setContentsMargins(0, 0, 0, 0)

        lbl_horizontal = QLabel("Horizontal:")
        self._style_label_field(lbl_horizontal, LABEL_W, LABEL_H)
        lbl_vertical = QLabel("Vertical:")
        self._style_label_field(lbl_vertical, LABEL_W, LABEL_H)

        self.flip_horizontal_cb = QCheckBox()
        self.flip_vertical_cb = QCheckBox()

        grid.addWidget(lbl_horizontal, 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.flip_horizontal_cb, 0, 1, Qt.AlignLeft | Qt.AlignVCenter)
        grid.addWidget(lbl_vertical, 1, 0, Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.flip_vertical_cb, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        return lay

    def create_brightness_section(self):
        lay = QVBoxLayout()
        lay.setSpacing(10)
        title = QLabel("Brightness Augmentations")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet("color:#8ecaff;")
        lay.addWidget(title)

        LABEL_W = 170
        LABEL_H = 30

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(25)
        grid.setContentsMargins(0, 0, 0, 0)

        lbl_enable_brightness = QLabel("Enable Brightness:")
        self._style_label_field(lbl_enable_brightness, LABEL_W, LABEL_H)
        self.brightness_cb = QCheckBox()
        self.brightness_cb.toggled.connect(self._refresh_enabled_states)

        brightness_label = QLabel("Brightness Variation:")
        self._style_label_field(brightness_label, LABEL_W, LABEL_H)
        self.brightness_spin = QDoubleSpinBox()
        self.brightness_spin.setRange(0, 100)
        self.brightness_spin.setValue(20)
        self.brightness_spin.setSingleStep(5)
        self.brightness_spin.setSuffix("%")
        self._style_double_spin_grey(self.brightness_spin, 32)

        grid.addWidget(lbl_enable_brightness, 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.brightness_cb,    0, 1, Qt.AlignLeft  | Qt.AlignVCenter)
        grid.addWidget(brightness_label,      1, 0, Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.brightness_spin,  1, 1, Qt.AlignLeft  | Qt.AlignVCenter)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        return lay

    def create_saturation_section(self):
        lay = QVBoxLayout()
        lay.setSpacing(10)
        title = QLabel("Saturation Augmentations")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet("color:#8ecaff;")
        lay.addWidget(title)

        LABEL_W = 170
        LABEL_H = 30

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(25)
        grid.setContentsMargins(0, 0, 0, 0)

        lbl_enable_saturation = QLabel("Enable Saturation:")
        self._style_label_field(lbl_enable_saturation, LABEL_W, LABEL_H)
        self.saturation_cb = QCheckBox()
        self.saturation_cb.toggled.connect(self._refresh_enabled_states)

        saturation_label = QLabel("Saturation Variation:")
        self._style_label_field(saturation_label, LABEL_W, LABEL_H)
        self.saturation_spin = QDoubleSpinBox()
        self.saturation_spin.setRange(0, 100)
        self.saturation_spin.setValue(20)
        self.saturation_spin.setSingleStep(5)
        self.saturation_spin.setSuffix("%")
        self._style_double_spin_grey(self.saturation_spin, 32)

        grid.addWidget(lbl_enable_saturation, 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.saturation_cb,    0, 1, Qt.AlignLeft  | Qt.AlignVCenter)
        grid.addWidget(saturation_label,      1, 0, Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(self.saturation_spin,  1, 1, Qt.AlignLeft  | Qt.AlignVCenter)

        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        return lay

    def _style_label_field(self, label: QLabel, width: int, height: int):
        label.setFixedSize(width, height)
        label.setStyleSheet("""
            QLabel { background-color:#2d2d2d; color:#fff; border:2px solid #404040; border-radius:8px; padding:8px 12px; font-size:12px; font-weight:bold; }
        """)
        label.setAlignment(Qt.AlignCenter)

    def _style_double_spin_grey(self, dsb: QDoubleSpinBox, h: int):
        dsb.setFixedHeight(h)
        dsb.setFixedWidth(140)
        dsb.setStyleSheet("QDoubleSpinBox { font-size: 12px; selection-background-color:#2d2d2d; selection-color:#ffffff; }")

    def _refresh_enabled_states(self):
        self.brightness_spin.setEnabled(self.brightness_cb.isChecked())
        self.saturation_spin.setEnabled(self.saturation_cb.isChecked())

    def get_config(self):
        return {
            "flip_horizontal": self.flip_horizontal_cb.isChecked(),
            "flip_vertical":   self.flip_vertical_cb.isChecked(),
            "brightness_pct":  self.brightness_spin.value() if self.brightness_cb.isChecked() else 0.0,
            "saturation_pct":  self.saturation_spin.value() if self.saturation_cb.isChecked() else 0.0,
        }


class ProgressPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(parent)

    def setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 20)
        root.setSpacing(18)

        header = QVBoxLayout()
        header.setContentsMargins(80, 0, 0, 0)
        title = QLabel("Augmentation Progress")
        title.setFont(QFont("Arial", 19, QFont.Bold))
        title.setStyleSheet("color:#007acc;")
        header.addWidget(title)
        root.addLayout(header)
        header.addSpacing(20)

        card = QFrame()
        card.setStyleSheet("QFrame { background-color:#252525; border:1px solid #333; border-radius:10px; padding:16px; }")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(6, 6, 6, 6)
        card_l.setSpacing(14)

        panel_qss = """
            QFrame#panel { background-color:#303233; border:1px solid #3b3d3e; border-radius:8px; padding:20px; }
        """

        progress_panel = QFrame(); progress_panel.setObjectName("panel"); progress_panel.setStyleSheet(panel_qss)
        progress_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        progress_panel_l = QVBoxLayout(progress_panel)
        progress_panel_l.setContentsMargins(10, 10, 10, 10)
        progress_panel_l.setSpacing(15)
        progress_panel_l.addLayout(self.create_progress_section())

        log_panel = QFrame(); log_panel.setObjectName("panel"); log_panel.setStyleSheet(panel_qss)
        log_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        log_panel_l = QVBoxLayout(log_panel)
        log_panel_l.setContentsMargins(10, 10, 10, 10)
        log_panel_l.setSpacing(15)
        log_panel_l.addLayout(self.create_log_section())

        card_l.addWidget(progress_panel)
        card_l.addWidget(log_panel)
        root.addWidget(card, alignment=Qt.AlignCenter)
        root.addStretch()

    def create_progress_section(self):
        section_layout = QVBoxLayout()
        section_layout.setSpacing(12)

        title = QLabel("Processing Progress")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet("color:#8ecaff;")
        section_layout.addWidget(title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(28)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setStyleSheet("""
            QProgressBar { background-color:#2d2d2d; border:2px solid #404040; border-radius:6px; text-align:center; color:#000; font-size:11px; font-weight:bold; }
            QProgressBar::chunk { background-color:#007acc; border-radius:4px; border:none; }
        """)
        section_layout.addWidget(self.progress_bar)
        return section_layout

    def create_log_section(self):
        section_layout = QVBoxLayout()
        section_layout.setSpacing(12)
        title = QLabel("Processing Log")
        title.setFont(QFont("Arial", 13, QFont.Bold))
        title.setStyleSheet("color:#8ecaff;")
        section_layout.addWidget(title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setMinimumHeight(220)
        self.log_text.setMaximumHeight(260)
        self.log_text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.log_text.document().setDocumentMargin(10)
        self.log_text.setStyleSheet("""
            QTextEdit { background-color:#1e1e1e; color:#00ff00; border:2px solid #404040; border-radius:6px;
                        padding:12px; font-family: Consolas, monospace; font-size:10px; }
        """)
        section_layout.addWidget(self.log_text)
        return section_layout

    def log_message(self, message):
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.log_text.append(f"[{timestamp}] {message}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_progress(self, value):
        self.progress_bar.setValue(value)


# ==================== Preprocessing Panel/Window ====================
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
            processed_count, output_folder = process_folder_with_params(
                self.input_folder, self.dpi_value, self.denoise_h, self.denoise_hcolor,
                7, 15, self.kernel_size, self.iterations
            )
            self.finished.emit((processed_count, output_folder))
        except Exception as e:
            print(f"Error in preprocessing: {e}")
            self.finished.emit((0, ""))

class PreprocessingPanel(QWidget):
    finished = pyqtSignal(tuple)  # (processed_count, output_folder)
    back_requested = pyqtSignal() 
    def __init__(self, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.embedded = embedded            # <<< NEW
        self._build_ui()
        self.process_thread = None

    def _build_ui(self):
        from PyQt5.QtWidgets import QAbstractSpinBox

        def _shadow(w, **kw):
            try:
                apply_drop_shadow(w, **kw)
            except Exception:
                pass

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("headerBar")
        header.setStyleSheet("""
            QFrame#headerBar { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0  #0e1116, stop:1  #131722); border-bottom:1px solid #252a31; }
        """)
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(48, 18, 48, 18)
        title = QLabel("Image Preprocessing")
        title.setFont(QFont("Arial", 22, QFont.Bold))
        title.setStyleSheet("color:#79b0ff;")
        hbox.addWidget(title, 0, Qt.AlignVCenter)
        hbox.addStretch()
        root.addWidget(header)

        # ---------- CONTENT CONTAINER ----------
        # When embedded inside the main GUI (which already has a scroll area),
        # DO NOT add another QScrollArea to avoid nested scrollbars.
        if self.embedded:
            host = QWidget()
            root.addWidget(host, 1)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setStyleSheet("QScrollArea { background: transparent; border:none; }")
            root.addWidget(scroll, 1)
            host = QWidget()
            scroll.setWidget(host)

        content = QVBoxLayout(host)
        content.setContentsMargins(0, 20, 0, 20)

        center_row = QHBoxLayout()
        center_row.addStretch()

        # Card
        card = QFrame()
        card.setObjectName("mainCard")
        card.setStyleSheet("""
            QFrame#mainCard { background-color:#1a1f27; border:1px solid #2a3240; border-radius:14px; }
        """)
        _shadow(card, blur=30, yoff=16, alpha=150)
        # IMPORTANT: don't force a fixed width; cap it instead to avoid horizontal scrollbars
        card.setMaximumWidth(1280)                                   # <<< CHANGED (was setFixedWidth)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(18, 18, 18, 18)
        card_l.setSpacing(16)

        panel_qss = """
            QFrame#panel { background-color:#202733; border:1px solid #2c3544; border-radius:12px; }
        """

        # Input panel
        input_panel = QFrame(); input_panel.setObjectName("panel"); input_panel.setStyleSheet(panel_qss)
        in_l = QVBoxLayout(input_panel); in_l.setContentsMargins(16, 16, 16, 16); in_l.setSpacing(12)
        in_title = QLabel("Input Folder"); in_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        in_l.addWidget(in_title)
        row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select input folder containing images…")
        self.folder_edit.setStyleSheet("""
            QLineEdit { background:#141a22; color:#f0f3f6; border:2px solid #2d3644; border-radius:10px; padding:10px 12px; font-size:12px; }
            QLineEdit:hover { border-color:#3a485b; }
            QLineEdit:focus { border-color:#2d7ef1; }
        """)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedSize(96, 34)
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setStyleSheet("""
            QPushButton { background:#2d7ef1; color:#fff; border:none; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#1f6bd1; }
        """)
        browse_btn.clicked.connect(self._browse_folder)
        row.addWidget(self.folder_edit, 1)
        row.addSpacing(8)
        row.addWidget(browse_btn, 0)
        in_l.addLayout(row)
        card_l.addWidget(input_panel)

        # Params
        params_panel = QFrame(); params_panel.setObjectName("panel"); params_panel.setStyleSheet(panel_qss)
        pa_l = QVBoxLayout(params_panel); pa_l.setContentsMargins(16, 16, 16, 16); pa_l.setSpacing(12)
        pa_title = QLabel("Preprocessing Parameters")
        pa_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        pa_l.addWidget(pa_title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(12)

        def mk_lbl(txt):
            lb = QLabel(txt)
            lb.setStyleSheet("color:#d6deea; font-size:12px; font-weight:600;")
            return lb

        self.dpi_spin = QSpinBox(); self.dpi_spin.setRange(72, 600); self.dpi_spin.setValue(300); self.dpi_spin.setSuffix(" DPI")
        self.denoise_h_spin = QSpinBox(); self.denoise_h_spin.setRange(1, 50); self.denoise_h_spin.setValue(10)
        self.denoise_hcolor_spin = QSpinBox(); self.denoise_hcolor_spin.setRange(1, 50); self.denoise_hcolor_spin.setValue(10)
        self.kernel_spin = QSpinBox(); self.kernel_spin.setRange(1, 15); self.kernel_spin.setValue(5)
        self.iterations_spin = QSpinBox(); self.iterations_spin.setRange(1, 10); self.iterations_spin.setValue(1)

        for sb in (self.dpi_spin, self.denoise_h_spin, self.denoise_hcolor_spin, self.kernel_spin, self.iterations_spin):
            sb.setAccelerated(True)
            sb.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            sb.setFixedHeight(32)
            sb.setMinimumWidth(140)

        grid.addWidget(mk_lbl("DPI Scaling"),            0, 0, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(self.dpi_spin,                    0, 1)
        grid.addWidget(mk_lbl("Denoise Strength (h)"),   1, 0, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(self.denoise_h_spin,              1, 1)
        grid.addWidget(mk_lbl("Denoise Color (hColor)"), 2, 0, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(self.denoise_hcolor_spin,         2, 1)
        grid.addWidget(mk_lbl("Kernel Size"),            3, 0, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(self.kernel_spin,                 3, 1)
        grid.addWidget(mk_lbl("Iterations"),             4, 0, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(self.iterations_spin,             4, 1)

        pa_l.addLayout(grid)
        card_l.addWidget(params_panel)

        # Progress
        progress_panel = QFrame(); progress_panel.setObjectName("panel"); progress_panel.setStyleSheet(panel_qss)
        pr_l = QVBoxLayout(progress_panel); pr_l.setContentsMargins(16, 16, 16, 16); pr_l.setSpacing(12)

        pr_title = QLabel("Progress")
        pr_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        pr_l.addWidget(pr_title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setFixedHeight(28)
        self.progress_bar.setStyleSheet("""
            QProgressBar { background:#141a22; border:2px solid #2d3644; border-radius:10px; color:#0e1013; text-align:center; font-weight:700; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0  #2d7ef1, stop:1  #7aa8ff); border-radius:8px; }
        """)
        self.status_label = QLabel("Select folder and click Process to start")
        self.status_label.setStyleSheet("color:#c6cfda;")
        pr_l.addWidget(self.progress_bar)
        pr_l.addWidget(self.status_label)
        card_l.addWidget(progress_panel)

        center_row.addWidget(card)
        center_row.addStretch()
        content.addLayout(center_row)
        content.addSpacing(10)

        # Footer (inside the panel)
        footer = QFrame()
        footer.setFixedHeight(72)
        footer.setStyleSheet("QFrame { background: rgba(17,17,17,180); border-top:1px solid #252a31; }")
        f = QHBoxLayout(footer)
        f.setContentsMargins(40, 14, 40, 14)

        self.close_btn = QPushButton("Close" if not self.embedded else "Back")   # <<< CHANGED
        self.close_btn.setFixedSize(100, 38)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton { background:#2a323e; color:#ff2d2d; border:1px solid #394456; border-radius:19px; font-weight:700; }
            QPushButton:hover { background:#333d4b; }
        """)

        # Only close a window in standalone mode; in embedded mode, the main GUI will
        # connect this button to "go to dataset page".
        if not self.embedded:
            self.close_btn.clicked.connect(self._close_parent_window)
        else:
            self.close_btn.clicked.connect(self.back_requested.emit)

        self.process_btn = QPushButton("Process Images")
        self.process_btn.setFixedSize(160, 38)
        self.process_btn.setCursor(Qt.PointingHandCursor)
        self.process_btn.setStyleSheet("""
            QPushButton { background:#2d7ef1; color:white; border:none; border-radius:19px; font-weight:800; }
            QPushButton:hover { background:#246de0; }
            QPushButton:pressed { background:#1e5ec3; }
            QPushButton:disabled { background:#294768; color:#99b7e6; }
        """)
        self.process_btn.clicked.connect(self._process_images)

        f.addWidget(self.close_btn)
        f.addStretch()
        f.addWidget(self.process_btn)
        root.addWidget(footer)

    def _show_help(self):
        HelpGuideDialog(self).exec_()

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.folder_edit.setText(folder)

    def _process_images(self):
        input_folder = self.folder_edit.text().strip()
        if not input_folder or not os.path.exists(input_folder):
            QMessageBox.warning(self, "Error", "Please select a valid input folder")
            return

        dpi_value       = self.dpi_spin.value()
        denoise_h       = self.denoise_h_spin.value()
        denoise_hcolor  = self.denoise_hcolor_spin.value()
        kernel_size     = self.kernel_spin.value()
        iterations      = self.iterations_spin.value()

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("Processing images…")
        self.process_btn.setEnabled(False)

        self.process_thread = PreprocessingThread(
            input_folder, dpi_value, denoise_h, denoise_hcolor, kernel_size, iterations
        )
        self.process_thread.finished.connect(self._on_finished)
        self.process_thread.start()

    def _on_finished(self, result):
        processed_count, output_folder = result
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)

        if processed_count > 0:
            self.status_label.setText(f"Processed {processed_count} images successfully!")
            QMessageBox.information(self, "Success",
                f"Processed {processed_count} images successfully!\nOutput folder: {output_folder}")
        else:
            self.status_label.setText("No images were processed")
            QMessageBox.warning(self, "Warning",
                "No images were processed. Check if folder contains valid images.")

        self.finished.emit(result)

    def _close_parent_window(self):
        w = self.window()
        if isinstance(w, QMainWindow):
            w.close()

class GammaPanel(QWidget):
    back_requested = pyqtSignal()   # <- main window connects this to go back to index 0

    """
    Embedded gamma-correction tool for the main stacked widget.
    Uses the existing GammaWorker.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self._build_ui()

    # ---------------------- UI ----------------------
    def _build_ui(self):
        self.setStyleSheet("QWidget { color:#ffffff; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top header
        header = QFrame()
        header.setStyleSheet("QFrame { background: transparent; border-bottom:1px solid #252a31; }")
        h = QHBoxLayout(header)
        h.setContentsMargins(48, 18, 48, 18)
        title = QLabel("Gamma Correction")
        title.setFont(QFont("Arial", 22, QFont.Bold))
        title.setStyleSheet("color:#79b0ff;")
        h.addWidget(title)
        h.addStretch()
        root.addWidget(header)

        # Scrollable body (so long logs don’t push the footer)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        host = QWidget()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        # Outer content layout
        content = QVBoxLayout(host)
        content.setContentsMargins(32, 20, 32, 20)
        content.setSpacing(16)

        # -------- Centered container to control width (no horizontal scrollbar) --------
        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)
        center_row.addStretch()

        container = QFrame()
        container.setObjectName("gammaContainer")
        container.setStyleSheet("QFrame#gammaContainer { background: transparent; }")
        container.setMaximumWidth(1120)  # <- a little wider than before
        c = QVBoxLayout(container)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(16)

        center_row.addWidget(container)
        center_row.addStretch()
        content.addLayout(center_row)

        panel_qss = """
            QFrame#panel { background-color:#202733; border:1px solid #2c3544; border-radius:12px; }
        """

        # ---- Input folder panel
        input_panel = QFrame(); input_panel.setObjectName("panel"); input_panel.setStyleSheet(panel_qss)
        in_l = QVBoxLayout(input_panel); in_l.setContentsMargins(16,16,16,16); in_l.setSpacing(10)
        in_title = QLabel("Input Folder"); in_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        in_l.addWidget(in_title)

        row = QHBoxLayout()
        self.g_folder_edit = QLineEdit()
        self.g_folder_edit.setPlaceholderText("Select input folder containing images…")
        self.g_folder_edit.setStyleSheet("""
            QLineEdit { background:#141a22; color:#f0f3f6; border:2px solid #2d3644; border-radius:10px; padding:10px 12px; font-size:12px; }
            QLineEdit:hover { border-color:#3a485b; }
            QLineEdit:focus { border-color:#2d7ef1; }
        """)
        b = QPushButton("Browse"); b.setFixedSize(96, 34); b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet("""
            QPushButton { background:#2d7ef1; color:#fff; border:none; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#1f6bd1; }
        """)
        b.clicked.connect(self._browse_folder)
        row.addWidget(self.g_folder_edit, 1); row.addSpacing(8); row.addWidget(b, 0)
        in_l.addLayout(row)
        c.addWidget(input_panel)

        # ---- Parameters panel
        params = QFrame(); params.setObjectName("panel"); params.setStyleSheet(panel_qss)
        pa = QVBoxLayout(params); pa.setContentsMargins(16,16,16,16); pa.setSpacing(10)
        pa_title = QLabel("Parameters")
        pa_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        pa.addWidget(pa_title)

        grid = QGridLayout(); grid.setHorizontalSpacing(16); grid.setVerticalSpacing(12)
        lbl = QLabel("Gamma Exponent"); lbl.setStyleSheet("color:#d6deea; font-size:12px; font-weight:600;")
        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.05, 5.0)
        self.gamma_spin.setSingleStep(0.05)
        self.gamma_spin.setValue(0.5)
        self.gamma_spin.setSuffix("  (0.5=brighter, 2.0=darker)")
        self.gamma_spin.setFixedHeight(32); self.gamma_spin.setMinimumWidth(240)

        grid.addWidget(lbl, 0, 0, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(self.gamma_spin, 0, 1)
        pa.addLayout(grid)
        c.addWidget(params)

        # ---- Progress + log panel
        pr = QFrame(); pr.setObjectName("panel"); pr.setStyleSheet(panel_qss)
        pr_l = QVBoxLayout(pr); pr_l.setContentsMargins(16,16,16,16); pr_l.setSpacing(10)
        pr_title = QLabel("Progress")
        pr_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        pr_l.addWidget(pr_title)

        self.g_progress = QProgressBar()
        self.g_progress.setMinimum(0); self.g_progress.setMaximum(100); self.g_progress.setValue(0)
        self.g_progress.setFixedHeight(28); self.g_progress.setTextVisible(True)
        self.g_progress.setFormat("%p%")
        self.g_progress.setStyleSheet("""
            QProgressBar { background:#141a22; border:2px solid #2d3644; border-radius:10px; color:#000; text-align:center; font-weight:700; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0  #2d7ef1, stop:1  #7aa8ff); border-radius:8px; }
        """)
        pr_l.addWidget(self.g_progress)

        self.g_log = QTextEdit(); self.g_log.setReadOnly(True)
        self.g_log.setFont(QFont("Consolas", 10))
        self.g_log.setMinimumHeight(220)
        self.g_log.setStyleSheet("""
            QTextEdit { background-color:#1e1e1e; color:#00ff00; border:2px solid #404040; border-radius:6px; padding:12px; }
        """)
        pr_l.addWidget(self.g_log)
        c.addWidget(pr)

        # ---- Inline footer (panel local) with Back + Run buttons
        footer = QFrame()
        footer.setFixedHeight(66)
        footer.setStyleSheet("QFrame { background: rgba(17,17,17,180); border-top:1px solid #252a31; }")
        f = QHBoxLayout(footer)
        f.setContentsMargins(32, 12, 32, 12)

        self.back_btn = QPushButton("Back")
        self.back_btn.setFixedSize(100, 38)
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet("""
            QPushButton { background:#2a323e; color:#ff2d2d; border:1px solid #394456; border-radius:19px; font-weight:700; }
            QPushButton:hover { background:#333d4b; }
        """)
        self.back_btn.clicked.connect(self.back_requested.emit)  # <- tell the wizard to go to Dataset page

        self.run_btn = QPushButton("Run Gamma Correction"); self.run_btn.setFixedSize(220, 38)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setStyleSheet("""
            QPushButton { background:#2d7ef1; color:white; border:none; border-radius:19px; font-weight:800; }
            QPushButton:hover { background:#246de0; }
            QPushButton:pressed { background:#1e5ec3; }
            QPushButton:disabled { background:#294768; color:#99b7e6; }
        """)
        self.run_btn.clicked.connect(self._run_gamma)

        f.addWidget(self.back_btn)
        f.addStretch()
        f.addWidget(self.run_btn)

        # footer sits under the centered container
        content.addWidget(footer)

    # ---------------------- Actions ----------------------
    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.g_folder_edit.setText(folder)

    def _run_gamma(self):
        in_dir = self.g_folder_edit.text().strip()
        if not in_dir or not os.path.isdir(in_dir):
            QMessageBox.warning(self, "Error", "Please select a valid input folder.")
            return

        gexp = float(self.gamma_spin.value())
        if gexp <= 0:
            QMessageBox.warning(self, "Error", "Gamma exponent must be > 0.")
            return

        self.run_btn.setEnabled(False)
        self.g_progress.setValue(0)
        self.g_log.clear()
        self._log("Starting gamma correction…")

        self.worker = GammaWorker(in_dir, gexp)
        self.worker.progress.connect(self.g_progress.setValue)
        self.worker.message.connect(self._log)
        self.worker.finished_signal.connect(self._done)
        self.worker.error.connect(self._err)
        self.worker.start()

    def _log(self, msg: str):
        ts = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.g_log.append(f"[{ts}] {msg}")
        self.g_log.verticalScrollBar().setValue(self.g_log.verticalScrollBar().maximum())

    def _done(self, result):
        count, out_dir = result
        self._log(f"Completed! Processed {count} images.\nSaved in: {out_dir}")
        # QtWidgets.QMessageBox.information(self, "Success", f"Processed {count} images.\nSaved in: {out_dir}")
        w = self.window()
        if hasattr(w, "toast"): w.toast(f"Gamma correction finished: {count} image(s).", "success", 2800)
        self.run_btn.setEnabled(True)

    def _err(self, e: str):
        self._log(f"ERROR: {e}")
        # QMessageBox.critical(self, "Error", e)
        w = self.window()
        if hasattr(w, "toast"): w.toast("Gamma correction failed.", "error", 3000)
        self.run_btn.setEnabled(True)


class PreprocessingWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preprocessing — Image Augmentation Suite")
        self._build_ui()
        self.showMaximized()

    def _build_ui(self):
        self.setStyleSheet("QMainWindow { background-color:#111; } QWidget { color:#ffffff; }")

        central = QWidget()
        self.setCentralWidget(central)

        main_h = QHBoxLayout(central)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        self.sidebar = SidebarWidget()
        main_h.addWidget(self.sidebar, 0)

        right = QWidget()
        right.setObjectName("rightBg")
        right.setStyleSheet("""
            QWidget#rightBg { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0  #171A1F, stop:0.5 #1b1f24, stop:1  #14161a); }
        """)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(0)

        self.panel = PreprocessingPanel()
        right_l.addWidget(self.panel)

        main_h.addWidget(right, 1)


# ======================= Gamma Window ===============================
class GammaCorrectionWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gamma Correction — Image Augmentation Suite")
        self.worker = None
        self._build_ui()
        self.showMaximized()

    def _build_ui(self):
        self.setStyleSheet("QMainWindow { background-color:#111; } QWidget { color:#ffffff; }")

        central = QWidget()
        self.setCentralWidget(central)
        main_h = QHBoxLayout(central)
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        self.sidebar = SidebarWidget()
        main_h.addWidget(self.sidebar, 0)

        right = QWidget()
        right.setObjectName("rightBgGamma")
        right.setStyleSheet("""
            QWidget#rightBgGamma { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0  #171A1F, stop:0.5 #1b1f24, stop:1  #14161a); }
        """)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("QFrame { background: transparent; border-bottom:1px solid #252a31; }")
        h = QHBoxLayout(header)
        h.setContentsMargins(48, 18, 48, 18)
        title = QLabel("Gamma Correction")
        title.setFont(QFont("Arial", 22, QFont.Bold))
        title.setStyleSheet("color:#79b0ff;")
        h.addWidget(title)
        h.addStretch()
        right_l.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border:none; background:transparent; }")
        host = QWidget()
        scroll.setWidget(host)
        content = QVBoxLayout(host)
        content.setContentsMargins(0, 20, 0, 20)
        content.setSpacing(0)

        center_row = QHBoxLayout()
        center_row.addStretch()

        card = QFrame()
        card.setObjectName("gammaCard")
        card.setStyleSheet("""
            QFrame#gammaCard { background-color:#1a1f27; border:1px solid #2a3240; border-radius:14px; }
        """)
        apply_drop_shadow(card, blur=30, yoff=16, alpha=150)
        card.setFixedWidth(980)
        c = QVBoxLayout(card)
        c.setContentsMargins(18, 18, 18, 18)
        c.setSpacing(16)

        panel_qss = """
            QFrame#panel { background-color:#202733; border:1px solid #2c3544; border-radius:12px; }
        """

        # Input
        input_panel = QFrame(); input_panel.setObjectName("panel"); input_panel.setStyleSheet(panel_qss)
        in_l = QVBoxLayout(input_panel); in_l.setContentsMargins(16, 16, 16, 16); in_l.setSpacing(12)
        in_title = QLabel("Input Folder"); in_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        in_l.addWidget(in_title)
        row = QHBoxLayout()
        self.g_folder_edit = QLineEdit()
        self.g_folder_edit.setPlaceholderText("Select input folder containing images…")
        self.g_folder_edit.setStyleSheet("""
            QLineEdit { background:#141a22; color:#f0f3f6; border:2px solid #2d3644; border-radius:10px; padding:10px 12px; font-size:12px; }
            QLineEdit:hover { border-color:#3a485b; }
            QLineEdit:focus { border-color:#2d7ef1; }
        """)
        b = QPushButton("Browse"); b.setFixedSize(96, 34); b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet("""
            QPushButton { background:#2d7ef1; color:#fff; border:none; border-radius:8px; font-weight:700; }
            QPushButton:hover { background:#1f6bd1; }
        """)
        b.clicked.connect(self._browse_folder)
        row.addWidget(self.g_folder_edit, 1); row.addSpacing(8); row.addWidget(b, 0)
        in_l.addLayout(row)
        c.addWidget(input_panel)

        # Parameters
        params = QFrame(); params.setObjectName("panel"); params.setStyleSheet(panel_qss)
        pa = QVBoxLayout(params); pa.setContentsMargins(16, 16, 16, 16); pa.setSpacing(12)
        pa_title = QLabel("Parameters")
        pa_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        pa.addWidget(pa_title)

        grid = QGridLayout(); grid.setHorizontalSpacing(16); grid.setVerticalSpacing(12)
        lbl = QLabel("Gamma Exponent"); lbl.setStyleSheet("color:#d6deea; font-size:12px; font-weight:600;")
        self.gamma_spin = QDoubleSpinBox()
        self.gamma_spin.setRange(0.05, 5.0)
        self.gamma_spin.setSingleStep(0.05)
        self.gamma_spin.setValue(0.5)
        self.gamma_spin.setSuffix("  (0.5=brighter, 2.0=darker)")
        self.gamma_spin.setFixedHeight(32); self.gamma_spin.setMinimumWidth(220)
        grid.addWidget(lbl, 0, 0, alignment=Qt.AlignRight|Qt.AlignVCenter)
        grid.addWidget(self.gamma_spin, 0, 1)
        pa.addLayout(grid)
        c.addWidget(params)

        # Progress
        pr = QFrame(); pr.setObjectName("panel"); pr.setStyleSheet(panel_qss)
        pr_l = QVBoxLayout(pr); pr_l.setContentsMargins(16, 16, 16, 16); pr_l.setSpacing(12)
        pr_title = QLabel("Progress")
        pr_title.setStyleSheet("color:#8ecaff; font-size:14px; font-weight:700;")
        pr_l.addWidget(pr_title)

        self.g_progress = QProgressBar()
        self.g_progress.setMinimum(0); self.g_progress.setMaximum(100); self.g_progress.setValue(0)
        self.g_progress.setFixedHeight(28); self.g_progress.setTextVisible(True)
        self.g_progress.setFormat("%p%")
        self.g_progress.setStyleSheet("""
            QProgressBar { background:#141a22; border:2px solid #2d3644; border-radius:10px; color:#000; text-align:center; font-weight:700; }
            QProgressBar::chunk { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0  #2d7ef1, stop:1  #7aa8ff); border-radius:8px; }
        """)
        pr_l.addWidget(self.g_progress)

        self.g_log = QTextEdit(); self.g_log.setReadOnly(True)
        self.g_log.setFont(QFont("Consolas", 10))
        self.g_log.setMinimumHeight(200)
        self.g_log.setStyleSheet("""
            QTextEdit { background-color:#1e1e1e; color:#00ff00; border:2px solid #404040; border-radius:6px; padding:12px; }
        """)
        pr_l.addWidget(self.g_log)
        c.addWidget(pr)

        # Footer
        footer = QFrame()
        footer.setFixedHeight(72)
        footer.setStyleSheet("QFrame { background: rgba(17,17,17,180); border-top:1px solid #252a31; }")
        f = QHBoxLayout(footer)
        f.setContentsMargins(40, 14, 40, 14)

        close_btn = QPushButton("Close"); close_btn.setFixedSize(100, 38)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton { background:#2a323e; color:#ff2d2d; border:1px solid #394456; border-radius:19px; font-weight:700; }
            QPushButton:hover { background:#333d4b; }
        """)
        close_btn.clicked.connect(self.close)

        self.run_btn = QPushButton("Run Gamma Correction"); self.run_btn.setFixedSize(220, 38)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setStyleSheet("""
            QPushButton { background:#2d7ef1; color:white; border:none; border-radius:19px; font-weight:800; }
            QPushButton:hover { background:#246de0; }
            QPushButton:pressed { background:#1e5ec3; }
            QPushButton:disabled { background:#294768; color:#99b7e6; }
        """)
        self.run_btn.clicked.connect(self._run_gamma)

        f.addWidget(close_btn)
        f.addStretch()
        f.addWidget(self.run_btn)

        center_row.addWidget(card)
        center_row.addStretch()
        content.addLayout(center_row)
        content.addSpacing(10)

        right_l.addWidget(scroll, 1)
        right_l.addWidget(footer)
        main_h.addWidget(right, 1)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.g_folder_edit.setText(folder)

    def _run_gamma(self):
        in_dir = self.g_folder_edit.text().strip()
        if not in_dir or not os.path.isdir(in_dir):
            QMessageBox.warning(self, "Error", "Please select a valid input folder.")
            return

        gexp = float(self.gamma_spin.value())
        if gexp <= 0:
            QMessageBox.warning(self, "Error", "Gamma exponent must be > 0.")
            return

        self.run_btn.setEnabled(False)
        self.g_progress.setValue(0)
        self.g_log.clear()
        self._log(f"Starting gamma correction…")

        self.worker = GammaWorker(in_dir, gexp)
        self.worker.progress.connect(self.g_progress.setValue)
        self.worker.message.connect(self._log)
        self.worker.finished_signal.connect(self._done)
        self.worker.error.connect(self._err)
        self.worker.start()

    def _log(self, msg: str):
        ts = QDateTime.currentDateTime().toString("hh:mm:ss")
        self.g_log.append(f"[{ts}] {msg}")
        sb = self.g_log.verticalScrollBar(); sb.setValue(sb.maximum())

    def _done(self, result):
        count, out_dir = result
        self._log(f"Completed! Processed {count} images.\nSaved in: {out_dir}")
        QMessageBox.information(self, "Success", f"Processed {count} images.\nSaved in: {out_dir}")
        self.run_btn.setEnabled(True)

    def _err(self, e: str):
        self._log(f"ERROR: {e}")
        QMessageBox.critical(self, "Error", e)
        self.run_btn.setEnabled(True)


# ========================== Wizard UI ===============================
def _page_heading(title_text, subtitle_text):
    box = QVBoxLayout()
    box.setSpacing(4)
    title = QLabel(title_text); title.setObjectName("pageTitle"); title.setFont(QFont("Segoe UI", 17, QFont.Bold))
    subtitle = QLabel(subtitle_text); subtitle.setObjectName("pageSubtitle"); subtitle.setFont(QFont("Segoe UI", 10))
    box.addWidget(title); box.addWidget(subtitle)
    return box


def _section_heading(text, detail=None):
    box = QVBoxLayout(); box.setSpacing(3)
    title = QLabel(text); title.setObjectName("sectionTitle"); title.setFont(QFont("Segoe UI", 11, QFont.Bold)); box.addWidget(title)
    if detail:
        subtitle = QLabel(detail); subtitle.setObjectName("mutedText"); subtitle.setWordWrap(True); box.addWidget(subtitle)
    return box


class ModernCheckBox(QCheckBox):
    """Application checkbox with a platform-independent painted tick."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(32)

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self.text()) + 34, 32)

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        box = QRectF(1, (self.height() - 18) / 2, 18, 18)
        painter.setPen(QColor("#2868e8") if self.isChecked() else QColor("#9fb0c5"))
        painter.setBrush(QColor("#2868e8") if self.isChecked() else QColor("#ffffff"))
        painter.drawRoundedRect(box, 4, 4)
        if self.isChecked():
            painter.setPen(QColor("#ffffff")); font = painter.font(); font.setBold(True); font.setPointSize(10); painter.setFont(font)
            painter.drawText(box, Qt.AlignCenter, "✓")
        painter.setPen(QColor("#233653")); painter.setFont(self.font())
        painter.drawText(QRectF(29, 0, self.width() - 29, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class ToggleSwitch(QPushButton):
    """Painted industrial switch that is independent of the host QPushButton QSS."""
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setObjectName("toggleSwitch")
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAccessibleName("Toggle switch")
        self._hovered = False

    def sizeHint(self):
        return QSize(44, 24)

    def minimumSizeHint(self):
        return QSize(44, 24)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        track = QRectF(1.0, 1.5, 42.0, 21.0)

        if not self.isEnabled():
            track_color = QColor("#E5EAF1")
            knob_color = QColor("#B9C3D2")
        elif self.isChecked():
            track_color = QColor("#174FD2" if self._hovered else "#255CED")
            knob_color = QColor("#FFFFFF")
        else:
            track_color = QColor("#C7D2E1" if self._hovered else "#D9E1ED")
            knob_color = QColor("#FFFFFF")

        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 10.5, 10.5)

        knob_d = 17.0
        knob_y = 3.5
        knob_x = 23.5 if self.isChecked() else 3.5

        painter.setBrush(QColor(0, 0, 0, 26))
        painter.drawEllipse(QRectF(knob_x, knob_y + 1.0, knob_d, knob_d))
        painter.setBrush(knob_color)
        painter.drawEllipse(QRectF(knob_x, knob_y, knob_d, knob_d))


class _Badge(QLabel):
    def __init__(self, text="", kind="neutral", parent=None):
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("badgeKind", kind)

    def set_kind(self, kind):
        self.setProperty("badgeKind", kind)
        self.style().unpolish(self); self.style().polish(self)


class _Tag(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setObjectName("transformTag")
        self.setAlignment(Qt.AlignCenter)


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _field_block(label_text, widget, helper_text=""):
    host = QWidget(); host.setObjectName("fieldBlock")
    v = QVBoxLayout(host); v.setContentsMargins(0,0,0,0); v.setSpacing(6)
    label = QLabel(label_text); label.setObjectName("fieldLabel")
    v.addWidget(label); v.addWidget(widget)
    if helper_text:
        helper = QLabel(helper_text); helper.setObjectName("fieldHelper"); helper.setWordWrap(True); v.addWidget(helper)
    return host


def _section_header(title_text, subtitle_text="", badge_text="", badge_kind="neutral"):
    host = QWidget(); host.setObjectName("contentHeader")
    h = QHBoxLayout(host); h.setContentsMargins(20,16,20,16); h.setSpacing(12)
    col = QVBoxLayout(); col.setSpacing(4)
    title = QLabel(title_text); title.setObjectName("contentTitle")
    col.addWidget(title)
    if subtitle_text:
        sub = QLabel(subtitle_text); sub.setObjectName("contentSubtitle"); sub.setWordWrap(True); col.addWidget(sub)
    h.addLayout(col,1)
    badge = None
    if badge_text:
        badge = _Badge(badge_text, badge_kind); h.addWidget(badge,0,Qt.AlignTop)
    return host, badge


def _card(title_text, subtitle_text=""):
    frame = QFrame(); frame.setObjectName("innerCard")
    v = QVBoxLayout(frame); v.setContentsMargins(16,15,16,15); v.setSpacing(10)
    title = QLabel(title_text); title.setObjectName("cardTitle"); v.addWidget(title)
    if subtitle_text:
        sub = QLabel(subtitle_text); sub.setObjectName("cardSubtitle"); sub.setWordWrap(True); v.addWidget(sub)
    return frame, v


class ProfessionalDatasetPage(DatasetSetupPage):
    """Approved dataset-setup design while retaining the original config contract."""
    def setup_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        head, self.step_badge = _section_header(
            "Dataset Setup",
            "Select source/output folders and configure how the augmented dataset will be written.",
            "Step 1 of 3",
        )
        root.addWidget(head)
        sep = QFrame(); sep.setObjectName("hairline"); sep.setFixedHeight(1); root.addWidget(sep)

        body = QWidget(); body.setObjectName("pageBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(20,18,20,18); bl.setSpacing(15)

        two = QHBoxLayout(); two.setSpacing(15)
        locations, ll = _card("Dataset Locations", "Choose where images are read from and where generated data is saved.")
        output, ol = _card("Output Configuration", "Control split reproducibility and generated image format.")

        self.input_dir_edit = QLineEdit(); self.input_dir_edit.setPlaceholderText("Select source folder...")
        self.output_dir_edit = QLineEdit(); self.output_dir_edit.setPlaceholderText("Select destination folder...")

        for text, edit, callback, helper in (
            ("Input directory", self.input_dir_edit, self.browse_input_dir,
             "Source images used to create the augmented training dataset."),
            ("Output directory", self.output_dir_edit, self.browse_output_dir,
             "Generated train/validation images and metadata will be written here."),
        ):
            label = QLabel(text); label.setObjectName("fieldLabel")
            ll.addWidget(label)
            row = QHBoxLayout(); row.setSpacing(8); row.addWidget(edit,1)
            browse = QPushButton("Browse"); browse.clicked.connect(callback); row.addWidget(browse)
            ll.addLayout(row)
            helper_label = QLabel(helper); helper_label.setObjectName("fieldHelper"); helper_label.setWordWrap(True); ll.addWidget(helper_label)

        self.train_ratio_spin = QDoubleSpinBox(); self.train_ratio_spin.setRange(.1,.9); self.train_ratio_spin.setSingleStep(.05); self.train_ratio_spin.setValue(.8); self.train_ratio_spin.setDecimals(2)
        self.quality_spin = QSpinBox(); self.quality_spin.setRange(1,100); self.quality_spin.setValue(95); self.quality_spin.setSuffix(" %")
        self.seed_spin = QSpinBox(); self.seed_spin.setRange(0,9999); self.seed_spin.setValue(42)
        self.float_precision_combo = QComboBox(); self.float_precision_combo.addItems(["4","6","8","10","12","16"]); self.float_precision_combo.setCurrentText("16")

        grid = QGridLayout(); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(12)
        grid.addWidget(_field_block("Train / validation split", self.train_ratio_spin),0,0)
        grid.addWidget(_field_block("JPEG quality", self.quality_spin),0,1)
        grid.addWidget(_field_block("Random seed", self.seed_spin),1,0)
        grid.addWidget(_field_block("Float precision", self.float_precision_combo),1,1)
        ol.addLayout(grid); ol.addStretch(1)

        two.addWidget(locations,1); two.addWidget(output,1); bl.addLayout(two)

        self.validation_label = QLabel(); self.validation_label.setObjectName("validationMessage"); self.validation_label.hide(); bl.addWidget(self.validation_label)

        summary = QFrame(); summary.setObjectName("readinessStrip")
        sl = QHBoxLayout(summary); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)
        self.ready_input = self._summary_cell("INPUT DATASET", "Not selected")
        self.ready_output = self._summary_cell("OUTPUT DATASET", "Not selected")
        self.ready_split = self._summary_cell("SPLIT", "80 / 20")
        self.ready_seed = self._summary_cell("REPRODUCIBILITY", "Seed 42", success=True, last=True)
        for w in (self.ready_input,self.ready_output,self.ready_split,self.ready_seed): sl.addWidget(w,1)
        bl.addWidget(summary)
        bl.addStretch(1)
        root.addWidget(body,1)

        self.input_dir_edit.textChanged.connect(self._update_readiness)
        self.output_dir_edit.textChanged.connect(self._update_readiness)
        self.train_ratio_spin.valueChanged.connect(self._update_readiness)
        self.seed_spin.valueChanged.connect(self._update_readiness)
        self._update_readiness()

    def _summary_cell(self, caption, value, success=False, last=False):
        host = QWidget(); host.setObjectName("summaryCell"); host.setProperty("lastCell", "true" if last else "false")
        v = QVBoxLayout(host); v.setContentsMargins(14,10,14,10); v.setSpacing(4)
        c = QLabel(caption); c.setObjectName("summaryCaption")
        val = QLabel(value); val.setObjectName("summaryValue"); val.setProperty("summaryState","success" if success else "neutral")
        host._value_label = val
        v.addWidget(c); v.addWidget(val)
        return host

    def _update_readiness(self):
        inp = self.input_dir_edit.text().strip(); out = self.output_dir_edit.text().strip()
        self.ready_input._value_label.setText("Selected" if inp else "Not selected")
        self.ready_output._value_label.setText("Selected" if out else "Not selected")
        for host, ok in ((self.ready_input,bool(inp)),(self.ready_output,bool(out))):
            host._value_label.setProperty("summaryState","success" if ok else "neutral")
            host._value_label.style().unpolish(host._value_label); host._value_label.style().polish(host._value_label)
        split = int(round(self.train_ratio_spin.value()*100))
        self.ready_split._value_label.setText(f"{split} / {100-split}")
        self.ready_seed._value_label.setText(f"Seed {self.seed_spin.value()}")


class ProfessionalAugmentationPage(AugmentationSettingsPage):
    """Three transformation cards with switch controls and live summary."""
    def setup_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        head, self.transform_badge = _section_header(
            "Augmentation Settings", "Choose the transformations to apply to the training data.", "0 transformations selected"
        )
        root.addWidget(head)
        sep = QFrame(); sep.setObjectName("hairline"); sep.setFixedHeight(1); root.addWidget(sep)

        body = QWidget(); body.setObjectName("pageBody")
        bl = QVBoxLayout(body); bl.setContentsMargins(20,18,20,18); bl.setSpacing(15)
        cards = QHBoxLayout(); cards.setSpacing(14)

        flip, fl = self._transform_card("Flip", "Mirror samples to improve orientation robustness.", "FL"); self.flip_card=flip
        self.flip_horizontal_cb = ToggleSwitch(True)
        self.flip_vertical_cb = ToggleSwitch(False)
        fl.addLayout(self._switch_row("Horizontal flip", self.flip_horizontal_cb))
        fl.addLayout(self._switch_row("Vertical flip", self.flip_vertical_cb)); fl.addStretch(1)

        bright, br = self._transform_card("Brightness", "Randomly vary image luminance around the original.", "BR"); self.brightness_card=bright
        self.brightness_cb = ToggleSwitch(True)
        br.addLayout(self._switch_row("Enable brightness", self.brightness_cb))
        self.brightness_slider = QSlider(Qt.Horizontal); self.brightness_slider.setRange(0,100); self.brightness_slider.setValue(20)
        self.brightness_spin = QDoubleSpinBox(); self.brightness_spin.setRange(0,100); self.brightness_spin.setValue(20); self.brightness_spin.setSingleStep(5); self.brightness_spin.setSuffix(" %"); self.brightness_spin.setFixedWidth(82)
        brightness_variation = QLabel("Variation"); brightness_variation.setObjectName("variationCaption"); br.addWidget(brightness_variation)
        rr = QHBoxLayout(); rr.setContentsMargins(0,0,0,0); rr.setSpacing(10); rr.addWidget(self.brightness_slider,1); rr.addWidget(self.brightness_spin); br.addLayout(rr); br.addStretch(1)

        sat, sr = self._transform_card("Saturation", "Randomly vary colour intensity around the original.", "SA"); self.saturation_card=sat
        self.saturation_cb = ToggleSwitch(True)
        sr.addLayout(self._switch_row("Enable saturation", self.saturation_cb))
        self.saturation_slider = QSlider(Qt.Horizontal); self.saturation_slider.setRange(0,100); self.saturation_slider.setValue(20)
        self.saturation_spin = QDoubleSpinBox(); self.saturation_spin.setRange(0,100); self.saturation_spin.setValue(20); self.saturation_spin.setSingleStep(5); self.saturation_spin.setSuffix(" %"); self.saturation_spin.setFixedWidth(82)
        saturation_variation = QLabel("Variation"); saturation_variation.setObjectName("variationCaption"); sr.addWidget(saturation_variation)
        rr2 = QHBoxLayout(); rr2.setContentsMargins(0,0,0,0); rr2.setSpacing(10); rr2.addWidget(self.saturation_slider,1); rr2.addWidget(self.saturation_spin); sr.addLayout(rr2); sr.addStretch(1)

        for w in (flip,bright,sat): cards.addWidget(w,1)
        bl.addLayout(cards)

        summary, sv = _card("Transformation Summary", "Only enabled transformations are included when augmentation starts.")
        self.tags_host = QWidget(); self.tags_layout = QHBoxLayout(self.tags_host); self.tags_layout.setContentsMargins(0,0,0,0); self.tags_layout.setSpacing(7); self.tags_layout.addStretch(1)
        sv.addWidget(self.tags_host)
        bl.addWidget(summary); bl.addStretch(1); root.addWidget(body,1)

        self.brightness_slider.valueChanged.connect(lambda v: self.brightness_spin.setValue(float(v)))
        self.brightness_spin.valueChanged.connect(lambda v: self.brightness_slider.setValue(int(round(v))))
        self.saturation_slider.valueChanged.connect(lambda v: self.saturation_spin.setValue(float(v)))
        self.saturation_spin.valueChanged.connect(lambda v: self.saturation_slider.setValue(int(round(v))))
        for control in (self.flip_horizontal_cb,self.flip_vertical_cb,self.brightness_cb,self.saturation_cb): control.toggled.connect(self._refresh_enabled_states)
        self.brightness_spin.valueChanged.connect(self._update_summary)
        self.saturation_spin.valueChanged.connect(self._update_summary)
        self._refresh_enabled_states()

    def _transform_card(self,title,subtitle,icon):
        frame = QFrame(); frame.setObjectName("transformCard")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setMinimumHeight(184)
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v = QVBoxLayout(frame); v.setContentsMargins(16,15,16,15); v.setSpacing(10)
        top = QHBoxLayout(); top.setSpacing(10)
        col = QVBoxLayout(); col.setSpacing(4)
        t = QLabel(title); t.setObjectName("cardTitle"); s = QLabel(subtitle); s.setObjectName("cardSubtitle"); s.setWordWrap(True)
        col.addWidget(t); col.addWidget(s)
        ico = QLabel(icon); ico.setObjectName("transformIcon"); ico.setAlignment(Qt.AlignCenter)
        top.addLayout(col,1); top.addWidget(ico,0,Qt.AlignTop); v.addLayout(top)
        return frame,v

    def _switch_row(self,text,switch):
        host = QWidget(); host.setObjectName("switchRow")
        h = QHBoxLayout(host); h.setContentsMargins(0,0,0,0); h.setSpacing(10)
        l=QLabel(text); l.setObjectName("switchLabel")
        h.addWidget(l,1); h.addWidget(switch,0,Qt.AlignVCenter)
        wrapper = QHBoxLayout(); wrapper.setContentsMargins(0,0,0,0); wrapper.addWidget(host)
        return wrapper

    def _refresh_enabled_states(self):
        brightness_on = self.brightness_cb.isChecked()
        saturation_on = self.saturation_cb.isChecked()
        flip_on = self.flip_horizontal_cb.isChecked() or self.flip_vertical_cb.isChecked()

        self.brightness_spin.setEnabled(brightness_on); self.brightness_slider.setEnabled(brightness_on)
        self.saturation_spin.setEnabled(saturation_on); self.saturation_slider.setEnabled(saturation_on)

        for card, active in (
            (getattr(self, "flip_card", None), flip_on),
            (getattr(self, "brightness_card", None), brightness_on),
            (getattr(self, "saturation_card", None), saturation_on),
        ):
            if card is not None:
                card.setProperty("transformActive", bool(active))
                card.style().unpolish(card)
                card.style().polish(card)
                card.update()

        self._update_summary()

    def _selected_transformations(self):
        tags=[]
        if self.flip_horizontal_cb.isChecked(): tags.append("Horizontal Flip")
        if self.flip_vertical_cb.isChecked(): tags.append("Vertical Flip")
        if self.brightness_cb.isChecked(): tags.append(f"Brightness ±{self.brightness_spin.value():g}%")
        if self.saturation_cb.isChecked(): tags.append(f"Saturation ±{self.saturation_spin.value():g}%")
        return tags

    def _update_summary(self):
        tags=self._selected_transformations(); n=len(tags)
        self.transform_badge.setText(f"{n} transformation{'s' if n != 1 else ''} selected")
        while self.tags_layout.count():
            item=self.tags_layout.takeAt(0); w=item.widget()
            if w: w.deleteLater()
        if tags:
            for tag in tags: self.tags_layout.addWidget(_Tag(tag),0,Qt.AlignLeft)
        else:
            empty=QLabel("No transformations enabled."); empty.setObjectName("fieldHelper"); self.tags_layout.addWidget(empty)
        self.tags_layout.addStretch(1)


class ProfessionalProgressPage(ProgressPage):
    start_requested = pyqtSignal()
    back_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def setup_ui(self):
        self._elapsed_seconds=0; self._source_total=0
        self._elapsed_timer=QTimer(self); self._elapsed_timer.timeout.connect(self._tick_elapsed)
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        head,self.ready_badge=_section_header("Review & Run","Confirm the dataset configuration, then start augmentation and monitor progress.","Ready to run","green")
        root.addWidget(head); sep=QFrame(); sep.setObjectName("hairline"); sep.setFixedHeight(1); root.addWidget(sep)
        body=QWidget(); body.setObjectName("pageBody"); bl=QVBoxLayout(body); bl.setContentsMargins(20,18,20,18); bl.setSpacing(14)

        top=QHBoxLayout(); top.setSpacing(15)
        summary,sv=_card("Run Summary")
        self.summary_grid=QVBoxLayout(); self.summary_grid.setSpacing(0); sv.addLayout(self.summary_grid)
        self.summary_values={}
        for key,label in (("input","Input dataset"),("output","Output dataset"),("split","Train / validation"),("quality","JPEG quality"),("seed","Random seed"),("precision","Float precision")):
            row=QWidget(); row.setObjectName("summaryRow"); h=QHBoxLayout(row); h.setContentsMargins(0,8,0,8); h.setSpacing(10)
            k=QLabel(label); k.setObjectName("summaryKey"); v=QLabel("—"); v.setObjectName("summaryDataValue"); v.setAlignment(Qt.AlignRight|Qt.AlignVCenter); v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            h.addWidget(k,1); h.addWidget(v,1); self.summary_grid.addWidget(row); self.summary_values[key]=v
        top.addWidget(summary,11)

        transforms,tv=_card("Selected Transformations","The following transformations will be applied to the training subset.")
        self.review_tags_host=QWidget(); self.review_tags_layout=QHBoxLayout(self.review_tags_host); self.review_tags_layout.setContentsMargins(0,0,0,0); self.review_tags_layout.setSpacing(7); tv.addWidget(self.review_tags_host)
        self.page_start_btn=QPushButton("Start Augmentation"); self.page_start_btn.setObjectName("primaryButton"); self.page_start_btn.clicked.connect(self.start_requested.emit); tv.addWidget(self.page_start_btn,0,Qt.AlignLeft); tv.addStretch(1)
        top.addWidget(transforms,9); bl.addLayout(top)

        prog_head=QHBoxLayout(); ptitle=QLabel("Progress"); ptitle.setObjectName("cardTitle"); self.progress_text=QLabel("0% complete"); self.progress_text.setObjectName("summaryDataValue"); prog_head.addWidget(ptitle); prog_head.addStretch(); prog_head.addWidget(self.progress_text); bl.addLayout(prog_head)
        self.progress_bar=QProgressBar(); self.progress_bar.setRange(0,100); self.progress_bar.setValue(0); self.progress_bar.setTextVisible(False); bl.addWidget(self.progress_bar)

        stats=QHBoxLayout(); stats.setSpacing(10)
        self.processed_value=self._stat_card(stats,"PROCESSED","0 / 0")
        self.elapsed_value=self._stat_card(stats,"ELAPSED","00:00")
        self.status_value=self._stat_card(stats,"STATUS","Waiting")
        bl.addLayout(stats)

        self.log_text=QTextEdit(); self.log_text.setObjectName("processingLog"); self.log_text.setReadOnly(True); self.log_text.setMinimumHeight(215); self.log_text.setPlaceholderText("Processing details will appear here after you start augmentation."); bl.addWidget(self.log_text,1)
        footer=QHBoxLayout(); footer.setSpacing(9); self.page_back_btn=QPushButton("← Back"); self.page_back_btn.clicked.connect(self.back_requested.emit); footer.addWidget(self.page_back_btn); footer.addStretch(); self.page_cancel_btn=QPushButton("Cancel"); self.page_cancel_btn.setObjectName("ghostButton"); self.page_cancel_btn.clicked.connect(self.cancel_requested.emit); footer.addWidget(self.page_cancel_btn); bl.addLayout(footer)
        root.addWidget(body,1)

    def _stat_card(self,layout,caption,value):
        card=QFrame(); card.setObjectName("statCard"); v=QVBoxLayout(card); v.setContentsMargins(11,8,11,8); v.setSpacing(3)
        c=QLabel(caption); c.setObjectName("summaryCaption"); val=QLabel(value); val.setObjectName("statValue"); v.addWidget(c); v.addWidget(val); layout.addWidget(card,1); return val

    def set_run_summary(self,config):
        split=int(float(config.get("train_ratio",.8))*100)
        vals={"input":config.get("input_dir") or "Not selected","output":config.get("output_dir") or "Not selected","split":f"{split} / {100-split}","quality":f"{int(config.get('jpeg_quality',95))}%","seed":str(config.get("seed",42)),"precision":str(config.get("float_precision",16))}
        for k,v in vals.items(): self.summary_values[k].setText(str(v))
        tags=[]
        if config.get("flip_horizontal"): tags.append("Horizontal Flip")
        if config.get("flip_vertical"): tags.append("Vertical Flip")
        if config.get("brightness_pct"): tags.append(f"Brightness ±{config.get('brightness_pct'):g}%")
        if config.get("saturation_pct"): tags.append(f"Saturation ±{config.get('saturation_pct'):g}%")
        while self.review_tags_layout.count():
            item=self.review_tags_layout.takeAt(0); w=item.widget()
            if w: w.deleteLater()
        for tag in tags: self.review_tags_layout.addWidget(_Tag(tag),0,Qt.AlignLeft)
        if not tags:
            no=QLabel("No transformations enabled."); no.setObjectName("fieldHelper"); self.review_tags_layout.addWidget(no)
        self.review_tags_layout.addStretch(1)
        self._source_total=self._estimate_pairs(config.get("input_dir","")); self.processed_value.setText(f"0 / {self._source_total}")

    def _estimate_pairs(self,folder):
        try:
            p=Path(folder); exts={".jpg",".jpeg",".png",".bmp",".tif",".tiff"}
            return sum(1 for f in p.iterdir() if f.is_file() and f.suffix.lower() in exts and (p/(f.stem+".json")).exists())
        except Exception: return 0

    def start_run_state(self):
        self._elapsed_seconds=0; self.elapsed_value.setText("00:00"); self.status_value.setText("Running"); self.page_start_btn.setEnabled(False); self.page_start_btn.setText("Running…"); self._elapsed_timer.start(1000)

    def finish_run_state(self,success=True):
        self._elapsed_timer.stop(); self.status_value.setText("Completed" if success else "Failed"); self.page_start_btn.setEnabled(True); self.page_start_btn.setText("Run Again" if success else "Start Augmentation")

    def _tick_elapsed(self):
        self._elapsed_seconds+=1; m,s=divmod(self._elapsed_seconds,60); self.elapsed_value.setText(f"{m:02d}:{s:02d}")

    def update_progress(self,value):
        self.progress_bar.setValue(value); self.progress_text.setText(f"{int(value)}% complete")
        if self._source_total>0: self.processed_value.setText(f"{min(self._source_total, round(self._source_total*value/100))} / {self._source_total}")

    def log_message(self,message):
        ts=QDateTime.currentDateTime().toString("hh:mm:ss"); self.log_text.append(f"[{ts}] {message}"); sb=self.log_text.verticalScrollBar(); sb.setValue(sb.maximum())


class ProfessionalPreprocessingPanel(PreprocessingPanel):
    def _build_ui(self):
        self.process_thread=None
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        head,self.tool_badge=_section_header("Image Preprocessing","Clean and standardize images before augmentation or model training.","Image Processing")
        root.addWidget(head); sep=QFrame(); sep.setObjectName("hairline"); sep.setFixedHeight(1); root.addWidget(sep)
        body=QWidget(); body.setObjectName("pageBody"); bl=QVBoxLayout(body); bl.setContentsMargins(20,18,20,18); bl.setSpacing(15)
        top=QHBoxLayout(); top.setSpacing(15)

        inp,iv=_card("Input Dataset","Choose the folder containing images to preprocess.")
        self.folder_edit=QLineEdit(); self.folder_edit.setPlaceholderText("Select folder containing images...")
        row=QHBoxLayout(); row.setSpacing(8); row.addWidget(self.folder_edit,1); browse=QPushButton("Browse"); browse.clicked.connect(self._browse_folder); row.addWidget(browse); iv.addLayout(row)
        status=QFrame(); status.setObjectName("statusPanel"); sh=QHBoxLayout(status); sh.setContentsMargins(12,10,12,10); sc=QVBoxLayout(); sc.setSpacing(3); st=QLabel("Processing Status"); st.setObjectName("cardTitle"); ss=QLabel("Configuration is ready. Start processing when the input folder is selected."); ss.setObjectName("cardSubtitle"); ss.setWordWrap(True); sc.addWidget(st); sc.addWidget(ss); self.status_chip=_Badge("READY","green"); sh.addLayout(sc,1); sh.addWidget(self.status_chip); iv.addWidget(status); iv.addStretch(1)
        top.addWidget(inp,1)

        cfg,cv=_card("Preprocessing Configuration","Tune scaling and denoise parameters.")
        self.dpi_spin=QSpinBox(); self.dpi_spin.setRange(72,600); self.dpi_spin.setValue(300); self.dpi_spin.setSuffix(" DPI")
        self.denoise_h_spin=QSpinBox(); self.denoise_h_spin.setRange(1,50); self.denoise_h_spin.setValue(10)
        self.denoise_hcolor_spin=QSpinBox(); self.denoise_hcolor_spin.setRange(1,50); self.denoise_hcolor_spin.setValue(10)
        self.kernel_spin=QSpinBox(); self.kernel_spin.setRange(1,15); self.kernel_spin.setValue(5)
        self.iterations_spin=QSpinBox(); self.iterations_spin.setRange(1,10); self.iterations_spin.setValue(1)
        grid=QGridLayout(); grid.setHorizontalSpacing(12); grid.setVerticalSpacing(11)
        for i,(label,control) in enumerate((("DPI scaling",self.dpi_spin),("Denoise strength",self.denoise_h_spin),("Colour denoise",self.denoise_hcolor_spin),("Kernel size",self.kernel_spin),("Iterations",self.iterations_spin))):
            r,c=divmod(i,2); grid.addWidget(_field_block(label,control),r,c)
        cv.addLayout(grid); cv.addStretch(1); top.addWidget(cfg,1); bl.addLayout(top)

        output,ov=_card("Processing Output","Status and processing messages will appear here.")
        self.progress_bar=QProgressBar(); self.progress_bar.setVisible(False); self.progress_bar.setTextVisible(False); ov.addWidget(self.progress_bar)
        self.status_label=QLabel("Ready. Select an input folder and start preprocessing."); self.status_label.setObjectName("fieldHelper"); ov.addWidget(self.status_label)
        self.processing_log=QTextEdit(); self.processing_log.setObjectName("processingLog"); self.processing_log.setReadOnly(True); self.processing_log.setMinimumHeight(175); self.processing_log.setPlaceholderText("Ready. Select an input folder and start preprocessing."); ov.addWidget(self.processing_log,1)
        bl.addWidget(output,1)
        footer=QHBoxLayout(); self.close_btn=QPushButton("← Back"); footer.addWidget(self.close_btn); footer.addStretch(); self.cancel_btn=QPushButton("Cancel"); self.cancel_btn.setObjectName("ghostButton"); footer.addWidget(self.cancel_btn); self.process_btn=QPushButton("Process Images"); self.process_btn.setObjectName("primaryButton"); self.process_btn.clicked.connect(self._process_images); footer.addWidget(self.process_btn); bl.addLayout(footer)
        root.addWidget(body,1)
        if not self.embedded: self.close_btn.clicked.connect(self._close_parent_window)
        else: self.close_btn.clicked.connect(self.back_requested.emit)

    def _process_images(self):
        input_folder=self.folder_edit.text().strip()
        if not input_folder or not os.path.exists(input_folder): QMessageBox.warning(self,"Error","Please select a valid input folder"); return
        self.progress_bar.setVisible(True); self.progress_bar.setRange(0,0); self.status_label.setText("Processing images…"); self.status_chip.setText("RUNNING"); self.status_chip.set_kind("blue"); self.process_btn.setEnabled(False); self.processing_log.clear(); self.processing_log.append("[START] Reading input images and applying preprocessing pipeline…")
        self.process_thread=PreprocessingThread(input_folder,self.dpi_spin.value(),self.denoise_h_spin.value(),self.denoise_hcolor_spin.value(),self.kernel_spin.value(),self.iterations_spin.value())
        self.process_thread.finished.connect(self._on_finished); self.process_thread.start()

    def _on_finished(self,result):
        processed_count,output_folder=result; self.progress_bar.setVisible(False); self.process_btn.setEnabled(True)
        if processed_count>0:
            self.status_label.setText(f"Processed {processed_count} images successfully."); self.status_chip.setText("COMPLETED"); self.status_chip.set_kind("green"); self.processing_log.append(f"[DONE] Processed {processed_count} image(s).\nOutput: {output_folder}")
        else:
            self.status_label.setText("No images were processed"); self.status_chip.setText("REVIEW"); self.status_chip.set_kind("amber"); self.processing_log.append("[WARN] No images were processed. Check the selected folder.")
        self.finished.emit(result)


class ProfessionalGammaPanel(GammaPanel):
    def _build_ui(self):
        self.worker=None
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        head,self.tool_badge=_section_header("Gamma Correction","Adjust image brightness using gamma correction.","Image Processing")
        root.addWidget(head); sep=QFrame(); sep.setObjectName("hairline"); sep.setFixedHeight(1); root.addWidget(sep)
        body=QWidget(); body.setObjectName("pageBody"); bl=QVBoxLayout(body); bl.setContentsMargins(20,18,20,18); bl.setSpacing(15)
        top=QHBoxLayout(); top.setSpacing(15)
        cfg,cv=_card("Gamma Configuration","Choose an input folder and tune the gamma value.")
        label=QLabel("Input folder"); label.setObjectName("fieldLabel"); cv.addWidget(label)
        r=QHBoxLayout(); r.setSpacing(8); self.g_folder_edit=QLineEdit(); self.g_folder_edit.setPlaceholderText("Select folder containing images..."); browse=QPushButton("Browse"); browse.clicked.connect(self._browse_folder); r.addWidget(self.g_folder_edit,1); r.addWidget(browse); cv.addLayout(r)
        gl=QLabel("Gamma value"); gl.setObjectName("fieldLabel"); cv.addWidget(gl)
        self.gamma_value_label=QLabel("0.50"); self.gamma_value_label.setObjectName("gammaValue"); cv.addWidget(self.gamma_value_label)
        self.gamma_slider=QSlider(Qt.Horizontal); self.gamma_slider.setRange(5,500); self.gamma_slider.setValue(50); cv.addWidget(self.gamma_slider)
        scale=QHBoxLayout(); a=QLabel("Darker"); a.setObjectName("fieldHelper"); b=QLabel("Neutral 1.00"); b.setObjectName("fieldHelper"); c=QLabel("Brighter"); c.setObjectName("fieldHelper"); scale.addWidget(a); scale.addStretch(); scale.addWidget(b); scale.addStretch(); scale.addWidget(c); cv.addLayout(scale)
        self.gamma_help=QLabel("Gamma 0.50 brightens darker image regions."); self.gamma_help.setObjectName("fieldHelper"); cv.addWidget(self.gamma_help); cv.addStretch(1)
        self.gamma_spin=QDoubleSpinBox(); self.gamma_spin.setRange(.05,5.0); self.gamma_spin.setSingleStep(.05); self.gamma_spin.setValue(.5); self.gamma_spin.hide()
        top.addWidget(cfg,11)
        preview=QFrame(); preview.setObjectName("previewPlaceholder"); pv=QVBoxLayout(preview); pv.addStretch(); g=QLabel("γ"); g.setObjectName("previewGamma"); g.setAlignment(Qt.AlignCenter); pt=QLabel("Preview Area"); pt.setObjectName("previewTitle"); pt.setAlignment(Qt.AlignCenter); ps=QLabel("Optional image preview can be added later\nwithout changing the current processing backend."); ps.setObjectName("cardSubtitle"); ps.setAlignment(Qt.AlignCenter); pv.addWidget(g); pv.addWidget(pt); pv.addWidget(ps); pv.addStretch(); top.addWidget(preview,9); bl.addLayout(top)
        ph=QHBoxLayout(); ptitle=QLabel("Progress"); ptitle.setObjectName("cardTitle"); self.g_progress_text=QLabel("0%"); self.g_progress_text.setObjectName("summaryDataValue"); ph.addWidget(ptitle); ph.addStretch(); ph.addWidget(self.g_progress_text); bl.addLayout(ph)
        self.g_progress=QProgressBar(); self.g_progress.setRange(0,100); self.g_progress.setValue(0); self.g_progress.setTextVisible(False); bl.addWidget(self.g_progress)
        self.g_log=QTextEdit(); self.g_log.setObjectName("processingLog"); self.g_log.setReadOnly(True); self.g_log.setMinimumHeight(190); self.g_log.setPlaceholderText("Processing log will appear here."); bl.addWidget(self.g_log,1)
        footer=QHBoxLayout(); self.back_btn=QPushButton("← Back"); self.back_btn.clicked.connect(self.back_requested.emit); footer.addWidget(self.back_btn); footer.addStretch(); self.cancel_btn=QPushButton("Cancel"); self.cancel_btn.setObjectName("ghostButton"); footer.addWidget(self.cancel_btn); self.run_btn=QPushButton("Run Gamma Correction"); self.run_btn.setObjectName("primaryButton"); self.run_btn.clicked.connect(self._run_gamma); footer.addWidget(self.run_btn); bl.addLayout(footer)
        root.addWidget(body,1)
        self.gamma_slider.valueChanged.connect(self._gamma_slider_changed); self._gamma_slider_changed(50)

    def _gamma_slider_changed(self,value):
        gamma=value/100.0; self.gamma_spin.setValue(gamma); self.gamma_value_label.setText(f"{gamma:.2f}")
        if gamma<1: text=f"Gamma {gamma:.2f} brightens darker image regions."
        elif gamma>1: text=f"Gamma {gamma:.2f} darkens brighter image regions."
        else: text="Gamma 1.00 leaves brightness unchanged."
        self.gamma_help.setText(text)

    def _run_gamma(self):
        in_dir=self.g_folder_edit.text().strip()
        if not in_dir or not os.path.isdir(in_dir): QMessageBox.warning(self,"Error","Please select a valid input folder."); return
        gexp=float(self.gamma_spin.value())
        if gexp<=0: QMessageBox.warning(self,"Error","Gamma exponent must be > 0."); return
        self.run_btn.setEnabled(False); self.g_progress.setValue(0); self.g_progress_text.setText("0%"); self.g_log.clear(); self._log("Starting gamma correction…")
        self.worker=GammaWorker(in_dir,gexp); self.worker.progress.connect(self._on_gamma_progress); self.worker.message.connect(self._log); self.worker.finished_signal.connect(self._done); self.worker.error.connect(self._err); self.worker.start()

    def _on_gamma_progress(self,value): self.g_progress.setValue(value); self.g_progress_text.setText(f"{int(value)}%")


class AugmentationWizard(QMainWindow):
    """Modern embedded-safe augmentation workspace."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._toast_mgr = ToastManager(self)
        self.setWindowTitle("Image Augmentation Suite")
        self.setGeometry(100,100,1400,900)
        self.current_page=0; self.config={}; self.augmentation_completed=False; self.worker=None; self._tool_page=None
        self._theme_restore_scheduled=False
        self._restoring_local_theme=False
        self.setup_ui(); self.center_and_fit_screen()

    def toast(self,msg: str,kind: str="info",ms: int=2500):
        if hasattr(self,"status_message"):
            colors={"info":"#255CED","success":"#089957","warn":"#B26B00","warning":"#B26B00","error":"#C83A49"}
            self.status_message.setStyleSheet(f"color:{colors.get(kind,'#255CED')};font-weight:600;background:transparent;border:0;")
            self.status_message.setText(msg)
            QTimer.singleShot(ms,lambda: self.status_message.clear() if self.status_message.text()==msg else None)

    def center_and_fit_screen(self):
        screen_geometry=QApplication.desktop().availableGeometry(); width=int(screen_geometry.width()*.9); height=int(screen_geometry.height()*.9); self.resize(width,height); fg=self.frameGeometry(); fg.moveCenter(screen_geometry.center()); self.move(fg.topLeft())

    def setup_ui(self):
        self.setObjectName("augmentationRoot")
        central=QWidget(); central.setObjectName("augmentationRoot"); central.setAttribute(Qt.WA_StyledBackground,True); self._root_widget=central; self.setCentralWidget(central)
        root=QVBoxLayout(central); root.setContentsMargins(24,16,24,22); root.setSpacing(14)

        header=QHBoxLayout(); header.setSpacing(10)
        identity=QVBoxLayout(); identity.setSpacing(4)
        title=QLabel("Dataset Augmentation"); title.setObjectName("pageTitle")
        subtitle=QLabel("Prepare robust training data with repeatable transformations and image processing tools."); subtitle.setObjectName("pageSubtitle")
        identity.addWidget(title); identity.addWidget(subtitle); header.addLayout(identity,1)
        self.help_btn=QPushButton("?"); self.help_btn.setObjectName("helpButton"); self.help_btn.setFixedSize(38,38); self.help_btn.setToolTip("Open help guide"); self.help_btn.clicked.connect(self.show_help_guide); header.addWidget(self.help_btn,0,Qt.AlignTop)
        root.addLayout(header)

        body=QHBoxLayout(); body.setSpacing(16)
        rail=QFrame(); rail.setObjectName("workflowRail"); rail.setFixedWidth(215); self._workflow_rail=rail
        rl=QVBoxLayout(rail); rl.setContentsMargins(14,15,14,15); rl.setSpacing(7)
        eye=QLabel("AUGMENTATION STEPS"); eye.setObjectName("railEyebrow"); rl.addWidget(eye)
        self.step_buttons=[]
        for number,caption in enumerate(("Dataset Setup","Settings","Review & Run"),1):
            btn=QPushButton(f"{number}    {caption}"); btn.setObjectName("stepButton"); btn.setCheckable(True); btn.setProperty("stepIndex",number-1); btn.clicked.connect(lambda checked=False,i=number-1:self._jump_step(i)); self.step_buttons.append(btn); rl.addWidget(btn)
        divider=QFrame(); divider.setObjectName("railDivider"); divider.setFixedHeight(1); rl.addSpacing(6); rl.addWidget(divider); rl.addSpacing(5)
        tool_label=QLabel("IMAGE PROCESSING"); tool_label.setObjectName("railEyebrow"); rl.addWidget(tool_label)
        self.preprocessing_btn=QPushButton("PP    Preprocessing"); self.preprocessing_btn.setObjectName("toolButton"); self.preprocessing_btn.setCheckable(True); self.preprocessing_btn.clicked.connect(lambda:self.open_tool_page("pre"))
        self.gamma_btn=QPushButton("γ     Gamma Correction"); self.gamma_btn.setObjectName("toolButton"); self.gamma_btn.setCheckable(True); self.gamma_btn.clicked.connect(lambda:self.open_tool_page("gamma"))
        rl.addWidget(self.preprocessing_btn); rl.addWidget(self.gamma_btn); rl.addStretch(1)
        body.addWidget(rail)

        shell=QFrame(); shell.setObjectName("workspaceCard"); self._workspace_card=shell
        shell_l=QVBoxLayout(shell); shell_l.setContentsMargins(0,0,0,0); shell_l.setSpacing(0)
        self.stacked_widget=QStackedWidget(); self.stacked_widget.setObjectName("augmentationWorkspace")
        self.dataset_page=ProfessionalDatasetPage(); self.augmentation_page=ProfessionalAugmentationPage(); self.progress_page=ProfessionalProgressPage(); self.preprocessing_page=ProfessionalPreprocessingPanel(embedded=True); self.gamma_page=ProfessionalGammaPanel()
        for page in (self.dataset_page,self.augmentation_page,self.progress_page,self.preprocessing_page,self.gamma_page): self.stacked_widget.addWidget(page)
        shell_l.addWidget(self.stacked_widget,1)

        self.footer=QWidget(); self.footer.setObjectName("workspaceFooter"); fl=QHBoxLayout(self.footer); fl.setContentsMargins(20,10,20,14); fl.setSpacing(9)
        self.back_btn=QPushButton("← Back"); self.back_btn.clicked.connect(self.previous_page)
        self.status_message=QLabel(); self.status_message.setObjectName("footerStatus")
        self.cancel_btn=QPushButton("Cancel"); self.cancel_btn.setObjectName("ghostButton"); self.cancel_btn.clicked.connect(self.close)
        self.next_btn=QPushButton("Continue to Settings →"); self.next_btn.setObjectName("primaryButton"); self.next_btn.clicked.connect(self.next_page)
        self.start_btn=QPushButton("Start Augmentation"); self.start_btn.setObjectName("primaryButton"); self.start_btn.clicked.connect(self.start_augmentation)
        self.finish_btn=QPushButton("Finish"); self.finish_btn.setObjectName("primaryButton"); self.finish_btn.clicked.connect(self.finish_augmentation)
        fl.addWidget(self.back_btn); fl.addWidget(self.status_message); fl.addStretch(); fl.addWidget(self.cancel_btn); fl.addWidget(self.finish_btn); fl.addWidget(self.start_btn); fl.addWidget(self.next_btn)
        shell_l.addWidget(self.footer)
        body.addWidget(shell,1); root.addLayout(body,1)

        self.progress_page.start_requested.connect(self.start_augmentation); self.progress_page.back_requested.connect(self.previous_page); self.progress_page.cancel_requested.connect(self.close)
        self.preprocessing_page.back_requested.connect(self.previous_page)
        self.gamma_page.back_requested.connect(self.previous_page)
        self.preprocessing_page.finished.connect(lambda res:self.toast(f"Preprocessing done: {res[0]} images → {res[1]}","success",3200))
        self.preprocessing_page.cancel_btn.clicked.connect(self.close); self.gamma_page.cancel_btn.clicked.connect(self.close)
        self.sidebar=SidebarWidget(); self.sidebar.hide()  # compatibility only
        self.installEventFilter(self); self._root_widget.installEventFilter(self)
        self.update_navigation(); self.update_sidebar_steps(); self._force_local_augmentation_theme()

    def _force_local_augmentation_theme(self):
        """Reassert the approved local theme after embedding/reparenting.

        The host's legacy compatibility adapter clears child stylesheets.
        This page deliberately owns its own design system, so it must restore
        the stylesheet after any external StyleChange/ParentChange.
        """
        if self._restoring_local_theme:
            return

        self._restoring_local_theme = True
        try:
            root = getattr(self, "_root_widget", None) or self.centralWidget()

            # Mark both the hidden QMainWindow and the embedded root so the host
            # can identify this as a self-themed page.
            self.setProperty("preserveLocalTheme", True)
            if root is not None:
                root.setProperty("preserveLocalTheme", True)
                root.setAttribute(Qt.WA_StyledBackground, True)

            self.setStyleSheet(AUGMENTATION_QSS)
            if root is not None:
                root.setStyleSheet(AUGMENTATION_QSS)

            # Force structural surfaces to repaint immediately.  This is
            # particularly important after adapt_legacy_page() changed palettes.
            targets = [
                root,
                getattr(self, "_workflow_rail", None),
                getattr(self, "_workspace_card", None),
                getattr(self, "stacked_widget", None),
                getattr(self, "dataset_page", None),
                getattr(self, "augmentation_page", None),
                getattr(self, "progress_page", None),
                getattr(self, "preprocessing_page", None),
                getattr(self, "gamma_page", None),
            ]
            for target in targets:
                if target is None:
                    continue
                target.setAttribute(Qt.WA_StyledBackground, True)
                target.style().unpolish(target)
                target.style().polish(target)
                target.update()

            self.style().unpolish(self)
            self.style().polish(self)
            self.update()
        finally:
            self._restoring_local_theme = False

    def _schedule_theme_restore(self):
        if self._theme_restore_scheduled or self._restoring_local_theme:
            return
        self._theme_restore_scheduled = True

        def restore():
            self._theme_restore_scheduled = False
            self._force_local_augmentation_theme()

        # Multiple passes intentionally survive late host/global stylesheet work.
        QTimer.singleShot(0, restore)
        QTimer.singleShot(60, self._force_local_augmentation_theme)
        QTimer.singleShot(160, self._force_local_augmentation_theme)
        QTimer.singleShot(320, self._force_local_augmentation_theme)

    def eventFilter(self, watched, event):
        if watched in (self, getattr(self, "_root_widget", None)):
            etype = event.type()

            if etype in (QEvent.ParentChange, QEvent.Show):
                self._schedule_theme_restore()

            # The legacy adapter calls setStyleSheet("") on embedded widgets.
            # Detect that exact loss and restore after the adapter completes.
            elif etype == QEvent.StyleChange and not self._restoring_local_theme:
                root = getattr(self, "_root_widget", None)
                if watched is root:
                    current_qss = root.styleSheet() if root is not None else ""
                    if "QFrame#workflowRail" not in current_qss:
                        self._schedule_theme_restore()

        return super().eventFilter(watched, event)

    def showEvent(self,event):
        super().showEvent(event)
        self._schedule_theme_restore()

    def initialize_tool(self):
        """Called by Main_GUI after the central widget is reparented."""
        self._force_local_augmentation_theme()
        self.update_navigation()
        self.update_sidebar_steps()
        self._schedule_theme_restore()

    def show_help_guide(self): HelpGuideDialog(self).exec_()

    def _jump_step(self,index):
        if index==self.current_page and not self._tool_page: return
        if index==0:
            self.current_page=0
        elif index==1:
            if not self.validate_dataset_setup(): return
            self.config.update(self.dataset_page.get_config()); self.current_page=1
        elif index==2:
            if not self.validate_dataset_setup(): return
            self.config.update(self.dataset_page.get_config()); self.config.update(self.augmentation_page.get_config()); self.current_page=2; self.progress_page.set_run_summary(self.config)
        self._tool_page=None; self.stacked_widget.setCurrentIndex(self.current_page); self.update_navigation(); self.update_sidebar_steps()

    def open_tool_page(self,which: str):
        self._tool_page=which
        self.stacked_widget.setCurrentWidget(self.preprocessing_page if which=="pre" else self.gamma_page)
        self.preprocessing_btn.setChecked(which=="pre"); self.gamma_btn.setChecked(which=="gamma")
        for b in self.step_buttons: b.setChecked(False)
        self.footer.hide(); self._force_local_augmentation_theme()

    def update_sidebar_steps(self):
        captions=("Dataset Setup","Settings","Review & Run")
        for index,button in enumerate(self.step_buttons):
            state="complete" if index<self.current_page else "current" if index==self.current_page and not self._tool_page else "upcoming"
            button.setProperty("stepState",state); button.setText(f"{index+1}    {captions[index]}"); button.setChecked(state=="current"); button.style().unpolish(button); button.style().polish(button)
        if not self._tool_page: self.preprocessing_btn.setChecked(False); self.gamma_btn.setChecked(False)

    def update_navigation(self):
        self.footer.show(); self._tool_page=None
        self.back_btn.setVisible(self.current_page>0); self.cancel_btn.setVisible(True); self.finish_btn.hide(); self.start_btn.hide()
        if self.current_page==0:
            self.next_btn.show(); self.next_btn.setText("Continue to Settings →")
        elif self.current_page==1:
            self.next_btn.show(); self.next_btn.setText("Review & Run →")
        else:
            self.next_btn.hide(); self.footer.hide()  # review page owns its own footer/actions
        self._force_local_augmentation_theme()

    def next_page(self):
        if self.current_page==0:
            if not self.validate_dataset_setup(): return
            self.config.update(self.dataset_page.get_config()); self.current_page=1; self.toast("Step 2: set your augmentation options.","info",1800)
        elif self.current_page==1:
            self.config.update(self.augmentation_page.get_config()); self.current_page=2; self.progress_page.set_run_summary(self.config); self.toast("Review the configuration, then start augmentation.","info",2200)
        self._tool_page=None; self.stacked_widget.setCurrentIndex(self.current_page); self.update_navigation(); self.update_sidebar_steps()

    def previous_page(self):
        if self._tool_page:
            self._tool_page=None; self.stacked_widget.setCurrentIndex(self.current_page); self.update_navigation(); self.update_sidebar_steps(); return
        if self.current_page>0:
            self.current_page-=1; self.stacked_widget.setCurrentIndex(self.current_page); self.update_navigation(); self.update_sidebar_steps()

    def validate_dataset_setup(self):
        config=self.dataset_page.get_config(); self.dataset_page.validation_label.hide()
        if not config['input_dir']:
            self.dataset_page.validation_label.setText("Select an input directory to continue."); self.dataset_page.validation_label.show(); self.toast("Please select input directory.","warn"); return False
        if not config['output_dir']:
            self.dataset_page.validation_label.setText("Select an output directory to continue."); self.dataset_page.validation_label.show(); self.toast("Please select output directory.","warn"); return False
        input_dir=Path(config['input_dir'])
        if not input_dir.exists():
            self.dataset_page.validation_label.setText("The selected input directory does not exist."); self.dataset_page.validation_label.show(); self.toast("Input directory does not exist.","error"); return False
        self.toast("Dataset configuration looks good.","success",1800); return True

    def start_augmentation(self):
        if self.worker is not None and self.worker.isRunning(): return
        self.config.update(self.dataset_page.get_config()); self.config.update(self.augmentation_page.get_config()); self.progress_page.set_run_summary(self.config)
        self.toast("Starting augmentation…","info"); self.progress_page.start_run_state(); self.progress_page.progress_bar.setValue(0); self.progress_page.progress_text.setText("0% complete"); self.progress_page.log_text.clear()
        self.worker=AugmentationWorker(self.config); self.worker.progress.connect(self.progress_page.update_progress); self.worker.message.connect(self.progress_page.log_message); self.worker.finished_signal.connect(self.augmentation_finished); self.worker.error.connect(self.augmentation_error); self.worker.start()

    def augmentation_finished(self,message):
        self.progress_page.log_message(message); self.progress_page.finish_run_state(True); self.augmentation_completed=True; self.toast("Augmentation completed successfully!","success",3000)

    def augmentation_error(self,error_message):
        self.progress_page.log_message(f"ERROR: {error_message}"); self.progress_page.finish_run_state(False); self.toast("Augmentation failed. See log for details.","error",3500)

    def finish_augmentation(self):
        self.current_page=0; self.augmentation_completed=False; self.config={}; self.dataset_page.input_dir_edit.clear(); self.dataset_page.output_dir_edit.clear(); self.dataset_page.train_ratio_spin.setValue(.8); self.dataset_page.seed_spin.setValue(42); self.dataset_page.quality_spin.setValue(95); self.dataset_page.float_precision_combo.setCurrentText("16"); self.augmentation_page.flip_horizontal_cb.setChecked(True); self.augmentation_page.flip_vertical_cb.setChecked(False); self.augmentation_page.brightness_cb.setChecked(True); self.augmentation_page.brightness_spin.setValue(20); self.augmentation_page.saturation_cb.setChecked(True); self.augmentation_page.saturation_spin.setValue(20); self.progress_page.progress_bar.setValue(0); self.progress_page.log_text.clear(); self.stacked_widget.setCurrentIndex(0); self.update_navigation(); self.update_sidebar_steps(); self.toast("Wizard reset — start a new augmentation anytime.","info",2500)


# ======================= Entry Point ================================
def main():
    import sys
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(35, 35, 35))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(50, 50, 50))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)

    window = AugmentationWizard()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
