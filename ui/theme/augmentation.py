"""EYRES approved light theme for the Dataset Augmentation workspace."""

AUGMENTATION_QSS = r"""
QMainWindow#augmentationRoot,
QWidget#augmentationRoot {
    background: #F6F9FD;
    color: #0E1729;
}

QWidget#augmentationRoot QLabel {
    background: transparent;
    border: 0px;
    color: #0E1729;
}

QLabel#pageTitle {
    color: #0E1729;
    font-size: 24px;
    font-weight: 700;
}
QLabel#pageSubtitle {
    color: #61708A;
    font-size: 12px;
}

QFrame#workflowRail {
    background: #FFFFFF;
    border: 1px solid #DBE3F0;
    border-radius: 16px;
}
QLabel#railEyebrow {
    color: #61708A;
    font-size: 9px;
    font-weight: 700;
}
QFrame#railDivider,
QFrame#hairline {
    background: #DBE3F0;
    border: 0px;
}

QPushButton#stepButton,
QPushButton#toolButton {
    min-height: 44px;
    padding: 0px 12px;
    text-align: left;
    border-radius: 10px;
    border: 1px solid transparent;
    background: transparent;
    color: #5F6D83;
    font-size: 11px;
    font-weight: 600;
}
QPushButton#stepButton:hover,
QPushButton#toolButton:hover {
    background: #F7F9FD;
    border-color: #DBE3F0;
}
QPushButton#stepButton[stepState="current"] {
    color: #255CED;
    background: #ECF2FF;
    border: 1px solid #C9D9FF;
    font-weight: 700;
}
QPushButton#stepButton[stepState="complete"] {
    color: #089957;
    background: #F0FBF5;
    border: 1px solid #D1F0DE;
    font-weight: 700;
}
QPushButton#stepButton[stepState="upcoming"] {
    color: #5F6D83;
    background: transparent;
    border: 1px solid transparent;
}
QPushButton#toolButton:checked {
    color: #255CED;
    background: #ECF2FF;
    border: 1px solid #C9D9FF;
    font-weight: 700;
}

QFrame#workspaceCard {
    background: #FFFFFF;
    border: 1px solid #DBE3F0;
    border-radius: 16px;
}
QStackedWidget#augmentationWorkspace,
QWidget#pageBody,
QWidget#contentHeader,
QWidget#workspaceFooter,
QWidget#fieldBlock {
    background: transparent;
    border: 0px;
}

QLabel#contentTitle {
    color: #0E1729;
    font-size: 15px;
    font-weight: 700;
}
QLabel#contentSubtitle,
QLabel#cardSubtitle {
    color: #61708A;
    font-size: 10px;
}
QLabel#cardTitle {
    color: #0E1729;
    font-size: 12px;
    font-weight: 700;
}
QLabel#fieldLabel,
QLabel#switchLabel {
    color: #4E5C73;
    font-size: 10px;
    font-weight: 600;
}
QLabel#fieldHelper {
    color: #7A89A0;
    font-size: 9px;
}
QLabel#validationMessage {
    color: #C83A49;
    background: #FFF0F2;
    border: 1px solid #F2CDD3;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 10px;
    font-weight: 600;
}

QFrame#innerCard,
QFrame#transformCard,
QFrame#statCard,
QFrame#statusPanel {
    background: #FBFCFF;
    border: 1px solid #DBE3F0;
    border-radius: 13px;
}
QFrame#transformCard {
    background: #FFFFFF;
}
QFrame#transformCard[transformActive="true"] {
    background: #FFFFFF;
    border: 1px solid #D3DFF4;
}
QFrame#transformCard[transformActive="false"] {
    background: #FBFCFF;
    border: 1px solid #E1E7F0;
}
QWidget#switchRow {
    background: transparent;
    border: 0px;
    min-height: 30px;
}
QLabel#variationCaption {
    color: #61708A;
    font-size: 9px;
    font-weight: 600;
    padding-top: 2px;
}
QFrame#previewPlaceholder {
    background: #F7F9FC;
    border: 1px dashed #C9D6EB;
    border-radius: 13px;
}
QLabel#transformIcon {
    min-width: 34px;
    max-width: 34px;
    min-height: 34px;
    max-height: 34px;
    background: #ECF2FF;
    color: #255CED;
    border-radius: 9px;
    font-size: 10px;
    font-weight: 700;
}
QLabel#previewGamma {
    color: #A0ACC0;
    font-size: 30px;
    font-weight: 700;
}
QLabel#previewTitle {
    color: #65748C;
    font-size: 11px;
    font-weight: 700;
}
QLabel#gammaValue {
    color: #255CED;
    font-size: 30px;
    font-weight: 700;
}

QLabel#badge {
    min-height: 28px;
    max-height: 28px;
    padding-left: 10px;
    padding-right: 10px;
    border-radius: 14px;
    background: #F0F4FA;
    color: #5E6D84;
    font-size: 9px;
    font-weight: 700;
}
QLabel#badge[badgeKind="green"] {
    background: #E8FAF0;
    color: #089957;
}
QLabel#badge[badgeKind="blue"] {
    background: #ECF2FF;
    color: #255CED;
}
QLabel#badge[badgeKind="amber"] {
    background: #FFF5D9;
    color: #B26B00;
}

QLabel#transformTag {
    min-height: 26px;
    max-height: 26px;
    padding-left: 9px;
    padding-right: 9px;
    border-radius: 13px;
    background: #ECF2FF;
    color: #255CED;
    font-size: 9px;
    font-weight: 700;
}

QFrame#readinessStrip {
    background: #F7FAFF;
    border: 1px solid #D9E4F8;
    border-radius: 12px;
}
QWidget#summaryCell {
    background: transparent;
    border-right: 1px solid #E2E9F4;
}
QWidget#summaryCell[lastCell="true"] {
    border-right: 0px;
}
QLabel#summaryCaption {
    color: #738199;
    font-size: 8px;
    font-weight: 700;
}
QLabel#summaryValue,
QLabel#summaryDataValue {
    color: #0E1729;
    font-size: 10px;
    font-weight: 700;
}
QLabel#summaryValue[summaryState="success"] {
    color: #089957;
}
QLabel#summaryValue[summaryState="neutral"] {
    color: #8491A6;
}
QWidget#summaryRow {
    background: transparent;
    border-bottom: 1px solid #EAEFF6;
}
QLabel#summaryKey {
    color: #61708A;
    font-size: 10px;
}
QLabel#statValue {
    color: #0E1729;
    font-size: 12px;
    font-weight: 700;
}

QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox {
    min-height: 38px;
    max-height: 38px;
    background: #FFFFFF;
    color: #0E1729;
    border: 1px solid #C9D6EB;
    border-radius: 8px;
    padding-left: 10px;
    padding-right: 10px;
    selection-background-color: #255CED;
    selection-color: #FFFFFF;
    font-size: 10px;
}
QLineEdit:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QComboBox:focus {
    border: 1px solid #8EAAF8;
}
QLineEdit:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled,
QComboBox:disabled {
    background: #F1F4F8;
    color: #9BA8BC;
}
QComboBox::drop-down {
    border: 0px;
    width: 24px;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    color: #0E1729;
    border: 1px solid #DBE3F0;
    selection-background-color: #ECF2FF;
    selection-color: #0E1729;
    outline: 0px;
}

QPushButton {
    min-height: 38px;
    padding-left: 14px;
    padding-right: 14px;
    border-radius: 9px;
    border: 1px solid #C9D6EB;
    background: #FFFFFF;
    color: #0E1729;
    font-size: 10px;
    font-weight: 600;
}
QPushButton:hover {
    background: #F8FAFD;
    border-color: #ADC0E4;
}
QPushButton:pressed {
    background: #EEF3FA;
}
QPushButton:disabled {
    color: #9BA8BC;
    background: #F4F6F9;
    border-color: #E2E7EF;
}
QPushButton#primaryButton {
    background: #255CED;
    border-color: #255CED;
    color: #FFFFFF;
    font-weight: 700;
}
QPushButton#primaryButton:hover {
    background: #174FD2;
    border-color: #174FD2;
}
QPushButton#ghostButton {
    background: transparent;
    border-color: transparent;
    color: #61708A;
}
QPushButton#ghostButton:hover {
    background: #F3F6FA;
}
QPushButton#helpButton {
    min-width: 38px;
    max-width: 38px;
    min-height: 38px;
    max-height: 38px;
    padding: 0px;
    background: #FFFFFF;
    color: #255CED;
    border: 1px solid #C9D6EB;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 700;
}
QPushButton#helpButton:hover {
    background: #ECF2FF;
}

/* Custom painted switch: override the generic QPushButton 38px minimum. */
QPushButton#toggleSwitch {
    min-width: 44px;
    max-width: 44px;
    min-height: 24px;
    max-height: 24px;
    padding: 0px;
    margin: 0px;
    border: 0px;
    background: transparent;
}
QPushButton#toggleSwitch:hover,
QPushButton#toggleSwitch:pressed,
QPushButton#toggleSwitch:checked {
    border: 0px;
    background: transparent;
}

QSlider::groove:horizontal {
    height: 5px;
    background: #D9E1ED;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #255CED;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 14px;
    margin: -5px 0px;
    background: #255CED;
    border: 2px solid #FFFFFF;
    border-radius: 7px;
}
QSlider::groove:horizontal:disabled,
QSlider::sub-page:horizontal:disabled {
    background: #E7EBF1;
}
QSlider::handle:horizontal:disabled {
    background: #AAB5C6;
}

QProgressBar {
    min-height: 10px;
    max-height: 10px;
    border: 0px;
    border-radius: 5px;
    background: #E8EDF4;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: #255CED;
    border-radius: 5px;
}

QTextEdit#processingLog {
    background: #07101E;
    color: #DDE6F4;
    border: 1px solid #13213A;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 9px;
    selection-background-color: #255CED;
}

QLabel#footerStatus {
    color: #61708A;
    font-size: 9px;
}

QScrollArea {
    border: 0px;
    background: transparent;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #C7D2E4;
    min-height: 32px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
"""
