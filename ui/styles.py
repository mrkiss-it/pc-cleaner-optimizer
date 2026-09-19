# Modern Dark Theme Stylesheet (QSS) for PC Auto Cleaner & RAM Optimizer

DARK_THEME = """
QMainWindow {
    background-color: #0b0f19;
}

QWidget {
    color: #f1f5f9;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
    font-size: 13px;
}

/* Dialogs & MessageBox Dark Mode */
QDialog, QMessageBox {
    background-color: #0f172a;
    color: #f1f5f9;
}

QMessageBox QLabel {
    color: #f1f5f9;
    font-size: 13px;
    background-color: transparent;
}

QMessageBox QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: bold;
    min-width: 80px;
    padding: 8px 18px;
    border-radius: 6px;
    border: none;
}

QMessageBox QPushButton:hover {
    background-color: #1d4ed8;
}

QMessageBox QPushButton:pressed {
    background-color: #1e40af;
}


/* Tab Widget Styling */
QTabWidget::pane {
    border: 1px solid #1e293b;
    background-color: #0f172a;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    background-color: #0b0f19;
    color: #94a3b8;
    padding: 10px 20px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    font-size: 13px;
    border: 1px solid transparent;
}

QTabBar::tab:hover {
    color: #38bdf8;
    background-color: #1e293b;
}

QTabBar::tab:selected {
    color: #38bdf8;
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-bottom: 2px solid #38bdf8;
}

/* Card / Container frames */
QFrame.card {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 16px;
}

QFrame.card:hover {
    border-color: #475569;
}

/* Buttons */
QPushButton {
    background-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
    padding: 10px 20px;
    border-radius: 8px;
    border: none;
}

QPushButton:hover {
    background-color: #1d4ed8;
}

QPushButton:pressed {
    background-color: #1e40af;
}

QPushButton:disabled {
    background-color: #334155;
    color: #64748b;
}

QPushButton.btn-primary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #06b6d4);
    color: #ffffff;
    font-size: 15px;
    font-weight: bold;
    padding: 14px 28px;
    border-radius: 10px;
}

QPushButton.btn-primary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0891b2);
}

QPushButton.btn-success {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #10b981);
    color: #ffffff;
    font-size: 14px;
    font-weight: bold;
    padding: 10px 20px;
    border-radius: 8px;
}

QPushButton.btn-success:hover {
    background: #047857;
}

QPushButton.btn-secondary {
    background-color: #334155;
    color: #e2e8f0;
    border: 1px solid #475569;
}

QPushButton.btn-secondary:hover {
    background-color: #475569;
}

QPushButton.btn-warning {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d97706, stop:1 #f59e0b);
    color: #ffffff;
    font-weight: bold;
    padding: 10px 16px;
    border-radius: 8px;
}

QPushButton.btn-warning:hover {
    background: #b45309;
}

QPushButton.btn-purple {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:1 #a855f7);
    color: #ffffff;
    font-weight: bold;
    padding: 10px 16px;
    border-radius: 8px;
}

QPushButton.btn-purple:hover {
    background: #6d28d9;
}

/* Checkboxes */
QCheckBox {
    spacing: 10px;
    color: #e2e8f0;
    font-size: 13px;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 5px;
    border: 1px solid #475569;
    background-color: #0f172a;
}

QCheckBox::indicator:hover {
    border-color: #38bdf8;
}

QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
    image: url(""); /* Can use draw or check mark text */
}

/* SpinBox & ComboBox */
QSpinBox, QComboBox {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    color: #f8fafc;
    padding: 6px 12px;
    min-width: 80px;
}

QSpinBox:focus, QComboBox:focus {
    border-color: #38bdf8;
}

QComboBox::drop-down {
    border: none;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #1e293b;
    border: 1px solid #334155;
    selection-background-color: #0284c7;
    selection-color: white;
    color: #f8fafc;
    padding: 4px;
}

/* Table View for History */
QTableWidget {
    background-color: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 8px;
    gridline-color: #1e293b;
    color: #e2e8f0;
}

QTableWidget::item {
    padding: 8px;
    border-bottom: 1px solid #1e293b;
}

QTableWidget::item:selected {
    background-color: #1e293b;
    color: #38bdf8;
}

QHeaderView::section {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 8px;
    font-weight: 600;
    border: none;
    border-bottom: 1px solid #334155;
}

/* Scroll Area */
QScrollArea {
    background-color: transparent;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* ScrollBar */
QScrollBar:vertical {
    background: #0f172a;
    width: 8px;
    border-radius: 4px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #334155;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: #0f172a;
    height: 8px;
    border-radius: 4px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #334155;
    border-radius: 4px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
    background: #475569;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}

QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}

/* Progress Bar */
QProgressBar {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    height: 12px;
    text-align: center;
    color: #f8fafc;
    font-size: 10px;
}

QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #10b981);
    border-radius: 5px;
}

/* Tweak Cards & Badges */
QFrame.tweak-card {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 12px;
}

QFrame.tweak-card:hover {
    border-color: #38bdf8;
    background-color: #223046;
}

QLabel.badge-rec {
    background-color: #064e3b;
    color: #34d399;
    border: 1px solid #059669;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}

QLabel.badge-adv {
    background-color: #451a03;
    color: #fbbf24;
    border: 1px solid #d97706;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: 600;
}

QPushButton.btn-tweak-on {
    background: #059669;
    color: #ffffff;
    font-weight: bold;
    border-radius: 6px;
    padding: 6px 14px;
}

QPushButton.btn-tweak-on:hover {
    background: #047857;
}

QPushButton.btn-tweak-off {
    background: #334155;
    color: #94a3b8;
    font-weight: 600;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px 14px;
}

QPushButton.btn-tweak-off:hover {
    background: #475569;
    color: #f1f5f9;
}
"""

