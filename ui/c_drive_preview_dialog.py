"""Xem trước dung lượng trước khi dọn ổ C. Không tự xóa."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class CDrivePreviewDialog(QDialog):
    """Danh sách ước lượng từng mục. «Dọn ngay» mới được coi là xác nhận xóa."""

    def __init__(self, preview: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quét ổ C — xem trước")
        self.setModal(True)
        self.setMinimumSize(560, 420)
        self.resize(680, 520)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f1f5f9; }
            QLabel { color: #e2e8f0; background: transparent; border: none; }
            QPlainTextEdit {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                font-size: 13px;
                padding: 8px;
            }
        """)

        data = preview if isinstance(preview, dict) else {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        if data.get("deep_admin") and data.get("is_admin"):
            title_text = "Dọn sâu (cần Admin) — xem trước"
        elif data.get("deep_admin"):
            title_text = "Dọn sâu (cần Admin) — chưa chạy"
        else:
            title_text = "Quét ổ C (không cần Admin)"
        title = QLabel(title_text)
        title.setStyleSheet("color: #f8fafc; font-size: 16px; font-weight: bold;")
        layout.addWidget(title)

        total = str(data.get("total_label_vi") or "0 B")
        files = int(data.get("total_files") or 0)
        summary = QLabel(
            f"Có thể giải phóng khoảng {total} ({files} tệp). "
            "Đây là ước lượng — chưa xóa tệp nào."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #99f6e4; font-size: 13px; font-weight: 600;")
        layout.addWidget(summary)

        card = QFrame()
        card.setObjectName("CDrivePreviewCard")
        card.setStyleSheet("""
            QFrame#CDrivePreviewCard {
                background-color: #042f2e;
                border: 1px solid #0f766e;
                border-radius: 12px;
            }
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(str(data.get("preview_vi") or "Không có mục nào để quét."))
        text.setMinimumHeight(240)
        card_layout.addWidget(text)
        layout.addWidget(card, 1)

        hint = QLabel(
            "Mục «Cần Admin» bị bỏ qua và không cộng vào tổng. "
            "Tệp đang khóa sẽ được bỏ qua lúc dọn, không tính phần chưa xóa. "
            "Thùng rác và Downloads chỉ xuất hiện khi bạn đang bật."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(10)
        btn_later = QPushButton("Để sau")
        btn_later.setCursor(Qt.PointingHandCursor)
        btn_later.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #e2e8f0;
                font-weight: 600;
                padding: 8px 16px;
                border-radius: 8px;
                border: 1px solid #475569;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_later.clicked.connect(self.reject)

        btn_clean = QPushButton("Dọn ngay")
        btn_clean.setCursor(Qt.PointingHandCursor)
        btn_clean.setDefault(True)
        btn_clean.setStyleSheet("""
            QPushButton {
                background-color: #0f766e;
                color: #f0fdfa;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 8px;
                border: 1px solid #14b8a6;
            }
            QPushButton:hover { background-color: #0d9488; }
        """)
        btn_clean.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(btn_later)
        row.addWidget(btn_clean)
        layout.addLayout(row)
