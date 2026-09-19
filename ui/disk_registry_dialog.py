import os
import logging
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTabWidget, QFrame, QProgressBar, QTableWidget, 
    QTableWidgetItem, QHeaderView, QCheckBox, QMessageBox, 
    QPlainTextEdit, QScrollArea, QListWidget, QListWidgetItem
)

from ui.styles import DARK_THEME
from core.registry_cleaner import SafeRegistryCleaner
from core.disk_health_optimizer import DiskHealthOptimizer

logger = logging.getLogger("DiskRegistryDialog")

class RegistryScanWorker(QThread):
    finished = pyqtSignal(list)

    def run(self):
        items = SafeRegistryCleaner.scan()
        self.finished.emit(items)

class TrimWorker(QThread):
    finished = pyqtSignal(dict)

    def __init__(self, drive_letter: str = None):
        super().__init__()
        self.drive_letter = drive_letter

    def run(self):
        if self.drive_letter:
            res = DiskHealthOptimizer.run_trim(self.drive_letter)
        else:
            res = DiskHealthOptimizer.run_trim_all()
        self.finished.emit(res)

class DiskRegistryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản Lý Sức Khỏe Ổ Cứng, SSD TRIM & Dọn Dẹp Registry")
        self.resize(960, 680)
        self.setMinimumSize(850, 580)
        self.setStyleSheet(DARK_THEME)

        self.registry_findings = []
        self.init_ui()
        self.refresh_disk_info()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        # Header
        hdr_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)

        lbl_title = QLabel("💽 SỨC KHỎE Ổ ĐĨA & DỌN DẸP REGISTRY AN TOÀN")
        lbl_title.setStyleSheet("color: #38bdf8; font-size: 16px; font-weight: 800; letter-spacing: 0.5px;")
        lbl_sub = QLabel("Kiểm tra phần cứng ổ đĩa, làm mới tốc độ SSD qua TRIM và rà soát các khóa Registry mồ côi kèm sao lưu an toàn")
        lbl_sub.setStyleSheet("color: #94a3b8; font-size: 11px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        hdr_layout.addLayout(title_box)
        hdr_layout.addStretch()

        btn_close = QPushButton("✕ Đóng")
        btn_close.setProperty("class", "btn-secondary")
        btn_close.setCursor(Qt.PointingHandCursor)
        btn_close.clicked.connect(self.accept)
        hdr_layout.addWidget(btn_close)
        main_layout.addLayout(hdr_layout)

        # Tabs
        self.tabs = QTabWidget()
        self.tab_disk = QWidget()
        self.tab_registry = QWidget()

        self.init_tab_disk()
        self.init_tab_registry()

        self.tabs.addTab(self.tab_disk, "💽 Sức Khỏe Ổ Cứng & SSD TRIM")
        self.tabs.addTab(self.tab_registry, "🛡️ Dọn Dẹp Registry An Toàn")
        main_layout.addWidget(self.tabs, 1)

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 1: DISK HEALTH & SSD TRIM
    # ──────────────────────────────────────────────────────────────────────────
    def init_tab_disk(self):
        outer_layout = QVBoxLayout(self.tab_disk)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Overview Card
        card_overview = QFrame()
        card_overview.setStyleSheet("QFrame { background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; }")
        lo_ov = QHBoxLayout(card_overview)
        lo_ov.setContentsMargins(16, 14, 16, 14)

        self.lbl_disk_badge = QLabel("🟢 TẤT CẢ Ổ CỨNG AN TOÀN")
        self.lbl_disk_badge.setStyleSheet("""
            background-color: #064e3b; color: #34d399;
            font-size: 13px; font-weight: bold; padding: 6px 16px;
            border-radius: 16px; border: 1px solid #059669;
        """)

        self.lbl_storage_summary = QLabel("Đang tải dữ liệu lưu trữ...")
        self.lbl_storage_summary.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 600;")

        self.btn_trim_all = QPushButton("⚡ Tối Ưu SSD TRIM Toàn Bộ Ổ Đĩa")
        self.btn_trim_all.setProperty("class", "btn-primary")
        self.btn_trim_all.setCursor(Qt.PointingHandCursor)
        self.btn_trim_all.clicked.connect(self.run_trim_all_drives)

        self.btn_refresh_disk = QPushButton("🔄 Làm Mới")
        self.btn_refresh_disk.setProperty("class", "btn-secondary")
        self.btn_refresh_disk.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_disk.clicked.connect(self.refresh_disk_info)

        lo_ov.addWidget(self.lbl_disk_badge)
        lo_ov.addSpacing(16)
        lo_ov.addWidget(self.lbl_storage_summary)
        lo_ov.addStretch()
        lo_ov.addWidget(self.btn_trim_all)
        lo_ov.addWidget(self.btn_refresh_disk)
        layout.addWidget(card_overview)

        # Section: Physical Disks
        lbl_sec1 = QLabel("🔧 THÔNG TIN PHẦN CỨNG Ổ ĐĨA VẬT LÝ (PHYSICAL DISKS)")
        lbl_sec1.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 700; margin-top: 6px;")
        layout.addWidget(lbl_sec1)

        self.container_disks = QVBoxLayout()
        self.container_disks.setSpacing(10)
        layout.addLayout(self.container_disks)

        # Section: Volumes / Partitions
        lbl_sec2 = QLabel("📁 PHÂN VÙNG DUNG LƯỢNG & THAO TÁC SSD TRIM RIÊNG TỪNG Ổ")
        lbl_sec2.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 700; margin-top: 10px;")
        layout.addWidget(lbl_sec2)

        self.container_volumes = QVBoxLayout()
        self.container_volumes.setSpacing(10)
        layout.addLayout(self.container_volumes)

        # Educational Note on TRIM
        card_info = QFrame()
        card_info.setStyleSheet("QFrame { background-color: #0b1329; border: 1px solid #1e3a8a; border-radius: 8px; }")
        lo_info = QVBoxLayout(card_info)
        lo_info.setContentsMargins(14, 12, 14, 12)
        lo_info.setSpacing(4)

        lbl_info_title = QLabel("💡 Công nghệ SSD TRIM hoạt động thế nào?")
        lbl_info_title.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 12px;")
        lbl_info_desc = QLabel(
            "Khi bạn xóa file trong Windows, ổ SSD chỉ đánh dấu các cung từ là 'không dùng' nhưng chưa xóa thật. "
            "Sau một thời gian sử dụng, tốc độ ghi sẽ bị giảm vì SSD phải vừa xóa dữ liệu cũ vừa ghi mới. "
            "Lệnh TRIM gửi tín hiệu cho chip điều khiển SSD dọn dẹp trước các cell nhớ nhàn rỗi, giúp khôi phục "
            "tốc độ ghi dữ liệu nhanh như lúc mới mua và kéo dài tuổi thọ chip NAND."
        )
        lbl_info_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        lbl_info_desc.setWordWrap(True)
        lo_info.addWidget(lbl_info_title)
        lo_info.addWidget(lbl_info_desc)
        layout.addWidget(card_info)

        layout.addStretch()
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

    def refresh_disk_info(self):
        summary = DiskHealthOptimizer.get_summary()

        # Update Overview
        total_gb = summary["total_storage_gb"]
        free_gb = summary["total_free_gb"]
        self.lbl_storage_summary.setText(
            f"Tổng dung lượng: {total_gb:.1f} GB • Còn trống: {free_gb:.1f} GB ({summary['ssd_count']} SSD, {summary['hdd_count']} HDD)"
        )

        if summary["overall_status"] == "HEALTHY":
            self.lbl_disk_badge.setText("🟢 TẤT CẢ Ổ CỨNG AN TOÀN")
            self.lbl_disk_badge.setStyleSheet("""
                background-color: #064e3b; color: #34d399;
                font-size: 13px; font-weight: bold; padding: 6px 16px;
                border-radius: 16px; border: 1px solid #059669;
            """)
        else:
            self.lbl_disk_badge.setText("🟡 PHÁT HIỆN CẢNH BÁO SỨC KHỎE")
            self.lbl_disk_badge.setStyleSheet("""
                background-color: #422006; color: #fbbf24;
                font-size: 13px; font-weight: bold; padding: 6px 16px;
                border-radius: 16px; border: 1px solid #d97706;
            """)

        # Clear old items
        while self.container_disks.count():
            item = self.container_disks.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        while self.container_volumes.count():
            item = self.container_volumes.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Populate Physical Disks
        for d in summary["disks"]:
            card = QFrame()
            card.setStyleSheet("QFrame { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; }")
            lo = QHBoxLayout(card)
            lo.setContentsMargins(14, 10, 14, 10)

            lbl_icon = QLabel("💾" if not d["is_ssd"] else "⚡")
            lbl_icon.setStyleSheet("font-size: 20px;")

            info_box = QVBoxLayout()
            info_box.setSpacing(2)
            lbl_name = QLabel(f"Disk #{d['device_id']}: {d['name']}")
            lbl_name.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 13px;")

            lbl_meta = QLabel(f"Chuẩn giao tiếp: {d['bus_type']} • Dung lượng: {d['size_gb']:.1f} GB")
            lbl_meta.setStyleSheet("color: #94a3b8; font-size: 11px;")
            info_box.addWidget(lbl_name)
            info_box.addWidget(lbl_meta)

            badge_type = QLabel(d["media_type"])
            badge_type.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-size: 11px; padding: 4px 10px; border-radius: 6px; font-weight: 600;")

            badge_health = QLabel(f"S.M.A.R.T: {d['health_status']}")
            hcolor = "#34d399" if d['health_status'].upper() == "HEALTHY" else "#fbbf24"
            badge_health.setStyleSheet(f"background-color: #0f172a; color: {hcolor}; font-size: 11px; padding: 4px 10px; border-radius: 6px; font-weight: 600;")

            lo.addWidget(lbl_icon)
            lo.addSpacing(10)
            lo.addLayout(info_box, 1)
            lo.addWidget(badge_type)
            lo.addSpacing(8)
            lo.addWidget(badge_health)
            self.container_disks.addWidget(card)

        # Populate Volumes
        for v in summary["volumes"]:
            card = QFrame()
            card.setStyleSheet("QFrame { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; }")
            lo = QHBoxLayout(card)
            lo.setContentsMargins(14, 10, 14, 10)

            v_info = QVBoxLayout()
            v_info.setSpacing(4)
            lbl_v_title = QLabel(f"Ổ đĩa {v['letter']}: ({v['label']}) — {v['file_system']}")
            lbl_v_title.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 13px;")

            pbar = QProgressBar()
            pbar.setRange(0, 100)
            pbar.setValue(int(v["used_pct"]))
            pbar.setFixedHeight(8)
            pbar.setTextVisible(False)
            bar_color = "#38bdf8" if v["used_pct"] < 80 else ("#fbbf24" if v["used_pct"] < 90 else "#f43f5e")
            pbar.setStyleSheet(f"""
                QProgressBar {{ background-color: #0f172a; border: none; border-radius: 4px; }}
                QProgressBar::chunk {{ background-color: {bar_color}; border-radius: 4px; }}
            """)

            lbl_v_stat = QLabel(
                f"Đã dùng {v['used_gb']:.1f} GB ({v['used_pct']:.1f}%) • Còn trống {v['free_gb']:.1f} GB / {v['total_gb']:.1f} GB"
            )
            lbl_v_stat.setStyleSheet("color: #94a3b8; font-size: 11px;")

            v_info.addWidget(lbl_v_title)
            v_info.addWidget(pbar)
            v_info.addWidget(lbl_v_stat)

            btn_trim_single = QPushButton(f"⚡ TRIM Ổ {v['letter']}:")
            btn_trim_single.setProperty("class", "btn-secondary")
            btn_trim_single.setCursor(Qt.PointingHandCursor)
            btn_trim_single.setFixedWidth(120)
            btn_trim_single.clicked.connect(lambda checked, ltr=v['letter']: self.run_trim_single_drive(ltr))

            lo.addLayout(v_info, 1)
            lo.addSpacing(16)
            lo.addWidget(btn_trim_single)
            self.container_volumes.addWidget(card)

    def run_trim_single_drive(self, drive_letter: str):
        self.btn_trim_all.setEnabled(False)
        self.trim_worker = TrimWorker(drive_letter)
        self.trim_worker.finished.connect(self._on_trim_finished)
        self.trim_worker.start()

    def run_trim_all_drives(self):
        self.btn_trim_all.setEnabled(False)
        self.btn_trim_all.setText("⏳ Đang thực thi TRIM...")
        self.trim_worker = TrimWorker(None)
        self.trim_worker.finished.connect(self._on_trim_finished)
        self.trim_worker.start()

    def _on_trim_finished(self, res: dict):
        self.btn_trim_all.setEnabled(True)
        self.btn_trim_all.setText("⚡ Tối Ưu SSD TRIM Toàn Bộ Ổ Đĩa")
        msg = res.get("message", "Đã hoàn thành tối ưu hóa SSD TRIM.")
        if res.get("success", True):
            QMessageBox.information(self, "Tối Ưu SSD Thành Công", msg)
        else:
            QMessageBox.warning(self, "Thông Báo", msg)
        self.refresh_disk_info()

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 2: SAFE REGISTRY CLEANER
    # ──────────────────────────────────────────────────────────────────────────
    def init_tab_registry(self):
        layout = QVBoxLayout(self.tab_registry)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Control Bar
        ctrl_bar = QHBoxLayout()
        self.btn_scan_reg = QPushButton("🔍 Quét Lỗi Registry")
        self.btn_scan_reg.setProperty("class", "btn-primary")
        self.btn_scan_reg.setCursor(Qt.PointingHandCursor)
        self.btn_scan_reg.clicked.connect(self.scan_registry)

        self.lbl_reg_count = QLabel("Chưa quét Registry.")
        self.lbl_reg_count.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600;")

        self.btn_restore_view = QPushButton("⏪ Quản Lý Bản Sao Lưu (.reg)")
        self.btn_restore_view.setProperty("class", "btn-secondary")
        self.btn_restore_view.setCursor(Qt.PointingHandCursor)
        self.btn_restore_view.clicked.connect(self.open_backups_manager)

        ctrl_bar.addWidget(self.btn_scan_reg)
        ctrl_bar.addSpacing(14)
        ctrl_bar.addWidget(self.lbl_reg_count)
        ctrl_bar.addStretch()
        ctrl_bar.addWidget(self.btn_restore_view)
        layout.addLayout(ctrl_bar)

        # Table
        self.table_reg = QTableWidget()
        self.table_reg.setColumnCount(4)
        self.table_reg.setHorizontalHeaderLabels(["Chọn", "Phân Loại", "Khóa / Giá Trị Registry", "Chi Tiết Lỗi"])
        self.table_reg.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_reg.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_reg.horizontalHeader().setSectionResizeMode(2, QHeaderView.Interactive)
        self.table_reg.horizontalHeader().resizeSection(2, 280)
        self.table_reg.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_reg.verticalHeader().setVisible(False)
        self.table_reg.setAlternatingRowColors(True)
        layout.addWidget(self.table_reg, 1)

        # Bottom Actions Bar
        bot_bar = QHBoxLayout()
        self.btn_select_all = QPushButton("Chọn Tất Cả")
        self.btn_select_all.setProperty("class", "btn-secondary")
        self.btn_select_all.clicked.connect(lambda: self._set_all_selection(True))

        self.btn_deselect_all = QPushButton("Bỏ Chọn Tất Cả")
        self.btn_deselect_all.setProperty("class", "btn-secondary")
        self.btn_deselect_all.clicked.connect(lambda: self._set_all_selection(False))

        self.btn_clean_reg = QPushButton("💾 Sao Lưu & Dọn Dẹp Mục Đã Chọn")
        self.btn_clean_reg.setProperty("class", "btn-primary")
        self.btn_clean_reg.setCursor(Qt.PointingHandCursor)
        self.btn_clean_reg.clicked.connect(self.clean_selected_registry)

        bot_bar.addWidget(self.btn_select_all)
        bot_bar.addWidget(self.btn_deselect_all)
        bot_bar.addStretch()
        bot_bar.addWidget(self.btn_clean_reg)
        layout.addLayout(bot_bar)

        # Log terminal
        self.txt_reg_log = QPlainTextEdit()
        self.txt_reg_log.setReadOnly(True)
        self.txt_reg_log.setMaximumHeight(80)
        self.txt_reg_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #020617; color: #38bdf8;
                font-family: 'Consolas', monospace; font-size: 11px;
                border: 1px solid #1e293b; border-radius: 6px; padding: 6px;
            }
        """)
        layout.addWidget(self.txt_reg_log)

    def scan_registry(self):
        self.btn_scan_reg.setEnabled(False)
        self.btn_scan_reg.setText("⏳ Đang quét...")
        self.txt_reg_log.appendPlainText("Đang bắt đầu quét Registry an toàn...")

        self.scan_worker = RegistryScanWorker()
        self.scan_worker.finished.connect(self._on_scan_finished)
        self.scan_worker.start()

    def _on_scan_finished(self, findings: list):
        self.btn_scan_reg.setEnabled(True)
        self.btn_scan_reg.setText("🔍 Quét Lỗi Registry")
        self.registry_findings = findings

        self.lbl_reg_count.setText(f"Phát hiện {len(findings)} mục lỗi/mồ côi trong Registry.")
        self.txt_reg_log.appendPlainText(f"Quét hoàn tất: Tìm thấy {len(findings)} vấn đề cần xử lý.")

        self.table_reg.setRowCount(len(findings))
        for row_idx, item in enumerate(findings):
            chk = QCheckBox()
            chk.setChecked(True)
            chk.stateChanged.connect(lambda st, idx=row_idx: self._on_item_checked(idx, st))
            self.table_reg.setCellWidget(row_idx, 0, chk)

            cat_item = QTableWidgetItem(item["category"])
            cat_item.setTextAlignment(Qt.AlignCenter)
            self.table_reg.setItem(row_idx, 1, cat_item)

            val_item = QTableWidgetItem(f"{item['root_name']}\\{item['key_path']} -> {item['value_name']}")
            self.table_reg.setItem(row_idx, 2, val_item)

            reason_item = QTableWidgetItem(item["reason"])
            reason_item.setForeground(Qt.yellow)
            self.table_reg.setItem(row_idx, 3, reason_item)

    def _on_item_checked(self, idx: int, state: int):
        if idx < len(self.registry_findings):
            self.registry_findings[idx]["selected"] = (state == Qt.Checked)

    def _set_all_selection(self, selected: bool):
        for r in range(self.table_reg.rowCount()):
            widget = self.table_reg.cellWidget(r, 0)
            if isinstance(widget, QCheckBox):
                widget.setChecked(selected)
        for it in self.registry_findings:
            it["selected"] = selected

    def clean_selected_registry(self):
        selected_items = [it for it in self.registry_findings if it.get("selected", True)]
        if not selected_items:
            QMessageBox.information(self, "Chưa Chọn Mục Nào", "Vui lòng tích chọn ít nhất 1 mục để dọn dẹp.")
            return

        reply = QMessageBox.question(
            self, "Xác Nhận Dọn Dẹp Registry",
            f"Bạn có chắc muốn dọn dẹp {len(selected_items)} mục đã chọn?\n\n"
            "Hệ thống sẽ TỰ ĐỘNG TẠO FILE SAO LƯU (.reg) trước khi dọn để bạn có thể hoàn tác 100% bất kỳ lúc nào.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return

        res = SafeRegistryCleaner.clean_items(selected_items)
        b_path = res.get("backup_path", "")
        cleaned = res.get("cleaned_count", 0)

        self.txt_reg_log.appendPlainText(f"Đã dọn dẹp {cleaned} mục. File sao lưu: {b_path}")
        QMessageBox.information(
            self, "Dọn Dẹp Hoàn Tất",
            f"Đã dọn dẹp thành công {cleaned} mục rác Registry.\n\n"
            f"File sao lưu an toàn đã được lưu tại:\n{b_path}"
        )

        # Quét lại để cập nhật danh sách
        self.scan_registry()

    def open_backups_manager(self):
        backups = SafeRegistryCleaner.get_backup_files()
        if not backups:
            QMessageBox.information(self, "Bản Sao Lưu", "Chưa có bản sao lưu Registry nào được tạo.")
            return

        # Hiển thị dialog danh sách bản sao lưu
        dlg = QDialog(self)
        dlg.setWindowTitle("Quản Lý & Hoàn Tác Bản Sao Lưu Registry")
        dlg.resize(600, 360)
        dlg.setStyleSheet(DARK_THEME)

        d_layout = QVBoxLayout(dlg)
        d_layout.setContentsMargins(16, 16, 16, 16)
        d_layout.setSpacing(12)

        lbl_b_title = QLabel("Danh sách các bản sao lưu Registry đã tạo:")
        lbl_b_title.setStyleSheet("color: #f8fafc; font-weight: bold;")
        d_layout.addWidget(lbl_b_title)

        list_w = QListWidget()
        list_w.setStyleSheet("QListWidget { background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 6px; }")

        for b in backups:
            item = QListWidgetItem(f"📄 {b['filename']} ({b['size_kb']:.1f} KB) — {b['created_at']}")
            item.setData(Qt.UserRole, b["path"])
            list_w.addItem(item)
        d_layout.addWidget(list_w, 1)

        b_btns = QHBoxLayout()
        btn_restore = QPushButton("⏪ Hoàn Tác Bản Sao Lưu Đã Chọn")
        btn_restore.setProperty("class", "btn-primary")
        btn_restore.clicked.connect(lambda: self._restore_selected_backup(list_w, dlg))

        btn_open_folder = QPushButton("📁 Mở Thư Mục Chứa")
        btn_open_folder.setProperty("class", "btn-secondary")
        btn_open_folder.clicked.connect(lambda: os.startfile(SafeRegistryCleaner.BACKUP_DIR))

        b_btns.addWidget(btn_restore)
        b_btns.addWidget(btn_open_folder)
        b_btns.addStretch()
        d_layout.addLayout(b_btns)

        dlg.exec_()

    def _restore_selected_backup(self, list_w: QListWidget, parent_dlg: QDialog):
        item = list_w.currentItem()
        if not item:
            QMessageBox.information(parent_dlg, "Chưa Chọn", "Vui lòng chọn một bản sao lưu trong danh sách.")
            return
        b_path = item.data(Qt.UserRole)
        ret = SafeRegistryCleaner.restore_backup(b_path)
        if ret.get("success"):
            QMessageBox.information(parent_dlg, "Hoàn Tác Thành Công", ret.get("message"))
            parent_dlg.accept()
            self.scan_registry()
        else:
            QMessageBox.warning(parent_dlg, "Lỗi Hoàn Tác", ret.get("message"))
