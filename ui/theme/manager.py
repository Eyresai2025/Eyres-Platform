"""Theme helpers and packaged asset resolution."""
from pathlib import Path
import sys
from PyQt5 import QtCore, QtGui, QtWidgets


def _base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def asset_path(name: str) -> Path:
    modern = _base_dir() / "ui" / "assets" / name
    if modern.is_file():
        return modern
    return _base_dir() / "Media" / name


def apply_light_surface(widget: QtWidgets.QWidget) -> None:
    """Remove legacy per-widget dark QSS and inherit the central application theme."""
    for child in widget.findChildren(QtWidgets.QWidget):
        child.setStyleSheet("")
    widget.setStyleSheet("")
    widget.setProperty("eyresLightSurface", True)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def adapt_legacy_page(widget: QtWidgets.QWidget) -> None:
    """Apply the white design system to an embedded legacy tool.

    Old tools carry large per-widget dark stylesheets which override the
    application stylesheet. Clearing those declarations lets controls inherit
    the shared theme. Graphics/image viewports retain a neutral inspection
    surface so image contrast is not compromised.
    """
    if widget is None:
        return

    # Fully redesigned pages can explicitly own their local stylesheet.
    # Do not clear their child styles with the legacy compatibility pass.
    if bool(widget.property("preserveLocalTheme")):
        return

    viewport_types = (QtWidgets.QGraphicsView,)
    for child in (widget, *widget.findChildren(QtWidgets.QWidget)):
        if isinstance(child, viewport_types):
            child.setStyleSheet(
                "QGraphicsView{background:#111827;border:1px solid #CBD6E4;"
                "border-radius:8px;}"
            )
            continue
        child.setStyleSheet("")
        palette = child.palette()
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#172033"))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#172033"))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#172033"))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#FFFFFF"))
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#F6F8FC"))
        child.setPalette(palette)
    widget.setProperty("eyresLightSurface", True)
    widget.setAutoFillBackground(True)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def fade_in(widget: QtWidgets.QWidget, duration_ms: int = 180) -> None:
    """Run a restrained page fade suitable for an industrial desktop UI."""
    if widget is None or not widget.isVisible():
        return
    effect = QtWidgets.QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    animation = QtCore.QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(max(80, int(duration_ms)))
    animation.setStartValue(0.72)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def finish():
        widget.setGraphicsEffect(None)

    animation.finished.connect(finish)
    widget._eyres_page_animation = animation
    animation.start()
