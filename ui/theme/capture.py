"""White industrial design system for the camera acquisition workflow."""
from PyQt5 import QtGui

CAPTURE_STYLESHEET = """
* { font-family:'Segoe UI',Arial,sans-serif; font-size:12px; }
QWidget { background:#f5f7fb; color:#0f172a; }
QLabel { background:transparent; }
QWidget#sidebar { background:#fff; border-right:1px solid #d8e2f0; }
QWidget#mainContainer,QStackedWidget#contentStack { background:#f5f7fb; }
QWidget#topBar { background:#fff; border-bottom:1px solid #d8e2f0; }
QWidget#navBar { background:#fff; border-top:1px solid #d8e2f0; }
QWidget#sidebarSeparator { background:#d8e2f0; min-width:1px; max-width:1px; }
QLabel#pageTitle,QLabel#modeTitle { color:#0f172a; font-size:22px; font-weight:800; }
QLabel#pageSubtitle { color:#64748b; font-size:11px; }
QLabel#stepTitle { color:#475569; font-weight:600; }
QLabel#simulationBadge { color:#8a4b08; background:#fff7e6; border:1px solid #f3cf8a;
 border-radius:9px; padding:4px 10px; font-size:10px; font-weight:750; }
QLabel#deviceCount { color:#64748b; }
QLabel#sectionLabel { color:#2563eb; font-size:10px; font-weight:750; }
QLabel#formLabel { color:#334155; font-weight:600; }
QLabel#infoLabel { color:#475569; font-size:11px; padding:10px; background:#f8fafc; border:1px solid #d8e2f0; border-radius:8px; }
QWidget#modeCard,QWidget#formContainer,QWidget#progressContainer,QWidget#previewCard,QFrame#helpCard { background:#fff; border:1px solid #d5dfed; border-radius:12px; }
QWidget#modeCard:hover,QWidget#previewCard:hover { border-color:#8eb2fb; background:#fbfdff; }
QLabel#cardTitle { color:#0f172a; font-size:16px; font-weight:700; }
QLabel#cardDesc { color:#64748b; font-size:11px; }
QLabel#modeCheck { color:#fff; background:#2868e8; border-radius:12px; font-weight:800; }
QLabel#folderStatus[ready="true"] { color:#087f5b; font-weight:650; padding-top:8px; }
QLabel#folderStatus[ready="false"] { color:#dc2626; font-weight:650; padding-top:8px; }
QLabel#captureSummary,QLabel#previewSummary { color:#334155; font-weight:650; }
QLabel#previewInfo { color:#475569; background:#fff; border:1px solid #d5dfed; border-radius:7px; padding:7px 10px; font-family:Consolas,'Courier New'; font-size:10px; }
QLabel#fullImageTitle { color:#0f172a; font-size:14px; font-weight:700; }
QRadioButton,QCheckBox { color:#334155; background:transparent; }
QRadioButton::indicator { width:17px; height:17px; border-radius:9px; border:1px solid #94a3b8; background:#fff; }
QRadioButton::indicator:checked { background:#2868e8; border:4px solid #dce8ff; }
QCheckBox::indicator { width:16px; height:16px; border:1px solid #94a3b8; background:#fff; border-radius:4px; }
QCheckBox::indicator:checked { background:#2868e8; border-color:#2868e8; }
QListWidget#deviceList { background:#fff; border:1px solid #d5dfed; border-radius:12px; padding:8px; }
QListWidget#deviceList::item { background:#fff; color:#334155; border:1px solid #e2e8f0; border-radius:8px; padding:14px; margin:3px; }
QListWidget#deviceList::item:hover { background:#f1f5ff; border-color:#b7cdfb; }
QListWidget#deviceList::item:selected { background:#eaf1ff; color:#1d4ed8; border-color:#7da6fa; }
QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox { background:#fff; color:#0f172a; border:1px solid #c5d2e5; border-radius:8px; padding:8px 10px; selection-background-color:#dce8ff; }
QLineEdit:focus,QSpinBox:focus,QDoubleSpinBox:focus,QComboBox:focus { border-color:#2868e8; }
QLineEdit:disabled,QSpinBox:disabled,QComboBox:disabled { background:#eef2f7; color:#94a3b8; }
QComboBox QAbstractItemView { background:#fff; color:#0f172a; border:1px solid #c5d2e5; selection-background-color:#eaf1ff; selection-color:#1d4ed8; outline:0; }
QProgressBar#modernProgress { background:#eef2f7; color:#334155; border:1px solid #d8e2f0; border-radius:10px; text-align:center; font-weight:650; }
QProgressBar#modernProgress::chunk { background:#2868e8; border-radius:9px; }
QPlainTextEdit#captureLog { background:#0f172a; color:#dbeafe; border:1px solid #24324a; border-radius:9px; padding:10px; font-family:Consolas,'Courier New'; font-size:11px; }
QLabel#previewCamera { color:#2563eb; font-weight:700; }
QLabel#previewFilename { color:#64748b; font-size:10px; font-family:Consolas; }
QPushButton { min-height:34px; border-radius:8px; padding:0 16px; font-weight:650; }
QPushButton#primaryButton,QPushButton#primaryNavButton { background:#2868e8; color:#fff; border:1px solid #2868e8; }
QPushButton#primaryButton:hover,QPushButton#primaryNavButton:hover { background:#1d57ca; }
QPushButton#secondaryButton,QPushButton#navButton { background:#fff; color:#2563eb; border:1px solid #b7cdfb; }
QPushButton#secondaryButton:hover,QPushButton#navButton:hover { background:#eef4ff; }
QPushButton#dangerButton { background:#fff; color:#dc2626; border:1px solid #f5a3a8; }
QPushButton#dangerButton:hover { background:#fff1f2; }
QPushButton:disabled { background:#edf2f7; color:#94a3b8; border-color:#d8e2f0; }
QToolButton#helpButton { background:#eaf1ff; color:#2563eb; border:1px solid #c9dafc; border-radius:17px; }
QToolButton#helpButton:hover { background:#dce8ff; }
QTextBrowser#helpText { background:#fff; color:#334155; border:none; }
QScrollArea { border:none; background:transparent; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollArea#fullImageScroll { background:#101827; border:1px solid #24324a; border-radius:8px; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:#cbd5e1; min-height:30px; border-radius:5px; }
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical { height:0; }
"""

def apply_light_application_palette(app):
    app.setStyle("Fusion")
    p = QtGui.QPalette()
    for role, color in ((p.Window,"#f5f7fb"),(p.Base,"#fff"),(p.AlternateBase,"#f8fafc"),
                        (p.Text,"#0f172a"),(p.WindowText,"#0f172a"),(p.Button,"#fff"),
                        (p.ButtonText,"#0f172a"),(p.Highlight,"#eaf1ff"),(p.HighlightedText,"#1d4ed8")):
        p.setColor(role, QtGui.QColor(color))
    app.setPalette(p)
