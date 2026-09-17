# toasts.py
from PyQt5 import QtCore, QtGui, QtWidgets

_KIND_COLORS = {
    "info":    ("#0d6efd", "#1f2937"),
    "success": ("#198754", "#1f2937"),
    "warning": ("#b78103", "#1f2937"),
    "error":   ("#dc3545", "#1f2937"),
}


class Toast(QtWidgets.QFrame):
    """White rounded toast with no dark halo; antialiased custom paint."""
    closed = QtCore.pyqtSignal()

    def __init__(self, text, kind="info", duration_ms=2500, parent=None):
        # Frameless floating tool window
        super().__init__(parent, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, False)
        self.setObjectName("ToastFrame")

        self._radius = 12
        self._accent, self._text_color = _KIND_COLORS.get(kind, _KIND_COLORS["info"])

        # --- content layout ---
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)

        dot = QtWidgets.QLabel("●")
        dot.setStyleSheet(f"color:{self._accent}; font-size:14px; background: transparent;")
        lay.addWidget(dot, 0, QtCore.Qt.AlignTop)

        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("ToastText")
        lbl.setWordWrap(True)
        f = lbl.font()
        f.setFamily("Segoe UI")
        f.setPointSize(10)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color:{self._text_color}; background: transparent;")
        lay.addWidget(lbl, 1)

        btn = QtWidgets.QPushButton("✕")
        btn.setObjectName("CloseBtn")
        btn.setFixedSize(22, 22)
        bf = btn.font()
        bf.setPointSize(11)
        btn.setFont(bf)
        btn.setStyleSheet(f"""
            QPushButton#CloseBtn {{
                background: transparent; color: {self._text_color};
                border: none; font-weight: 700;
            }}
            QPushButton#CloseBtn:hover {{ color: #000; }}
        """)
        btn.clicked.connect(self._close_now)
        lay.addWidget(btn, 0, QtCore.Qt.AlignTop)
        self.adjustSize()
        self.setMinimumSize(self.sizeHint())

        self.setAutoFillBackground(False)
        self.setStyleSheet("""
            #ToastFrame { background: transparent; }
            #ToastFrame QLabel, #ToastFrame QPushButton { background: transparent; }
        """)

        # opacity effect
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(200)

        self._life_timer = QtCore.QTimer(self, interval=max(800, duration_ms), singleShot=True)
        self._life_timer.timeout.connect(self.hide_smooth)

    # ------------- public API -----------------
    def show_smooth(self):
        self._fade.stop()
        self._opacity.setOpacity(0.0)
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._life_timer.start()

    @QtCore.pyqtSlot()
    def hide_smooth(self):
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._on_faded_out)
        self._fade.start()

    # ------------- internals ------------------
    def _on_faded_out(self):
        self._fade.finished.disconnect(self._on_faded_out)
        self.hide()
        self.closed.emit()

    def _close_now(self):
        self._life_timer.stop()
        self.hide_smooth()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        r = self._radius
        rect = self.rect().adjusted(0, 0, -1, -1)
        rectf = QtCore.QRectF(rect)

        # White rounded card
        path = QtGui.QPainterPath()
        path.addRoundedRect(rectf, float(r), float(r))
        p.fillPath(path, QtGui.QColor("#ffffff"))

        # Subtle shadow/border
        pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 30))
        p.setPen(pen)
        p.drawPath(path)

        # Left accent strip
        strip_w = 6
        strip_rectf = QtCore.QRectF(0.0, 0.0, float(strip_w), float(rectf.height()))
        strip_full = QtGui.QPainterPath()
        strip_full.addRoundedRect(rectf, float(r), float(r))
        strip_slice = QtGui.QPainterPath()
        strip_slice.addRect(strip_rectf)
        strip_path = strip_full.intersected(strip_slice)
        p.fillPath(strip_path, QtGui.QColor(self._accent))


class ToastManager(QtCore.QObject):
    """
    Bottom-right stacked toasts on a host widget (e.g., QMainWindow).

    - Uses sizeHint() so height is always valid for the content.
    - Stacks toasts upwards without overlap.
    - If there is not enough vertical space, it automatically closes
      the oldest toasts so nothing is pushed off-screen.
    """
    _instance = None

    def __init__(self, host: QtWidgets.QWidget):
        super().__init__(host)
        self.host = host
        self.toasts = []
        host.installEventFilter(self)

    @classmethod
    def install(cls, host):
        mgr = cls(host)
        cls._instance = mgr
        return mgr

    @classmethod
    def instance(cls):
        return cls._instance

    # ---------- sizing helpers ----------
    def _preferred_size(self, toast: Toast) -> QtCore.QSize:
        """
        Compute toast size:
        - Width: fraction of host width, clamped to [260, 360]
        - Height: from sizeHint() plus a little headroom so Windows
            doesn't "correct" it and complain.
        """
        toast.adjustSize()
        natural = toast.sizeHint()
        host_w = max(1, self.host.width())

        w = min(360, max(260, int(host_w * 0.26)))
        h = natural.height() + 20   # extra vertical margin to avoid setGeometry warning
        return QtCore.QSize(w, h)


    # ---------- public API ----------
    def show(self, text, kind="info", duration_ms=2500):
        t = Toast(text, kind, duration_ms, parent=self.host)
        t.closed.connect(lambda: self._remove(t))

        sz = self._preferred_size(t)
        t.resize(sz)
        t.show_smooth()

        self.toasts.append(t)
        self._reposition()

    # ---------- internal ----------
    def _remove(self, t):
        if t in self.toasts:
            self.toasts.remove(t)
        self._reposition()

    def _reposition(self):
        if not self.toasts or not self.host.isVisible():
            return

        margin = 16
        spacing = 8

        # Host rect in global coords
        host_top_left = self.host.mapToGlobal(QtCore.QPoint(0, 0))
        host_w = self.host.width()
        host_h = self.host.height()

        # Bottom line where to start stacking
        bottom_y = host_top_left.y() + host_h - margin
        left_x   = host_top_left.x() + host_w - margin

        # Stack bottom-up: newest at bottom, oldest above
        y = bottom_y
        # keep only toasts that fit vertically; oldest will be removed if needed
        visible_toasts = []

        for t in reversed(self.toasts):
            sz = self._preferred_size(t)
            h = sz.height()
            w = sz.width()

            # Check if placing this toast would go above the top margin
            next_y = y - h
            if next_y < host_top_left.y() + margin:
                # no more room -> close all remaining older toasts
                t.hide_smooth()
                continue

            x = left_x - w
            t.resize(sz)
            t.move(x, next_y)
            visible_toasts.append(t)

            y = next_y - spacing

        # rebuild list in chronological order, but only visible ones
        self.toasts = list(reversed(visible_toasts))

    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() in (
            QtCore.QEvent.Resize,
            QtCore.QEvent.Move,
            QtCore.QEvent.Show,
        ):
            self._reposition()
        return super().eventFilter(obj, ev)
