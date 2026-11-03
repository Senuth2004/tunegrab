"""The Tunegrab dark theme, shared by every desktop platform."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


STYLESHEET = """
QWidget {
    color: #edf0f5;
    font-size: 10pt;
}
QMainWindow, QDialog {
    background: #111318;
}
QTabWidget::pane {
    background: #15181e;
    border: 1px solid #2b3039;
    border-radius: 10px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #aab2bf;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    padding: 10px 18px;
    margin-right: 4px;
}
QTabBar::tab:selected {
    color: #ffffff;
    border-bottom-color: #8b7cff;
}
QTabBar::tab:hover:!selected {
    color: #e0e4eb;
    background: #20242c;
    border-radius: 6px 6px 0 0;
}
QLineEdit, QComboBox, QPlainTextEdit, QTableWidget {
    background: #1b1f27;
    border: 1px solid #303641;
    border-radius: 7px;
    padding: 7px 9px;
    selection-background-color: #6558d9;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTableWidget:focus {
    border-color: #8b7cff;
}
QComboBox::drop-down {
    border: 0;
    width: 26px;
}
QComboBox QAbstractItemView {
    background: #1b1f27;
    border: 1px solid #303641;
    selection-background-color: #6558d9;
}
QPushButton {
    background: #252a33;
    border: 1px solid #373e49;
    border-radius: 7px;
    padding: 8px 13px;
}
QPushButton:hover {
    background: #303642;
    border-color: #4a5260;
}
QPushButton:pressed {
    background: #20242c;
}
QPushButton:disabled {
    color: #737c89;
    background: #1b1f25;
    border-color: #292e36;
}
QTableWidget {
    gridline-color: #292e37;
    alternate-background-color: #191d24;
    padding: 0;
}
QHeaderView::section {
    background: #1b1f27;
    color: #aab2bf;
    border: 0;
    border-bottom: 1px solid #303641;
    padding: 9px;
    font-weight: 600;
}
QTableWidget::item {
    padding: 6px;
}
QTableWidget::item:selected {
    background: #34304f;
}
QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QProgressBar {
    background: #1b1f27;
    border: 1px solid #303641;
    border-radius: 6px;
    text-align: center;
    min-height: 12px;
}
QProgressBar::chunk {
    background: #8b7cff;
    border-radius: 5px;
}
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #3a414c;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QToolTip {
    background: #252a33;
    color: #edf0f5;
    border: 1px solid #414957;
    padding: 5px;
}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#15181e",
        QPalette.ColorRole.WindowText: "#edf0f5",
        QPalette.ColorRole.Base: "#1b1f27",
        QPalette.ColorRole.AlternateBase: "#20242c",
        QPalette.ColorRole.ToolTipBase: "#252a33",
        QPalette.ColorRole.ToolTipText: "#edf0f5",
        QPalette.ColorRole.Text: "#edf0f5",
        QPalette.ColorRole.Button: "#252a33",
        QPalette.ColorRole.ButtonText: "#edf0f5",
        QPalette.ColorRole.BrightText: "#ffffff",
        QPalette.ColorRole.Link: "#a99dff",
        QPalette.ColorRole.Highlight: "#6558d9",
        QPalette.ColorRole.HighlightedText: "#ffffff",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#737c89"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#737c89"))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)
