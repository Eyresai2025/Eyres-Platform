"""Light styling for the annotation workspace and its dialogs."""

ANNOTATION_QSS = r"""
QWidget#annotationWorkspace { background:#F6F8FC; color:#0F172A; }
QWidget#annotationCommandBar { background:#FFFFFF; border-bottom:1px solid #D8E2F0; }
QWidget#annotationCanvasPanel { background:#F6F8FC; }
QFrame#toolbarSeparator { background:#D8E2F0; border:0; }
QLabel#toolbarLabel { color:#64748B; font-size:10px; font-weight:700; padding:0 1px; }
QLabel#currentFileLabel { color:#334155; font-size:11px; font-weight:700; padding:2px 4px; }
QGroupBox { background:#FFFFFF; border:1px solid #D8E2F0; border-radius:10px; margin-top:10px; padding:12px 9px 9px; color:#334155; font-size:11px; font-weight:700; }
QGroupBox::title { subcontrol-origin:margin; left:10px; padding:0 5px; }
QLabel { background:transparent; color:#334155; }
QLabel#annotationStatus { color:#047857; background:#ECFDF5; border:1px solid #A7F3D0; border-radius:16px; padding:6px 10px; font-size:10px; font-weight:700; }
QPushButton { min-height:30px; background:#FFFFFF; color:#155EEF; border:1px solid #B9D0FF; border-radius:7px; padding:3px 8px; font-size:11px; font-weight:600; }
QPushButton:hover { background:#EFF5FF; border-color:#6EA0FF; }
QPushButton:pressed { background:#E1ECFF; }
QPushButton#primaryAction { background:#286BE8; color:#FFFFFF; border-color:#286BE8; }
QPushButton#primaryAction:hover { background:#155EEF; }
QPushButton#helpAction { min-width:36px; max-width:36px; min-height:36px; max-height:36px; border-radius:18px; background:#E8F0FF; color:#155EEF; font-size:16px; font-weight:800; }
QPushButton#toolbarAction, QPushButton#toolbarDanger, QPushButton#toolbarWarning, QPushButton#toolbarPrimary {
    min-height:32px; max-height:32px; margin:0; padding:1px 8px;
    background:#FFFFFF; color:#155EEF; border:1px solid #C5D7F8;
    border-radius:7px; font-size:10px; font-weight:700;
}
QPushButton#toolbarAction:hover { background:#EFF5FF; border-color:#7BA7F7; }
QPushButton#toolbarPrimary { background:#286BE8; color:#FFFFFF; border-color:#286BE8; }
QPushButton#toolbarPrimary:hover { background:#155EEF; border-color:#155EEF; }
QPushButton#toolbarDanger { color:#C81E3A; border-color:#F2BEC8; }
QPushButton#toolbarDanger:hover { background:#FFF1F3; border-color:#E85D75; }
QPushButton#toolbarWarning { color:#9A5B00; border-color:#F1D39A; }
QPushButton#toolbarWarning:hover { background:#FFF8E8; border-color:#D9A441; }
QComboBox#toolbarCombo, QLineEdit#toolbarInput { min-height:32px; max-height:32px; margin:0; padding:1px 8px; }
QComboBox#activeTool { min-height:32px; max-height:32px; margin:0; padding:1px 8px; background:#286BE8; color:#FFFFFF; border:1px solid #286BE8; border-radius:7px; font-weight:700; }
QComboBox#activeTool::drop-down { border:0; width:24px; }
QComboBox#activeTool QAbstractItemView { background:#FFFFFF; color:#0F172A; selection-background-color:#E8F0FF; selection-color:#155EEF; }
QPushButton:disabled { background:#F1F5F9; color:#A8B4C5; border-color:#E2E8F0; }
QPushButton#dangerAction { color:#C81E3A; border-color:#F4B4C0; }
QPushButton#dangerAction:hover { background:#FFF1F3; border-color:#E85D75; }
QLineEdit, QComboBox { min-height:30px; background:#FFFFFF; color:#0F172A; border:1px solid #C8D6EA; border-radius:7px; padding:2px 8px; selection-background-color:#286BE8; selection-color:#FFFFFF; }
QLineEdit:focus, QComboBox:focus { border:1px solid #286BE8; }
QComboBox QAbstractItemView { background:#FFFFFF; color:#0F172A; border:1px solid #C8D6EA; selection-background-color:#E8F0FF; selection-color:#155EEF; outline:0; }
QListWidget#annotationThumbnails { background:#FFFFFF; color:#334155; border:1px solid #D8E2F0; border-radius:10px; padding:6px; outline:0; }
QListWidget#annotationThumbnails::item { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:7px; margin:3px; padding:5px; color:#475569; }
QListWidget#annotationThumbnails::item:selected { background:#E8F0FF; border:2px solid #286BE8; color:#155EEF; }
QScrollBar:vertical { background:#F1F5F9; width:8px; margin:0; }
QScrollBar::handle:vertical { background:#B8C6D9; border-radius:4px; min-height:28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar:horizontal { background:#F1F5F9; height:8px; margin:0; }
QScrollBar::handle:horizontal { background:#B8C6D9; border-radius:4px; min-width:28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width:0; }
"""

DIALOG_QSS = r"""
QDialog { background:#F6F8FC; color:#0F172A; }
QLabel { color:#334155; background:transparent; }
QLabel#dialogTitle { color:#0F172A; font-size:16px; font-weight:800; }
QLabel#dialogSummary { color:#155EEF; background:#E8F0FF; border-radius:7px; padding:8px; font-weight:700; }
QLineEdit, QListWidget { background:#FFFFFF; color:#0F172A; border:1px solid #C8D6EA; border-radius:7px; padding:6px; selection-background-color:#286BE8; selection-color:#FFFFFF; }
QListWidget::item { min-height:34px; border-bottom:1px solid #EEF2F7; padding:4px; }
QListWidget::item:selected { background:#E8F0FF; color:#155EEF; }
QPushButton { min-height:34px; background:#FFFFFF; color:#155EEF; border:1px solid #B9D0FF; border-radius:7px; padding:4px 12px; font-weight:700; }
QPushButton:hover { background:#EFF5FF; }
QPushButton#primaryAction { background:#286BE8; color:#FFFFFF; border-color:#286BE8; }
"""
