# fine_live.py  (FRONTEND + INFERENCE INTEGRATION)
from __future__ import annotations

import sys
import time
import os
import threading
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
import shutil
import traceback

from PyQt5 import QtCore, QtGui, QtWidgets

# Import the inference module
try:
    from inferences.inflator_batch_infer import run_inference_on_folder
    INFERENCE_AVAILABLE = True
    print("[INFO] Inference module loaded successfully")
except ImportError:
    # Try direct import
    try:
        from inflator_batch_infer import run_inference_on_folder
        INFERENCE_AVAILABLE = True
        print("[INFO] Inference module loaded directly")
    except ImportError as e:
        INFERENCE_AVAILABLE = False
        print(f"[WARNING] Inference module not available: {e}")


# ----------------------------
# App base dir + logo finder
# ----------------------------
def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _find_logo() -> Optional[Path]:
    media = _app_base_dir() / "Media"
    if not media.exists():
        return None
    for name in ("EYRES LOGO-02.png", "LOGO-02.png", "logo.png", "Logo.png", "logo@2x.png"):
        p = media / name
        if p.is_file():
            return p
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp"):
        files = list(media.glob(ext))
        if files:
            return files[0]
    return None


# ----------------------------
# Small Toggle Switch (safe)
# ----------------------------
class ToggleSwitch(QtWidgets.QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(False)

        self._offset = 0.0
        self._anim = QtCore.QPropertyAnimation(self, b"offset", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(46, 24)

    def sizeHint(self):
        return QtCore.QSize(46, 24)

    def mouseReleaseEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.setChecked(not self.isChecked())
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = rect.height() / 2

        track_off = QtGui.QColor("#cbd5e1")
        track_on = QtGui.QColor("#94a3b8")
        p.setPen(QtGui.QPen(QtGui.QColor("#b0b7c3"), 2))
        p.setBrush(track_on if self.isChecked() else track_off)
        p.drawRoundedRect(rect, radius, radius)

        knob_d = rect.height() - 6
        x_min = rect.left() + 3
        x_max = rect.right() - 3 - knob_d
        x = x_min + (x_max - x_min) * float(self._offset)
        knob_rect = QtCore.QRectF(x, rect.top() + 3, knob_d, knob_d)

        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(knob_rect)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        try:
            self._anim.stop()
            self._anim.setStartValue(self._offset)
            self._anim.setEndValue(1.0 if checked else 0.0)
            self._anim.start()
        except Exception:
            self._offset = 1.0 if checked else 0.0
            self.update()

    @QtCore.pyqtProperty(float)
    def offset(self):
        return self._offset

    @offset.setter
    def offset(self, v: float):
        self._offset = float(v)
        self.update()


# ----------------------------
# Metric card (sidebar)
# ----------------------------
class MetricCard(QtWidgets.QFrame):
    def __init__(self, title: str, value: str = "0", bar_color="#94a3b8", parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")

        self.title_lbl = QtWidgets.QLabel(title)
        self.title_lbl.setObjectName("MetricTitle")

        self.value_lbl = QtWidgets.QLabel(value)
        self.value_lbl.setObjectName("MetricValue")
        self.value_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        top = QtWidgets.QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.title_lbl)
        top.addStretch(1)
        top.addWidget(self.value_lbl)

        self.bar = QtWidgets.QFrame()
        self.bar.setObjectName("MetricBar")
        self.bar.setFixedHeight(4)
        self.bar.setStyleSheet(f"#MetricBar{{background:{bar_color}; border-radius:2px;}}")

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(8)
        lay.addLayout(top)
        lay.addWidget(self.bar)

    def set_value(self, text: str):
        self.value_lbl.setText(text)


# ----------------------------
# Frame card (main area)
# ----------------------------
class FrameCard(QtWidgets.QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("FrameCard")
        self._pix: Optional[QtGui.QPixmap] = None
        self._original_image: Optional[str] = None

        self.title_lbl = QtWidgets.QLabel(title)
        self.title_lbl.setObjectName("FrameTitle")

        self.image_lbl = QtWidgets.QLabel("Waiting…")
        self.image_lbl.setObjectName("ImageArea")
        self.image_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self.image_lbl.setMinimumHeight(220)
        self.image_lbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)

        self.footer_lbl = QtWidgets.QLabel("Status: —   |   Score: —")
        self.footer_lbl.setObjectName("FrameFooter")
        self.footer_lbl.setAlignment(QtCore.Qt.AlignCenter)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)
        lay.addWidget(self.title_lbl)
        lay.addWidget(self.image_lbl, 1)
        lay.addWidget(self.footer_lbl)

    def clear(self):
        self._pix = None
        self._original_image = None
        self.image_lbl.setText("Waiting…")
        self.image_lbl.setPixmap(QtGui.QPixmap())
        self.set_status("—", "—")

    def set_status(self, status: str, score: str):
        self.footer_lbl.setText(f"Status: {status}   |   Score: {score}")

    def set_image_path(self, image_path: str):
        """Load image from file path"""
        self._original_image = image_path
        if os.path.exists(image_path):
            pix = QtGui.QPixmap(image_path)
            if not pix.isNull():
                self._pix = pix
                self._apply_scaled()
                return True
        return False

    def set_image(self, pix: QtGui.QPixmap):
        self._pix = pix
        self._apply_scaled()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._pix is not None:
            self._apply_scaled()

    def _apply_scaled(self):
        if not self._pix:
            return
        target = self.image_lbl.size() - QtCore.QSize(18, 18)
        scaled = self._pix.scaled(target, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.image_lbl.setText("")
        self.image_lbl.setPixmap(scaled)


# ----------------------------
# Main Window
# ----------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live Inspection")
        self.resize(1400, 820)
        self.setMinimumSize(1200, 720)

        self._start_time = time.time()
        self._cycle = 0
        self._good_count = 0
        self._bad_count = 0
        self._total_count = 0
        
        # Store inspection results
        self._current_results: List[Dict] = []
        self._inference_thread: Optional[threading.Thread] = None
        self._inference_running = False
        
        # Input/Output folders
        self._input_folder = ""
        self._output_folder = ""
        
        # Track processed images
        self._processed_images = set()
        
        # Create default output directory
        self._create_default_output_folder()

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)

        root = QtWidgets.QHBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # Sidebar (scrollable so it never cuts off)
        self.sidebar = self._build_sidebar()
        side_scroll = QtWidgets.QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        side_scroll.setWidget(self.sidebar)
        side_scroll.setFixedWidth(290)

        # Tabs (no outer borders; thin green indicator on selected tab)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setObjectName("MainTabs")

        self.live_page = self._build_live_page()
        self.prev_page = self._build_previous_page()

        self.tabs.addTab(self.live_page, "Live Inspection")
        self.tabs.addTab(self.prev_page, "Previous Inspection")

        right_wrap = QtWidgets.QWidget()
        right_lay = QtWidgets.QVBoxLayout(right_wrap)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.addWidget(self.tabs)

        right_scroll = QtWidgets.QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        right_scroll.setWidget(right_wrap)

        root.addWidget(side_scroll, 0)
        root.addWidget(right_scroll, 1)

        # Timer for updating UI
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        
        # Timer for checking new images
        self.inspection_timer = QtCore.QTimer(self)
        self.inspection_timer.timeout.connect(self._check_for_new_images)
        self.inspection_timer.start(2000)  # Check every 2 seconds

        self._apply_styles()

    def _create_default_output_folder(self):
        """Create a default output folder if not exists"""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self._output_folder = os.path.join(base_dir, "inspection_output")
        os.makedirs(self._output_folder, exist_ok=True)
        
        # Create subdirectories for organized storage
        os.makedirs(os.path.join(self._output_folder, "good"), exist_ok=True)
        os.makedirs(os.path.join(self._output_folder, "bad"), exist_ok=True)
        os.makedirs(os.path.join(self._output_folder, "raw"), exist_ok=True)
        
        # Load processed images
        self._processed_file = os.path.join(self._output_folder, "processed_images.txt")
        if os.path.exists(self._processed_file):
            with open(self._processed_file, 'r') as f:
                self._processed_images = set(line.strip() for line in f)
        else:
            with open(self._processed_file, 'w') as f:
                pass

    # ----------------------------
    # Sidebar
    # ----------------------------
    def _build_sidebar(self) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        card = QtWidgets.QFrame()
        card.setObjectName("SidebarCard")
        card_l = QtWidgets.QVBoxLayout(card)
        card_l.setContentsMargins(10, 10, 10, 10)
        card_l.setSpacing(12)

        # Logo area
        self.logo_lbl = QtWidgets.QLabel()
        self.logo_lbl.setObjectName("BrandLogo")
        self.logo_lbl.setAlignment(QtCore.Qt.AlignCenter)
        self.logo_lbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.logo_lbl.setFixedHeight(86)

        logo_path = _find_logo()
        self._logo_pix: Optional[QtGui.QPixmap] = None
        if logo_path:
            pix = QtGui.QPixmap(str(logo_path))
            if not pix.isNull():
                self._logo_pix = pix
                self._apply_logo_scaled()
            else:
                self.logo_lbl.setText("Logo not found")
        else:
            self.logo_lbl.setText("Logo not found")

        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setObjectName("Divider")

        hdr = QtWidgets.QLabel("INSPECTION SUMMARY")
        hdr.setObjectName("SectionHeader")

        self.good_card = MetricCard("Good (G)", "0", bar_color="#22c55e")
        self.bad_card = MetricCard("Bad (NG)", "0", bar_color="#ef4444")
        self.rr_card = MetricCard("Rej. Ratio (RR)", "0.00%", bar_color="#f59e0b")
        self.total_card = MetricCard("Total", "0", bar_color="#64748b")

        # Folder selection
        folder_group = QtWidgets.QGroupBox("Input Folder")
        folder_group.setObjectName("GroupBox")
        folder_layout = QtWidgets.QVBoxLayout(folder_group)
        
        self.folder_path_label = QtWidgets.QLabel("Not selected")
        self.folder_path_label.setObjectName("PathLabel")
        self.folder_path_label.setWordWrap(True)
        
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.setObjectName("ActionBtn")
        browse_btn.clicked.connect(self._browse_input_folder)
        
        folder_layout.addWidget(self.folder_path_label)
        folder_layout.addWidget(browse_btn)

        # Action buttons
        self.start_btn = QtWidgets.QPushButton("Start Inspection")
        self.start_btn.setObjectName("PrimaryBtn")
        self.start_btn.clicked.connect(self._start_inspection)
        
        self.stop_btn = QtWidgets.QPushButton("Stop Inspection")
        self.stop_btn.setObjectName("SecondaryBtn")
        self.stop_btn.clicked.connect(self._stop_inspection)
        self.stop_btn.setEnabled(False)

        self.reset_btn = QtWidgets.QPushButton("Reset Counts / Images")
        self.reset_btn.setObjectName("DangerBtn")
        self.reset_btn.clicked.connect(self._reset_all)

        bypass_row = QtWidgets.QHBoxLayout()
        bypass_row.setContentsMargins(0, 0, 0, 0)
        bypass_lbl = QtWidgets.QLabel("Rejection Bypass")
        bypass_lbl.setObjectName("RowLabel")
        self.bypass_toggle = ToggleSwitch()
        bypass_row.addWidget(bypass_lbl)
        bypass_row.addStretch(1)
        bypass_row.addWidget(self.bypass_toggle)

        self.uptime_pill = self._pill("Uptime", "00:00:00")
        self.cycle_pill = self._pill("Cycle", "0")

        card_l.addWidget(self.logo_lbl)
        card_l.addWidget(line)
        card_l.addWidget(hdr)

        card_l.addWidget(self.good_card)
        card_l.addWidget(self.bad_card)
        card_l.addWidget(self.rr_card)
        card_l.addWidget(self.total_card)
        
        card_l.addWidget(folder_group)
        card_l.addWidget(self.start_btn)
        card_l.addWidget(self.stop_btn)
        card_l.addWidget(self.reset_btn)
        card_l.addLayout(bypass_row)
        card_l.addWidget(self.uptime_pill)
        card_l.addWidget(self.cycle_pill)

        card_l.addStretch(1)

        lay.addWidget(card)
        return w

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._logo_pix is not None:
            self._apply_logo_scaled()

    def _apply_logo_scaled(self):
        if self._logo_pix is None:
            return
        target = self.logo_lbl.size() - QtCore.QSize(4, 4)
        w = max(1, target.width())
        h = max(1, target.height())
        scaled = self._logo_pix.scaled(w, h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        self.logo_lbl.setPixmap(scaled)
        self.logo_lbl.setText("")

    def _pill(self, left: str, right: str) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setObjectName("Pill")
        l = QtWidgets.QHBoxLayout(f)
        l.setContentsMargins(12, 8, 12, 8)
        l.setSpacing(8)
        a = QtWidgets.QLabel(left)
        a.setObjectName("PillLeft")
        b = QtWidgets.QLabel(right)
        b.setObjectName("PillRight")
        b.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        l.addWidget(a)
        l.addStretch(1)
        l.addWidget(b)
        f._right_label = b
        return f

    # ----------------------------
    # Live page
    # ----------------------------
    def _build_live_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(page)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        grid_wrap = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(grid_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        self.frames: Dict[int, FrameCard] = {
            1: FrameCard("Frame 1"),
            2: FrameCard("Frame 2"),
            3: FrameCard("Frame 3"),
            4: FrameCard("Frame 4"),
            5: FrameCard("Frame 5"),
        }

        grid.addWidget(self.frames[1], 0, 0)
        grid.addWidget(self.frames[2], 0, 1)
        grid.addWidget(self.frames[3], 0, 2)
        grid.addWidget(self.frames[4], 1, 0)
        grid.addWidget(self.frames[5], 1, 1)

        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)

        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        grid.addWidget(spacer, 1, 2)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(grid_wrap)

        outer.addWidget(scroll, 1)
        return page

    # ----------------------------
    # Previous page
    # ----------------------------
    def _build_previous_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(page)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        box = QtWidgets.QFrame()
        box.setObjectName("PlaceholderBox")
        b = QtWidgets.QVBoxLayout(box)
        b.setContentsMargins(16, 16, 16, 16)
        b.setSpacing(8)

        t = QtWidgets.QLabel("Previous Inspection")
        t.setObjectName("PlaceholderTitle")
        d = QtWidgets.QLabel("This page is a placeholder UI.\nLater you can connect DB/history here.")
        d.setObjectName("PlaceholderDesc")

        b.addWidget(t)
        b.addWidget(d)
        b.addStretch(1)

        lay.addWidget(box, 1)
        return page

    # ----------------------------
    # Folder and Inspection Actions
    # ----------------------------
    def _browse_input_folder(self):
        """Open dialog to select input folder"""
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Input Folder", os.path.expanduser("~")
        )
        if folder:
            self._input_folder = folder
            self.folder_path_label.setText(os.path.basename(folder))
            
            # Check for images in the folder
            image_count = self._count_images_in_folder(folder)
            QtWidgets.QMessageBox.information(
                self, "Folder Selected",
                f"Selected folder: {os.path.basename(folder)}\n"
                f"Found {image_count} image(s)\n"
                f"Click 'Start Inspection' to begin processing."
            )

    def _count_images_in_folder(self, folder: str) -> int:
        """Count valid image files in folder"""
        valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
        if not os.path.exists(folder):
            return 0
        count = 0
        for file in os.listdir(folder):
            if file.lower().endswith(valid_exts):
                count += 1
        return count

    def _start_inspection(self):
        """Start the inspection process"""
        if not self._input_folder or not os.path.exists(self._input_folder):
            QtWidgets.QMessageBox.warning(
                self, "No Input Folder",
                "Please select an input folder first."
            )
            return
        
        if not INFERENCE_AVAILABLE:
            QtWidgets.QMessageBox.critical(
                self, "Inference Module Missing",
                "The inference module is not available.\n"
                "Please ensure the inference module files are accessible."
            )
            return
        
        # Check if there are images to process
        image_count = self._count_images_in_folder(self._input_folder)
        if image_count == 0:
            QtWidgets.QMessageBox.warning(
                self, "No Images Found",
                f"No images found in the selected folder: {self._input_folder}"
            )
            return
        
        # Start inference in a separate thread
        self._inference_running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        self._inference_thread = threading.Thread(
            target=self._run_inference_loop,
            daemon=True
        )
        self._inference_thread.start()
        
        QtWidgets.QMessageBox.information(
            self, "Inspection Started",
            f"Inspection started on folder: {os.path.basename(self._input_folder)}\n"
            f"Found {image_count} image(s) to process.\n"
            f"Results will be saved to: {self._output_folder}"
        )

    def _stop_inspection(self):
        """Stop the inspection process"""
        self._inference_running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        QtWidgets.QMessageBox.information(
            self, "Inspection Stopped",
            "Inspection has been stopped."
        )

    def _run_inference_loop(self):
        """Run inference in background thread continuously"""
        try:
            while self._inference_running:
                # Get unprocessed images
                unprocessed_images = self._get_unprocessed_images()
                
                if unprocessed_images:
                    print(f"[INFO] Processing {len(unprocessed_images)} new images")
                    
                    # Process images in batches
                    for i in range(0, len(unprocessed_images), 4):
                        if not self._inference_running:
                            break
                        
                        batch = unprocessed_images[i:i+4]
                        try:
                            # Run inference on this batch
                            results = run_inference_on_folder(
                                input_folder=self._input_folder,
                                output_dir=self._output_folder,
                                device="cuda",  # Change to "cpu" if no GPU
                                batch_size=4
                            )
                            
                            # Mark images as processed
                            for img_path in batch:
                                self._mark_as_processed(img_path)
                            
                            # Update UI with results
                            if results:
                                QtCore.QMetaObject.invokeMethod(self, 
                                                              "_update_counts_from_results",
                                                              QtCore.Qt.QueuedConnection,
                                                              QtCore.Q_ARG(list, results))
                            
                        except Exception as e:
                            print(f"[ERROR] Batch inference failed: {e}")
                            QtCore.QMetaObject.invokeMethod(self,
                                                          "_show_error_message",
                                                          QtCore.Qt.QueuedConnection,
                                                          QtCore.Q_ARG(str, f"Inference Error: {str(e)}"))
                
                # Wait before checking for new images
                time.sleep(2)
                
        except Exception as e:
            print(f"[ERROR] Inference loop failed: {e}")
            traceback.print_exc()
            QtCore.QMetaObject.invokeMethod(self,
                                          "_show_error_message",
                                          QtCore.Qt.QueuedConnection,
                                          QtCore.Q_ARG(str, f"Fatal Error: {str(e)}"))

    def _get_unprocessed_images(self):
        """Get list of unprocessed images in input folder"""
        valid_exts = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
        unprocessed = []
        
        if not os.path.exists(self._input_folder):
            return unprocessed
        
        for file in os.listdir(self._input_folder):
            if file.lower().endswith(valid_exts):
                img_path = os.path.join(self._input_folder, file)
                if img_path not in self._processed_images:
                    unprocessed.append(img_path)
        
        return unprocessed

    def _mark_as_processed(self, image_path: str):
        """Mark an image as processed"""
        self._processed_images.add(image_path)
        with open(self._processed_file, 'a') as f:
            f.write(f"{image_path}\n")

    def _check_for_new_images(self):
        """Check for new annotated images in output folder and display them"""
        if not self._inference_running:
            return
            
        # Look for annotated images in the output folder
        annotated_files = []
        for root, dirs, files in os.walk(self._output_folder):
            for file in files:
                if file.endswith("_annotated.png"):
                    file_path = os.path.join(root, file)
                    annotated_files.append((file_path, os.path.getmtime(file_path)))
        
        # Sort by modification time (newest first)
        annotated_files.sort(key=lambda x: x[1], reverse=True)
        
        # Display up to 4 most recent images in frames 1-4
        for i, frame_num in enumerate([1, 2, 3, 4]):
            if i < len(annotated_files):
                image_path = annotated_files[i][0]
                self.frames[frame_num].set_image_path(image_path)
                
                # Determine status based on folder
                status = "Good" if "good" in image_path.lower() else "Bad"
                score = "100%" if status == "Good" else "0%"
                self.frames[frame_num].set_status(status, score)
            else:
                # Clear frame if no image
                self.frames[frame_num].clear()

    @QtCore.pyqtSlot(list)
    def _update_counts_from_results(self, results: List[Dict]):
        """Update counts based on inference results"""
        if not results:
            return
            
        # Group results by image
        results_by_image = {}
        for result in results:
            image_name = result.get("image", "")
            if image_name not in results_by_image:
                results_by_image[image_name] = []
            results_by_image[image_name].append(result)
        
        # Process each image
        for image_name, image_results in results_by_image.items():
            self._total_count += 1
            self._cycle += 1
            
            # Determine if the image is good or bad
            # For now, if any holes are detected, consider it bad
            has_holes = any(r.get("type") == "hole" for r in image_results)
            
            if has_holes and not self.bypass_toggle.isChecked():
                self._bad_count += 1
                self._organize_result("bad", image_results)
            else:
                self._good_count += 1
                self._organize_result("good", image_results)
            
            # Update UI
            self._update_counts_ui()

    def _organize_result(self, category: str, results: List[Dict]):
        """Organize results into appropriate folders"""
        try:
            if results and len(results) > 0:
                image_name = results[0].get("image", "")
                if image_name:
                    # Find the annotated image
                    base_name = os.path.splitext(image_name)[0]
                    annotated_pattern = f"{base_name}_annotated.png"
                    
                    # Search for the annotated image
                    for root, dirs, files in os.walk(self._output_folder):
                        for file in files:
                            if file == f"{base_name}_annotated.png":
                                src_path = os.path.join(root, file)
                                dest_folder = os.path.join(self._output_folder, category)
                                os.makedirs(dest_folder, exist_ok=True)
                                
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                dest_path = os.path.join(dest_folder, f"{timestamp}_{file}")
                                shutil.copy2(src_path, dest_path)
                                
                                # Also copy CSV if exists
                                csv_file = f"{base_name}_results.csv"
                                csv_src = os.path.join(root, csv_file)
                                if os.path.exists(csv_src):
                                    csv_dest = os.path.join(dest_folder, f"{timestamp}_{csv_file}")
                                    shutil.copy2(csv_src, csv_dest)
                                
                                break
        except Exception as e:
            print(f"[ERROR] Organizing results failed: {e}")

    @QtCore.pyqtSlot()
    def _update_counts_ui(self):
        """Update count displays in UI"""
        self.good_card.set_value(str(self._good_count))
        self.bad_card.set_value(str(self._bad_count))
        self.total_card.set_value(str(self._total_count))
        
        # Calculate rejection ratio
        if self._total_count > 0:
            rr = (self._bad_count / self._total_count) * 100
            self.rr_card.set_value(f"{rr:.2f}%")
        else:
            self.rr_card.set_value("0.00%")
        
        self.cycle_pill._right_label.setText(str(self._cycle))

    @QtCore.pyqtSlot(str)
    def _show_error_message(self, message: str):
        """Show error message in UI thread"""
        QtWidgets.QMessageBox.critical(self, "Error", message)

    # ----------------------------
    # Actions
    # ----------------------------
    def _reset_all(self):
        """Reset all counts and clear images"""
        self._good_count = 0
        self._bad_count = 0
        self._total_count = 0
        self._cycle = 0
        self._processed_images.clear()
        
        # Clear the processed images file
        if os.path.exists(self._processed_file):
            with open(self._processed_file, 'w') as f:
                pass
        
        self.good_card.set_value("0")
        self.bad_card.set_value("0")
        self.rr_card.set_value("0.00%")
        self.total_card.set_value("0")
        
        for f in self.frames.values():
            f.clear()
        
        QtWidgets.QMessageBox.information(
            self, "Reset Complete",
            "All counts have been reset and images cleared."
        )

    def _tick(self):
        """Update uptime timer"""
        sec = int(time.time() - self._start_time)
        hh = sec // 3600
        mm = (sec % 3600) // 60
        ss = sec % 60
        self.uptime_pill._right_label.setText(f"{hh:02d}:{mm:02d}:{ss:02d}")

    # ----------------------------
    # Styling
    # ----------------------------
    def _apply_styles(self):
        border = "#b0b7c3"
        border2 = "#c7cdd6"
        text = "#0f172a"
        subtext = "#475569"
        green = "#22c55e"
        blue = "#3b82f6"

        self.setStyleSheet(f"""
        QWidget {{
            background: #ffffff;
            color: {text};
            font-family: Segoe UI;
            font-size: 12px;
        }}

        /* Tabs: thin green indicator */
        QTabWidget#MainTabs::pane {{
            border: none;
            background: #ffffff;
            padding: 0px;
        }}
        QTabBar {{
            background: #ffffff;
        }}
        QTabBar::tab {{
            background: transparent;
            border: none;
            padding: 10px 14px;
            margin-right: 10px;
            min-width: 150px;
            font-weight: 800;
            color: {subtext};
        }}
        QTabBar::tab:selected {{
            color: {text};
            border-bottom: 2px solid {green};   /* thinner indicator */
        }}
        QTabBar::tab:!selected {{
            border-bottom: 2px solid transparent;
        }}

        /* Sidebar card */
        QFrame#SidebarCard {{
            border: 1px solid {border};
            border-radius: 14px;
            background: #ffffff;
        }}

        /* Group boxes */
        QGroupBox#GroupBox {{
            border: 1px solid {border};
            border-radius: 10px;
            margin-top: 10px;
            padding-top: 10px;
            font-weight: 800;
            color: {text};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px 0 5px;
        }}

        /* Path label */
        QLabel#PathLabel {{
            background: #f8fafc;
            border: 1px solid {border};
            border-radius: 6px;
            padding: 6px;
            font-weight: 700;
            color: {subtext};
        }}

        /* Action buttons */
        QPushButton#ActionBtn {{
            border: 1px solid {blue};
            background: #ffffff;
            color: {blue};
            padding: 6px 10px;
            border-radius: 10px;
            font-weight: 800;
        }}
        QPushButton#ActionBtn:hover {{
            background: #eff6ff;
        }}

        QPushButton#PrimaryBtn {{
            border: 1px solid {green};
            background: {green};
            color: #ffffff;
            padding: 8px 12px;
            border-radius: 10px;
            font-weight: 800;
        }}
        QPushButton#PrimaryBtn:hover {{
            background: #16a34a;
            border-color: #16a34a;
        }}
        QPushButton#PrimaryBtn:disabled {{
            background: #bbf7d0;
            border-color: #bbf7d0;
            color: #86efac;
        }}

        QPushButton#SecondaryBtn {{
            border: 1px solid #64748b;
            background: #64748b;
            color: #ffffff;
            padding: 8px 12px;
            border-radius: 10px;
            font-weight: 800;
        }}
        QPushButton#SecondaryBtn:hover {{
            background: #475569;
            border-color: #475569;
        }}
        QPushButton#SecondaryBtn:disabled {{
            background: #cbd5e1;
            border-color: #cbd5e1;
            color: #94a3b8;
        }}

        /* Logo: NO border box */
        QLabel#BrandLogo {{
            border: none;
            padding: 0px;
            background: transparent;
        }}

        QFrame#Divider {{
            color: {border2};
            background: {border2};
            max-height: 1px;
        }}
        QLabel#SectionHeader {{
            margin-top: 2px;
            font-weight: 800;
            letter-spacing: 1px;
            color: {subtext};
        }}

        /* Metric cards */
        QFrame#MetricCard {{
            border: 1px solid {border};
            border-radius: 12px;
            background: #ffffff;
        }}
        QLabel#MetricTitle {{
            font-weight: 700;
            color: {text};
        }}
        QLabel#MetricValue {{
            font-weight: 900;
            font-size: 14px;
        }}

        /* Reset button: smaller */
        QPushButton#DangerBtn {{
            border: 1px solid #ef4444;
            background: #ffffff;
            color: #ef4444;
            padding: 6px 10px;          /* reduced */
            border-radius: 10px;        /* slightly smaller */
            font-weight: 800;
        }}
        QPushButton#DangerBtn:hover {{
            background: #fff1f2;
        }}

        QLabel#RowLabel {{
            font-weight: 800;
            color: {text};
        }}

        /* Pills */
        QFrame#Pill {{
            border: 1px solid {border};
            border-radius: 12px;
            background: #ffffff;
        }}
        QLabel#PillLeft {{
            font-weight: 800;
            color: {text};
        }}
        QLabel#PillRight {{
            font-weight: 900;
        }}

        /* Frame cards */
        QFrame#FrameCard {{
            border: 1px solid {border};
            border-radius: 14px;
            background: #ffffff;
        }}
        QLabel#FrameTitle {{
            font-weight: 900;
        }}
        QLabel#ImageArea {{
            border: 1px dashed #94a3b8;
            border-radius: 12px;
            color: #64748b;
            font-weight: 800;
            background: #ffffff;
        }}
        QLabel#FrameFooter {{
            font-weight: 800;
            color: {text};
        }}

        /* Previous placeholder */
        QFrame#PlaceholderBox {{
            border: 1px solid {border};
            border-radius: 14px;
            background: #ffffff;
        }}
        QLabel#PlaceholderTitle {{
            font-size: 18px;
            font-weight: 900;
        }}
        QLabel#PlaceholderDesc {{
            color: {subtext};
            font-weight: 700;
        }}
        """)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()