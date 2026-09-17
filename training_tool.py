from __future__ import annotations
import sys, os, json, mimetypes, urllib.parse, threading, http.server, socketserver, shutil, tempfile, textwrap
from typing import List, Tuple
from pathlib import Path
from datetime import datetime
from PyQt5 import QtCore, QtGui, QtWidgets
import socket

# ===================== Configure your default runs directory here =====================
DEFAULT_RUNS_DIR = r"E:\Office\Desktop\My files\project files\AI pipline\runs"
# ======================================================================================

# ================================== UI CONSTANTS =====================================
# Compact industrial / enterprise visual system.
COLORS = {
    "bg_app": "#F6F9FD",
    "bg_card": "#FFFFFF",
    "bg_subtle": "#FBFCFF",
    "bg_sidebar": "#FFFFFF",
    "bg_header": "#F6F9FD",
    "border_light": "#DBE3F0",
    "border_strong": "#C9D6EB",
    "border_focus": "#255CED",
    "text_primary": "#0E1729",
    "text_secondary": "#61708A",
    "text_muted": "#8CA0BA",
    "primary": "#255CED",
    "primary_hover": "#174BD0",
    "primary_light": "#ECF2FF",
    "success": "#089957",
    "success_light": "#E8FAF0",
    "success_border": "#ADE5C7",
    "detectron": "#6B40E5",
    "detectron_light": "#F2EDFF",
    "danger": "#D92D20",
    "danger_light": "#FEF3F2",
    "warning": "#F0A61A",
    "warning_light": "#FFF8E8",
    "console_bg": "#060B16",
    "console_text": "#ADC7E5",
    "console_muted": "#6B82A3",
}

FONTS = {
    "family": "Segoe UI",
    "size_xs": "10px",
    "size_sm": "11px",
    "size_md": "12px",
    "size_lg": "13px",
    "size_xl": "18px",
    "size_xxl": "22px",
}


def _preferred_ui_font() -> str:
    """Resolve the closest available font to the Figma file without bundling fonts."""
    try:
        families = set(QtGui.QFontDatabase().families())
        for candidate in ("Inter", "Segoe UI Variable Text", "Segoe UI", "Arial"):
            if candidate in families:
                return candidate
    except Exception:
        pass
    try:
        return QtWidgets.QApplication.font().family()
    except Exception:
        return "Segoe UI"


def _font_decl() -> str:
    return f'font-family:"{_preferred_ui_font()}";'


def _style_model_card_direct(card: QtWidgets.QFrame) -> None:
    """Apply model-card styling directly to each widget.

    The host EYRES application has its own global QSS. Direct per-widget QSS is
    deliberately used here so the approved Figma styling cannot be flattened
    when this training widget is embedded/re-parented by the main application.
    """
    selected = bool(card.property("selected")) or bool(getattr(card, "_selected", False))
    family = str(card.property("family") or "yolo")
    accent = "#6B40E5" if family == "detectron" else "#255CED"
    light = "#F2EDFF" if family == "detectron" else "#ECF2FF"
    surface = light if selected else "#FFFFFF"
    border = accent if selected else "#DBE3F0"
    card.setStyleSheet(
        f'QFrame#modeCard{{background:{surface};border:1px solid {border};border-radius:14px;}}'
    )
    card.setAttribute(QtCore.Qt.WA_StyledBackground, True)

    def child(cls, name):
        return card.findChild(cls, name)

    accent_bar = child(QtWidgets.QFrame, "cardAccent")
    if accent_bar:
        accent_bar.setStyleSheet(f'QFrame#cardAccent{{background:{accent};border:0;border-radius:2px;}}')
        accent_bar.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    body = child(QtWidgets.QWidget, "modeCardContent")
    if body:
        body.setStyleSheet('QWidget#modeCardContent{background:transparent;border:0;}')
    icon = child(QtWidgets.QLabel, "frameworkIcon")
    if icon:
        ibg = accent if selected else light
        icol = "#FFFFFF" if selected else accent
        icon.setStyleSheet(
            f'QLabel#frameworkIcon{{{_font_decl()}background:{ibg};color:{icol};border:0;border-radius:12px;font-size:15px;font-weight:700;}}'
        )
    title = child(QtWidgets.QLabel, "cardTitle")
    if title:
        title.setStyleSheet(f'QLabel#cardTitle{{{_font_decl()}background:transparent;color:#0E1729;font-size:16px;font-weight:700;}}')
    task = child(QtWidgets.QLabel, "modelTask")
    if task:
        task.setStyleSheet(
            f'QLabel#modelTask{{{_font_decl()}background:{light};color:{accent};border:0;border-radius:7px;padding:5px 10px;font-size:10px;font-weight:600;}}'
        )
    desc = child(QtWidgets.QLabel, "cardDescription")
    if desc:
        desc.setStyleSheet(f'QLabel#cardDescription{{{_font_decl()}background:transparent;color:#61708A;font-size:12px;font-weight:400;}}')
    divider = child(QtWidgets.QFrame, "cardDivider")
    if divider:
        divider.setStyleSheet('QFrame#cardDivider{background:#DBE3F0;border:0;min-height:1px;max-height:1px;}')
        divider.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    engine = child(QtWidgets.QLabel, "engineLabel")
    if engine:
        engine.setStyleSheet(f'QLabel#engineLabel{{{_font_decl()}background:transparent;color:#61708A;font-size:11px;font-weight:500;}}')
    action = child(QtWidgets.QLabel, "cardAction")
    if action:
        action.setStyleSheet(
            f'QLabel#cardAction{{{_font_decl()}background:transparent;color:{accent if selected else "#0E1729"};font-size:12px;font-weight:600;}}'
        )


def _style_weight_card_direct(card: QtWidgets.QFrame) -> None:
    selected = bool(card.property("selected")) or bool(getattr(card, "_selected", False))
    bg = "#ECF2FF" if selected else "#FBFCFF"
    border = "#255CED" if selected else "#C9D6EB"
    card.setStyleSheet(f'QFrame#weightChoiceCard{{background:{bg};border:1px solid {border};border-radius:14px;}}')
    card.setAttribute(QtCore.Qt.WA_StyledBackground, True)
    icon = card.findChild(QtWidgets.QLabel, "weightIcon")
    if icon:
        icon.setStyleSheet(
            f'QLabel#weightIcon{{{_font_decl()}background:{"#255CED" if selected else "#F2EDFF"};color:{"#FFFFFF" if selected else "#6B40E5"};border:0;border-radius:12px;font-size:13px;font-weight:700;}}'
        )
    for name, size, weight, color in (
        ("weightTitle",16,700,"#0E1729"),
        ("weightSubtitle",11,400,"#61708A"),
        ("weightNote",11,400,"#61708A"),
        ("weightFileStatus",11,400,"#61708A"),
    ):
        w = card.findChild(QtWidgets.QLabel, name)
        if w:
            w.setStyleSheet(f'QLabel#{name}{{{_font_decl()}background:transparent;color:{color};font-size:{size}px;font-weight:{weight};}}')
    pill = card.findChild(QtWidgets.QLabel, "selectedPill")
    if pill:
        pill.setStyleSheet(f'QLabel#selectedPill{{{_font_decl()}background:#FFFFFF;color:#255CED;border:0;border-radius:7px;padding:5px 10px;font-size:10px;font-weight:700;}}')
    divider = card.findChild(QtWidgets.QFrame, "cardDivider")
    if divider:
        divider.setStyleSheet('QFrame#cardDivider{background:#DBE3F0;border:0;min-height:1px;max-height:1px;}')
        divider.setAttribute(QtCore.Qt.WA_StyledBackground, True)


def _apply_direct_named_styles(root: QtWidgets.QWidget) -> None:
    """Force the Figma visual tokens directly on named widgets.

    This is intentionally independent from inherited application QSS so the
    appearance remains identical when embedded inside the EYRES shell.
    """
    if root is None:
        return
    widgets = [root] + root.findChildren(QtWidgets.QWidget)
    fam = _preferred_ui_font()

    static = {
        "modelWorkspace": 'QFrame#modelWorkspace{background:#FFFFFF;border:1px solid #DBE3F0;border-radius:18px;}',
        "modelEyebrow": f'QLabel#modelEyebrow{{font-family:"{fam}";background:transparent;color:#61708A;font-size:10px;font-weight:600;}}',
        "pageTitle": f'QLabel#pageTitle{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:22px;font-weight:700;}}',
        "pageSubtitle": f'QLabel#pageSubtitle{{font-family:"{fam}";background:transparent;color:#61708A;font-size:12px;font-weight:400;}}',
        "heroBadge": f'QLabel#heroBadge{{font-family:"{fam}";background:#F6F9FD;color:#61708A;border:0;border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;}}',
        "motionSpec": f'QLabel#motionSpec{{font-family:"{fam}";background:transparent;color:#61708A;font-size:10px;font-weight:400;}}',
        "trainingWorkspace": 'QFrame#trainingWorkspace{background:#FFFFFF;border:1px solid #DBE3F0;border-radius:18px;}',
        "trainingEyebrow": f'QLabel#trainingEyebrow{{font-family:"{fam}";background:transparent;color:#61708A;font-size:10px;font-weight:600;}}',
        "trainingPageTitle": f'QLabel#trainingPageTitle{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:18px;font-weight:700;}}',
        "trainingPageSubtitle": f'QLabel#trainingPageSubtitle{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;}}',
        "stageBar": 'QFrame#stageBar{background:transparent;border:0;}',
        "trainingStack": 'QStackedWidget#trainingStack{background:#FFFFFF;border:0;}',
        "card": 'QFrame#card{background:#FFFFFF;border:0;}',
        "sectionFrame": 'QFrame#sectionFrame{background:#FBFCFF;border:1px solid #DBE3F0;border-radius:14px;}',
        "sectionTitle": f'QLabel#sectionTitle{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:13px;font-weight:700;}}',
        "sectionSubtitle": f'QLabel#sectionSubtitle{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;font-weight:400;}}',
        "sectionMiniLabel": f'QLabel#sectionMiniLabel{{font-family:"{fam}";background:transparent;color:#61708A;font-size:10px;font-weight:600;}}',
        "sectionBodyStrong": f'QLabel#sectionBodyStrong{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:13px;font-weight:600;}}',
        "fieldLabel": f'QLabel#fieldLabel{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;font-weight:500;}}',
        "fieldHint": f'QLabel#fieldHint{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;font-weight:400;}}',
        "miniTag": f'QLabel#miniTag{{font-family:"{fam}";background:#ECF2FF;color:#255CED;border:0;border-radius:7px;padding:5px 9px;font-size:10px;font-weight:600;}}',
        "pageLead": f'QLabel#pageLead{{font-family:"{fam}";background:transparent;color:#61708A;font-size:12px;font-weight:400;}}',
        "infoNote": 'QFrame#infoNote{background:#ECF2FF;border:0;border-radius:10px;}',
        "infoNoteIcon": f'QLabel#infoNoteIcon{{font-family:"{fam}";background:transparent;color:#255CED;font-size:16px;font-weight:700;}}',
        "infoNoteTitle": f'QLabel#infoNoteTitle{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:12px;font-weight:600;}}',
        "infoNoteDetail": f'QLabel#infoNoteDetail{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;font-weight:400;}}',
        "outputHint": 'QFrame#outputHint{background:#ECF2FF;border:0;border-radius:10px;}',
        "outputHintLabel": f'QLabel#outputHintLabel{{font-family:"{fam}";background:transparent;color:#255CED;font-size:10px;font-weight:700;}}',
        "outputHintValue": f'QLabel#outputHintValue{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:13px;font-weight:600;}}',
        "outputHintDetail": f'QLabel#outputHintDetail{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;}}',
        "consoleFrame": 'QFrame#consoleFrame{background:#060B16;border:0;border-radius:14px;}',
        "consoleTitle": f'QLabel#consoleTitle{{font-family:"{fam}";background:transparent;color:#8CA8D1;font-size:10px;font-weight:600;}}',
        "readyPill": f'QLabel#readyPill{{font-family:"{fam}";background:#0F3329;color:#5CEB9C;border:0;border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;}}',
        "console": 'QPlainTextEdit#console{background:#060B16;border:0;color:#ADC7E5;font-family:"Cascadia Mono","Consolas";font-size:12px;padding:0;selection-background-color:#255CED;}',
        "stageActionBar": 'QWidget#stageActionBar{background:transparent;border:0;}',
        "reviewSide": 'QFrame#reviewSide{background:#FBFCFF;border:1px solid #DBE3F0;border-radius:14px;}',
        "reviewSideTitle": f'QLabel#reviewSideTitle{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:13px;font-weight:700;}}',
        "reviewSideSubtitle": f'QLabel#reviewSideSubtitle{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;}}',
        "summaryItem": 'QFrame#summaryItem{background:transparent;border:0;}',
        "summaryKey": f'QLabel#summaryKey{{font-family:"{fam}";background:transparent;color:#61708A;font-size:10px;font-weight:600;}}',
        "summaryValue": f'QLabel#summaryValue{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:13px;font-weight:500;}}',
        "selectedPill": f'QLabel#selectedPill{{font-family:"{fam}";background:#FFFFFF;color:#255CED;border:0;border-radius:7px;padding:5px 10px;font-size:10px;font-weight:700;}}',
        "weightTitle": f'QLabel#weightTitle{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:16px;font-weight:700;}}',
        "weightSubtitle": f'QLabel#weightSubtitle{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;}}',
        "weightNote": f'QLabel#weightNote{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;}}',
        "weightFileStatus": f'QLabel#weightFileStatus{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;}}',
    }
    for w in widgets:
        name = w.objectName()
        if name in static:
            w.setStyleSheet(static[name])
            if isinstance(w, (QtWidgets.QFrame, QtWidgets.QWidget)):
                w.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        if name == "modernSpin":
            w.setStyleSheet(
                f'{w.metaObject().className()}#modernSpin{{font-family:"{fam}";min-height:40px;background:#FFFFFF;border:1px solid #C9D6EB;border-radius:8px;padding:0 10px;color:#0E1729;font-size:12px;}}'
            )
        elif name == "modernCheck":
            w.setStyleSheet(f'QCheckBox#modernCheck{{font-family:"{fam}";color:#0E1729;font-size:12px;spacing:7px;}}')

    for card in root.findChildren(QtWidgets.QFrame, "modeCard"):
        _style_model_card_direct(card)
    for card in root.findChildren(QtWidgets.QFrame, "weightChoiceCard"):
        _style_weight_card_direct(card)


def _apply_stage_button_direct(button: QtWidgets.QPushButton, state: str) -> None:
    fam = _preferred_ui_font()
    if state == "complete":
        bg, fg, border = "#E8FAF0", "#089957", "#ADE5C7"
    elif state == "current":
        bg, fg, border = "#ECF2FF", "#255CED", "#255CED"
    else:
        bg, fg, border = "#FFFFFF", "#61708A", "#C9D6EB"
    button.setStyleSheet(
        f'QPushButton#stageButton{{font-family:"{fam}";min-height:40px;padding:0 14px;border:1px solid {border};border-radius:9px;background:{bg};color:{fg};font-size:12px;font-weight:600;text-align:left;}}'
        f'QPushButton#stageButton:hover{{border-color:#8CAFF0;background:{bg};}}'
    )

# ================================== HELPER CLASSES ====================================

class ModernCard(QtWidgets.QFrame):
    """Reusable enterprise surface."""
    def __init__(self, parent=None, shadow=True):
        super().__init__(parent)
        self.setObjectName("modernCard")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        if shadow:
            effect = QtWidgets.QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(24)
            effect.setXOffset(0)
            effect.setYOffset(6)
            effect.setColor(QtGui.QColor(15, 23, 42, 16))
            self.setGraphicsEffect(effect)


class AnimatedModelCard(QtWidgets.QFrame):
    """Figma-style model card with restrained 160ms elevation animation."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("modeCard")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setMouseTracking(True)
        self._selected = False

        self._shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(14)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(4)
        self._shadow.setColor(QtGui.QColor(10, 20, 41, 16))
        self.setGraphicsEffect(self._shadow)

        self._blur_anim = QtCore.QPropertyAnimation(self._shadow, b"blurRadius", self)
        self._blur_anim.setDuration(160)
        self._blur_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._offset_anim = QtCore.QPropertyAnimation(self._shadow, b"yOffset", self)
        self._offset_anim.setDuration(160)
        self._offset_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def _animate_elevation(self, blur: float, offset: float):
        self._blur_anim.stop(); self._offset_anim.stop()
        self._blur_anim.setStartValue(float(self._shadow.blurRadius()))
        self._blur_anim.setEndValue(float(blur))
        self._offset_anim.setStartValue(float(self._shadow.yOffset()))
        self._offset_anim.setEndValue(float(offset))
        self._blur_anim.start(); self._offset_anim.start()

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        self._shadow.setColor(QtGui.QColor(37, 92, 237, 30) if self._selected else QtGui.QColor(10, 20, 41, 16))
        self._animate_elevation(22 if self._selected else 14, 6 if self._selected else 4)
        self.style().unpolish(self); self.style().polish(self); self.update()
        _style_model_card_direct(self)

    def enterEvent(self, event):
        self._animate_elevation(24 if self._selected else 20, 7 if self._selected else 6)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._animate_elevation(22 if self._selected else 14, 6 if self._selected else 4)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SelectableWeightCard(QtWidgets.QFrame):
    """Large checkpoint choice card used by YOLO weight selection."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("weightChoiceCard")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self._selected = False

    def set_selected(self, selected: bool):
        self._selected = bool(selected)
        self.setProperty("selected", self._selected)
        self.style().unpolish(self); self.style().polish(self); self.update()
        _style_weight_card_direct(self)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ModernLineEdit(QtWidgets.QLineEdit):
    def __init__(self, placeholder="", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(42)
        self.setClearButtonEnabled(True)
        self.setStyleSheet(f"""
            QLineEdit {{
                background: #FFFFFF;
                border: 1px solid {COLORS['border_light']};
                border-radius: 8px;
                padding: 0 11px;
                color: {COLORS['text_primary']};
                font-size: {FONTS['size_md']};
            }}
            QLineEdit:hover {{ border-color: {COLORS['border_strong']}; }}
            QLineEdit:focus {{ border: 1px solid {COLORS['border_focus']}; }}
            QLineEdit:disabled {{ background: #F1F5F9; color: {COLORS['text_muted']}; }}
        """)


class ModernComboBox(QtWidgets.QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(42)
        self.setStyleSheet(f"""
            QComboBox {{
                background: #FFFFFF;
                border: 1px solid {COLORS['border_light']};
                border-radius: 7px;
                padding: 0 34px 0 11px;
                color: {COLORS['text_primary']};
                font-size: {FONTS['size_md']};
            }}
            QComboBox:hover {{ border-color: {COLORS['border_strong']}; }}
            QComboBox:focus {{ border: 1px solid {COLORS['border_focus']}; }}
            QComboBox::drop-down {{ border: none; width: 30px; }}
            QComboBox::down-arrow {{
                image: none; width: 0; height: 0;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {COLORS['text_secondary']};
                margin-right: 9px;
            }}
            QComboBox QAbstractItemView {{
                background: #FFFFFF;
                border: 1px solid {COLORS['border_light']};
                selection-background-color: {COLORS['primary_light']};
                selection-color: {COLORS['primary']};
                outline: 0;
                padding: 4px;
            }}
        """)



class DetectronComboBox(ModernComboBox):
    """ModernComboBox with a platform-independent painted dropdown chevron."""
    def __init__(self, parent=None):
        super().__init__(parent)

        # Disable the platform/QSS arrow. We paint the chevron ourselves so the
        # control looks the same regardless of the Windows theme / DPI scaling.
        self.setStyleSheet(self.styleSheet() + """
            QComboBox::drop-down {
                border: none;
                width: 32px;
                background: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
            }
        """)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        pen = QtGui.QPen(QtGui.QColor("#61708A"))
        pen.setWidthF(1.6)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)

        # Small Figma-like down chevron, vertically centered.
        cx = self.width() - 17
        cy = self.height() // 2
        painter.drawLine(cx - 4, cy - 2, cx, cy + 2)
        painter.drawLine(cx, cy + 2, cx + 4, cy - 2)
        painter.end()


class ModernPushButton(QtWidgets.QPushButton):
    def __init__(self, text, variant="secondary", parent=None):
        super().__init__(text, parent)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.setMinimumHeight(40)
        if variant == "primary":
            bg, hover, text_col, border = COLORS['primary'], COLORS['primary_hover'], "#FFFFFF", COLORS['primary']
        elif variant == "ghost":
            bg, hover, text_col, border = "transparent", COLORS['primary_light'], COLORS['primary'], "transparent"
        elif variant == "danger":
            bg, hover, text_col, border = COLORS['danger_light'], "#FEE4E2", COLORS['danger'], "#FECDCA"
        elif variant == "dark":
            bg, hover, text_col, border = "#FFFFFF", "#F6F9FD", COLORS['primary'], COLORS['border_strong']
        else:
            bg, hover, text_col, border = "#FFFFFF", "#F6F9FD", COLORS['primary'], COLORS['border_strong']
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {text_col}; border: 1px solid {border};
                border-radius: 8px; padding: 0 16px;
                font-size: 12px; font-weight: 650;
            }}
            QPushButton:hover {{ background: {hover}; border-color: {COLORS['primary'] if variant != 'danger' else '#FDA29B'}; }}
            QPushButton:pressed {{ padding-top:1px; }}
            QPushButton:focus {{ border: 1px solid {COLORS['border_focus']}; }}
            QPushButton:disabled {{ background:#EEF2F6; color:#98A5B7; border-color:#DDE5EF; }}
        """)


class SectionFrame(QtWidgets.QFrame):
    """Figma-style neutral configuration panel."""
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("sectionFrame")
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        self.outer = QtWidgets.QVBoxLayout(self)
        self.outer.setContentsMargins(20, 16, 20, 18)
        self.outer.setSpacing(8)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("sectionTitle")
        self.outer.addWidget(title_label)
        if subtitle:
            subtitle_label = QtWidgets.QLabel(subtitle)
            subtitle_label.setObjectName("sectionSubtitle")
            subtitle_label.setWordWrap(True)
            self.outer.addWidget(subtitle_label)

        self.body = QtWidgets.QVBoxLayout()
        self.body.setSpacing(10)
        self.outer.addSpacing(2)
        self.outer.addLayout(self.body)


# ================================== DASHBOARD HANDLER ================================
# ================================== DASHBOARD HANDLER ================================

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
                                rel = fp.relative_to(base).as_posix()
                                files.append(rel)
                        try:
                            mtime = p.stat().st_mtime
                        except Exception:
                            mtime = 0.0
                        runs.append({"name": p.name, "files": files, "mtime": mtime})
            return self._send_json({"base": str(base), "runs": runs})

        if url.path == "/file":
            q = urllib.parse.parse_qs(url.query)
            rel = (q.get("path", [""])[0]).replace("\\", "/").strip("/")
            fp = (self.base_dir / rel)
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
            cand = [
                app_base_dir() / "dashboard.html",
                app_base_dir().parent / "dashboard.html",
                Path.cwd() / "dashboard.html",
            ]
            for p in cand:
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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

def start_dashboard_server(base_dir: str | Path) -> tuple[str, socketserver.TCPServer]:
    port = _pick_free_port()
    Handler = _DashHandler
    Handler.base_dir = Path(base_dir)
    httpd = socketserver.TCPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    api_url = f"http://127.0.0.1:{port}"
    return api_url, httpd

# ---------------- Dependency helper: PyYAML on demand ----------------
def require_yaml(parent: QtWidgets.QWidget | None = None):
    try:
        import yaml
        return yaml
    except Exception:
        ans = QtWidgets.QMessageBox.question(
            parent, "Missing dependency",
            "PyYAML is required but not installed.\n\nInstall it now via pip?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if ans == QtWidgets.QMessageBox.Yes:
            try:
                import subprocess
                subprocess.check_call([sys.executable, "-m", "pip", "install", "pyyaml"])
                import yaml
                QtWidgets.QMessageBox.information(parent, "Installed", "PyYAML installed successfully.")
                return yaml
            except Exception as e:
                QtWidgets.QMessageBox.critical(parent, "Install failed", f"Could not install PyYAML.\n\n{e}")
                raise ImportError("PyYAML not available.") from e
        else:
            raise ImportError("PyYAML not available.")

def app_base_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent

def candidate_dirs() -> list[Path]:
    base = app_base_dir()
    return [
        base, base / "assets", base / "Assets", base / "models", base / "Models",
        base / "weights", base / "Weights", base / "data", base / "Data",
        base.parent / "assets", base.parent / "models", base.parent / "data",
    ]

def find_first_file(*names_or_relpaths: str) -> Path | None:
    for folder in candidate_dirs():
        for name in names_or_relpaths:
            p = (folder / name)
            if p.is_file():
                return p
    return None

def fwd(p: Path | str) -> str:
    return str(p).replace("\\", "/")

# ---------- ultra-short help ----------
HELP_HTML = """
<div style="font-family: 'Segoe UI', sans-serif; color: #111827;">
<h2 style="color: #2563EB; margin-bottom: 6px;">Training Wizard</h2>
<p style="color: #5B6474;">Configure a model training run in two controlled steps.</p>
<ol style="line-height: 1.8; color: #374151;">
<li><b>Select model</b> — Choose YOLO or Detectron2, then select segmentation or detection.</li>
<li><b>Configure training</b> — Set dataset, starting weights, runtime parameters, and review the generated command.</li>
</ol>
<p style="color: #5B6474;">CUDA is used when it is available in the active PyTorch environment; otherwise CPU remains available.</p>
<p style="color: #2563EB; font-weight: 600;">Training does not start until you press <b>Start Training</b> on the Review &amp; Run page.</p>
</div>
"""

class SimpleHelpDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Help")
        self.resize(560, 360)
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)

        frame = QtWidgets.QFrame()
        frame.setObjectName("helpCard")
        flay = QtWidgets.QVBoxLayout(frame)

        txt = QtWidgets.QTextBrowser()
        txt.setObjectName("helpText")
        txt.setOpenExternalLinks(True)
        txt.setHtml(HELP_HTML)
        txt.setStyleSheet("background: transparent; border: none;")
        flay.addWidget(txt)

        v.addWidget(frame, 1)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        v.addWidget(btns, 0, QtCore.Qt.AlignRight)

# ================================== DATASET MERGE DIALOG ==============================

class DatasetMergeDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Merge / Update Dataset")
        self.resize(760, 580)
        self.out_base_yaml = ""

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(24, 24, 24, 24)
        v.setSpacing(16)

        self.base_yaml = self._file_row("Base data.yaml")
        self.update_yaml = self._file_row("Update data.yaml")

        self.src_train_images = self._folder_row("Update train/images")
        self.src_train_labels = self._folder_row("Update train/labels")
        self.src_test_images = self._folder_row("Update test/images")
        self.src_test_labels = self._folder_row("Update test/labels")

        self.dst_train_images = self._folder_row("Base train/images (dest)")
        self.dst_train_labels = self._folder_row("Base train/labels (dest)")
        self.dst_test_images = self._folder_row("Base test/images (dest)")
        self.dst_test_labels = self._folder_row("Base test/labels (dest)")

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        form.setFormAlignment(QtCore.Qt.AlignVCenter)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)

        for lbl, row in [
            self.base_yaml, self.update_yaml,
            self.src_train_images, self.src_train_labels,
            self.src_test_images, self.src_test_labels,
            self.dst_train_images, self.dst_train_labels,
            self.dst_test_images, self.dst_test_labels,
        ]:
            form.addRow(lbl, row)

        card = ModernCard()
        card.setLayout(form)
        v.addWidget(card, 1)

        btns = QtWidgets.QDialogButtonBox()
        self.run_btn = ModernPushButton("Run Merge", "primary")
        self.cancel_btn = ModernPushButton("Cancel", "secondary")
        btns.addButton(self.run_btn, QtWidgets.QDialogButtonBox.AcceptRole)
        btns.addButton(self.cancel_btn, QtWidgets.QDialogButtonBox.RejectRole)
        self.run_btn.clicked.connect(self._run_merge)
        self.cancel_btn.clicked.connect(self.reject)
        v.addWidget(btns)

    def _chip(self, text: str) -> QtWidgets.QLabel:
        lb = QtWidgets.QLabel(text)
        lb.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        lb.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: 600; font-size: {FONTS['size_sm']};")
        return lb

    def _file_row(self, label_text: str):
        label = self._chip(label_text)
        edit = ModernLineEdit()
        btn = ModernPushButton("Browse…", "ghost")
        btn.setFixedWidth(90)
        def pick():
            fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file", os.path.expanduser("~"), "YAML Files (*.yaml *.yml);;All Files (*.*)")
            if fn: edit.setText(fn)
        btn.clicked.connect(pick)
        row = QtWidgets.QHBoxLayout(); row.setSpacing(8); row.setContentsMargins(0,0,0,0)
        row.addWidget(edit, 1); row.addWidget(btn, 0)
        w = QtWidgets.QWidget(); w.setLayout(row)
        return label, w

    def _folder_row(self, label_text: str):
        label = self._chip(label_text)
        edit = ModernLineEdit()
        btn = ModernPushButton("Browse…", "ghost")
        btn.setFixedWidth(90)
        def pick():
            dn = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder", os.path.expanduser("~"))
            if dn: edit.setText(dn)
        btn.clicked.connect(pick)
        row = QtWidgets.QHBoxLayout(); row.setSpacing(8); row.setContentsMargins(0,0,0,0)
        row.addWidget(edit, 1); row.addWidget(btn, 0)
        w = QtWidgets.QWidget(); w.setLayout(row)
        return label, w

    def _val(self, row_widget: QtWidgets.QWidget) -> str:
        le = row_widget.findChild(QtWidgets.QLineEdit)
        return (le.text() or "").strip() if le else ""

    def _run_merge(self):
        yaml = require_yaml(self)
        import shutil as _shutil

        base_yaml_path = self._val(self.base_yaml[1])
        update_yaml_path = self._val(self.update_yaml[1])
        src_train_images = self._val(self.src_train_images[1])
        src_train_labels = self._val(self.src_train_labels[1])
        src_test_images = self._val(self.src_test_images[1])
        src_test_labels = self._val(self.src_test_labels[1])
        dst_train_images = self._val(self.dst_train_images[1])
        dst_train_labels = self._val(self.dst_train_labels[1])
        dst_test_images = self._val(self.dst_test_images[1])
        dst_test_labels = self._val(self.dst_test_labels[1])

        update_train_dir = src_train_labels
        update_test_dir = src_test_labels

        required = [
            base_yaml_path, update_yaml_path,
            src_train_images, src_train_labels, src_test_images, src_test_labels,
            dst_train_images, dst_train_labels, dst_test_images, dst_test_labels
        ]
        if not all(required):
            QtWidgets.QMessageBox.warning(self, "Missing", "Please fill all paths.")
            return

        for p in [base_yaml_path, update_yaml_path]:
            if not os.path.isfile(p):
                QtWidgets.QMessageBox.warning(self, "Not found", f"File not found:\n{p}")
                return

        for d in [src_train_images, src_train_labels, src_test_images, src_test_labels,
                  dst_train_images, dst_train_labels, dst_test_images, dst_test_labels]:
            if not os.path.isdir(d):
                QtWidgets.QMessageBox.warning(self, "Not a folder", f"Folder not found:\n{d}")
                return

        try:
            with open(base_yaml_path, "r", encoding="utf-8") as f:
                base_data = yaml.safe_load(f) or {}
            with open(update_yaml_path, "r", encoding="utf-8") as f:
                update_data = yaml.safe_load(f) or {}

            base_data.setdefault("names", [])
            update_names = update_data.get("names", [])

            for cls in update_names:
                if cls not in base_data["names"]:
                    base_data["names"].append(cls)

            base_data["nc"] = len(base_data["names"])

            class InlineList(list): pass
            def represent_inline_list(dumper, data):
                return dumper.represent_sequence('tag:yaml.org,2002:seq', data, flow_style=True)
            yaml.add_representer(InlineList, represent_inline_list)
            base_data['names'] = InlineList(base_data['names'])

            with open(base_yaml_path, 'w', encoding="utf-8") as f:
                yaml.safe_dump(base_data, f, default_flow_style=False, sort_keys=False)

            update_to_final_map = {i: base_data['names'].index(cls) for i, cls in enumerate(update_names)}

            def update_labels_in_place(folder, mapping):
                files = [f for f in os.listdir(folder) if f.endswith('.txt')]
                for item in files:
                    fp = os.path.join(folder, item)
                    rows = []
                    with open(fp, 'r', encoding="utf-8") as myfile:
                        for line in myfile:
                            s = line.strip()
                            if s:
                                parts = s.split(" ")
                                rows.append(parts)
                    for r in rows:
                        old = r[0]
                        if old.isdigit():
                            r[0] = str(mapping.get(int(old), int(old)))
                    with open(fp, 'w', encoding="utf-8") as wf:
                        for r in rows:
                            wf.write(" ".join(r) + "\n")

            update_labels_in_place(update_train_dir, update_to_final_map)
            update_labels_in_place(update_test_dir, update_to_final_map)

            for d in [dst_train_images, dst_train_labels, dst_test_images, dst_test_labels]:
                os.makedirs(d, exist_ok=True)

            def copy_files(src, dst):
                for file in os.listdir(src):
                    s = os.path.join(src, file)
                    d = os.path.join(dst, file)
                    if os.path.isfile(s):
                        _shutil.copy2(s, d)

            copy_files(src_train_images, dst_train_images)
            copy_files(src_train_labels, dst_train_labels)
            copy_files(src_test_images, dst_test_images)
            copy_files(src_test_labels, dst_test_labels)

            self.out_base_yaml = base_yaml_path
            self.accept()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Merge failed", str(e))

# ================================== STEP INDICATOR ===================================

class StepIndicator(QtWidgets.QWidget):
    def __init__(self, number: int, title: str, parent=None):
        super().__init__(parent)
        self.number = number
        self.setObjectName("stepIndicator")
        self.is_active = False
        self.is_complete = False
        self.setFixedHeight(48)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)
        self.circle = QtWidgets.QLabel(str(number))
        self.circle.setFixedSize(28, 28)
        self.circle.setAlignment(QtCore.Qt.AlignCenter)
        self.circle.setObjectName("stepCircle")
        self.title_label = QtWidgets.QLabel(title)
        self.title_label.setObjectName("stepTitle")
        layout.addWidget(self.circle)
        layout.addWidget(self.title_label, 1)
        self._update_style()

    def set_active(self, active: bool):
        self.is_active = active; self._update_style()

    def set_complete(self, complete: bool):
        self.is_complete = complete; self._update_style()

    def _update_style(self):
        self.setStyleSheet("QWidget#stepIndicator { background:transparent; border:0; }")
        if self.is_complete:
            self.circle.setText(str(self.number))
            self.circle.setStyleSheet("QLabel#stepCircle { background:#089957; color:white; border-radius:14px; font-weight:800; font-size:11px; }")
            self.title_label.setStyleSheet("color:#0E1729; font-weight:600; font-size:12px;")
        elif self.is_active:
            self.circle.setText(str(self.number))
            self.circle.setStyleSheet("QLabel#stepCircle { background:#255CED; color:white; border-radius:14px; font-weight:800; font-size:11px; }")
            self.title_label.setStyleSheet("color:#0E1729; font-weight:bold; font-size:12px;")
        else:
            self.circle.setText(str(self.number))
            self.circle.setStyleSheet("QLabel#stepCircle { background:#E8EDF5; color:#61708A; border-radius:14px; font-weight:bold; font-size:11px; }")
            self.title_label.setStyleSheet("color:#61708A; font-weight:500; font-size:12px;")


# ================================== PAGES ====================================================
# ================================== PAGES ====================================================
# ================================== PAGES ====================================================

class TrainingStageBar(QtWidgets.QFrame):
    """Full-width segmented stage navigation matching the approved Figma design."""
    currentChanged = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("stageBar")
        self.setFixedHeight(42)
        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(0,0,0,0)
        self._layout.setSpacing(8)
        self._buttons = []
        self._group = QtWidgets.QButtonGroup(self); self._group.setExclusive(True)
        self._current_stack_index = -1

    def set_steps(self, steps):
        while self._layout.count():
            item=self._layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self._buttons=[]
        for position,(stack_index,label) in enumerate(steps,start=1):
            b=QtWidgets.QPushButton(f"{position:02d}   {label}")
            b.setObjectName("stageButton"); b.setCheckable(True)
            b.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.clicked.connect(lambda checked=False, idx=stack_index: self.setCurrentIndex(idx))
            self._group.addButton(b); self._layout.addWidget(b,1)
            self._buttons.append((b,stack_index,label))

    def setCurrentIndex(self, stack_index:int):
        selected=-1
        for pos,(b,idx,_) in enumerate(self._buttons):
            if idx==stack_index:
                selected=pos; b.setChecked(True); break
        if selected<0: return
        self._current_stack_index=stack_index
        for pos,(b,_,label) in enumerate(self._buttons):
            state='complete' if pos<selected else 'current' if pos==selected else 'upcoming'
            prefix=f"{pos+1:02d}"
            b.setText(f"{prefix}   {label}")
            b.setProperty('stageState',state)
            b.style().unpolish(b); b.style().polish(b); b.update()
            _apply_stage_button_direct(b, state)
        self.currentChanged.emit(stack_index)

    def currentIndex(self): return self._current_stack_index
    def count(self): return len(self._buttons)


class StepModel(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    card_selected = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        root=QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(28,20,30,20); root.setSpacing(0)

        workspace=ModernCard(shadow=True); workspace.setObjectName("modelWorkspace")
        workspace.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Expanding)
        main=QtWidgets.QVBoxLayout(workspace); main.setContentsMargins(26,24,26,22); main.setSpacing(16)

        head=QtWidgets.QHBoxLayout(); head.setSpacing(12)
        titles=QtWidgets.QVBoxLayout(); titles.setSpacing(3)
        eyebrow=QtWidgets.QLabel("CHOOSE A WORKFLOW"); eyebrow.setObjectName("modelEyebrow")
        title=QtWidgets.QLabel("Select the model family and task"); title.setObjectName("pageTitle")
        subtitle=QtWidgets.QLabel("Four production-ready training paths. You can change the model before starting a run."); subtitle.setObjectName("pageSubtitle")
        titles.addWidget(eyebrow); titles.addWidget(title); titles.addWidget(subtitle)
        head.addLayout(titles,1)
        badge=QtWidgets.QLabel("4 WORKFLOWS"); badge.setObjectName("heroBadge")
        head.addWidget(badge,0,QtCore.Qt.AlignTop)
        main.addLayout(head)

        self._cards=[]; self._model_group=QtWidgets.QButtonGroup(self); self._model_group.setExclusive(True)
        meta={
            "YOLO Segmentation":("Y","SEGMENTATION","Pixel-level defect masks with fast training and export.","Ultralytics","yolo"),
            "YOLO Detection":("Y","DETECTION","Bounding-box object detection for fast localization.","Ultralytics","yolo"),
            "Detectron Segmentation":("D2","INSTANCE MASKS","Mask R-CNN for precise instance segmentation.","Detectron2","detectron"),
            "Detectron Detection":("D2","OBJECT DETECTION","Faster R-CNN for high-quality object detection.","Detectron2","detectron"),
        }
        keymap={"YOLO Segmentation":"seg","YOLO Detection":"det","Detectron Segmentation":"dseg","Detectron Detection":"ddet"}
        grid=QtWidgets.QGridLayout(); grid.setContentsMargins(0,0,0,0); grid.setHorizontalSpacing(14); grid.setVerticalSpacing(14)
        grid.setColumnStretch(0,1); grid.setColumnStretch(1,1)

        def add_card(r,c,name):
            icon,task,desc,engine,family=meta[name]
            card=AnimatedModelCard(); card.setProperty("family",family); card.setMinimumHeight(220); card.setMaximumHeight(220)
            h=QtWidgets.QHBoxLayout(card); h.setContentsMargins(0,0,0,0); h.setSpacing(0)
            accent=QtWidgets.QFrame(); accent.setObjectName("cardAccent"); accent.setFixedWidth(5); h.addWidget(accent)
            body=QtWidgets.QWidget(); body.setObjectName("modeCardContent")
            v=QtWidgets.QVBoxLayout(body); v.setContentsMargins(20,18,20,15); v.setSpacing(9)
            top=QtWidgets.QHBoxLayout(); top.setSpacing(14)
            badge_icon=QtWidgets.QLabel(icon); badge_icon.setObjectName("frameworkIcon"); badge_icon.setAlignment(QtCore.Qt.AlignCenter); badge_icon.setFixedSize(52,52)
            namecol=QtWidgets.QVBoxLayout(); namecol.setSpacing(5)
            title_lbl=QtWidgets.QLabel(name); title_lbl.setObjectName("cardTitle")
            task_lbl=QtWidgets.QLabel(task); task_lbl.setObjectName("modelTask"); task_lbl.setSizePolicy(QtWidgets.QSizePolicy.Maximum,QtWidgets.QSizePolicy.Fixed)
            namecol.addWidget(title_lbl); namecol.addWidget(task_lbl,0,QtCore.Qt.AlignLeft); namecol.addStretch(1)
            top.addWidget(badge_icon,0,QtCore.Qt.AlignTop); top.addLayout(namecol,1)
            v.addLayout(top)
            d=QtWidgets.QLabel(desc); d.setObjectName("cardDescription"); d.setWordWrap(True); v.addWidget(d)
            v.addStretch(1)
            divider=QtWidgets.QFrame(); divider.setObjectName("cardDivider"); divider.setFixedHeight(1); v.addWidget(divider)
            foot=QtWidgets.QHBoxLayout(); foot.setSpacing(8)
            eng=QtWidgets.QLabel(engine); eng.setObjectName("engineLabel")
            action=QtWidgets.QLabel("Select  →"); action.setObjectName("cardAction")
            foot.addWidget(eng); foot.addStretch(1); foot.addWidget(action)
            v.addLayout(foot); h.addWidget(body,1)
            rb=QtWidgets.QRadioButton(); rb.setVisible(False); self._model_group.addButton(rb)
            rb.toggled.connect(self.changed.emit); rb.toggled.connect(self._update_card_styles)
            card._action=action
            for child in (accent,body,badge_icon,title_lbl,task_lbl,d,divider,eng,action):
                child.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents,True)
            def choose():
                rb.setChecked(True); self._update_card_styles(); self.card_selected.emit(keymap[name])
            card.clicked.connect(choose)
            grid.addWidget(card,r,c); self._cards.append((card,rb,name))

        add_card(0,0,"YOLO Segmentation"); add_card(0,1,"YOLO Detection")
        add_card(1,0,"Detectron Segmentation"); add_card(1,1,"Detectron Detection")
        self._cards[0][1].setChecked(True); self._update_card_styles()
        main.addLayout(grid,1)
        motion=QtWidgets.QLabel("Hover elevation   ·   Selected state highlighted   ·   Smooth transition")
        motion.setObjectName("motionSpec"); main.addWidget(motion)
        root.addWidget(workspace,1)
        _apply_direct_named_styles(self)
        for card, _, _ in self._cards:
            _style_model_card_direct(card)

    def _update_card_styles(self):
        for card,rb,_ in self._cards:
            selected=bool(rb.isChecked()); card.set_selected(selected)
            card._action.setText("Selected" if selected else "Select  →")
            _style_model_card_direct(card)

    def value(self):
        for _,rb,name in self._cards:
            if rb.isChecked():
                return {"YOLO Segmentation":"seg","YOLO Detection":"det","Detectron Segmentation":"dseg","Detectron Detection":"ddet"}[name]
        return "seg"


class StepTrain(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    request_model_page = QtCore.pyqtSignal()

    DEFAULT_SEG_PATH = fwd(find_first_file("yolo11s-seg.pt", "yolo11s-seg/yolo11s-seg.pt", "seg.pt") or Path(""))
    DEFAULT_DET_PATH = fwd(find_first_file("yolo11n.pt", "yolo11n/yolo11n.pt", "det.pt") or Path(""))

    def __init__(self, mode: str = "seg"):
        super().__init__()
        self.mode = mode
        root=QtWidgets.QVBoxLayout(self); root.setContentsMargins(28,20,30,20); root.setSpacing(0)
        content=ModernCard(shadow=True); content.setObjectName("trainingWorkspace"); content.setSizePolicy(QtWidgets.QSizePolicy.Expanding,QtWidgets.QSizePolicy.Expanding)
        cLay=QtWidgets.QVBoxLayout(content); cLay.setContentsMargins(24,20,24,20); cLay.setSpacing(14)

        head=QtWidgets.QHBoxLayout(); head.setSpacing(12)
        title_column=QtWidgets.QVBoxLayout(); title_column.setSpacing(3)
        self.training_mode_eyebrow=QtWidgets.QLabel("YOLO · SEGMENTATION"); self.training_mode_eyebrow.setObjectName("trainingEyebrow")
        self.training_title=QtWidgets.QLabel("Dataset setup"); self.training_title.setObjectName("trainingPageTitle")
        self.training_subtitle=QtWidgets.QLabel(""); self.training_subtitle.setObjectName("trainingPageSubtitle"); self.training_subtitle.hide()
        title_column.addWidget(self.training_mode_eyebrow); title_column.addWidget(self.training_title)
        head.addLayout(title_column,1)
        self.mode_badge=QtWidgets.QLabel("YOLO · SEGMENTATION"); self.mode_badge.setObjectName("modeBadge"); self.mode_badge.setAlignment(QtCore.Qt.AlignCenter)
        head.addWidget(self.mode_badge,0,QtCore.Qt.AlignTop)
        cLay.addLayout(head)

        self.nav=TrainingStageBar(self); cLay.addWidget(self.nav)
        self.stack=QtWidgets.QStackedWidget(); self.stack.setObjectName("trainingStack"); self._page_animation=None; self._page_effect=None
        cLay.addWidget(self.stack,1)

        self._build_page_dataset(); self._build_page_seg(); self._build_page_det(); self._build_page_hparams(); self._build_page_run()
        self.detectron_page=self._build_page_detectron(); self.detectron_det_page=self._build_page_detectron_det()
        self.nav.currentChanged.connect(self._change_training_page)

        # Figma flow controls live inside the configuration canvas, not in a global footer.
        self.stage_action_bar=QtWidgets.QWidget(); self.stage_action_bar.setObjectName("stageActionBar")
        sal=QtWidgets.QHBoxLayout(self.stage_action_bar); sal.setContentsMargins(0,0,0,0); sal.setSpacing(8); sal.addStretch(1)
        self.stage_back=ModernPushButton("← Back","secondary"); self.stage_back.setFixedWidth(90)
        self.stage_next=ModernPushButton("Next","primary"); self.stage_next.setFixedWidth(102)
        self.stage_back.clicked.connect(self._stage_back); self.stage_next.clicked.connect(self._stage_next)
        sal.addWidget(self.stage_back); sal.addWidget(self.stage_next)
        cLay.addWidget(self.stage_action_bar)

        root.addWidget(content,1)
        self._apply_local_qss()
        _apply_direct_named_styles(self)
        self.seg_default_rb.toggled.connect(self._update_states); self.det_default_rb.toggled.connect(self._update_states)
        self._update_states(); self._jump_to_mode(mode)

    def _stage_position(self):
        current=self.nav.currentIndex()
        for pos,(_,idx,_) in enumerate(self.nav._buttons):
            if idx==current:
                return pos
        return -1

    def _stage_back(self):
        # On the final Review & run page, provide a direct route back to model selection.
        if self.nav.currentIndex() == 4:
            self.request_model_page.emit()
            return

        pos=self._stage_position()
        if pos > 0:
            self.nav.setCurrentIndex(self.nav._buttons[pos-1][1])
        else:
            self.request_model_page.emit()

    def _stage_next(self):
        pos=self._stage_position()
        if 0 <= pos < len(self.nav._buttons)-1:
            self.nav.setCurrentIndex(self.nav._buttons[pos+1][1])

    def _update_stage_actions(self):
        if not hasattr(self, "stage_action_bar"):
            return

        pos=self._stage_position()
        is_review=(self.nav.currentIndex()==4)

        # Keep a compact action row on Review so the operator can return directly
        # to model selection without restarting the whole training session.
        self.stage_action_bar.setVisible(True)

        if is_review:
            self.stage_back.setText("← Model selection")
            self.stage_back.setFixedWidth(150)
            self.stage_back.show()
            self.stage_next.hide()
            return

        self.stage_back.setText("← Back")
        self.stage_back.setFixedWidth(90)
        self.stage_back.show()

        if 0 <= pos < len(self.nav._buttons)-1:
            next_idx=self.nav._buttons[pos+1][1]
            self.stage_next.setText("Review" if next_idx==4 else "Next")
            self.stage_next.show()
        else:
            self.stage_next.hide()

    def set_mode(self, mode: str):
        self.mode = mode
        self._jump_to_mode(mode)

    def _animate_current_page(self):
        page = self.stack.currentWidget()
        if page is None:
            return
        effect = QtWidgets.QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        effect.setOpacity(0.78)
        anim = QtCore.QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(170)
        anim.setStartValue(0.78)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        anim.finished.connect(lambda p=page: p.setGraphicsEffect(None))
        self._page_effect = effect
        self._page_animation = anim
        anim.start()

    def _change_training_page(self, index: int):
        self.stack.setCurrentIndex(index)
        headings={0:"Dataset setup",1:"Starting checkpoint",2:"Starting checkpoint",3:"Hyperparameters",4:"Review & run"}
        title=headings.get(index,"Dataset setup")
        if self.mode in ("dseg","ddet") and index==1: title="Configuration"
        self.training_title.setText(title)
        if index==4: self._refresh_review_summary()
        self._update_stage_actions()
        _apply_direct_named_styles(self)
        self._animate_current_page()

    def _jump_to_mode(self, mode: str):
        if mode == "seg":
            self.mode_badge.setText("YOLO · SEGMENTATION"); self.mode_badge.setProperty("family","yolo"); self.training_mode_eyebrow.setText("YOLO · SEGMENTATION"); self._repolish_mode_badge()
            self._swap_seg_slot(None)
            self.nav.set_steps([
                (0, "Dataset"), (1, "Model weights"),
                (3, "Hyperparameters"), (4, "Review & run"),
            ])
            self.nav.setCurrentIndex(0)
        elif mode == "det":
            self.mode_badge.setText("YOLO · DETECTION"); self.mode_badge.setProperty("family","yolo"); self.training_mode_eyebrow.setText("YOLO · DETECTION"); self._repolish_mode_badge()
            self._swap_seg_slot(None)
            self.nav.set_steps([
                (0, "Dataset"), (2, "Model weights"),
                (3, "Hyperparameters"), (4, "Review & run"),
            ])
            self.nav.setCurrentIndex(0)
        elif mode == "dseg":
            self.mode_badge.setText("DETECTRON2 · SEGMENTATION"); self.mode_badge.setProperty("family","detectron"); self.training_mode_eyebrow.setText("DETECTRON2 · SEGMENTATION"); self._repolish_mode_badge()
            self._swap_seg_slot(self.detectron_page)
            self.nav.set_steps([(1, "Configuration"), (4, "Review & run")])
            self.nav.setCurrentIndex(1)
        elif mode == "ddet":
            self.mode_badge.setText("DETECTRON2 · DETECTION"); self.mode_badge.setProperty("family","detectron"); self.training_mode_eyebrow.setText("DETECTRON2 · DETECTION"); self._repolish_mode_badge()
            self._swap_seg_slot(self.detectron_det_page)
            self.nav.set_steps([(1, "Configuration"), (4, "Review & run")])
            self.nav.setCurrentIndex(1)

    def _repolish_mode_badge(self):
        if hasattr(self, "mode_badge"):
            self.mode_badge.style().unpolish(self.mode_badge)
            self.mode_badge.style().polish(self.mode_badge)
            self.mode_badge.update()
            fam = _preferred_ui_font()
            detectron = str(self.mode_badge.property("family") or "") == "detectron"
            bg = "#F2EDFF" if detectron else "#ECF2FF"
            fg = "#6B40E5" if detectron else "#255CED"
            self.mode_badge.setStyleSheet(
                f'QLabel#modeBadge{{font-family:"{fam}";background:{bg};color:{fg};border:0;border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;}}'
            )
            self.mode_badge.setAttribute(QtCore.Qt.WA_StyledBackground, True)

    def _fill_device_combo(self, combo: QtWidgets.QComboBox):
        import subprocess
        opts = ["cpu"]
        gpu_names = []
        try:
            import torch
            if torch.cuda.is_available():
                n = torch.cuda.device_count()
                opts += ["cuda"] + [f"cuda:{i}" for i in range(n)]
                for i in range(n):
                    try:
                        gpu_names.append(torch.cuda.get_device_name(i))
                    except Exception:
                        pass
            elif shutil.which("nvidia-smi"):
                try:
                    out = subprocess.run(
                        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                        capture_output=True, text=True, timeout=2
                    ).stdout.strip()
                    if out:
                        gpu_names = [ln.strip() for ln in out.splitlines() if ln.strip()]
                except Exception:
                    pass
        except Exception:
            pass
        combo.clear()
        combo.addItems(opts)
        if "cuda" in opts:
            combo.setCurrentText("cuda")
            if gpu_names:
                combo.setToolTip("CUDA available: " + ", ".join(gpu_names))
        elif gpu_names:
            combo.setToolTip("NVIDIA GPU detected, but CUDA is not available in the current PyTorch environment.")

    def _swap_seg_slot(self, new_widget: QtWidgets.QWidget | None):
        current = self.stack.widget(1)
        if new_widget is None:
            if current is not self.seg_page:
                self.stack.removeWidget(current)
                self.stack.insertWidget(1, self.seg_page)
            return
        if current is self.seg_page:
            self.stack.removeWidget(self.seg_page)
            self.stack.insertWidget(1, new_widget)
        elif current is not new_widget:
            self.stack.removeWidget(current)
            self.stack.insertWidget(1, new_widget)

    def _card(self) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setObjectName("card")
        f.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        f.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        return f

    def _field_label(self, text: str) -> QtWidgets.QLabel:
        lb = QtWidgets.QLabel(text)
        lb.setObjectName("fieldLabel")
        return lb

    def _field_box(self, label: str, widget: QtWidgets.QWidget, helper: str = "") -> QtWidgets.QWidget:
        box = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(5)
        v.addWidget(self._field_label(label))
        v.addWidget(widget)
        if helper:
            hint = QtWidgets.QLabel(helper)
            hint.setObjectName("fieldHint")
            hint.setWordWrap(True)
            v.addWidget(hint)
        return box

    def _path_row(self, edit: QtWidgets.QLineEdit, button: QtWidgets.QPushButton) -> QtWidgets.QWidget:
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(edit, 1)
        row.addWidget(button, 0)
        return self._wrap(row)

    def _scroll_sections(self, sections: list[QtWidgets.QWidget]) -> QtWidgets.QScrollArea:
        host = QtWidgets.QWidget()
        v = QtWidgets.QVBoxLayout(host)
        v.setContentsMargins(0, 0, 5, 0)
        v.setSpacing(10)
        for section in sections:
            v.addWidget(section)
        v.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("configScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(host)
        return scroll

    def _equalize_label_sizes(self, labels: list[QtWidgets.QLabel]):
        if not labels:
            return
        w = max(l.sizeHint().width() for l in labels)
        h = max(l.sizeHint().height() for l in labels)
        for l in labels:
            l.setWordWrap(False)
            l.setMinimumSize(w, h)
            l.setMaximumHeight(h)
            l.setFixedHeight(h)

    def _info_note(self, title: str, detail: str = "") -> QtWidgets.QFrame:
        f=QtWidgets.QFrame(); f.setObjectName("infoNote")
        h=QtWidgets.QHBoxLayout(f); h.setContentsMargins(14,12,14,12); h.setSpacing(10)
        icon=QtWidgets.QLabel("i"); icon.setObjectName("infoNoteIcon"); icon.setAlignment(QtCore.Qt.AlignCenter); icon.setFixedWidth(18)
        col=QtWidgets.QVBoxLayout(); col.setSpacing(2)
        t=QtWidgets.QLabel(title); t.setObjectName("infoNoteTitle"); col.addWidget(t)
        if detail:
            d=QtWidgets.QLabel(detail); d.setObjectName("infoNoteDetail"); d.setWordWrap(True); col.addWidget(d)
        h.addWidget(icon,0,QtCore.Qt.AlignTop); h.addLayout(col,1)
        return f

    def _output_hint(self) -> QtWidgets.QFrame:
        f=QtWidgets.QFrame(); f.setObjectName("outputHint")
        v=QtWidgets.QVBoxLayout(f); v.setContentsMargins(14,12,14,12); v.setSpacing(4)
        a=QtWidgets.QLabel("RUN OUTPUT"); a.setObjectName("outputHintLabel")
        b=QtWidgets.QLabel("runs/train…"); b.setObjectName("outputHintValue")
        c=QtWidgets.QLabel("Weights, plots and metrics"); c.setObjectName("outputHintDetail")
        v.addWidget(a); v.addWidget(b); v.addWidget(c); return f

    def _build_weight_card(self, title, subtitle, note, icon_text, selected, browse_cb=None):
        card=SelectableWeightCard(); card.setMinimumHeight(226); card.setMaximumHeight(226); card._selected_pill=None
        v=QtWidgets.QVBoxLayout(card); v.setContentsMargins(20,18,20,16); v.setSpacing(10)
        top=QtWidgets.QHBoxLayout(); top.setSpacing(14)
        icon=QtWidgets.QLabel(icon_text); icon.setObjectName("weightIcon"); icon.setAlignment(QtCore.Qt.AlignCenter); icon.setFixedSize(52,52)
        texts=QtWidgets.QVBoxLayout(); texts.setSpacing(4)
        ttl=QtWidgets.QLabel(title); ttl.setObjectName("weightTitle")
        sub=QtWidgets.QLabel(subtitle); sub.setObjectName("weightSubtitle")
        texts.addWidget(ttl); texts.addWidget(sub); texts.addStretch(1)
        top.addWidget(icon); top.addLayout(texts,1); v.addLayout(top)
        action_row=QtWidgets.QHBoxLayout(); action_row.setSpacing(10)
        if selected:
            tag=QtWidgets.QLabel("SELECTED"); tag.setObjectName("selectedPill"); action_row.addWidget(tag,0); card._selected_pill=tag
        elif browse_cb is not None:
            choose=ModernPushButton("Choose file","secondary"); choose.setMinimumWidth(126); choose.clicked.connect(browse_cb); action_row.addWidget(choose,0)
            status=QtWidgets.QLabel("No file selected"); status.setObjectName("weightFileStatus"); action_row.addWidget(status,0); card._file_status=status; card._choose_btn=choose
        action_row.addStretch(1); v.addLayout(action_row)
        v.addStretch(1)
        div=QtWidgets.QFrame(); div.setObjectName("cardDivider"); div.setFixedHeight(1); v.addWidget(div)
        n=QtWidgets.QLabel(note); n.setObjectName("weightNote"); v.addWidget(n)
        for w in (icon,ttl,sub,n): w.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents,True)
        return card

    def _open_merge_dialog(self):
        dlg = DatasetMergeDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            if dlg.out_base_yaml:
                self.data_edit.setText(dlg.out_base_yaml)
            QtWidgets.QMessageBox.information(self, "Dataset updated", "Dataset classes and files were merged successfully.")

    def _build_page_dataset(self):
        card=self._card(); page=QtWidgets.QHBoxLayout(card); page.setContentsMargins(0,4,0,0); page.setSpacing(14)
        framework=SectionFrame("Training framework","Runtime selection")
        self.ver_combo=ModernComboBox(); self.ver_combo.addItems(["8","10","11","12"]); self.ver_combo.setCurrentText("11")
        framework.body.addWidget(self._field_box("Ultralytics version",self.ver_combo))
        fw_tag=QtWidgets.QLabel("ULTRALYTICS"); fw_tag.setObjectName("miniTag"); framework.body.addWidget(fw_tag,0,QtCore.Qt.AlignLeft)
        framework.body.addSpacing(10)
        env=QtWidgets.QLabel("Environment"); env.setObjectName("sectionMiniLabel"); framework.body.addWidget(env)
        rt=QtWidgets.QLabel("Python runtime"); rt.setObjectName("sectionBodyStrong"); framework.body.addWidget(rt)
        cap=QtWidgets.QLabel("Local / CUDA capable"); cap.setObjectName("fieldHint"); framework.body.addWidget(cap)
        framework.setFixedWidth(360); framework.setMinimumHeight(356); framework.setMaximumHeight(356)

        dataset=SectionFrame("Dataset source","Select the data.yaml used for this run")
        self.data_edit=ModernLineEdit("Select data.yaml")
        self.btn_browse_data=ModernPushButton("Browse","secondary"); self.btn_browse_data.setMinimumWidth(120); self.btn_browse_data.clicked.connect(self._browse_data_yaml)
        dataset.body.addWidget(self._field_box("Dataset YAML",self._path_row(self.data_edit,self.btn_browse_data)))
        merge_btn=ModernPushButton("Merge / Update","secondary"); merge_btn.clicked.connect(self._open_merge_dialog)
        ar=QtWidgets.QHBoxLayout(); ar.addWidget(merge_btn,0); ar.addStretch(1); dataset.body.addLayout(ar)
        dataset.body.addSpacing(8)
        dataset.body.addWidget(self._info_note("Dataset paths are validated before command generation.","Missing train/validation paths are resolved before training starts."))
        dataset.setMinimumHeight(356); dataset.setMaximumHeight(356)
        page.addWidget(framework,0,QtCore.Qt.AlignTop); page.addWidget(dataset,1,QtCore.Qt.AlignTop)
        self.stack.addWidget(card)

    def _weight_option_style(self) -> str:
        return f"""
            QRadioButton {{
                color:{COLORS['text_primary']}; font-size:12px; font-weight:bold;
                padding:13px 15px; border:1px solid #CBD6E3;
                border-radius:9px; background:#FFFFFF;
            }}
            QRadioButton:hover {{ border-color:#8FB4EC; background:#F7FAFF; }}
            QRadioButton:checked {{ background:#EEF5FF; border:2px solid {COLORS['primary']}; color:#174EA6; }}
            QRadioButton::indicator {{ width:16px; height:16px; border-radius:8px; border:2px solid #9AA9BC; background:#FFFFFF; }}
            QRadioButton::indicator:checked {{ border:5px solid {COLORS['primary']}; background:#FFFFFF; }}
        """

    def _build_page_seg(self):
        card=self._card(); self.seg_page=card
        page=QtWidgets.QVBoxLayout(card); page.setContentsMargins(0,4,0,0); page.setSpacing(12)
        hint=QtWidgets.QLabel("Choose how this training run should initialize."); hint.setObjectName("pageLead"); page.addWidget(hint)
        row=QtWidgets.QHBoxLayout(); row.setSpacing(14)
        self.seg_default_rb=QtWidgets.QRadioButton(); self.seg_custom_rb=QtWidgets.QRadioButton(); self.seg_default_rb.setVisible(False); self.seg_custom_rb.setVisible(False); self.seg_default_rb.setChecked(True)
        self.seg_default_card=self._build_weight_card("Packaged default weights","Recommended for a clean training run.","Uses the bundled segmentation checkpoint.","D",True)
        def browse_seg():
            self.seg_custom_rb.setChecked(True); self._browse_path(self.seg_path_edit)
            if self.seg_path_edit.text().strip() and hasattr(self.seg_custom_card,'_file_status'): self.seg_custom_card._file_status.setText(os.path.basename(self.seg_path_edit.text().strip()))
        self.seg_custom_card=self._build_weight_card("Custom checkpoint (.pt)","Resume or fine-tune an existing model.","Use only when intentionally continuing training.","PT",False,browse_seg)
        self.seg_default_card.clicked.connect(lambda: self.seg_default_rb.setChecked(True)); self.seg_custom_card.clicked.connect(lambda: self.seg_custom_rb.setChecked(True))
        self.seg_path_edit=ModernLineEdit("Select checkpoint"); self.seg_path_edit.setVisible(False)
        self.seg_browse=QtWidgets.QPushButton(); self.seg_browse.setVisible(False)
        self.seg_weights_container=QtWidgets.QWidget(); self.seg_weights_container.setVisible(False)
        row.addWidget(self.seg_default_card,1); row.addWidget(self.seg_custom_card,1); page.addLayout(row); page.addWidget(self.seg_path_edit); page.addWidget(self.seg_weights_container); page.addStretch(1)
        self.seg_default_rb.toggled.connect(self._update_states); self.seg_custom_rb.toggled.connect(self._update_states); self.seg_default_rb.toggled.connect(lambda _: self._sync_weight_cards())
        self.stack.addWidget(card)

    def _build_page_det(self):
        card=self._card(); page=QtWidgets.QVBoxLayout(card); page.setContentsMargins(0,4,0,0); page.setSpacing(12)
        hint=QtWidgets.QLabel("Choose how this training run should initialize."); hint.setObjectName("pageLead"); page.addWidget(hint)
        row=QtWidgets.QHBoxLayout(); row.setSpacing(14)
        self.det_default_rb=QtWidgets.QRadioButton(); self.det_custom_rb=QtWidgets.QRadioButton(); self.det_default_rb.setVisible(False); self.det_custom_rb.setVisible(False); self.det_default_rb.setChecked(True)
        self.det_default_card=self._build_weight_card("Packaged default weights","Recommended for a clean training run.","Uses the bundled detection checkpoint.","D",True)
        def browse_det():
            self.det_custom_rb.setChecked(True); self._browse_path(self.det_path_edit)
            if self.det_path_edit.text().strip() and hasattr(self.det_custom_card,'_file_status'): self.det_custom_card._file_status.setText(os.path.basename(self.det_path_edit.text().strip()))
        self.det_custom_card=self._build_weight_card("Custom checkpoint (.pt)","Resume or fine-tune an existing model.","Use only when intentionally continuing training.","PT",False,browse_det)
        self.det_default_card.clicked.connect(lambda: self.det_default_rb.setChecked(True)); self.det_custom_card.clicked.connect(lambda: self.det_custom_rb.setChecked(True))
        self.det_path_edit=ModernLineEdit("Select checkpoint"); self.det_path_edit.setVisible(False)
        self.det_browse=QtWidgets.QPushButton(); self.det_browse.setVisible(False)
        self.det_weights_container=QtWidgets.QWidget(); self.det_weights_container.setVisible(False)
        row.addWidget(self.det_default_card,1); row.addWidget(self.det_custom_card,1); page.addLayout(row); page.addWidget(self.det_path_edit); page.addWidget(self.det_weights_container); page.addStretch(1)
        self.det_default_rb.toggled.connect(self._update_states); self.det_custom_rb.toggled.connect(self._update_states); self.det_default_rb.toggled.connect(lambda _: self._sync_weight_cards())
        self.stack.addWidget(card)

    def _sync_weight_cards(self):
        if hasattr(self,'seg_default_card'):
            self.seg_default_card.set_selected(self.seg_default_rb.isChecked()); self.seg_custom_card.set_selected(self.seg_custom_rb.isChecked())
            if getattr(self.seg_default_card, '_selected_pill', None):
                self.seg_default_card._selected_pill.setVisible(self.seg_default_rb.isChecked())
        if hasattr(self,'det_default_card'):
            self.det_default_card.set_selected(self.det_default_rb.isChecked()); self.det_custom_card.set_selected(self.det_custom_rb.isChecked())
            if getattr(self.det_default_card, '_selected_pill', None):
                self.det_default_card._selected_pill.setVisible(self.det_default_rb.isChecked())

    def _style_spinbox(self, widget: QtWidgets.QAbstractSpinBox):
        widget.setMinimumHeight(40)
        widget.setObjectName("modernSpin")

    def _build_page_hparams(self):
        card=self._card(); page=QtWidgets.QGridLayout(card); page.setContentsMargins(0,4,0,0); page.setHorizontalSpacing(14); page.setVerticalSpacing(12)
        compute=SectionFrame("Compute","Execution resources"); training=SectionFrame("Training","Optimization settings"); output=SectionFrame("Output","Run destination")
        self.device_combo=ModernComboBox(); self._populate_device_combo()
        self.imgsz=QtWidgets.QSpinBox(); self.imgsz.setRange(32,4096); self.imgsz.setSingleStep(32); self.imgsz.setValue(1024); self._style_spinbox(self.imgsz)
        self.batch=QtWidgets.QSpinBox(); self.batch.setRange(1,512); self.batch.setValue(16); self._style_spinbox(self.batch)
        self.epochs=QtWidgets.QSpinBox(); self.epochs.setRange(1,5000); self.epochs.setValue(400); self._style_spinbox(self.epochs)
        self.opt=ModernComboBox(); self.opt.addItems(["Adam","SGD","AdamW"]); self.opt.setCurrentText("Adam")
        self.lr0=QtWidgets.QDoubleSpinBox(); self.lr0.setDecimals(6); self.lr0.setRange(1e-6,1.0); self.lr0.setSingleStep(0.0001); self.lr0.setValue(0.0001); self._style_spinbox(self.lr0)
        self.project=ModernLineEdit(); self.project.setText("runs")
        compute.body.addWidget(self._field_box("Device",self.device_combo)); compute.body.addWidget(self._field_box("Image size",self.imgsz)); compute.body.addWidget(self._field_box("Batch size",self.batch))
        training.body.addWidget(self._field_box("Epochs",self.epochs)); training.body.addWidget(self._field_box("Optimizer",self.opt)); training.body.addWidget(self._field_box("Learning rate",self.lr0))
        output.body.addWidget(self._field_box("Project",self.project)); output.body.addWidget(self._output_hint()); output.body.addStretch(1)
        for section in (compute,training,output): section.setMinimumHeight(344); section.setMaximumHeight(344)
        page.addWidget(compute,0,0,QtCore.Qt.AlignTop); page.addWidget(training,0,1,QtCore.Qt.AlignTop); page.addWidget(output,0,2,QtCore.Qt.AlignTop)
        page.setColumnStretch(0,1); page.setColumnStretch(1,1); page.setColumnStretch(2,1); page.setRowStretch(1,1)
        self.stack.addWidget(card)

    def _build_page_detectron(self) -> QtWidgets.QWidget:
        card=self._card(); outer=QtWidgets.QVBoxLayout(card); outer.setContentsMargins(0,4,0,0); outer.setSpacing(0)
        self.d_repo_edit=ModernLineEdit(); self.d_repo_edit.setText("detectron2_repo"); self.d_repo_edit.setClearButtonEnabled(False)
        repo_browse=ModernPushButton("Browse","secondary"); repo_browse.setMinimumWidth(110); repo_browse.clicked.connect(lambda:(lambda dn:self.d_repo_edit.setText(dn) if dn else None)(QtWidgets.QFileDialog.getExistingDirectory(self,"Detectron2 repo folder",os.path.expanduser("~"))))
        self.d_install_cb=QtWidgets.QCheckBox("Install Detectron2 before training"); self.d_install_cb.setObjectName("modernCheck")

        self.d_data_edit=ModernLineEdit("Dataset root"); self.d_data_edit.setClearButtonEnabled(False)
        data_browse=ModernPushButton("Browse","secondary"); data_browse.setMinimumWidth(112); data_browse.clicked.connect(lambda:(lambda dn:self.d_data_edit.setText(dn) if dn else None)(QtWidgets.QFileDialog.getExistingDirectory(self,"Data root folder",os.path.expanduser("~"))))

        self.d_train_edit=ModernLineEdit(); self.d_train_edit.setText("train10"); self.d_train_edit.setClearButtonEnabled(False)
        self.d_test_edit=ModernLineEdit(); self.d_test_edit.setText("test10"); self.d_test_edit.setClearButtonEnabled(False)
        self.d_classes_edit=ModernLineEdit(); self.d_classes_edit.setText("top_rectangle"); self.d_classes_edit.setClearButtonEnabled(False)

        self.d_model_combo=DetectronComboBox()
        self.d_model_combo.addItems([
            "COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x.yaml",
            "COCO-InstanceSegmentation/mask_rcnn_R_101_FPN_3x.yaml",
            "COCO-InstanceSegmentation/mask_rcnn_X_101_32x8d_FPN_3x.yaml",
        ])

        self.d_ims_per_batch=QtWidgets.QSpinBox(); self.d_ims_per_batch.setRange(1,64); self.d_ims_per_batch.setValue(2); self._style_spinbox(self.d_ims_per_batch); self.d_ims_per_batch.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.d_base_lr=QtWidgets.QDoubleSpinBox(); self.d_base_lr.setDecimals(6); self.d_base_lr.setRange(1e-6,1.0); self.d_base_lr.setValue(0.00025); self._style_spinbox(self.d_base_lr); self.d_base_lr.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.d_max_iter=QtWidgets.QSpinBox(); self.d_max_iter.setRange(10,100000); self.d_max_iter.setValue(1000); self._style_spinbox(self.d_max_iter); self.d_max_iter.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.d_workers=QtWidgets.QSpinBox(); self.d_workers.setRange(0,16); self.d_workers.setValue(2); self._style_spinbox(self.d_workers); self.d_workers.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

        self.d_device_combo=DetectronComboBox(); self._fill_device_combo(self.d_device_combo)
        self.d_output_edit=ModernLineEdit(); self.d_output_edit.setText("detectron_runs"); self.d_output_edit.setClearButtonEnabled(False)

        # Do not force Figma's exact 196px card height here. On Windows with
        # 125/150% scaling that value clips the second field row. These minimum
        # heights preserve the same visual proportions while allowing all text
        # and controls to remain fully visible.
        env=SectionFrame("Environment","Repository and runtime preparation")
        env.setMinimumHeight(222)
        env.body.addWidget(self._field_box("Detectron2 repository",self._path_row(self.d_repo_edit,repo_browse)))
        env.body.addWidget(self.d_install_cb)

        data=SectionFrame("Dataset","Training source and classes")
        data.setMinimumHeight(222)
        data.body.addWidget(self._field_box("Data root",self._path_row(self.d_data_edit,data_browse)))
        rr=QtWidgets.QHBoxLayout(); rr.setSpacing(8); rr.addWidget(self._field_box("Train",self.d_train_edit),1); rr.addWidget(self._field_box("Test",self.d_test_edit),1); rr.addWidget(self._field_box("Classes",self.d_classes_edit),1); data.body.addLayout(rr)
        # Figma layout: the runtime card has exactly TWO parameter rows.
        # Row 1 -> Model config | Batch | Base LR
        # Row 2 -> Iterations | Workers | Device | Output
        # Keeping the model config on its own row created a third row and caused
        # the lower controls to be clipped inside the fixed-height card.
        model=SectionFrame("Model & runtime","Training configuration")
        model.setMinimumHeight(236)

        r1=QtWidgets.QHBoxLayout()
        r1.setSpacing(10)
        r1.addWidget(self._field_box("Model config",self.d_model_combo),5)
        r1.addWidget(self._field_box("Batch",self.d_ims_per_batch),1)
        r1.addWidget(self._field_box("Base LR",self.d_base_lr),2)
        model.body.addLayout(r1)

        r2=QtWidgets.QHBoxLayout()
        r2.setSpacing(10)
        r2.addWidget(self._field_box("Iterations",self.d_max_iter),1)
        r2.addWidget(self._field_box("Workers",self.d_workers),1)
        r2.addWidget(self._field_box("Device",self.d_device_combo),1)
        r2.addWidget(self._field_box("Output",self.d_output_edit),2)
        model.body.addLayout(r2)
        grid=QtWidgets.QGridLayout(); grid.setContentsMargins(0,0,0,0); grid.setSpacing(14); grid.addWidget(env,0,0); grid.addWidget(data,0,1); grid.addWidget(model,1,0,1,2); grid.setColumnStretch(0,1); grid.setColumnStretch(1,1); grid.setRowStretch(2,1)
        outer.addLayout(grid); outer.addStretch(1); return card

    def _build_page_detectron_det(self) -> QtWidgets.QWidget:
        card=self._card(); outer=QtWidgets.QVBoxLayout(card); outer.setContentsMargins(0,4,0,0); outer.setSpacing(0)
        self.voc_images_root=ModernLineEdit("VOC images root"); btn_images=ModernPushButton("Browse","secondary"); btn_images.setMinimumWidth(110); btn_images.clicked.connect(lambda:(lambda dn:self.voc_images_root.setText(dn) if dn else None)(QtWidgets.QFileDialog.getExistingDirectory(self,"VOC Images Root",os.path.expanduser("~"))))
        self.voc_labels_root=ModernLineEdit("VOC XML labels folder"); btn_labels=ModernPushButton("Browse","secondary"); btn_labels.setMinimumWidth(110); btn_labels.clicked.connect(lambda:(lambda dn:self.voc_labels_root.setText(dn) if dn else None)(QtWidgets.QFileDialog.getExistingDirectory(self,"VOC XML Labels Root",os.path.expanduser("~"))))
        self.voc_split_name=ModernLineEdit(); self.voc_split_name.setText("train"); self.voc_classes_edit=ModernLineEdit(); self.voc_classes_edit.setText("chip_mark,cut_piece,out_piece,curling_damage,bs,dent,dr")
        self.d2det_model_combo=DetectronComboBox(); self.d2det_model_combo.addItems(["COCO-Detection/faster_rcnn_R_50_FPN_3x.yaml","COCO-Detection/faster_rcnn_R_101_FPN_3x.yaml","COCO-Detection/faster_rcnn_X_101_32x8d_FPN_3x.yaml"])
        self.d2det_weights_edit=ModernLineEdit("Optional checkpoint"); btn_w=ModernPushButton("Browse","secondary"); btn_w.setMinimumWidth(110); btn_w.clicked.connect(lambda:(lambda fn:self.d2det_weights_edit.setText(fn) if fn else None)(QtWidgets.QFileDialog.getOpenFileName(self,"Select Detectron weights",os.path.expanduser("~"),"PyTorch Weights (*.pth *.pkl);;All Files (*.*)")[0]))
        self.d2det_ims_per_batch=QtWidgets.QSpinBox(); self.d2det_ims_per_batch.setRange(1,64); self.d2det_ims_per_batch.setValue(6); self._style_spinbox(self.d2det_ims_per_batch); self.d2det_ims_per_batch.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.d2det_max_iter=QtWidgets.QSpinBox(); self.d2det_max_iter.setRange(10,100000); self.d2det_max_iter.setValue(3000); self._style_spinbox(self.d2det_max_iter); self.d2det_max_iter.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.d2det_steps_edit=ModernLineEdit("e.g. 2000,2600"); self.d2det_workers=QtWidgets.QSpinBox(); self.d2det_workers.setRange(0,32); self.d2det_workers.setValue(2); self._style_spinbox(self.d2det_workers); self.d2det_workers.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
        self.d2det_device_combo=DetectronComboBox(); self._fill_device_combo(self.d2det_device_combo); self.d2det_output_edit=ModernLineEdit(); self.d2det_output_edit.setText("detectron_det_runs")
        data=SectionFrame("Pascal VOC dataset","Training source and classes"); data.body.addWidget(self._field_box("Images root",self._path_row(self.voc_images_root,btn_images))); data.body.addWidget(self._field_box("XML labels",self._path_row(self.voc_labels_root,btn_labels)))
        rr=QtWidgets.QHBoxLayout(); rr.setSpacing(8); rr.addWidget(self._field_box("Split",self.voc_split_name),1); rr.addWidget(self._field_box("Classes",self.voc_classes_edit),2); data.body.addLayout(rr)
        model=SectionFrame("Model","Faster R-CNN configuration"); model.body.addWidget(self._field_box("Model config",self.d2det_model_combo)); model.body.addWidget(self._field_box("Start weights",self._path_row(self.d2det_weights_edit,btn_w)))
        runtime=SectionFrame("Model & runtime","Training configuration")
        r1=QtWidgets.QHBoxLayout(); r1.setSpacing(8); r1.addWidget(self._field_box("Batch",self.d2det_ims_per_batch),1); r1.addWidget(self._field_box("Iterations",self.d2det_max_iter),1); r1.addWidget(self._field_box("Steps",self.d2det_steps_edit),1); runtime.body.addLayout(r1)
        r2=QtWidgets.QHBoxLayout(); r2.setSpacing(8); r2.addWidget(self._field_box("Workers",self.d2det_workers),1); r2.addWidget(self._field_box("Device",self.d2det_device_combo),1); r2.addWidget(self._field_box("Output",self.d2det_output_edit),2); runtime.body.addLayout(r2)
        grid=QtWidgets.QGridLayout(); grid.setContentsMargins(0,0,0,0); grid.setSpacing(14); grid.addWidget(data,0,0); grid.addWidget(model,0,1); grid.addWidget(runtime,1,0,1,2); grid.setColumnStretch(0,1); grid.setColumnStretch(1,1); outer.addLayout(grid); outer.addStretch(1); return card

    def _summary_item(self, title: str, value: str = "—"):
        box=QtWidgets.QFrame(); box.setObjectName("summaryItem")
        lay=QtWidgets.QVBoxLayout(box); lay.setContentsMargins(0,4,0,4); lay.setSpacing(3)
        t=QtWidgets.QLabel(title.upper()); t.setObjectName("summaryKey")
        v=QtWidgets.QLabel(value); v.setObjectName("summaryValue"); v.setWordWrap(True)
        lay.addWidget(t); lay.addWidget(v); return box,v

    def _build_page_run(self):
        card=self._card(); page=QtWidgets.QHBoxLayout(card); page.setContentsMargins(0,4,0,0); page.setSpacing(14)
        console_frame=QtWidgets.QFrame(); console_frame.setObjectName("consoleFrame"); console_frame.setMinimumHeight(410); console_frame.setMaximumHeight(410)
        cv=QtWidgets.QVBoxLayout(console_frame); cv.setContentsMargins(14,10,14,14); cv.setSpacing(8)
        ch=QtWidgets.QHBoxLayout(); title=QtWidgets.QLabel("TRAINING CONSOLE"); title.setObjectName("consoleTitle"); ready=QtWidgets.QLabel("READY"); ready.setObjectName("readyPill")
        ch.addWidget(title); ch.addStretch(1); ch.addWidget(ready); cv.addLayout(ch)
        self.console=QtWidgets.QPlainTextEdit(); self.console.setObjectName("console"); self.console.setReadOnly(True); self.console.setPlaceholderText("$ Build command to preview the exact training invocation.\n\nOutput will stream here when training starts…")
        cv.addWidget(self.console,1)
        side=QtWidgets.QFrame(); side.setObjectName("reviewSide"); side.setFixedWidth(388); side.setMinimumHeight(410); side.setMaximumHeight(410)
        sv=QtWidgets.QVBoxLayout(side); sv.setContentsMargins(20,18,20,16); sv.setSpacing(8)
        st=QtWidgets.QLabel("Run summary"); st.setObjectName("reviewSideTitle"); sub=QtWidgets.QLabel("Ready to validate"); sub.setObjectName("reviewSideSubtitle"); sv.addWidget(st); sv.addWidget(sub); sv.addSpacing(8)
        mbox,self.review_model_value=self._summary_item("Workflow"); dbox,self.review_dataset_value=self._summary_item("Dataset"); devbox,self.review_device_value=self._summary_item("Device"); obox,self.review_output_value=self._summary_item("Output")
        for box in (mbox,dbox,devbox,obox): sv.addWidget(box)
        sv.addStretch(1)
        self.btn_build=ModernPushButton("Build command","secondary"); self.btn_start=ModernPushButton("Start training","primary"); self.btn_build.clicked.connect(self._on_build); self.btn_start.clicked.connect(self._on_start)
        sv.addWidget(self.btn_build); sv.addWidget(self.btn_start)
        page.addWidget(console_frame,3,QtCore.Qt.AlignTop); page.addWidget(side,1,QtCore.Qt.AlignTop); self.stack.addWidget(card)

    def _refresh_review_summary(self):
        mode_names = {
            "seg": "YOLO Segmentation",
            "det": "YOLO Detection",
            "dseg": "Detectron2 Segmentation",
            "ddet": "Detectron2 Detection",
        }
        self.review_model_value.setText(mode_names.get(self.mode, self.mode))

        dataset_text = "Not selected"
        device_text = "—"
        output_text = "—"
        if self.mode in ("seg", "det"):
            dataset_text = os.path.basename(self.data_edit.text().strip()) if self.data_edit.text().strip() else "Not selected"
            device_text = self.device_combo.currentText() if hasattr(self, "device_combo") else "—"
            output_text = self.project.text().strip() or "runs"
        elif self.mode == "dseg":
            dataset_text = self.d_data_edit.text().strip() or "Not selected"
            device_text = self.d_device_combo.currentText()
            output_text = self.d_output_edit.text().strip() or "detectron_runs"
        elif self.mode == "ddet":
            dataset_text = self.voc_images_root.text().strip() or "Not selected"
            device_text = self.d2det_device_combo.currentText()
            output_text = self.d2det_output_edit.text().strip() or "detectron_det_runs"

        self.review_dataset_value.setText(dataset_text)
        self.review_device_value.setText(device_text)
        self.review_output_value.setText(output_text)

    def _apply_local_qss(self):
        self.setStyleSheet(f"""
            QFrame#trainingWorkspace {{ background:#FFFFFF; border:1px solid #DBE3F0; border-radius:18px; }}
            QLabel#trainingEyebrow {{ color:#61708A; font-size:10px; font-weight:600; }}
            QLabel#trainingPageTitle {{ color:#0E1729; font-size:18px; font-weight:bold; }}
            QLabel#modeBadge {{ background:#ECF2FF; color:#255CED; border:0; border-radius:8px; padding:6px 12px; font-size:11px; font-weight:600; }}
            QFrame#stageBar {{ background:transparent; border:0; }}
            QPushButton#stageButton {{ min-height:40px; padding:0 14px; border:1px solid #C9D6EB; border-radius:9px; background:#FFFFFF; color:#61708A; font-weight:600; font-size:12px; text-align:left; }}
            QPushButton#stageButton:hover {{ background:#F6F9FD; border-color:#9CB7E4; }}
            QPushButton#stageButton[stageState="current"] {{ background:#ECF2FF; color:#255CED; border-color:#255CED; }}
            QPushButton#stageButton[stageState="complete"] {{ background:#E8FAF0; color:#089957; border-color:#ADE5C7; }}
            QStackedWidget#trainingStack {{ background:#FFFFFF; }}
            QFrame#card {{ background:#FFFFFF; border:0; }}
            QFrame#sectionFrame {{ background:#FBFCFF; border:1px solid #DBE3F0; border-radius:14px; }}
            QLabel#sectionTitle {{ color:#0E1729; font-size:13px; font-weight:bold; }}
            QLabel#sectionSubtitle {{ color:#61708A; font-size:11px; }}
            QLabel#sectionMiniLabel {{ color:#61708A; font-size:10px; font-weight:600; }}
            QLabel#sectionBodyStrong {{ color:#0E1729; font-size:13px; font-weight:600; }}
            QLabel#fieldLabel {{ color:#61708A; font-size:11px; font-weight:550; }}
            QLabel#fieldHint {{ color:#61708A; font-size:11px; }}
            QLabel#miniTag {{ background:#ECF2FF; color:#255CED; border:0; border-radius:7px; padding:5px 9px; font-size:10px; font-weight:600; }}
            QLabel#pageLead {{ color:#61708A; font-size:12px; }}
            QSpinBox#modernSpin, QDoubleSpinBox#modernSpin {{ min-height:40px; background:#FFFFFF; border:1px solid #C9D6EB; border-radius:8px; padding:0 10px; color:#0E1729; font-size:12px; }}
            QSpinBox#modernSpin:focus, QDoubleSpinBox#modernSpin:focus {{ border-color:#255CED; }}
            QCheckBox#modernCheck {{ color:#0E1729; font-size:12px; spacing:7px; }}
            QFrame#infoNote {{ background:#ECF2FF; border:0; border-radius:10px; }}
            QLabel#infoNoteIcon {{ color:#255CED; font-size:16px; font-weight:800; }}
            QLabel#infoNoteTitle {{ color:#0E1729; font-size:12px; font-weight:600; }}
            QLabel#infoNoteDetail {{ color:#61708A; font-size:11px; }}
            QFrame#outputHint {{ background:#ECF2FF; border:0; border-radius:10px; }}
            QLabel#outputHintLabel {{ color:#255CED; font-size:10px; font-weight:bold; }}
            QLabel#outputHintValue {{ color:#0E1729; font-size:13px; font-weight:600; }}
            QLabel#outputHintDetail {{ color:#61708A; font-size:11px; }}
            QFrame#weightChoiceCard {{ background:#FBFCFF; border:1px solid #C9D6EB; border-radius:14px; }}
            QFrame#weightChoiceCard:hover {{ border-color:#8CAFF0; background:#F8FAFF; }}
            QFrame#weightChoiceCard[selected="true"] {{ background:#ECF2FF; border:1px solid #255CED; }}
            QLabel#weightIcon {{ background:#F2EDFF; color:#6B40E5; border-radius:12px; font-size:13px; font-weight:bold; }}
            QFrame#weightChoiceCard[selected="true"] QLabel#weightIcon {{ background:#255CED; color:#FFFFFF; }}
            QLabel#weightTitle {{ color:#0E1729; font-size:16px; font-weight:bold; }}
            QLabel#weightSubtitle, QLabel#weightNote, QLabel#weightFileStatus {{ color:#61708A; font-size:11px; }}
            QLabel#selectedPill {{ background:#FFFFFF; color:#255CED; border-radius:7px; padding:5px 10px; font-size:10px; font-weight:bold; }}
            QFrame#cardDivider {{ background:#DBE3F0; border:0; }}
            QFrame#consoleFrame {{ background:#060B16; border:0; border-radius:14px; }}
            QLabel#consoleTitle {{ color:#8CA8D1; font-size:10px; font-weight:600; }}
            QLabel#readyPill {{ background:#0F3329; color:#5CEB9C; border-radius:8px; padding:6px 12px; font-size:11px; font-weight:600; }}
            QPlainTextEdit#console {{ background:#060B16; border:0; color:#ADC7E5; font-family:Consolas,'Cascadia Code',monospace; font-size:12px; padding:0; selection-background-color:#255CED; }}
            QWidget#stageActionBar {{ background:transparent; border:0; min-height:40px; }}
            QFrame#reviewSide {{ background:#FBFCFF; border:1px solid #DBE3F0; border-radius:14px; }}
            QLabel#reviewSideTitle {{ color:#0E1729; font-size:13px; font-weight:bold; }}
            QLabel#reviewSideSubtitle {{ color:#61708A; font-size:11px; }}
            QFrame#summaryItem {{ background:transparent; border:0; }}
            QLabel#summaryKey {{ color:#61708A; font-size:10px; font-weight:600; }}
            QLabel#summaryValue {{ color:#0E1729; font-size:13px; font-weight:550; }}
        """)

    def _wrap(self, layout: QtWidgets.QLayout) -> QtWidgets.QWidget:
        w = QtWidgets.QWidget(); w.setLayout(layout); return w

    def _browse_data_yaml(self):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select data.yaml", os.path.expanduser("~"), "YAML Files (*.yaml *.yml)")
        if fn: self.data_edit.setText(fn)

    def _browse_path(self, editor: QtWidgets.QLineEdit):
        fn, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select weights (.pt)", os.path.expanduser("~"), "PyTorch Weights (*.pt)")
        if fn: editor.setText(fn)

    def _update_states(self):
        if hasattr(self,'seg_path_edit'):
            self.seg_path_edit.setEnabled(self.seg_custom_rb.isChecked())
        if hasattr(self,'det_path_edit'):
            self.det_path_edit.setEnabled(self.det_custom_rb.isChecked())
        self._sync_weight_cards() if hasattr(self,'seg_default_card') else None

    def _populate_device_combo(self):
        import subprocess
        opts = ["cpu"]
        cuda_ok = False; gpu_names = []
        try:
            import torch
            try:
                if torch.cuda.is_available():
                    cuda_ok = True
                    n = torch.cuda.device_count()
                    opts.append("cuda")
                    for i in range(n):
                        opts.append(f"cuda:{i}")
                        try:
                            gpu_names.append(torch.cuda.get_device_name(i))
                        except Exception:
                            gpu_names.append(f"GPU {i}")
            except Exception:
                pass
        except ImportError:
            pass
        if not cuda_ok and shutil.which("nvidia-smi"):
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip()
                if out:
                    gpu_names = [ln.strip() for ln in out.splitlines() if ln.strip()]
            except Exception:
                pass
        self.device_combo.clear(); self.device_combo.addItems(opts)
        if cuda_ok:
            self.device_combo.setToolTip("CUDA available: " + ", ".join(gpu_names))
            self.device_combo.setCurrentText("cuda")
        else:
            tip = "No CUDA available. "
            if gpu_names:
                tip += "NVIDIA driver detected: " + ", ".join(gpu_names) + ". Install CUDA-enabled PyTorch."
            else:
                tip += "No NVIDIA GPU/driver detected or PyTorch not installed."
            self.device_combo.setToolTip(tip)

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

    def _on_build(self):
        try:
            info, cmds = self.build_commands()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Build error", str(e)); return
        self.console.appendPlainText("\n=== Built Command(s) ===")
        self.console.appendPlainText(info)
        for program, args in cmds:
            self.console.appendPlainText(self._fmt_cmd(program, args))
        self.nav.setCurrentIndex(4)

    def _on_start(self):
        try:
            info, cmds = self.build_commands()
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Cannot start", str(e)); return
        dev_txt = getattr(self, "device_combo", None)
        self.console.appendPlainText(f"\n=== Starting Training ({(dev_txt.currentText() if dev_txt else 'cpu').upper()}) ===")
        self.console.appendPlainText(info)
        for program, args in cmds:
            self.console.appendPlainText(self._fmt_cmd(program, args))
        self.nav.setCurrentIndex(4)
        try:
            self._overall_start = datetime.now()
            self.console.appendPlainText(f"[benchmark] Overall start: {self._overall_start.isoformat()}")
        except Exception:
            self._overall_start = None
        self._run_commands_sequential(cmds)

    def _pipe(self, data: QtCore.QByteArray):
        try:
            text = bytes(data).decode("utf-8", errors="ignore")
            if text:
                self.console.appendPlainText(text.rstrip())
            vsb = self.console.verticalScrollBar()
            if vsb: vsb.setValue(vsb.maximum())
        except Exception:
            pass

    def _run_commands_sequential(self, commands: list):
        if hasattr(self, "btn_start"): self.btn_start.setEnabled(False)
        if hasattr(self, "btn_build"): self.btn_build.setEnabled(False)
        self._proc = QtCore.QProcess(self)
        self._proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self._proc.readyRead.connect(lambda: self._pipe(self._proc.readAll()))
        self._proc.finished.connect(self._next_or_done)
        self._cmds = commands; self._idx = -1
        self._next_or_done()

    def _next_or_done(self):
        self._idx += 1
        if self._idx >= len(self._cmds):
            try:
                overall_end = datetime.now()
                if getattr(self, "_overall_start", None):
                    total = overall_end - self._overall_start
                    self.console.appendPlainText(f"\n=== All trainings finished ===")
                    self.console.appendPlainText(f"[benchmark] Overall end: {overall_end.isoformat()} — total duration {self._format_td(total)}")
                else:
                    self.console.appendPlainText("\n=== All trainings finished ===")
                    self.console.appendPlainText(f"[benchmark] Overall end: {overall_end.isoformat()}")
            except Exception:
                self.console.appendPlainText("\n=== All trainings finished ===")
            if hasattr(self, "btn_start"): self.btn_start.setEnabled(True)
            if hasattr(self, "btn_build"): self.btn_build.setEnabled(True)
            return

        program, args = self._cmds[self._idx]
        self.console.appendPlainText(f"\n[Running {self._idx+1}/{len(self._cmds)}] -> {program} " + " ".join(args))
        self._proc.start(program, args)

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


# ================================== MAIN WINDOW =============================================

class TrainingWindow(QtWidgets.QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Training Studio"); self.resize(1600,900); self.setMinimumSize(1120,720)
        central=QtWidgets.QWidget(); central.setObjectName("centralWidget")
        root=QtWidgets.QHBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)

        sidebar=QtWidgets.QWidget(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(218)
        sl=QtWidgets.QVBoxLayout(sidebar); sl.setContentsMargins(0,0,0,0); sl.setSpacing(0)
        sh=QtWidgets.QWidget(); sh.setObjectName("sidebarHeader"); shl=QtWidgets.QVBoxLayout(sh); shl.setContentsMargins(24,26,24,14); shl.setSpacing(3)
        eye=QtWidgets.QLabel("TRAINING STUDIO"); eye.setObjectName("sideEyebrow"); logo=QtWidgets.QLabel("Model training"); logo.setObjectName("logo"); shl.addWidget(eye); shl.addWidget(logo); sl.addWidget(sh)
        workflow_label=QtWidgets.QLabel("WORKFLOW"); workflow_label.setObjectName("workflowLabel"); workflow_label.setContentsMargins(24,12,0,4); sl.addWidget(workflow_label)
        steps=QtWidgets.QWidget(); self.steps_layout=QtWidgets.QVBoxLayout(steps); self.steps_layout.setContentsMargins(10,0,10,0); self.steps_layout.setSpacing(6); self.step_indicators=[]
        for i,t in enumerate(["Select model","Configure & run"]):
            ind=StepIndicator(i+1,t); self.step_indicators.append(ind); self.steps_layout.addWidget(ind)
        sl.addWidget(steps); sl.addStretch(1)
        utility=QtWidgets.QWidget(); ul=QtWidgets.QVBoxLayout(utility); ul.setContentsMargins(24,10,28,18); self.btn_dashboard_side=ModernPushButton("Runs dashboard","secondary"); self.btn_dashboard_side.clicked.connect(self._open_dashboard); ul.addWidget(self.btn_dashboard_side); sl.addWidget(utility)
        root.addWidget(sidebar)

        main=QtWidgets.QWidget(); main.setObjectName("mainContainer"); ml=QtWidgets.QVBoxLayout(main); ml.setContentsMargins(0,0,0,0); ml.setSpacing(0)
        top=QtWidgets.QWidget(); top.setObjectName("topBar"); top.setFixedHeight(74); tl=QtWidgets.QHBoxLayout(top); tl.setContentsMargins(34,12,22,10); tl.setSpacing(10)
        tcol=QtWidgets.QVBoxLayout(); tcol.setSpacing(2); top_title=QtWidgets.QLabel("Training Studio"); top_title.setObjectName("topTitle"); self.header_context=QtWidgets.QLabel("Choose a model workflow"); self.header_context.setObjectName("pageHeaderSubtitle"); tcol.addWidget(top_title); tcol.addWidget(self.header_context); tl.addLayout(tcol); tl.addStretch(1)
        self.btn_help=QtWidgets.QToolButton()
        self.btn_help.setObjectName("helpButton")
        self.btn_help.setText("?")
        self.btn_help.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        self.btn_help.setAutoRaise(False)
        self.btn_help.setToolTip("Training help (F1)")
        self.btn_help.setFixedSize(30,30)
        self.btn_help.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.btn_help.clicked.connect(self._show_help)
        QtWidgets.QShortcut(QtGui.QKeySequence.HelpContents,self,activated=self._show_help)
        tl.addWidget(self.btn_help,0,QtCore.Qt.AlignTop)
        ml.addWidget(top)
        self.stack=QtWidgets.QStackedWidget(); self.stack.setObjectName("contentStack"); self.step_model=StepModel(); self.step_train=StepTrain(mode="seg"); self.step_model.card_selected.connect(self._on_model_card_selected); self.step_train.request_model_page.connect(self._return_to_model); self.stack.addWidget(self.step_model); self.stack.addWidget(self.step_train); ml.addWidget(self.stack,1)
        nav=QtWidgets.QWidget(); nav.setObjectName("navBar"); nav.setFixedHeight(54); self.nav_bar=nav
        # Match the Figma footer position more closely: keep the same footer height,
        # but raise the action row slightly from the application edge.
        nl=QtWidgets.QHBoxLayout(nav); nl.setContentsMargins(28,0,28,14); nl.setSpacing(8); nl.addStretch(1)
        self.btn_back=ModernPushButton("← Back","secondary"); self.btn_back.setMinimumWidth(90); self.btn_next=ModernPushButton("Continue →","primary"); self.btn_next.setMinimumWidth(140); self.btn_back.clicked.connect(self._go_back); self.btn_next.clicked.connect(self._go_next); nl.addWidget(self.btn_back); nl.addWidget(self.btn_next); ml.addWidget(nav)
        root.addWidget(main,1)
        rf=QtWidgets.QFrame(); rf.setObjectName("trainingRoot"); wrap=QtWidgets.QVBoxLayout(rf); wrap.setContentsMargins(0,0,0,0); wrap.setSpacing(0); wrap.addWidget(central); rf.setAttribute(QtCore.Qt.WA_StyledBackground,True); self.setCentralWidget(rf)
        self._apply_qss(); self._apply_direct_shell_styles(); self._update_nav(); self._dash_httpd=None
        QtCore.QTimer.singleShot(0, self._apply_direct_shell_styles)

    def _apply_direct_shell_styles(self):
        """Apply all shell styles directly so host application QSS cannot override them."""
        fam = _preferred_ui_font()
        cw = self.centralWidget()
        if cw:
            cw.setStyleSheet('QFrame#trainingRoot{background:#F6F9FD;border:0;}')
            cw.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        central = cw.findChild(QtWidgets.QWidget, "centralWidget") if cw else None
        if central:
            central.setStyleSheet('QWidget#centralWidget{background:#F6F9FD;border:0;}')
            central.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        sidebar = self.findChild(QtWidgets.QWidget, "sidebar")
        if sidebar:
            sidebar.setStyleSheet('QWidget#sidebar{background:#FFFFFF;border-right:1px solid #DBE3F0;}')
            sidebar.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        sh = self.findChild(QtWidgets.QWidget, "sidebarHeader")
        if sh:
            sh.setStyleSheet('QWidget#sidebarHeader{background:#FFFFFF;border:0;}')
            sh.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        main = self.findChild(QtWidgets.QWidget, "mainContainer")
        if main:
            main.setStyleSheet('QWidget#mainContainer{background:#F6F9FD;border:0;}')
            main.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        top = self.findChild(QtWidgets.QWidget, "topBar")
        if top:
            top.setStyleSheet('QWidget#topBar{background:#F6F9FD;border:0;}')
            top.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        nav = self.findChild(QtWidgets.QWidget, "navBar")
        if nav:
            nav.setStyleSheet('QWidget#navBar{background:#F6F9FD;border:0;}')
            nav.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        stack = self.findChild(QtWidgets.QStackedWidget, "contentStack")
        if stack:
            stack.setStyleSheet('QStackedWidget#contentStack{background:#F6F9FD;border:0;}')

        if hasattr(self, "btn_help") and self.btn_help:
            self.btn_help.setStyleSheet(
                f'QToolButton#helpButton{{font-family:"{fam}";background:#ECF2FF;color:#255CED;'
                'border:0;border-radius:15px;font-size:14px;font-weight:700;padding:0;}'
                'QToolButton#helpButton:hover{background:#DDE8FF;color:#174FD2;}'
                'QToolButton#helpButton:pressed{background:#CEDDFF;}'
            )
            self.btn_help.show()

        shell_styles = {
            "sideEyebrow": f'QLabel#sideEyebrow{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;font-weight:600;}}',
            "logo": f'QLabel#logo{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:18px;font-weight:700;}}',
            "workflowLabel": f'QLabel#workflowLabel{{font-family:"{fam}";background:transparent;color:#61708A;font-size:10px;font-weight:600;}}',
            "topTitle": f'QLabel#topTitle{{font-family:"{fam}";background:transparent;color:#0E1729;font-size:19px;font-weight:700;}}',
            "pageHeaderSubtitle": f'QLabel#pageHeaderSubtitle{{font-family:"{fam}";background:transparent;color:#61708A;font-size:11px;font-weight:400;}}',
            "localPill": f'QLabel#localPill{{font-family:"{fam}";background:#FFFFFF;color:#0E1729;border:0;border-radius:8px;padding:6px 12px;font-size:11px;font-weight:600;}}',
        }
        for name, style in shell_styles.items():
            w = self.findChild(QtWidgets.QLabel, name)
            if w:
                w.setStyleSheet(style)
                w.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        _apply_direct_named_styles(self.step_model)
        _apply_direct_named_styles(self.step_train)
        self.step_model._update_card_styles()
        try:
            self.step_train._sync_weight_cards()
        except Exception:
            pass

    def _open_dashboard(self):
        api_url, self._dash_httpd = start_dashboard_server(DEFAULT_RUNS_DIR)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(f"{api_url}/ui?theme=dark"))

    def _on_model_card_selected(self, mode: str):
        self.step_train.set_mode(mode)

    def _return_to_model(self):
        self.stack.setCurrentIndex(0)
        self._update_nav()

    def current_step(self) -> int:
        return self.stack.currentIndex()

    def _go_back(self):
        if self.current_step() > 0:
            self.stack.setCurrentIndex(self.current_step()-1)
            self._update_nav()

    def _go_next(self):
        i = self.current_step()
        if i == 0:
            self.step_train.set_mode(self.step_model.value())
            self.stack.setCurrentIndex(1)
        else:
            self._restart_soft()
        self._update_nav()

    def _update_nav(self):
        i=self.current_step()
        for idx,indicator in enumerate(self.step_indicators): indicator.set_active(idx==i); indicator.set_complete(idx<i)
        if i==0:
            self.btn_back.hide(); self.btn_next.show(); self.btn_next.setText("Continue →"); self.header_context.setText("Choose a model workflow")
            self._apply_direct_shell_styles()
        else:
            # Keep the footer spacer for the approved 1600×900 proportions, but stage navigation
            # itself lives inside the white training canvas.
            self.btn_back.hide(); self.btn_next.hide(); self.header_context.setText("Configure & run training")

    def _restart_soft(self):
        try:
            self.step_model._cards[0][1].setChecked(True)
            self.step_model._update_card_styles()
            self.step_train.seg_default_rb.setChecked(True)
            self.step_train.det_default_rb.setChecked(True)
            self.step_train.data_edit.clear()
            self.step_train.console.clear()
        except Exception:
            pass
        self.stack.setCurrentIndex(0)
        self._update_nav()
        QtWidgets.QMessageBox.information(self, "Training", "Training session reset.")

    def _show_help(self):
        SimpleHelpDialog(self).exec_()

    def _apply_qss(self):
        self.setStyleSheet(f"""
            * {{ font-family:{FONTS['family']}; font-size:12px; }}
            QLabel {{ background:transparent; }}
            #trainingRoot, QWidget#mainContainer, QStackedWidget#contentStack {{ background:#F6F9FD; }}
            QWidget#sidebar {{ background:#FFFFFF; border-right:1px solid #DBE3F0; }}
            QWidget#sidebarHeader {{ background:#FFFFFF; border:0; }}
            QLabel#sideEyebrow {{ color:#61708A; font-size:11px; font-weight:600; }}
            QLabel#logo {{ color:#0E1729; font-size:18px; font-weight:bold; }}
            QLabel#workflowLabel {{ color:#61708A; font-size:10px; font-weight:600; }}
            QWidget#topBar {{ background:#F6F9FD; border:0; }}
            QLabel#topTitle {{ color:#0E1729; font-size:19px; font-weight:bold; }}
            QLabel#pageHeaderSubtitle {{ color:#61708A; font-size:11px; }}
            QLabel#localPill {{ background:#FFFFFF; color:#0E1729; border-radius:8px; padding:6px 12px; font-size:11px; font-weight:600; }}
            QToolButton#helpButton {{ background:#ECF2FF; color:#255CED; border:0; border-radius:15px; font-size:14px; font-weight:bold; }}
            QToolButton#helpButton:hover {{ background:#DDE8FF; color:#174FD2; }}
            QFrame#modelWorkspace {{ background:#FFFFFF; border:1px solid #DBE3F0; border-radius:18px; }}
            QLabel#modelEyebrow {{ color:#61708A; font-size:10px; font-weight:600; }}
            QLabel#pageTitle {{ color:#0E1729; font-size:22px; font-weight:bold; }}
            QLabel#pageSubtitle {{ color:#61708A; font-size:12px; }}
            QLabel#heroBadge {{ background:#F6F9FD; color:#61708A; border-radius:8px; padding:6px 12px; font-size:11px; font-weight:600; }}
            QFrame#modeCard {{ background:#FFFFFF; border:1px solid #DBE3F0; border-radius:14px; }}
            QFrame#modeCard:hover {{ border-color:#AFC4E8; background:#FEFFFF; }}
            QFrame#modeCard[selected="true"] {{ background:#ECF2FF; border:1px solid #255CED; }}
            QFrame#cardAccent {{ background:#255CED; border:0; border-top-left-radius:3px; border-bottom-left-radius:3px; }}
            QFrame#modeCard[family="detectron"] QFrame#cardAccent {{ background:#6B40E5; }}
            QWidget#modeCardContent {{ background:transparent; }}
            QLabel#frameworkIcon {{ background:#ECF2FF; color:#255CED; border-radius:12px; font-size:15px; font-weight:bold; }}
            QFrame#modeCard[family="detectron"] QLabel#frameworkIcon {{ background:#F2EDFF; color:#6B40E5; }}
            QFrame#modeCard[selected="true"] QLabel#frameworkIcon {{ background:#255CED; color:#FFFFFF; }}
            QLabel#cardTitle {{ color:#0E1729; font-size:16px; font-weight:bold; }}
            QLabel#modelTask {{ background:#ECF2FF; color:#255CED; border-radius:7px; padding:5px 10px; font-size:10px; font-weight:600; }}
            QFrame#modeCard[family="detectron"] QLabel#modelTask {{ background:#F2EDFF; color:#6B40E5; }}
            QLabel#cardDescription {{ color:#61708A; font-size:12px; }}
            QFrame#cardDivider {{ background:#DBE3F0; border:0; }}
            QLabel#engineLabel {{ color:#61708A; font-size:11px; }}
            QLabel#cardAction {{ color:#0E1729; font-size:12px; font-weight:600; }}
            QFrame#modeCard[selected="true"] QLabel#cardAction {{ color:#255CED; }}
            QLabel#motionSpec {{ color:#61708A; font-size:10px; }}
            QWidget#navBar {{ background:#F6F9FD; border:0; }}
        """)

        # IMPORTANT FOR EMBEDDED USE:
        # The main application loads this training window inside its own page.
        # If only the QMainWindow owns the stylesheet, the styling is lost when
        # the central widget is re-parented into the host application.
        #
        # Apply the exact same stylesheet directly to the embedded root and the
        # model-selection page so the Figma styling survives re-parenting.
        qss = self.styleSheet()
        embedded_root = self.centralWidget()
        if embedded_root is not None:
            embedded_root.setStyleSheet(qss)

            inner_shell = embedded_root.findChild(QtWidgets.QWidget, "centralWidget")
            if inner_shell is not None:
                inner_shell.setStyleSheet(qss)

        # StepModel has no independent stylesheet of its own, so keep the Figma
        # card/workspace styling local to the page as well. This prevents a host
        # application stylesheet from flattening the model cards.
        self.step_model.setStyleSheet(qss)

        # Re-polish the model cards now that the embedded stylesheet is active.
        for card, _, _ in self.step_model._cards:
            card.style().unpolish(card)
            card.style().polish(card)
            card.update()
        self.step_model._update_card_styles()


# ================================== ENTRYPOINT


# ================================== ENTRYPOINT ==============================================
def main():
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)
    win = TrainingWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()