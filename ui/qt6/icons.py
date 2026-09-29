"""Qt6 icon helpers for the EYRES shell.

Priority:
1. Reuse the application's existing sidebar PNG assets when present.
2. Fall back to crisp vector icons painted with Qt6.

This keeps the migrated shell visually consistent with the current EYRES app while
removing the old letter-only fallbacks.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

from .assets import project_root


SIDEBAR_ASSETS = {
    "dashboard": "sidebar_dashboard.png",
    "machines": "sidebar_machines.png",
    "projects": "sidebar_projects.png",
    "capture": "sidebar_capture.png",
    "annotation": "sidebar_annotation.png",
    "augmentation": "sidebar_augment.png",
    "training": "sidebar_training.png",
    "live": "sidebar_live.png",
    "measurement": "sidebar_roi.png",
    "plc": "sidebar_plc.png",
    "users": "sidebar_users.png",
    "maintenance": "sidebar_maintenance.png",
    "diagnostics": "sidebar_diagnostics.png",
    "logout": "sidebar_logout.png",
}


def _legacy_path(name: str) -> Path | None:
    filename = SIDEBAR_ASSETS.get(name)
    if not filename:
        return None
    candidates = (
        project_root() / "Media" / filename,
        project_root() / "ui" / "assets" / filename,
    )
    return next((p for p in candidates if p.is_file()), None)


def _clean_and_tint(path: Path, color: QColor, size: int) -> QPixmap:
    src = QPixmap(str(path))
    if src.isNull():
        return QPixmap()
    src = src.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )

    image = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    # Strip white boxes from older raster icons while preserving their linework.
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            opacity = min(
                pixel.alpha(),
                max(0, 255 - min(pixel.red(), pixel.green(), pixel.blue())),
            )
            pixel.setAlpha(opacity)
            image.setPixelColor(x, y, pixel)
    src = QPixmap.fromImage(image)

    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    x = (size - src.width()) // 2
    y = (size - src.height()) // 2
    painter.drawPixmap(x, y, src)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(canvas.rect(), color)
    painter.end()
    return canvas


def _pen(painter: QPainter, color: QColor, width: float = 1.8) -> None:
    p = QPen(color)
    p.setWidthF(width)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(p)
    painter.setBrush(Qt.BrushStyle.NoBrush)


def _draw_vector(name: str, color: QColor, size: int = 28) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _pen(p, color, max(1.5, size / 15.5))

    s = float(size)
    r = QtCore.QRectF

    if name == "dashboard":
        p.drawRoundedRect(r(.17*s,.18*s,.27*s,.27*s), .05*s,.05*s)
        p.drawRoundedRect(r(.56*s,.18*s,.27*s,.18*s), .05*s,.05*s)
        p.drawRoundedRect(r(.17*s,.57*s,.27*s,.18*s), .05*s,.05*s)
        p.drawRoundedRect(r(.56*s,.48*s,.27*s,.27*s), .05*s,.05*s)

    elif name in {"machines", "machine"}:
        p.drawRoundedRect(r(.19*s,.46*s,.62*s,.26*s), .06*s,.06*s)
        p.drawLine(QtCore.QPointF(.29*s,.46*s), QtCore.QPointF(.29*s,.31*s))
        p.drawLine(QtCore.QPointF(.71*s,.46*s), QtCore.QPointF(.71*s,.31*s))
        p.drawLine(QtCore.QPointF(.29*s,.31*s), QtCore.QPointF(.71*s,.31*s))
        p.drawEllipse(r(.26*s,.68*s,.12*s,.12*s))
        p.drawEllipse(r(.62*s,.68*s,.12*s,.12*s))
        p.drawLine(QtCore.QPointF(.50*s,.31*s), QtCore.QPointF(.50*s,.20*s))
        p.drawEllipse(r(.44*s,.12*s,.12*s,.12*s))

    elif name in {"projects", "project"}:
        path = QPainterPath()
        path.moveTo(.16*s,.31*s)
        path.lineTo(.41*s,.31*s)
        path.lineTo(.49*s,.39*s)
        path.lineTo(.84*s,.39*s)
        path.lineTo(.80*s,.76*s)
        path.lineTo(.18*s,.76*s)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QtCore.QPointF(.18*s,.39*s), QtCore.QPointF(.18*s,.27*s))
        p.drawLine(QtCore.QPointF(.18*s,.27*s), QtCore.QPointF(.42*s,.27*s))
        p.drawLine(QtCore.QPointF(.42*s,.27*s), QtCore.QPointF(.49*s,.34*s))

    elif name in {"database", "db"}:
        p.drawEllipse(r(.22*s,.17*s,.56*s,.18*s))
        p.drawArc(r(.22*s,.30*s,.56*s,.18*s), 180*16, 180*16)
        p.drawArc(r(.22*s,.46*s,.56*s,.18*s), 180*16, 180*16)
        p.drawArc(r(.22*s,.61*s,.56*s,.18*s), 180*16, 180*16)
        p.drawLine(QtCore.QPointF(.22*s,.26*s), QtCore.QPointF(.22*s,.70*s))
        p.drawLine(QtCore.QPointF(.78*s,.26*s), QtCore.QPointF(.78*s,.70*s))

    elif name in {"workflow", "pipeline"}:
        for x,y in ((.25,.25),(.75,.25),(.25,.75),(.75,.75)):
            p.drawRoundedRect(r((x-.08)*s,(y-.08)*s,.16*s,.16*s), .035*s,.035*s)
        p.drawLine(QtCore.QPointF(.33*s,.25*s), QtCore.QPointF(.67*s,.25*s))
        p.drawLine(QtCore.QPointF(.25*s,.33*s), QtCore.QPointF(.25*s,.67*s))
        p.drawLine(QtCore.QPointF(.75*s,.33*s), QtCore.QPointF(.75*s,.67*s))
        p.drawLine(QtCore.QPointF(.33*s,.75*s), QtCore.QPointF(.67*s,.75*s))
        p.drawLine(QtCore.QPointF(.33*s,.33*s), QtCore.QPointF(.67*s,.67*s))

    elif name == "capture":
        p.drawRoundedRect(r(.18*s,.30*s,.64*s,.43*s), .07*s,.07*s)
        p.drawEllipse(r(.38*s,.40*s,.24*s,.24*s))
        p.drawLine(QtCore.QPointF(.29*s,.30*s), QtCore.QPointF(.36*s,.20*s))
        p.drawLine(QtCore.QPointF(.36*s,.20*s), QtCore.QPointF(.58*s,.20*s))
        p.drawLine(QtCore.QPointF(.58*s,.20*s), QtCore.QPointF(.64*s,.30*s))

    elif name == "annotation":
        p.drawRoundedRect(r(.18*s,.18*s,.52*s,.52*s), .05*s,.05*s)
        p.drawLine(QtCore.QPointF(.33*s,.70*s), QtCore.QPointF(.76*s,.27*s))
        p.drawLine(QtCore.QPointF(.67*s,.22*s), QtCore.QPointF(.80*s,.35*s))
        p.drawLine(QtCore.QPointF(.29*s,.73*s), QtCore.QPointF(.39*s,.70*s))

    elif name == "augmentation":
        p.drawRoundedRect(r(.18*s,.18*s,.44*s,.44*s), .04*s,.04*s)
        p.drawRoundedRect(r(.38*s,.38*s,.44*s,.44*s), .04*s,.04*s)
        p.drawLine(QtCore.QPointF(.69*s,.18*s), QtCore.QPointF(.69*s,.34*s))
        p.drawLine(QtCore.QPointF(.61*s,.26*s), QtCore.QPointF(.77*s,.26*s))

    elif name == "training":
        p.drawEllipse(r(.20*s,.23*s,.60*s,.42*s))
        p.drawLine(QtCore.QPointF(.31*s,.67*s), QtCore.QPointF(.31*s,.78*s))
        p.drawLine(QtCore.QPointF(.50*s,.66*s), QtCore.QPointF(.50*s,.80*s))
        p.drawLine(QtCore.QPointF(.69*s,.67*s), QtCore.QPointF(.69*s,.78*s))
        p.drawEllipse(r(.31*s,.34*s,.08*s,.08*s))
        p.drawEllipse(r(.46*s,.29*s,.08*s,.08*s))
        p.drawEllipse(r(.61*s,.39*s,.08*s,.08*s))
        p.drawLine(QtCore.QPointF(.39*s,.38*s), QtCore.QPointF(.46*s,.34*s))
        p.drawLine(QtCore.QPointF(.54*s,.34*s), QtCore.QPointF(.61*s,.43*s))

    elif name == "live":
        p.drawArc(r(.14*s,.14*s,.72*s,.72*s), -50*16, 100*16)
        p.drawArc(r(.28*s,.28*s,.44*s,.44*s), -55*16, 110*16)
        p.drawEllipse(r(.45*s,.45*s,.10*s,.10*s))

    elif name in {"measurement", "roi"}:
        p.drawEllipse(r(.19*s,.19*s,.62*s,.62*s))
        p.drawLine(QtCore.QPointF(.50*s,.13*s), QtCore.QPointF(.50*s,.87*s))
        p.drawLine(QtCore.QPointF(.13*s,.50*s), QtCore.QPointF(.87*s,.50*s))
        p.drawEllipse(r(.46*s,.46*s,.08*s,.08*s))

    elif name == "plc":
        p.drawRoundedRect(r(.20*s,.26*s,.60*s,.48*s), .05*s,.05*s)
        for yy in (.38,.50,.62):
            p.drawLine(QtCore.QPointF(.31*s,yy*s), QtCore.QPointF(.69*s,yy*s))
        for xx in (.30,.43,.56,.69):
            p.drawLine(QtCore.QPointF(xx*s,.18*s), QtCore.QPointF(xx*s,.26*s))
            p.drawLine(QtCore.QPointF(xx*s,.74*s), QtCore.QPointF(xx*s,.82*s))

    elif name == "users":
        p.drawEllipse(r(.22*s,.23*s,.22*s,.22*s))
        p.drawEllipse(r(.56*s,.27*s,.18*s,.18*s))
        p.drawArc(r(.14*s,.42*s,.40*s,.34*s), 0, 180*16)
        p.drawArc(r(.49*s,.45*s,.34*s,.28*s), 0, 180*16)

    elif name == "maintenance":
        p.drawEllipse(r(.32*s,.32*s,.36*s,.36*s))
        p.drawEllipse(r(.43*s,.43*s,.14*s,.14*s))
        for angle in range(0,360,60):
            import math
            a=math.radians(angle)
            x1=.50*s+math.cos(a)*.22*s; y1=.50*s+math.sin(a)*.22*s
            x2=.50*s+math.cos(a)*.34*s; y2=.50*s+math.sin(a)*.34*s
            p.drawLine(QtCore.QPointF(x1,y1), QtCore.QPointF(x2,y2))

    elif name == "diagnostics":
        p.drawRoundedRect(r(.19*s,.18*s,.62*s,.64*s), .05*s,.05*s)
        p.drawLine(QtCore.QPointF(.29*s,.62*s), QtCore.QPointF(.40*s,.49*s))
        p.drawLine(QtCore.QPointF(.40*s,.49*s), QtCore.QPointF(.49*s,.58*s))
        p.drawLine(QtCore.QPointF(.49*s,.58*s), QtCore.QPointF(.67*s,.37*s))
        p.drawLine(QtCore.QPointF(.29*s,.30*s), QtCore.QPointF(.55*s,.30*s))

    elif name == "refresh":
        p.drawArc(r(.18*s,.18*s,.64*s,.64*s), 35*16, 285*16)
        path = QPainterPath()
        path.moveTo(.75*s,.18*s); path.lineTo(.84*s,.19*s); path.lineTo(.81*s,.28*s)
        p.drawPath(path)

    elif name == "chevron":
        p.drawLine(QtCore.QPointF(.38*s,.28*s), QtCore.QPointF(.60*s,.50*s))
        p.drawLine(QtCore.QPointF(.60*s,.50*s), QtCore.QPointF(.38*s,.72*s))

    elif name == "power":
        p.drawArc(r(.22*s,.22*s,.56*s,.56*s), 35*16, 290*16)
        p.drawLine(QtCore.QPointF(.50*s,.12*s), QtCore.QPointF(.50*s,.46*s))

    else:
        p.drawRoundedRect(r(.20*s,.20*s,.60*s,.60*s), .08*s,.08*s)

    p.end()
    return pm


@lru_cache(maxsize=256)
def icon_pixmap(name: str, color_hex: str = "#64748B", size: int = 28, prefer_legacy: bool = True) -> QPixmap:
    color = QColor(color_hex)
    if prefer_legacy:
        path = _legacy_path(name)
        if path is not None:
            pm = _clean_and_tint(path, color, size)
            if not pm.isNull():
                return pm
    return _draw_vector(name, color, size)


def icon(name: str, color_hex: str = "#64748B", size: int = 28, prefer_legacy: bool = True) -> QIcon:
    return QIcon(icon_pixmap(name, color_hex, size, prefer_legacy))
