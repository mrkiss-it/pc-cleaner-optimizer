"""
Danh sách khởi động tối thiểu: Run HKCU và thư mục Startup của tài khoản này.
Bật/tắt từng mục sau khi xác nhận. Không đo mili-giây.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QAbstractItemView,
)

from startup_manager import list_user_startup_entries, set_user_startup_enabled


class StartupEntriesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Khởi động của tài khoản này")
        self.setMinimumSize(860, 480)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #e2e8f0; }
            QLabel { color: #e2e8f0; }
            QTableWidget {
                background-color: #1e293b;
                color: #e2e8f0;
                gridline-color: #334155;
                border: 1px solid #334155;
                border-radius: 8px;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                border: none;
                padding: 6px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Khởi động cùng Windows — tài khoản này")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(title)

        self.lbl_scope = QLabel("")
        self.lbl_scope.setWordWrap(True)
        self.lbl_scope.setTextFormat(Qt.PlainText)
        self.lbl_scope.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(self.lbl_scope)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Tên", "Nguồn", "Lệnh hoặc đường dẫn", "Thời gian khởi động", "Thao tác",
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextFormat(Qt.PlainText)
        self.lbl_status.setStyleSheet("color: #fbbf24; font-size: 12px;")
        layout.addWidget(self.lbl_status)

        row = QHBoxLayout()
        btn_refresh = QPushButton("Làm mới")
        btn_refresh.setCursor(Qt.PointingHandCursor)
        btn_refresh.clicked.connect(self.reload)
        btn_close = QPushButton("Đóng")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_refresh)
        row.addStretch()
        row.addWidget(btn_close)
        layout.addLayout(row)

        self.reload()

    def reload(self):
        data = list_user_startup_entries()
        self.lbl_scope.setText(data.get("scope_vi") or "")
        entries = data.get("entries") or []
        self.table.setRowCount(len(entries))
        notes = list(data.get("errors") or [])
        if data.get("omitted_own_app"):
            notes.append("Đã bỏ mục khởi động của chính ứng dụng này — đổi ở tab Tự động.")
        if not entries and not notes:
            notes.append("Không thấy mục nào trong Run (HKCU) hoặc thư mục Startup.")
        self.lbl_status.setText(" ".join(notes))

        for row_idx, entry in enumerate(entries):
            name_item = QTableWidgetItem(entry.get("name") or "")
            name_item.setForeground(QColor("#f8fafc"))
            name_item.setToolTip(entry.get("note_vi") or "")
            source_item = QTableWidgetItem(entry.get("source_vi") or "")
            source_item.setForeground(QColor("#94a3b8"))
            command_item = QTableWidgetItem(entry.get("command") or "")
            command_item.setForeground(QColor("#cbd5e1"))
            command_item.setToolTip(entry.get("command") or "")
            impact_item = QTableWidgetItem(entry.get("impact") or "không rõ")
            impact_item.setForeground(QColor("#fbbf24"))
            impact_item.setToolTip(entry.get("note_vi") or "")
            self.table.setItem(row_idx, 0, name_item)
            self.table.setItem(row_idx, 1, source_item)
            self.table.setItem(row_idx, 2, command_item)
            self.table.setItem(row_idx, 3, impact_item)

            enabled = bool(entry.get("enabled"))
            button = QPushButton("Tắt mục này" if enabled else "Bật lại")
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(entry.get("note_vi") or "")
            entry_id = entry.get("id")
            entry_name = entry.get("name") or ""
            button.clicked.connect(
                lambda _checked=False, eid=entry_id, turn_on=not enabled, label=entry_name: self._toggle(
                    eid, turn_on, label
                )
            )
            self.table.setCellWidget(row_idx, 4, button)
            self.table.setRowHeight(row_idx, 36)

    def _toggle(self, entry_id: str, enable: bool, label: str):
        if enable:
            question = (
                f"Bật lại «{label}»?\n\n"
                "Windows của tài khoản này sẽ chạy mục này khi bạn đăng nhập. "
                "App không biết mục này thêm bao nhiêu mili-giây (không rõ)."
            )
        else:
            question = (
                f"Tắt «{label}»?\n\n"
                "Windows của tài khoản này sẽ không chạy mục này khi đăng nhập. "
                "Có thể bật lại trong danh sách này. "
                "Không đụng tài khoản khác và không cần Admin."
            )
        answer = QMessageBox.question(
            self,
            "Xác nhận từng mục",
            question,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.lbl_status.setText("Đã hủy. Mục khởi động không đổi.")
            return
        result = set_user_startup_enabled(entry_id, enable)
        message = result.get("message_vi") or ""
        if not result.get("success"):
            QMessageBox.warning(self, "Chưa đổi được", message or "Không tắt/bật được.")
        self.reload()
        if message:
            previous = self.lbl_status.text().strip()
            self.lbl_status.setText(message if not previous else f"{message}\n{previous}")
