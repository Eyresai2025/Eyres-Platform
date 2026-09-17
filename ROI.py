import sys, csv, time
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any

import cv2
import numpy as np

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QRect, QPoint
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QListWidget, QListWidgetItem,
    QLabel, QHBoxLayout, QVBoxLayout, QPushButton, QSplitter, QFormLayout, QGroupBox,
    QSpinBox, QDoubleSpinBox, QMessageBox, QAction, QSizePolicy, QComboBox, QCheckBox,
    QLineEdit, QScrollArea
)

# ---------------- Processing helpers (unchanged) ----------------
def imread_any(path: Path):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None: raise IOError(f"Failed to read image: {path}")
    return img

def preprocess(gray, clahe=True, blur_ksize=5):
    if clahe:
        cl = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = cl.apply(gray)
    if blur_ksize and blur_ksize > 1:
        gray = cv2.GaussianBlur(gray, (blur_ksize, blur_ksize), 0)
    return gray

def pratt_fit(points_xy: np.ndarray):
    x = points_xy[:, 0]; y = points_xy[:, 1]
    x_mean, y_mean = x.mean(), y.mean()
    u = x - x_mean; v = y - y_mean
    Suu = np.sum(u*u); Suv = np.sum(u*v); Svv = np.sum(v*v)
    Suuu = np.sum(u*u*u); Svvv = np.sum(v*v*v)
    Suvv = np.sum(u*v*v); Svuu = np.sum(v*u*u)
    A = np.array([[Suu, Suv], [Suv, Svv]], dtype=np.float64)
    b = 0.5*np.array([Suuu + Suvv, Svvv + Svuu], dtype=np.float64)
    if np.linalg.det(A) < 1e-12: return None
    uc, vc = np.linalg.solve(A, b)
    cx = x_mean + uc; cy = y_mean + vc
    r = np.sqrt(uc*uc + vc*vc + (Suu + Svv)/len(points_xy))
    return float(cx), float(cy), float(r)

def ransac_circle(points_xy: np.ndarray, iters=800, thresh=2.0, min_inliers=60):
    if len(points_xy) < 20: return None, None
    best = None; best_inliers = None; best_in = 0
    N = len(points_xy); rng = np.random.default_rng(1234)
    for _ in range(iters):
        idx = rng.choice(N, size=3, replace=False)
        p1, p2, p3 = points_xy[idx]
        area = abs(0.5*((p2[0]-p1[0])*(p3[1]-p1[1]) - (p3[0]-p1[0])*(p2[1]-p1[1])))
        if area < 1e-2: continue
        c = pratt_fit(np.array([p1, p2, p3], dtype=np.float64))
        if c is None: continue
        cx, cy, r = c
        d = np.sqrt((points_xy[:, 0]-cx)**2 + (points_xy[:, 1]-cy)**2)
        errs = np.abs(d - r)
        inliers = points_xy[errs < thresh]
        m = len(inliers)
        if m > best_in:
            if m >= 10:
                c2 = pratt_fit(inliers)
                if c2 is None: continue
                cx, cy, r = c2
            best = (cx, cy, r); best_inliers = inliers; best_in = m
    if best is None or best_in < min_inliers: return None, None
    return best, best_inliers

def arc_from_inliers(center, inliers_xy):
    cx, cy = center
    ang = np.degrees(np.arctan2(inliers_xy[:, 1]-cy, inliers_xy[:, 0]-cx)) % 360.0
    ang = np.sort(ang)
    diffs = np.diff(ang, append=ang[0]+360.0)
    max_gap_idx = int(np.argmax(diffs))
    coverage = 360.0 - float(diffs[max_gap_idx])
    start = float(ang[(max_gap_idx+1) % len(ang)])
    end = start + coverage
    return start, end, coverage

def classify_arc(coverage_deg, q_min=70, q_max=110, s_min=140, s_max=220, full_min=300):
    if coverage_deg >= full_min: return "circle"
    if s_min <= coverage_deg <= s_max: return "semicircle"
    if q_min <= coverage_deg <= q_max: return "quarter"
    return f"arc({coverage_deg:.1f}°)"

def draw_arc_overlay(bgr, circle, arc, tag_text, color=(0,255,0), line_th=1, font_scale=0.55, text_th=1):
    cx = int(round(circle[0])); cy = int(round(circle[1])); r = int(round(circle[2]))
    start_deg = float(arc[0]); end_deg = float(arc[1])
    over = bgr.copy()
    bgr_color = (int(color[0]), int(color[1]), int(color[2]))
    cv2.ellipse(over, (cx, cy), (r, r), 0.0, start_deg, end_deg, bgr_color, int(line_th), cv2.LINE_AA)
    cv2.circle(over, (cx, cy), 1, bgr_color, -1, cv2.LINE_AA)
    cv2.putText(over, tag_text, (max(5, cx - r), max(18, cy - r - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, float(font_scale), bgr_color, int(text_th), cv2.LINE_AA)
    return over

def save_arc_mask(out_path: Path, shape_hw, circle, arc, thickness=1):
    h, w = shape_hw
    mask = np.zeros((h, w), dtype=np.uint8)
    cx, cy, r = int(round(circle[0])), int(round(circle[1])), int(round(circle[2]))
    start_deg, end_deg, _ = arc
    cv2.ellipse(mask, (cx, cy), (r, r), 0.0, float(start_deg), float(end_deg), 255, int(thickness), cv2.LINE_AA)
    cv2.imwrite(str(out_path), mask)

def write_csv_header(f, px_per_mm):
    w = csv.writer(f)
    hdr = ["roi_id","center_x_px","center_y_px","radius_px","diameter_px","arc_deg","type","inliers"]
    if px_per_mm > 0: hdr += ["px_per_mm","mm_per_px","radius_mm","diameter_mm"]
    w.writerow(hdr); return w

def row_for(circle, arc, roi_id, inliers, kind, px_per_mm):
    cx, cy, r = circle; d = 2.0*r; cov = arc[2]
    row = [roi_id, f"{cx:.6f}", f"{cy:.6f}", f"{r:.6f}", f"{d:.6f}", f"{cov:.3f}", kind, inliers]
    if px_per_mm > 0:
        mm_per_px = 1.0/px_per_mm
        row += [f"{px_per_mm:.6f}", f"{mm_per_px:.6f}", f"{r*mm_per_px:.6f}", f"{d*mm_per_px:.6f}"]
    return row

def write_radius_diameter_reports(out_dir: Path, image_path: Path, results, px_per_mm: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    per_image = out_dir / f"{stem}_radius_diameter.csv"
    all_log = out_dir / "radius_diameter_all.csv"
    headers = ["image","roi_id","radius_px","diameter_px"]
    mm_per_px = (1.0/px_per_mm) if px_per_mm > 0 else None
    if mm_per_px is not None: headers += ["mm_per_px","radius_mm","diameter_mm"]
    rows = []
    for (roi_id, circle, _) in results:
        r = float(circle[2]); d = 2.0*r
        row = [stem, int(roi_id), f"{r:.6f}", f"{d:.6f}"]
        if mm_per_px is not None: row += [f"{mm_per_px:.6f}", f"{r*mm_per_px:.6f}", f"{d*mm_per_px:.6f}"]
        rows.append(row)
    with open(per_image, "w", newline="", encoding="utf-8") as f: w = csv.writer(f); w.writerow(headers); w.writerows(rows)
    new_file = not all_log.exists()
    with open(all_log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f); 
        if new_file: w.writerow(headers)
        w.writerows(rows)

# ---------------- ROI Canvas (unchanged drawing, themed border) ----------------
class RoiCanvas(QLabel):
    roisChanged = QtCore.pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundRole(QtGui.QPalette.Base)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setScaledContents(False)
        self._img_bgr: Optional[np.ndarray] = None
        self._pix: Optional[QtGui.QPixmap] = None
        self._zoom: float = 1.0
        self._rois: List[Dict[str, Any]] = []
        self._history: List[List[Dict[str, Any]]] = []
        self._redo: List[List[Dict[str, Any]]] = []
        self.drawEnabled: bool = True
        self.mode: str = 'rect'
        self._p0: Optional[QPoint] = None
        self._preview_rect: Optional[QRect] = None
        self._poly_pts: List[QPoint] = []
        self.setStyleSheet("QLabel { background: #111827; border: 1px solid #2a3242; border-radius: 8px; }")
    # public zoom helpers
    def zoom_in(self): self._bump_zoom(+0.1)
    def zoom_out(self): self._bump_zoom(-0.1)
    def fit_window(self): self._zoom = 1.0; self.update()
    def _bump_zoom(self, delta): self._zoom = max(0.2, min(5.0, self._zoom * (1.0 + delta))); self.update()
    # image helpers
    def hasImage(self) -> bool: return self._img_bgr is not None
    def loadBGR(self, bgr: np.ndarray):
        self._img_bgr = bgr.copy()
        h, w = bgr.shape[:2]
        qimg = QtGui.QImage(bgr.data, w, h, 3*w, QtGui.QImage.Format.Format_BGR888)
        self._pix = QtGui.QPixmap.fromImage(qimg)
        self._rois.clear(); self._preview_rect=None; self._poly_pts.clear()
        self._history.clear(); self._redo.clear(); self._zoom = 1.0
        self._push_state(); self.updateGeometry(); self.update(); self.roisChanged.emit()
    def imageSize(self) -> QtCore.QSize: return self._pix.size() if self._pix else QtCore.QSize(0, 0)
    def sizeHint(self): return self.imageSize()
    # ROI API
    def clearRois(self): self._rois.clear(); self._preview_rect=None; self._poly_pts.clear(); self._push_state(); self.update(); self.roisChanged.emit()
    def undoRoi(self):
        if len(self._history) > 1:
            self._redo.append(self._history.pop()); self._rois = self._clone_state(self._history[-1]); self.update(); self.roisChanged.emit()
    def redoRoi(self):
        if self._redo:
            state = self._redo.pop(); self._history.append(self._clone_state(state)); self._rois = self._clone_state(state); self.update(); self.roisChanged.emit()
    def setMode(self, mode: str): self.mode = mode; self._preview_rect=None; self._poly_pts.clear(); self.update()
    def setDrawEnabled(self, enabled: bool): self.drawEnabled = enabled
    def roisImageBoxes(self) -> List[Tuple[int,int,int,int]]:
        out=[]; 
        for r in self._rois:
            if r['type']=='rect':
                q: QRect = r['rect']; out.append((q.left(), q.top(), q.right(), q.bottom()))
            else:
                pts: List[QPoint] = r['pts']; 
                if not pts: continue
                xs=[p.x() for p in pts]; ys=[p.y() for p in pts]
                x0,x1=min(xs),max(xs); y0,y1=min(ys),max(ys); out.append((x0,y0,x1,y1))
        return out
    def setRoisImageBoxes(self, boxes): 
        self._rois=[]; 
        for (x0,y0,x1,y1) in boxes or []:
            self._rois.append({'type':'rect','rect': QRect(QPoint(int(x0),int(y0)), QPoint(int(x1),int(y1))).normalized()})
        self._push_state(); self.update(); self.roisChanged.emit()
    # history helpers
    def _clone_state(self, state): 
        snap=[]
        for r in state:
            if r['type']=='rect': snap.append({'type':'rect','rect': QRect(r['rect'])})
            else: snap.append({'type':'poly','pts':[QPoint(p) for p in r['pts']]})
        return snap
    def _push_state(self): self._history.append(self._clone_state(self._rois)); self._redo.clear()
    # geometry
    def _fitGeom(self):
        if not self._pix: return 0,0,0,0,1.0
        pix_w=self._pix.width(); pix_h=self._pix.height()
        lab_w=self.width(); lab_h=self.height()
        base=min(lab_w/pix_w if pix_w else 1.0, lab_h/pix_h if pix_h else 1.0)
        s=(base if base>0 else 1.0)*self._zoom
        draw_w=int(pix_w*s); draw_h=int(pix_h*s)
        off_x=(lab_w-draw_w)//2; off_y=(lab_h-draw_h)//2
        return off_x,off_y,draw_w,draw_h,s
    def _widgetToImagePoint(self, p: QPoint)->QPoint:
        if self._pix is None: return QPoint(0,0)
        off_x,off_y,_,_,s=self._fitGeom()
        pix_w=self._pix.width(); pix_h=self._pix.height()
        x=(p.x()-off_x)/s; y=(p.y()-off_y)/s
        x=max(0,min(pix_w-1,int(round(x)))); y=max(0,min(pix_h-1,int(round(y))))
        return QPoint(x,y)
    # wheel/mouse/paint
    def wheelEvent(self, ev: QtGui.QWheelEvent):
        if not self._pix: return
        delta=ev.angleDelta().y(); factor=1.0+(0.1 if delta>0 else -0.1)
        self._zoom=max(0.2,min(5.0,self._zoom*factor)); self.update()
    def mousePressEvent(self, ev: QtGui.QMouseEvent):
        if not self.drawEnabled or not self._pix: return
        if ev.button()==Qt.LeftButton:
            img_p=self._widgetToImagePoint(ev.pos())
            if self.mode=='rect': self._p0=img_p; self._preview_rect=QRect(img_p,img_p)
            else: self._poly_pts.append(img_p)
            self.update()
        elif ev.button()==Qt.RightButton and self.mode=='poly':
            if len(self._poly_pts)>=3:
                self._rois.append({'type':'poly','pts':list(self._poly_pts)})
                self._poly_pts.clear(); self._push_state(); self.roisChanged.emit(); self.update()
    def mouseMoveEvent(self, ev: QtGui.QMouseEvent):
        if not self.drawEnabled or not self._pix: return
        if self.mode=='rect' and self._p0 is not None:
            img_p=self._widgetToImagePoint(ev.pos())
            self._preview_rect=QRect(self._p0,img_p).normalized(); self.update()
    def mouseReleaseEvent(self, ev: QtGui.QMouseEvent):
        if not self.drawEnabled or not self._pix: return
        if ev.button()==Qt.LeftButton and self.mode=='rect' and self._p0 is not None:
            img_p=self._widgetToImagePoint(ev.pos())
            r=QRect(self._p0,img_p).normalized(); self._p0=None
            if r.width()>=6 and r.height()>=6:
                max_r=QRect(QPoint(0,0), self._pix.size()); r=r.intersected(max_r)
                if r.width()>=6 and r.height()>=6:
                    self._rois.append({'type':'rect','rect':r}); self._push_state(); self.roisChanged.emit()
            self._preview_rect=None; self.update()
    def paintEvent(self, ev: QtGui.QPaintEvent):
        super().paintEvent(ev)
        if not self._pix: return
        p=QtGui.QPainter(self); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        off_x,off_y,draw_w,draw_h,s=self._fitGeom(); target=QtCore.QRect(off_x,off_y,draw_w,draw_h)
        p.drawPixmap(target,self._pix)
        penG=QtGui.QPen(QtGui.QColor(56,189,248),1); penY=QtGui.QPen(QtGui.QColor(99,102,241),1)
        font=p.font(); font.setPointSizeF(10); p.setFont(font)
        p.setPen(penG); idx=1
        for r in self._rois:
            if r['type']=='rect':
                rr: QRect=r['rect']
                dr=QtCore.QRect(off_x+int(rr.left()*s), off_y+int(rr.top()*s), int(rr.width()*s), int(rr.height()*s))
                p.drawRect(dr); p.drawText(dr.left()+2, max(off_y+12, dr.top()-4), f"ROI#{idx}")
            else:
                pts: List[QPoint]=r['pts']
                if len(pts)>=2:
                    qpts=[QtCore.QPoint(off_x+int(pt.x()*s), off_y+int(pt.y()*s)) for pt in pts]
                    p.drawPolygon(QtGui.QPolygon(qpts))
                    bb=QtCore.QRect(min(qp.x() for qp in qpts), min(qp.y() for qp in qpts),
                                     max(qp.x() for qp in qpts)-min(qp.x() for qp in qpts),
                                     max(qp.y() for qp in qpts)-min(qp.y() for qp in qpts))
                    p.drawText(bb.left()+2, max(off_y+12, bb.top()-4), f"ROI#{idx}")
            idx+=1
        p.setPen(penY)
        if self.mode=='rect' and self._preview_rect is not None:
            pr=self._preview_rect
            dr=QtCore.QRect(off_x+int(pr.left()*s), off_y+int(pr.top()*s), int(pr.width()*s), int(pr.height()*s))
            p.drawRect(dr)
        elif self.mode=='poly' and self._poly_pts:
            qpts=[QtCore.QPoint(off_x+int(pt.x()*s), off_y+int(pt.y()*s)) for pt in self._poly_pts]
            p.drawPolyline(QtGui.QPolygon(qpts))
        p.end()

# ---------------- Theming ----------------
def apply_dark_blue_theme(app: QApplication):
    app.setStyle("Fusion")
    qss = """
    * { font-family: 'Segoe UI','Inter','Roboto',sans-serif; font-size: 12px; }
    QMainWindow, QWidget { background-color: #1e2430; color: #e5e7eb; }
    QMenuBar, QMenu { background: #1e2430; color: #e5e7eb; }
    QMenu::item:selected { background: #2b3340; }
    QGroupBox { border: 1px solid #2f3644; border-radius: 8px; margin-top: 12px; padding-top: 10px; background-color: #1b2030; }
    QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #9aa4b2; font-weight: 700; background: transparent; letter-spacing: .5px; }
    QLabel#countLabel { color: #a7f3d0; font-weight: 700; }
    QPushButton { background-color: #3b82f6; color: #ffffff; border: none; border-radius: 8px; padding: 8px 12px; font-weight: 700; }
    QPushButton:hover { background-color: #2563eb; }
    QPushButton:pressed { background-color: #1d4ed8; }
    QPushButton[variant="secondary"] { background: #2b3340; border: 1px solid #3a4250; color: #e5e7eb; font-weight: 600; }
    QPushButton[variant="danger"] { background: #ef4444; }
    QPushButton[variant="ghost"] { background: #1e2430; border: 1px solid #2f3644; color: #e5e7eb; font-weight: 600; }
    QLineEdit, QComboBox {
    background-color: #101522; color: #e5e7eb; border: 1px solid #2f3644; border-radius: 6px; padding: 6px 8px;
    }
    QComboBox QAbstractItemView { background: #101522; color: #e5e7eb; selection-background-color: #334155; }
    QListWidget { background-color: #1b2030; border: 1px solid #2a3242; border-radius: 8px; padding: 6px; }
    QListWidget::item { margin: 6px; padding: 6px; border-radius: 6px; }
    QListWidget::item:selected { background: #2d3748; }
    QSplitter::handle { background: #2a3242; width: 6px; }
    QToolTip { background: #111827; color: #e5e7eb; border: 1px solid #334155; }
    """
    app.setStyleSheet(qss)

# ---------------- Main Window ----------------
class ROIWindow(QMainWindow):
    # enforce good sidebar sizing even on fullscreen
    MIN_SIDEBAR_W   = 260
    IDEAL_SIDEBAR_W = 300
    MAX_SIDEBAR_W   = 420
    SIDEBAR_RATIO   = 0.20  # ~28% of window width (bounded by min/max)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ROI Arc Measure")
        self.resize(1320, 860)

        self.folder: Optional[Path] = None
        self.images: List[Path] = []
        self.current_path: Optional[Path] = None
        self.roi_cache: Dict[Path, List[Tuple[int,int,int,int]]] = {}
        self._sidebar_saved_w = self.IDEAL_SIDEBAR_W

        self.canvas = RoiCanvas()

        # ---- Left sidebar content (same controls as before) ----
        self.btnHelp = QPushButton("  Help / Instructions")
        self.btnHelp.clicked.connect(self._show_help)

        self.btnOpen = QPushButton("  Open Image Folder")
        self.btnOpen.clicked.connect(self._choose_folder)

        self.lblCount = QLabel("Annotated: 0/0"); self.lblCount.setObjectName("countLabel")

        boxFolder = QGroupBox("Folder Operations"); layF = QVBoxLayout(boxFolder); layF.setSpacing(8)
        layF.addWidget(self.btnOpen); layF.addWidget(self.lblCount)

        self.modeCombo = QComboBox(); self.modeCombo.addItems(["Rectangle", "Polygon (bbox)"])
        self.modeCombo.currentIndexChanged.connect(lambda i: self.canvas.setMode('rect' if i==0 else 'poly'))
        self.chkDraw = QCheckBox("Draw ROI enabled"); self.chkDraw.setChecked(True); self.chkDraw.toggled.connect(self.canvas.setDrawEnabled)
        self.labelEdit = QLineEdit(); self.labelEdit.setPlaceholderText("Enter object label")
        self.btnFinishPoly = QPushButton("  Finish Polygon"); self.btnFinishPoly.setProperty("variant","secondary")
        # re-use Undo to map this button (keeps your original behavior for now)
        self.btnFinishPoly.clicked.connect(self.canvas.undoRoi)
        self.btnClear = QPushButton("  Clear Annotations"); self.btnClear.setProperty("variant","secondary")
        self.btnClear.clicked.connect(self.canvas.clearRois)
        self.btnEdit = QPushButton("  Edit Label"); self.btnEdit.setProperty("variant","ghost"); self.btnEdit.setEnabled(False)
        self.btnDel  = QPushButton("  Delete Selected"); self.btnDel.setProperty("variant","ghost"); self.btnDel.setEnabled(False)
        self.btnCopy = QPushButton("  Copy"); self.btnCopy.setProperty("variant","ghost"); self.btnCopy.setEnabled(False)
        self.btnPaste= QPushButton("  Paste"); self.btnPaste.setProperty("variant","ghost"); self.btnPaste.setEnabled(False)

        boxAnnot = QGroupBox("Annotation Tools")
        formAnnot = QFormLayout(); formAnnot.setSpacing(8)
        formAnnot.addRow("Tool:", self.modeCombo); formAnnot.addRow("Label:", self.labelEdit)
        layAnnot = QVBoxLayout(); layAnnot.setSpacing(8)
        layAnnot.addWidget(self.chkDraw)
        layAnnot.addLayout(formAnnot)
        row1 = QHBoxLayout(); row1.addWidget(self.btnFinishPoly); row1.addWidget(self.btnClear); layAnnot.addLayout(row1)
        row2 = QHBoxLayout(); row2.addWidget(self.btnEdit); row2.addWidget(self.btnDel); layAnnot.addLayout(row2)
        row3 = QHBoxLayout(); row3.addWidget(self.btnCopy); row3.addWidget(self.btnPaste); layAnnot.addLayout(row3)
        boxAnnot.setLayout(layAnnot)

        self.btnZoomIn = QPushButton("  Zoom In"); self.btnZoomIn.clicked.connect(self.canvas.zoom_in)
        self.btnZoomOut = QPushButton("  Zoom Out"); self.btnZoomOut.clicked.connect(self.canvas.zoom_out)
        self.btnFit = QPushButton("  Window"); self.btnFit.clicked.connect(self.canvas.fit_window)
        boxZoom = QGroupBox("Zoom Tools"); layZ = QHBoxLayout(boxZoom); layZ.addWidget(self.btnZoomIn); layZ.addWidget(self.btnZoomOut); layZ.addWidget(self.btnFit)

        self.btnPrev = QPushButton("  Previous"); self.btnPrev.clicked.connect(lambda: self._step_image(-1))
        self.btnNext = QPushButton("  Next"); self.btnNext.clicked.connect(lambda: self._step_image(1))
        boxNav = QGroupBox("Navigation"); layN = QHBoxLayout(boxNav); layN.addWidget(self.btnPrev); layN.addWidget(self.btnNext)

        self.mmPerPx = QDoubleSpinBox(); self.mmPerPx.setRange(0.0, 1e6); self.mmPerPx.setDecimals(6); self.mmPerPx.setValue(0.0)
        self.edgeLow = QSpinBox(); self.edgeLow.setRange(0, 255); self.edgeLow.setValue(50)
        self.edgeHigh = QSpinBox(); self.edgeHigh.setRange(0, 255); self.edgeHigh.setValue(150)
        self.ransacIters = QSpinBox(); self.ransacIters.setRange(10, 100000); self.ransacIters.setValue(800)
        self.ransacThresh = QDoubleSpinBox(); self.ransacThresh.setRange(0.1, 100.0); self.ransacThresh.setDecimals(2); self.ransacThresh.setValue(2.0)
        self.ransacMinIn = QSpinBox(); self.ransacMinIn.setRange(1, 100000); self.ransacMinIn.setValue(60)
        form = QFormLayout(); form.setSpacing(8)
        form.addRow("mm_per_px:", self.mmPerPx); form.addRow("edge_low:", self.edgeLow)
        form.addRow("edge_high:", self.edgeHigh); form.addRow("ransac_iters:", self.ransacIters)
        form.addRow("ransac_thresh:", self.ransacThresh); form.addRow("ransac_min_inliers:", self.ransacMinIn)
        boxParams = QGroupBox("Parameters"); boxParams.setLayout(form)

        self.btnSave = QPushButton("  Save Current"); self.btnSave.setProperty("variant", "secondary")
        self.btnSaveAll = QPushButton("  Final Save · Verify")
        self.chkOverwrite = QCheckBox("Overwrite Existing Files"); self.chkOverwrite.setChecked(True)
        self.btnSave.clicked.connect(self._save_current); self.btnSaveAll.clicked.connect(self._save_all)
        boxSave = QGroupBox("Save Operations"); layS = QVBoxLayout(boxSave); layS.addWidget(self.btnSave); layS.addWidget(self.btnSaveAll); layS.addWidget(self.chkOverwrite)

        # LEFT column layout
        leftCol = QVBoxLayout(); leftCol.setContentsMargins(10,10,10,10); leftCol.setSpacing(10)
        leftCol.addWidget(self.btnHelp); leftCol.addWidget(boxFolder); leftCol.addWidget(boxAnnot)
        leftCol.addWidget(boxZoom); leftCol.addWidget(boxNav); leftCol.addWidget(boxParams)
        leftCol.addWidget(boxSave); leftCol.addStretch(1)

        leftContent = QWidget(); leftContent.setLayout(leftCol)
        leftContent.setMinimumWidth(self.MIN_SIDEBAR_W)
        leftContent.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # >>> KEY FIX: wrap in a scroll area so nothing is hidden when tall
        leftScroll = QScrollArea()
        leftScroll.setWidget(leftContent)
        leftScroll.setWidgetResizable(True)
        leftScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        leftScroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        leftScroll.setMinimumWidth(self.MIN_SIDEBAR_W)

        # RIGHT: canvas + thumbs
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.LeftToRight)
        self.thumbs.setResizeMode(QListWidget.Adjust)
        self.thumbs.setIconSize(QtCore.QSize(140, 100))
        self.thumbs.setFixedHeight(176)
        self.thumbs.setContentsMargins(6,0,6,6)
        self.thumbs.itemSelectionChanged.connect(self._on_thumb_select)

        rightColW = QWidget(); rightCol = QVBoxLayout(rightColW)
        rightCol.setContentsMargins(8,8,8,8)
        rightCol.addWidget(self.canvas, 1); rightCol.addWidget(self.thumbs, 0)

        # Splitter with robust sizing rules
        self.splitter = QSplitter()
        self.splitter.addWidget(leftScroll)
        self.splitter.addWidget(rightColW)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setHandleWidth(6)
        self.splitter.setCollapsible(0, False)  # don't allow collapsing the sidebar
        self.splitter.splitterMoved.connect(self._on_splitter_moved)

        # Central
        central = QWidget(); lay = QHBoxLayout(central)
        lay.setContentsMargins(0,0,0,0); lay.addWidget(self.splitter)
        self.setCentralWidget(central)

        # Menu & shortcuts
        QtWidgets.QShortcut(QtGui.QKeySequence(Qt.Key_Left), self, activated=lambda: self._step_image(-1))
        QtWidgets.QShortcut(QtGui.QKeySequence(Qt.Key_Right), self, activated=lambda: self._step_image(1))
        QtWidgets.QShortcut(QtGui.QKeySequence("A"), self, activated=lambda: self._step_image(-1))
        QtWidgets.QShortcut(QtGui.QKeySequence("D"), self, activated=lambda: self._step_image(1))
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Z"), self, activated=self.canvas.undoRoi)
        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+Y"), self, activated=self.canvas.redoRoi)

        self.canvas.roisChanged.connect(self._cache_current_rois)

        # Apply initial sizes *after* the window is realized
        QtCore.QTimer.singleShot(0, self._apply_initial_split_sizes)

    # ---------- Sidebar sizing helpers ----------
    def _apply_initial_split_sizes(self):
        target = max(self.MIN_SIDEBAR_W,
                     min(int(self.width() * self.SIDEBAR_RATIO), self.MAX_SIDEBAR_W))
        # if user previously dragged, prefer that (bounded)
        target = max(self.MIN_SIDEBAR_W, min(self._sidebar_saved_w, self.MAX_SIDEBAR_W, int(self.width()*0.45)))
        right = max(400, self.width() - target)
        self.splitter.setSizes([target, right])

    def _on_splitter_moved(self, *_):
        # remember user’s chosen width (bounded)
        w = self.splitter.sizes()[0]
        self._sidebar_saved_w = max(self.MIN_SIDEBAR_W, min(w, self.MAX_SIDEBAR_W))

    def resizeEvent(self, ev: QtGui.QResizeEvent):
        super().resizeEvent(ev)
        # keep a healthy left width when maximizing/minimizing
        sizes = self.splitter.sizes()
        if not sizes: return
        current_left = sizes[0]
        # If left is too small due to maximize/layout calc, expand it back
        min_target = max(self.MIN_SIDEBAR_W, min(int(self.width()*self.SIDEBAR_RATIO), self.MAX_SIDEBAR_W))
        desired = max(min_target, min(self._sidebar_saved_w, int(self.width()*0.45)))
        if current_left < self.MIN_SIDEBAR_W - 8:  # visibly compressed
            self.splitter.setSizes([desired, max(400, self.width()-desired)])

    # ---------- UI behavior ----------
    def _show_help(self):
        QMessageBox.information(self, "Help / Instructions",
            "1) Open a folder.\n2) Select an image (bottom gallery).\n"
            "3) Draw ROIs (Rectangle or Polygon-bbox; Right-click to finish polygon).\n"
            "4) Use Save Current or Final Save · Verify.\n"
            "Tips: Mouse wheel to zoom; Zoom buttons on the left; A/Left and D/Right to navigate."
        )

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select image folder")
        if not folder: return
        self.folder = Path(folder); self._scan_images()

    def _scan_images(self):
        # reset UI state
        self.images.clear()
        self.thumbs.clear()
        self.current_path = None

        if not self.folder:
            self._update_count()
            return

        # Only scan the immediate (top-level) contents of the chosen folder
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        for p in sorted(self.folder.iterdir()):  # <-- no recursion here
            if p.is_file() and p.suffix.lower() in exts:
                self.images.append(p)

        # If nothing found directly in the main folder, show a popup and stop
        if not self.images:
            self._update_count()  # will show 0/0
            QMessageBox.information(self, "No images found", "No images found.")
            return

        # Build thumbnails only for the top-level images we collected
        for path in self.images:
            item = QListWidgetItem()
            item.setText(path.name)
            try:
                bgr = imread_any(path)
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                qimg = QtGui.QImage(rgb.data, w, h, 3 * w, QtGui.QImage.Format.Format_RGB888)
                pm = QtGui.QPixmap.fromImage(qimg).scaled(
                    self.thumbs.iconSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                item.setIcon(QtGui.QIcon(pm))
            except Exception:
                pass
            item.setData(Qt.UserRole, str(path))
            self.thumbs.addItem(item)

        if self.images:
            self.thumbs.setCurrentRow(0)

        self._update_count()


    def _on_thumb_select(self):
        row = self.thumbs.currentRow()
        if 0 <= row < len(self.images):
            path = self.images[row]
            try: bgr = imread_any(path)
            except Exception as e: QMessageBox.critical(self, "Read error", str(e)); return
            self.current_path = path; self.canvas.loadBGR(bgr)
            boxes = self.roi_cache.get(path, []); self.canvas.setRoisImageBoxes(boxes)
            self._update_thumb_highlight(row); self._update_count()

    def _step_image(self, delta: int):
        if not self.images: return
        row = self.thumbs.currentRow()
        self.thumbs.setCurrentRow((row + delta) % len(self.images))

    def _cache_current_rois(self):
        if not self.current_path: return
        boxes = self.canvas.roisImageBoxes()
        self.roi_cache[self.current_path] = boxes
        idx = self.images.index(self.current_path) if self.current_path in self.images else -1
        if idx >= 0: self._update_thumb_highlight(idx)
        self._update_count()

    def _update_thumb_highlight(self, idx: int):
        item = self.thumbs.item(idx); path = self.images[idx]
        has = bool(self.roi_cache.get(path))
        item.setBackground(QtGui.QBrush(QtGui.QColor(35,78,57) if has else QtGui.QColor(27,32,48)))

    def _update_count(self):
        total = len(self.images); annotated = sum(1 for p in self.images if self.roi_cache.get(p))
        self.lblCount.setText(f"Annotated: {annotated}/{total}")

    # ---------- Save / Process (unchanged logic + overwrite toggle) ----------
    def _collect_params(self):
        return dict(
            mm_per_px=float(self.mmPerPx.value()),
            edge_low=int(self.edgeLow.value()),
            edge_high=int(self.edgeHigh.value()),
            iters=int(self.ransacIters.value()),
            thresh=float(self.ransacThresh.value()),
            min_in=int(self.ransacMinIn.value()),
        )

    def _save_current(self):
        if self.current_path is None or not self.canvas.hasImage():
            QMessageBox.information(self, "No Image", "Please select an image."); return
        boxes = self.canvas.roisImageBoxes()
        if not boxes:
            QMessageBox.information(self, "No ROIs", "Draw one or more ROIs first."); return
        t0 = time.time()
        self._process_image(self.current_path, boxes, **self._collect_params())
        QMessageBox.information(self, "Processing Complete", f"Image processed!\nCycle time: {time.time()-t0:.2f} s")

    def _save_all(self):
        if not self.roi_cache:
            QMessageBox.information(self, "Nothing to save", "No ROIs on any image."); return
        params = self._collect_params(); count=0; T0=time.time(); times=[]
        for path, boxes in self.roi_cache.items():
            if boxes:
                t=time.time(); self._process_image(path, boxes, **params); times.append((path.name, time.time()-t)); count+=1
        msg=[f"Processed {count} image(s) with ROIs.", f"Total processing time: {time.time()-T0:.2f} s", "", "Cycle times:"]
        for n,t in times: msg.append(f"  • {n}: {t:.2f} s")
        if times: msg.append(f"\nAverage: {sum(t for _,t in times)/len(times):.2f} s/image")
        QMessageBox.information(self, "Save All Complete", "\n".join(msg))

    def _process_image(self, img_path: Path, boxes: List[Tuple[int,int,int,int]], *,
                       mm_per_px: float, edge_low:int, edge_high:int, iters:int, thresh:float, min_in:int):
        img_dir = img_path.parent; out_dir = img_dir / f"{img_path.stem}_circle_outputs"; out_dir.mkdir(parents=True, exist_ok=True)
        bgr = imread_any(img_path); gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY); proc = preprocess(gray, clahe=True, blur_ksize=5)
        overlay_all = bgr.copy(); results = []; csv_path = out_dir / "circle_report_multi.csv"
        overwrite = self.chkOverwrite.isChecked()
        mode = "w" if overwrite or not csv_path.exists() else "a"
        with open(csv_path, mode, newline="", encoding="utf-8") as fcsv:
            w = write_csv_header(fcsv, mm_per_px) if mode=="w" else csv.writer(fcsv)
            for i,(x0,y0,x1,y1) in enumerate(boxes, start=1):
                t0=time.time(); roi = proc[y0:y1, x0:x1]
                edges = cv2.Canny(roi, edge_low, edge_high); ys, xs = np.where(edges > 0)
                if len(xs) < 20: print(f"{img_path.name} – ROI #{i}: too few edge points, skipped. ({time.time()-t0:.2f}s)"); continue
                pts = (np.stack([xs, ys], axis=1).astype(np.float64) + np.array([x0, y0], dtype=np.float64))
                circle, inliers_xy = ransac_circle(pts, iters=iters, thresh=thresh, min_inliers=min_in)
                if circle is None: print(f"{img_path.name} – ROI #{i}: could not fit a circle. ({time.time()-t0:.2f}s)"); continue
                arc = arc_from_inliers((circle[0],circle[1]), inliers_xy); kind = classify_arc(arc[2])
                tag = f"ROI#{i}  {kind}  r={circle[2]:.1f}px  d={2*circle[2]:.1f}px"
                over_one = draw_arc_overlay(bgr, circle, arc, tag, color=(0,255,0), line_th=1, font_scale=0.55, text_th=1)
                p_one = out_dir / f"overlay_roi_{i}.png"; p_mask = out_dir / f"roi_arc_mask_{i}.png"
                if overwrite or not p_one.exists(): cv2.imwrite(str(p_one), over_one)
                if overwrite or not p_mask.exists(): save_arc_mask(p_mask, bgr.shape[:2], circle, arc, thickness=1)
                overlay_all = draw_arc_overlay(overlay_all, circle, arc, tag, color=(0,255,0), line_th=1, font_scale=0.55, text_th=1)
                w.writerow(row_for(circle, arc, i, len(inliers_xy), kind, mm_per_px))
                results.append((i, circle, arc[2]))
                print(f"{img_path.name} – ROI #{i}: {kind}, r={circle[2]:.2f}px, d={2*circle[2]:.2f}px, arc={arc[2]:.1f}°, inliers={len(inliers_xy)}, time={time.time()-t0:.2f}s")
        p_all = out_dir / "overlay_all_rois.png"
        if overwrite or not p_all.exists(): cv2.imwrite(str(p_all), overlay_all)
        write_radius_diameter_reports(out_dir, img_path, results, mm_per_px)
        txt_path = out_dir / "circle_report_summary.txt"
        if results:
            radii=np.array([c[2] for (_,c,_) in results], dtype=float); diams=2.0*radii
            def stats(arr): m=float(np.mean(arr)); s=float(np.std(arr, ddof=1)) if len(arr)>1 else 0.0; return m,s, (s/m*100.0 if m else 0.0)
            r_mean,r_std,r_cv = stats(radii); d_mean,d_std,d_cv = stats(diams)
            lines=[f"Total ROIs measured: {len(results)}","",f"Radius (px):   mean={r_mean:.6f}  std={r_std:.6f}  CV%={r_cv:.3f}",
                   f"Diameter (px): mean={d_mean:.6f}  std={d_std:.6f}  CV%={d_cv:.3f}"]
            if mm_per_px>0:
                inv=1.0/mm_per_px
                lines+=["",f"(Scale {mm_per_px:.6f} px/mm = {inv:.6f} mm/px)",
                        f"Radius (mm):   mean={r_mean*inv:.6f}  std={r_std*inv:.6f}  CV%={(r_std/r_mean*100.0 if r_mean else 0):.3f}",
                        f"Diameter (mm): mean={d_mean*inv:.6f}  std={d_std*inv:.6f}  CV%={(d_std/d_mean*100.0 if d_mean else 0):.3f}"]
            txt_path.write_text("\n".join(lines), encoding="utf-8")
        else:
            txt_path.write_text("No valid ROIs measured.", encoding="utf-8")

# ---------------- Entrypoint ----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_dark_blue_theme(app)
    mw = ROIWindow(); mw.show()
    sys.exit(app.exec_())
 