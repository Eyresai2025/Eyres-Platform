"""Professional white EyRes.AI Qt stylesheet."""


def application_stylesheet() -> str:
    return """
    * { font-family:'Segoe UI'; font-size:13px; color:#172033; }
    QWidget { background:transparent; }
    QMainWindow, QDialog { background:#F6F8FC; }
    QWidget[eyresLightSurface="true"] { background:#F6F8FC; }
    QLabel { background:transparent; }
    QFrame#Sidebar { background:#FFFFFF; border-right:1px solid #DDE5F0; }
    QStackedWidget { background:#F6F8FC; }
    QWidget#login_card {
        background:#FFFFFF; border:1px solid #DDE5F0; border-radius:18px;
    }
    QWidget#header_box, QWidget#fields_container { background:transparent; }
    QLabel#PageTitle { color:#172033; font-size:24px; font-weight:700; }
    QLabel#PageSubtitle { color:#64748B; font-size:12px; }
    QFrame#stat_card, QFrame#UserChip {
        background:#FFFFFF; border:1px solid #DDE5F0; border-radius:14px;
    }
    QFrame#stat_card:hover { border:1px solid #AFC7F7; background:#FCFDFF; }
    QFrame#UserChip { min-height:42px; }
    QGroupBox {
        background:#FFFFFF; border:1px solid #DDE5F0; border-radius:12px;
        margin-top:14px; padding:14px;
    }
    QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; font-weight:600; }
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit,
    QListWidget, QTreeWidget {
        background:#FFFFFF; color:#172033; border:1px solid #CBD6E4;
        border-radius:8px; padding:8px; selection-background-color:#2868E8;
        selection-color:#FFFFFF;
    }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QTextEdit:focus, QPlainTextEdit:focus { border:1px solid #2868E8; }
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled,
    QDoubleSpinBox:disabled { background:#EEF2F7; color:#94A3B8; }
    QPushButton {
        background:#FFFFFF; color:#2868E8; border:1px solid #B9CDF4;
        border-radius:8px; padding:7px 14px; min-height:30px; font-weight:600;
    }
    QPushButton:hover { background:#EEF4FF; border-color:#2868E8; }
    QPushButton:pressed { background:#DDE9FF; }
    QPushButton:disabled { background:#EEF2F7; color:#94A3B8; border-color:#DDE5F0; }
    QPushButton#LoginButton, QPushButton[primary="true"] {
        background:#2868E8; color:#FFFFFF; border:1px solid #2868E8;
    }
    QPushButton#LoginButton:hover, QPushButton[primary="true"]:hover { background:#1E56C7; }
    QTableView, QTableWidget {
        background:#FFFFFF; alternate-background-color:#F8FAFD; border:1px solid #DDE5F0;
        border-radius:10px; gridline-color:#E8EDF5; selection-background-color:#E4EEFF;
        selection-color:#172033;
    }
    QHeaderView::section {
        background:#F0F4FA; color:#334155; border:0; border-bottom:1px solid #DDE5F0;
        padding:9px; font-weight:600;
    }
    QTableView::item, QTableWidget::item { padding:7px; }
    QTableView::item:selected, QTableWidget::item:selected {
        background:#E4EEFF; color:#172033;
    }
    QCheckBox, QRadioButton { spacing:7px; }
    QCheckBox::indicator, QRadioButton::indicator { width:16px; height:16px; }
    QProgressBar {
        background:#E8EDF5; border:0; border-radius:6px; height:12px; text-align:center;
    }
    QProgressBar::chunk { background:#2868E8; border-radius:6px; }
    QScrollArea { border:0; background:transparent; }
    QScrollBar:vertical { background:#F1F5F9; width:10px; }
    QScrollBar::handle:vertical { background:#B8C5D6; border-radius:5px; min-height:24px; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
    QTabWidget::pane { background:#FFFFFF; border:1px solid #DDE5F0; }
    QTabBar::tab { background:#EEF2F7; padding:8px 14px; }
    QTabBar::tab:selected { background:#FFFFFF; color:#2868E8; }
    QToolTip { background:#172033; color:#FFFFFF; border:0; padding:6px; }
    QMessageBox { background:#FFFFFF; }
    QSplitter::handle { background:#DDE5F0; }
    QSplitter::handle:hover { background:#9DB8EE; }
    """
