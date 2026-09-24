"""Xem trước dung lượng trước khi dọn ổ C. Không tự xóa."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.c_drive_clean import (
    category_offered_by_default,
    format_freed_vi,
    normalize_min_clean_mb,
    preview_rows_for_display,
)


class CDrivePreviewDialog(QDialog):
    """Danh sách ước lượng từng mục, xếp từ lớn đến nhỏ. «Dọn ngay» mới là xác nhận xóa."""

    def __init__(self, preview: dict, parent=None, min_clean_mb: int = 10):
        super().__init__(parent)
        self.setWindowTitle("Quét ổ C — xem trước")
        self.setModal(True)
        self.setMinimumSize(620, 520)
        self.resize(760, 640)
        self.setStyleSheet("""
            QDialog { background-color: #0f172a; color: #f1f5f9; }
            QLabel { color: #e2e8f0; background: transparent; border: none; }
            QCheckBox { color: #f8fafc; font-size: 13px; spacing: 8px; }
            QSpinBox {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px 8px;
                min-width: 88px;
            }
        """)

        data = preview if isinstance(preview, dict) else {}
        self._preview = data
        self._rows = preview_rows_for_display(data)
        self._checks = []
        self._downloads_present = any(
            isinstance(row, dict) and row.get("key") == "downloads_old"
            for row in (data.get("targets") or [])
        )
        try:
            self._downloads_days = int(data.get("downloads_min_age_days") or 30)
        except (TypeError, ValueError):
            self._downloads_days = 30
        self._downloads_days = max(1, min(365, self._downloads_days))

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
            f"Quét thấy khoảng {total} ({files} tệp). "
            "Xem trước — chưa xóa tệp nào. Danh sách xếp từ lớn đến nhỏ."
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #99f6e4; font-size: 13px; font-weight: 600;")
        layout.addWidget(summary)

        threshold_row = QHBoxLayout()
        threshold_label = QLabel("Ngưỡng «Dọn ngay»:")
        threshold_label.setStyleSheet("color: #94a3b8;")
        self.spin_min_clean_mb = QSpinBox()
        self.spin_min_clean_mb.setRange(0, 10240)
        self.spin_min_clean_mb.setSuffix(" MB")
        self.spin_min_clean_mb.setSpecialValueText("0 MB (tick mọi mục)")
        self.spin_min_clean_mb.setValue(normalize_min_clean_mb(min_clean_mb))
        self.spin_min_clean_mb.valueChanged.connect(self._apply_threshold_checks)
        threshold_hint = QLabel("Mục nhỏ hơn vẫn hiện. 0 = tick mọi mục có dữ liệu.")
        threshold_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        threshold_row.addWidget(threshold_label)
        threshold_row.addWidget(self.spin_min_clean_mb)
        threshold_row.addWidget(threshold_hint, 1)
        layout.addLayout(threshold_row)

        if self._downloads_present:
            age_row = QHBoxLayout()
            age_label = QLabel("Tệp Downloads cũ hơn:")
            age_label.setStyleSheet("color: #94a3b8;")
            self.spin_downloads_age = QSpinBox()
            self.spin_downloads_age.setRange(1, 365)
            self.spin_downloads_age.setSuffix(" ngày")
            self.spin_downloads_age.setValue(self._downloads_days)
            age_hint = QLabel("Không xóa thư mục. Đổi số ngày có hiệu lực lúc Dọn ngay.")
            age_hint.setStyleSheet("color: #64748b; font-size: 11px;")
            age_row.addWidget(age_label)
            age_row.addWidget(self.spin_downloads_age)
            age_row.addWidget(age_hint, 1)
            layout.addLayout(age_row)

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
        card_layout.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(8, 4, 8, 4)
        host_layout.setSpacing(6)

        if not self._rows:
            empty = QLabel("• Không có gì để xóa (0 B)")
            empty.setStyleSheet("color: #e2e8f0;")
            host_layout.addWidget(empty)
        for row in self._rows:
            host_layout.addWidget(self._build_row(row))
        for path in self._preview.get("excluded_paths") or []:
            skipped = QLabel(f"Đã bỏ qua: {path}")
            skipped.setWordWrap(True)
            skipped.setStyleSheet("color: #fbbf24; font-size: 12px;")
            host_layout.addWidget(skipped)
        host_layout.addStretch()
        scroll.setWidget(host)
        card_layout.addWidget(scroll)
        layout.addWidget(card, 1)

        self.lbl_selected = QLabel("")
        self.lbl_selected.setWordWrap(True)
        self.lbl_selected.setStyleSheet("color: #fde68a; font-size: 12px; font-weight: 600;")
        layout.addWidget(self.lbl_selected)

        hint = QLabel(
            "Mục «Cần Admin» bị bỏ qua và không cộng vào tổng. "
            "Tệp đang khóa sẽ được bỏ qua lúc dọn, không tính phần chưa xóa. "
            "Thùng rác và Downloads chỉ xuất hiện khi bạn đang bật. "
            "Mục dưới ngưỡng vẫn được quét — bỏ tick nghĩa là «Dọn ngay» không xóa mục đó."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
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

        self.btn_clean = QPushButton("Dọn ngay")
        self.btn_clean.setCursor(Qt.PointingHandCursor)
        self.btn_clean.setDefault(True)
        self.btn_clean.setStyleSheet("""
            QPushButton {
                background-color: #0f766e;
                color: #f0fdfa;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 8px;
                border: 1px solid #14b8a6;
            }
            QPushButton:hover { background-color: #0d9488; }
            QPushButton:disabled { background-color: #134e4a; color: #99f6e4; }
        """)
        self.btn_clean.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(btn_later)
        buttons.addWidget(self.btn_clean)
        layout.addLayout(buttons)

        self._apply_threshold_checks()

    def min_clean_mb(self) -> int:
        return normalize_min_clean_mb(self.spin_min_clean_mb.value())

    def downloads_min_age_days(self) -> int:
        if hasattr(self, "spin_downloads_age"):
            return max(1, min(365, int(self.spin_downloads_age.value())))
        return int(self._downloads_days or 30)

    def selected_keys(self):
        keys = []
        for checkbox, row in self._checks:
            if checkbox.isChecked():
                key = str(row.get("key") or "")
                if key:
                    keys.append(key)
        return keys

    def _build_row(self, row: dict) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        row_layout = QHBoxLayout(wrap)
        row_layout.setContentsMargins(0, 0, 0, 0)
        group = str(row.get("group_vi") or "Khác")
        name = str(row.get("name") or row.get("key") or "Mục")
        if row.get("status") == "skipped":
            label = QLabel(f"[{group}] {name}: đã bỏ qua — không xóa")
            label.setWordWrap(True)
            label.setStyleSheet("color: #fbbf24; font-size: 12px;")
            row_layout.addWidget(label)
            return wrap

        checkbox = QCheckBox(self._row_caption(row, offered=True))
        checkbox.setProperty("row_key", str(row.get("key") or ""))
        checkbox.stateChanged.connect(lambda _state: self._refresh_selected_label())
        self._checks.append((checkbox, row))
        row_layout.addWidget(checkbox, 1)
        return wrap

    def _row_caption(self, row: dict, offered: bool) -> str:
        group = str(row.get("group_vi") or "Khác")
        name = str(row.get("name") or row.get("key") or "Mục")
        size = int(row.get("reclaimable_bytes") or 0)
        count = int(row.get("reclaimable_files") or 0)
        if row.get("size_unknown"):
            detail = "chưa ước lượng được dung lượng — vẫn có thể dọn"
        elif row.get("key") == "empty_user_folders":
            detail = f"{count} thư mục trống ({format_freed_vi(size)})"
        elif row.get("key") == "downloads_old":
            days = int(row.get("min_age_days") or getattr(self, "_downloads_days", 30) or 30)
            detail = f"khoảng {format_freed_vi(size)} ({count} tệp, cũ hơn {days} ngày)"
        elif size <= 0 and count <= 0:
            detail = "khoảng 0 B"
        else:
            detail = f"khoảng {format_freed_vi(size)} ({count} tệp)"
        suffix = "" if offered else " — dưới ngưỡng"
        return f"[{group}] {name}: {detail}{suffix}"

    def _apply_threshold_checks(self):
        min_mb = self.min_clean_mb()
        for checkbox, row in self._checks:
            offered = category_offered_by_default(row, min_mb)
            checkbox.blockSignals(True)
            checkbox.setChecked(offered)
            checkbox.setText(self._row_caption(row, offered=offered))
            checkbox.blockSignals(False)
        self._refresh_selected_label()

    def _refresh_selected_label(self):
        chosen = 0
        files = 0
        for checkbox, row in self._checks:
            if not checkbox.isChecked():
                continue
            chosen += int(row.get("reclaimable_bytes") or 0)
            files += int(row.get("reclaimable_files") or 0)
        self.lbl_selected.setText(
            f"«Dọn ngay» sẽ xóa mục đang tick: {format_freed_vi(chosen)} ({files} tệp). "
            "Bỏ tick để giữ mục đó."
        )
        if hasattr(self, "btn_clean"):
            self.btn_clean.setEnabled(any(checkbox.isChecked() for checkbox, _row in self._checks))
