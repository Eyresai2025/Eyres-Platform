"""Reusable animated widgets for the EYRES PyQt6 shell."""
from __future__ import annotations

from PyQt6 import QtCore, QtGui, QtWidgets, sip
from PyQt6.QtCore import Qt, pyqtProperty
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QLabel, QPushButton

from .icons import icon, icon_pixmap


class NavButton(QPushButton):
    """Sidebar button with active indicator + restrained icon tilt animation."""

    def __init__(self, text: str, icon_name: str, parent=None):
        super().__init__(text, parent)
        self.full_text = text
        self.icon_name = icon_name
        self._compact = False
        self._hovered = False
        self._indicator_progress = 0.0
        self._icon_motion = 0.0
        self._base_icon_pixmap = QtGui.QPixmap()

        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self.setIconSize(QtCore.QSize(31, 31))

        self.toggled.connect(self._on_toggled)

        self._indicator_anim = QtCore.QPropertyAnimation(
            self, b"indicatorProgress", self
        )
        self._indicator_anim.setDuration(220)
        self._indicator_anim.setEasingCurve(
            QtCore.QEasingCurve.Type.OutCubic
        )

        self._icon_anim = QtCore.QPropertyAnimation(
            self, b"iconMotion", self
        )
        self._icon_anim.setDuration(205)
        self._icon_anim.setEasingCurve(
            QtCore.QEasingCurve.Type.OutBack
        )

        self._refresh_icon()
        self._apply_style()

    # ----- active indicator -------------------------------------------------
    def get_indicator_progress(self) -> float:
        return self._indicator_progress

    def set_indicator_progress(self, value: float) -> None:
        self._indicator_progress = float(value)
        self.update()

    indicatorProgress = pyqtProperty(
        float,
        fget=get_indicator_progress,
        fset=set_indicator_progress,
    )

    # ----- sidebar icon motion ---------------------------------------------
    def get_icon_motion(self) -> float:
        return self._icon_motion

    def set_icon_motion(self, value: float) -> None:
        self._icon_motion = max(0.0, min(1.0, float(value)))
        self._apply_icon_transform()

    iconMotion = pyqtProperty(
        float,
        fget=get_icon_motion,
        fset=set_icon_motion,
    )

    def _animate_icon(self, hovered: bool) -> None:
        self._icon_anim.stop()
        self._icon_anim.setStartValue(self._icon_motion)
        self._icon_anim.setEndValue(1.0 if hovered else 0.0)
        self._icon_anim.start()

    def _apply_icon_transform(self) -> None:
        """Rotate/scale the real EYRES sidebar icon on a transparent canvas."""
        if self._base_icon_pixmap.isNull():
            self.setIcon(QtGui.QIcon())
            return

        p = self._icon_motion
        # Sidebar motion is intentionally quieter than the KPI cards.
        angle = -5.0 * p
        scale = 1.0 + (0.055 * p)
        lift = -1.0 * p

        canvas_size = 34
        canvas = QtGui.QPixmap(canvas_size, canvas_size)
        canvas.fill(Qt.GlobalColor.transparent)

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.translate(canvas_size / 2.0, canvas_size / 2.0 + lift)
        painter.rotate(angle)
        painter.scale(scale, scale)

        target = QtCore.QRectF(-13.5, -13.5, 27.0, 27.0)
        painter.drawPixmap(
            target,
            self._base_icon_pixmap,
            QtCore.QRectF(self._base_icon_pixmap.rect()),
        )
        painter.end()

        self.setIcon(QtGui.QIcon(canvas))

    def _on_toggled(self, checked: bool) -> None:
        self._refresh_icon()
        self._indicator_anim.stop()
        self._indicator_anim.setStartValue(self._indicator_progress)
        self._indicator_anim.setEndValue(1.0 if checked else 0.0)
        self._indicator_anim.start()

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        self.setText("" if compact else self.full_text)
        self.setToolTip(self.full_text if compact else "")
        self._apply_style()

    def _refresh_icon(self) -> None:
        color = "#2868E8" if self.isChecked() or self._hovered else "#718096"
        self._base_icon_pixmap = icon_pixmap(
            self.icon_name,
            color,
            27,
            prefer_legacy=True,
        )
        self._apply_icon_transform()

    def _apply_style(self) -> None:
        if self._compact:
            self.setStyleSheet("""
            QPushButton {
                background: transparent; color:#40516A; border:0; border-radius:10px;
                padding:0; margin:0; text-align:center; font-size:13px; font-weight:650;
            }
            QPushButton:checked { background:#EAF1FF; color:#2868E8; }
            QPushButton:hover { background:#F3F6FC; }
            QPushButton:pressed { background:#E4EDFF; }
            """)
        else:
            self.setStyleSheet("""
            QPushButton {
                background: transparent; color:#40516A; border:0; border-radius:10px;
                padding:0 12px; text-align:left; font-size:13px; font-weight:650;
            }
            QPushButton:checked { background:#EAF1FF; color:#2868E8; }
            QPushButton:hover { background:#F3F6FC; color:#1E3C68; }
            QPushButton:pressed { background:#E4EDFF; }
            """)

    def enterEvent(self, event):
        self._hovered = True
        self._refresh_icon()
        self._animate_icon(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._animate_icon(False)
        # Keep blue while the mouse leaves an active item; otherwise restore grey.
        self._refresh_icon()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._indicator_progress <= 0.001:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2868E8"))

        target_h = 28.0
        h = max(4.0, target_h * self._indicator_progress)
        y = (self.height() - h) / 2.0
        painter.drawRoundedRect(
            QtCore.QRectF(0.0, y, 3.0, h),
            1.5,
            1.5,
        )

        if not self._compact:
            painter.setBrush(
                QColor(40, 104, 232, int(255 * self._indicator_progress))
            )
            painter.drawEllipse(
                QtCore.QRectF(
                    self.width() - 13,
                    self.height() / 2 - 2.5,
                    5,
                    5,
                )
            )
        painter.end()


class IconBadge(QFrame):
    """Painted KPI icon badge with a restrained tilt/lift hover animation."""

    def __init__(self, icon_name: str, color: str = "#2868E8", background: str = "#EEF4FF", parent=None):
        super().__init__(parent)
        self.setFixedSize(48, 48)
        self._icon_name = icon_name
        self._icon_color = color
        self._background = QColor(background)
        self._border = QColor("#DCE7F7")
        self._pixmap = icon_pixmap(icon_name, color, 29, prefer_legacy=False)
        self._hover_progress = 0.0

        self._hover_anim = QtCore.QPropertyAnimation(self, b"iconHoverProgress", self)
        self._hover_anim.setDuration(210)
        self._hover_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)

        # We paint the badge ourselves so the pixmap can rotate/scale smoothly.
        self.setStyleSheet("background:transparent;border:0;")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def get_icon_hover_progress(self) -> float:
        return self._hover_progress

    def set_icon_hover_progress(self, value: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(value)))
        self.update()

    iconHoverProgress = pyqtProperty(
        float,
        fget=get_icon_hover_progress,
        fset=set_icon_hover_progress,
    )

    def animate_hover(self, hovered: bool) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(1.0 if hovered else 0.0)
        self._hover_anim.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Badge surface.
        rect = QtCore.QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        painter.setPen(QtGui.QPen(self._border, 1.0))
        painter.setBrush(self._background)
        painter.drawRoundedRect(rect, 13.0, 13.0)

        # The approved preview used a small tilt + scale on card hover.
        # Keep it restrained for an industrial UI: ~7 degrees and 7% scale.
        p = self._hover_progress
        angle = -7.0 * p
        scale = 1.0 + (0.07 * p)
        lift = -1.5 * p

        painter.save()
        painter.translate(self.width() / 2.0, self.height() / 2.0 + lift)
        painter.rotate(angle)
        painter.scale(scale, scale)

        target = QtCore.QRectF(-14.5, -14.5, 29.0, 29.0)
        painter.drawPixmap(target, self._pixmap, QtCore.QRectF(self._pixmap.rect()))
        painter.restore()
        painter.end()


class AnimatedCard(QFrame):
    """Card with a safe drop-shadow hover and entrance animation."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._shadow = None
        self._blur_anim = None
        self._offset_anim = None
        self._entrance_anim = None
        self._hover_progress = 0.0
        self._hover_anim = QtCore.QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_anim.setDuration(190)
        self._hover_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._install_shadow()

    def _shadow_is_alive(self) -> bool:
        try:
            return self._shadow is not None and not sip.isdeleted(self._shadow)
        except Exception:
            return False

    def _install_shadow(self) -> None:
        if self._shadow_is_alive():
            try:
                if self.graphicsEffect() is self._shadow:
                    return
            except RuntimeError:
                pass

        for anim in (self._blur_anim, self._offset_anim, self._entrance_anim, getattr(self, '_hover_anim', None)):
            try:
                if anim is not None:
                    anim.stop()
            except RuntimeError:
                pass

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(14.0)
        shadow.setOffset(0.0, 4.0)
        shadow.setColor(QColor(36, 63, 102, 28))
        self.setGraphicsEffect(shadow)
        self._shadow = shadow

        self._blur_anim = QtCore.QPropertyAnimation(shadow, b"blurRadius", self)
        self._blur_anim.setDuration(180)
        self._blur_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

        self._offset_anim = QtCore.QPropertyAnimation(shadow, b"offset", self)
        self._offset_anim.setDuration(180)
        self._offset_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

    def _ensure_shadow(self) -> bool:
        try:
            current = self.graphicsEffect()
        except RuntimeError:
            current = None
        if not self._shadow_is_alive() or current is not self._shadow:
            self._install_shadow()
        return self._shadow_is_alive()

    def _animate_shadow(self, blur: float, y: float, duration: int = 180):
        if not self._ensure_shadow():
            return
        try:
            self._blur_anim.stop()
            self._offset_anim.stop()
            self._blur_anim.setDuration(max(80, int(duration)))
            self._offset_anim.setDuration(max(80, int(duration)))
            self._blur_anim.setStartValue(float(self._shadow.blurRadius()))
            self._blur_anim.setEndValue(float(blur))
            self._offset_anim.setStartValue(self._shadow.offset())
            self._offset_anim.setEndValue(QtCore.QPointF(0.0, float(y)))
            self._blur_anim.start()
            self._offset_anim.start()
        except RuntimeError:
            self._install_shadow()

    def animate_entrance(self, duration_ms: int = 260):
        """Depth reveal that keeps the card's drop shadow intact."""
        if not self._ensure_shadow():
            return
        try:
            self._blur_anim.stop()
            self._offset_anim.stop()
            self._shadow.setBlurRadius(4.0)
            self._shadow.setOffset(0.0, 0.0)
            self._shadow.setColor(QColor(36, 63, 102, 8))

            self._blur_anim.setDuration(max(120, int(duration_ms)))
            self._offset_anim.setDuration(max(120, int(duration_ms)))
            self._blur_anim.setStartValue(4.0)
            self._blur_anim.setEndValue(14.0)
            self._offset_anim.setStartValue(QtCore.QPointF(0.0, 0.0))
            self._offset_anim.setEndValue(QtCore.QPointF(0.0, 4.0))

            color_anim = QtCore.QVariantAnimation(self)
            color_anim.setDuration(max(120, int(duration_ms)))
            color_anim.setStartValue(8)
            color_anim.setEndValue(28)
            color_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)

            def _set_alpha(value):
                if self._shadow_is_alive():
                    self._shadow.setColor(QColor(36, 63, 102, int(value)))

            color_anim.valueChanged.connect(_set_alpha)
            self._entrance_anim = color_anim
            self._blur_anim.start()
            self._offset_anim.start()
            color_anim.start()
        except RuntimeError:
            self._install_shadow()

    def get_hover_progress(self) -> float:
        return self._hover_progress

    def set_hover_progress(self, value: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(value)))
        self.update()

    hoverProgress = pyqtProperty(float, fget=get_hover_progress, fset=set_hover_progress)

    def _animate_hover(self, target: float) -> None:
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_progress)
        self._hover_anim.setEndValue(float(target))
        self._hover_anim.start()

    def paintEvent(self, event):
        super().paintEvent(event)

        # KPI cards receive a visible but restrained blue hover elevation.
        # Large dashboard panels keep only the softer drop-shadow behaviour.
        if self.objectName() == "MetricCard" and self._hover_progress > 0.001:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            progress = self._hover_progress
            pen_color = QColor(40, 104, 232, int(105 * progress))
            pen = QtGui.QPen(pen_color)
            pen.setWidthF(1.35)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QtCore.QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
            p.drawRoundedRect(rect, 16.0, 16.0)

            # A very light top sheen makes the motion visible without looking
            # decorative or distracting in an industrial application.
            sheen = QColor(40, 104, 232, int(10 * progress))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(sheen)
            p.drawRoundedRect(
                QtCore.QRectF(2.0, 2.0, max(0.0, self.width() - 4.0), 18.0),
                14.0, 14.0,
            )
            p.end()

    def _animate_icon_badges(self, hovered: bool) -> None:
        # KPI cards contain an IconBadge. Trigger it from the CARD hover event
        # so the animation works even when the pointer is over card text rather
        # than directly over the icon itself.
        if self.objectName() != "MetricCard":
            return
        for badge in self.findChildren(IconBadge):
            badge.animate_hover(hovered)

    def enterEvent(self, event):
        self._animate_hover(1.0)
        self._animate_icon_badges(True)
        self._animate_shadow(34.0 if self.objectName() == "MetricCard" else 26.0,
                             9.0 if self.objectName() == "MetricCard" else 7.0)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_hover(0.0)
        self._animate_icon_badges(False)
        self._animate_shadow(14.0, 4.0)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._animate_icon_badges(False)
        for anim in (self._blur_anim, self._offset_anim, self._entrance_anim, getattr(self, '_hover_anim', None)):
            try:
                if anim is not None:
                    anim.stop()
            except RuntimeError:
                pass
        super().hideEvent(event)


class PulseDot(QtWidgets.QWidget):
    def __init__(self, color: str = "#0AA76A", parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        self._color = QColor(color)
        self._phase = 0.0
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setDuration(1800)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setLoopCount(-1)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._set_phase)
        self._anim.start()

    def _set_phase(self, value):
        self._phase = float(value)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        center = QtCore.QPointF(self.width()/2, self.height()/2)
        radius = 3.3 + 5.3 * self._phase
        halo = QColor(self._color)
        halo.setAlpha(int(70 * (1.0 - self._phase)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(center, radius, radius)
        p.setBrush(self._color)
        p.drawEllipse(center, 3.1, 3.1)
        p.end()


class SpinButton(QPushButton):
    """Compact refresh control with a clear circular-arrow glyph."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Refresh dashboard")
        self.setStyleSheet("""
        QPushButton {
            background:#F8FAFD;
            border:1px solid #D9E3F0;
            border-radius:10px;
        }
        QPushButton:hover {
            background:#EEF4FF;
            border-color:#BBD0F2;
        }
        QPushButton:pressed {
            background:#E4EEFF;
            border-color:#9FBAEB;
        }
        """)
        self._anim = QtCore.QPropertyAnimation(self, b"angle", self)
        self._anim.setDuration(460)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(360.0)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.InOutCubic)

    def get_angle(self) -> float:
        return self._angle

    def set_angle(self, value: float):
        self._angle = float(value)
        self.update()

    angle = pyqtProperty(float, fget=get_angle, fset=set_angle)

    def spin(self):
        self._anim.stop()
        base = self._angle % 360.0
        self._anim.setStartValue(base)
        self._anim.setEndValue(base + 360.0)
        self._anim.start()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.translate(self.width() / 2.0, self.height() / 2.0)
        p.rotate(self._angle)

        font = QtGui.QFont("Segoe UI Symbol")
        font.setPixelSize(20)
        font.setWeight(QtGui.QFont.Weight.Medium)
        p.setFont(font)
        p.setPen(QColor("#53677F"))
        rect = QtCore.QRectF(-14.0, -14.0, 28.0, 28.0)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "↻")
        p.end()


class MotionIconButton(QPushButton):
    """Reusable icon-only button for the remaining Qt6 page migrations.

    Hover behaviour:
    - small icon tilt
    - slight scale/lift
    - restrained background/border response

    This is intentionally for icon/tool buttons. Normal text action buttons
    should use hover lift/glow rather than rotating their text.
    """

    def __init__(
        self,
        icon_name: str,
        color: str = "#53677F",
        hover_color: str = "#2868E8",
        size: int = 36,
        icon_size: int = 19,
        parent=None,
    ):
        super().__init__(parent)
        self._icon_name = icon_name
        self._color = color
        self._hover_color = hover_color
        self._icon_px = int(icon_size)
        self._hovered = False
        self._motion = 0.0
        self._base = QtGui.QPixmap()

        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
        QPushButton {
            background:#F8FAFD;
            border:1px solid #D9E3F0;
            border-radius:10px;
        }
        QPushButton:hover {
            background:#EEF4FF;
            border-color:#BBD0F2;
        }
        QPushButton:pressed {
            background:#E4EEFF;
            border-color:#9FBAEB;
        }
        """)

        self._anim = QtCore.QPropertyAnimation(self, b"motion", self)
        self._anim.setDuration(190)
        self._anim.setEasingCurve(QtCore.QEasingCurve.Type.OutBack)
        self._refresh_base()

    def get_motion(self) -> float:
        return self._motion

    def set_motion(self, value: float):
        self._motion = max(0.0, min(1.0, float(value)))
        self.update()

    motion = pyqtProperty(float, fget=get_motion, fset=set_motion)

    def _refresh_base(self):
        color = self._hover_color if self._hovered else self._color
        self._base = icon_pixmap(
            self._icon_name,
            color,
            self._icon_px,
            prefer_legacy=False,
        )
        self.update()

    def enterEvent(self, event):
        self._hovered = True
        self._refresh_base()
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self._refresh_base()
        self._anim.stop()
        self._anim.setStartValue(self._motion)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._base.isNull():
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        amount = self._motion
        angle = -5.0 * amount
        scale = 1.0 + 0.055 * amount
        lift = -1.0 * amount

        p.translate(self.width() / 2.0, self.height() / 2.0 + lift)
        p.rotate(angle)
        p.scale(scale, scale)

        half = self._icon_px / 2.0
        target = QtCore.QRectF(-half, -half, self._icon_px, self._icon_px)
        p.drawPixmap(target, self._base, QtCore.QRectF(self._base.rect()))
        p.end()


class ToastOverlay(QFrame):
    """Non-blocking toast with slide + fade animation."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Qt6Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("""
        QFrame#Qt6Toast { background:#FFFFFF; border:1px solid #C9D5E5; border-left:4px solid #2868E8; border-radius:13px; }
        QLabel#ToastTitle { color:#142033; font-size:12px; font-weight:750; }
        QLabel#ToastText { color:#65758E; font-size:10px; }
        """)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(15, 11, 16, 11)
        layout.setSpacing(3)
        self.title = QLabel(objectName="ToastTitle")
        self.text = QLabel(objectName="ToastText")
        self.text.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.text)
        self.setFixedWidth(330)
        self.hide()

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        self._slide = QtCore.QPropertyAnimation(self, b"pos", self)
        self._group = QtCore.QParallelAnimationGroup(self)
        self._group.addAnimation(self._fade)
        self._group.addAnimation(self._slide)
        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    def show_message(self, title: str, text: str, ms: int = 4200):
        self.title.setText(title)
        self.text.setText(text)
        self.adjustSize()
        self.resize(330, max(66, self.sizeHint().height()))
        parent = self.parentWidget()
        target = QtCore.QPoint(parent.width() - self.width() - 22, parent.height() - self.height() - 22)
        start = QtCore.QPoint(target.x(), target.y() + 22)
        self.move(start)
        self.raise_()
        self.show()
        self._group.stop()
        self._fade.setDuration(190); self._fade.setStartValue(0.0); self._fade.setEndValue(1.0)
        self._slide.setDuration(220); self._slide.setStartValue(start); self._slide.setEndValue(target)
        self._fade.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._slide.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._group.start()
        self._hide_timer.start(ms)

    def _fade_out(self):
        self._fade.stop()
        self._fade.setDuration(160)
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        try:
            self._fade.finished.disconnect(self.hide)
        except TypeError:
            pass
        self._fade.finished.connect(self.hide)
        self._fade.start()

    def reposition(self):
        if self.isVisible() and self.parentWidget():
            p = self.parentWidget()
            self.move(p.width() - self.width() - 22, p.height() - self.height() - 22)
