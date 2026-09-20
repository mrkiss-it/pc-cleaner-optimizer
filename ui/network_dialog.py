"""
Network Optimizer Dialog - Trung tâm Giám sát và Tối ưu hóa Mạng Internet.
Cung cấp:
1. Giám sát tốc độ mạng tải xuống / tải lên / ping thời gian thực.
2. 1-Click Tối ưu hóa mạng (Flush DNS, purge ARP/NetBIOS, tinh chỉnh TCP stack).
3. DNS Benchmark: Đo độ trễ các nhà cung cấp DNS hàng đầu.
4. Quản lý các tiến trình đang chiếm dụng kết nối mạng ngầm.
"""

from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QWidget, QFrame, QMessageBox, QTabWidget, QPlainTextEdit,
    QAbstractItemView
)

from core.network_optimizer import NetworkOptimizer
from core.system_monitor import SystemMonitor
from core.logger import logger


class DnsBenchmarkWorker(QThread):
    finished = pyqtSignal(list)

    def run(self):
        results = NetworkOptimizer.benchmark_dns()
        self.finished.emit(results)


class NetworkOptimizeWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(dict)

    def run(self):
        self.progress.emit("Đang xóa bộ nhớ đệm DNS (ipconfig /flushdns)...", 25)
        dns_res = NetworkOptimizer.flush_dns()

        self.progress.emit("Đang làm mới bảng định tuyến NetBIOS & ARP...", 50)
        arp_res = NetworkOptimizer.purge_arp_netbios()

        self.progress.emit("Đang tinh chỉnh cấu hình TCP/IP stack (Heuristics, Autotuning)...", 75)
        tcp_res = NetworkOptimizer.optimize_tcp_stack()

        self.progress.emit("Tối ưu hóa mạng hoàn tất!", 100)
        res = {
            "dns": dns_res,
            "arp": arp_res,
            "tcp": tcp_res,
            "success": True
        }
        self.finished.emit(res)


class NetworkOptimizerDialog(QDialog):
    """
    Hộp thoại Quản lý & Tối ưu hóa Mạng hiện đại.
    """

    def __init__(self, monitor_hub=None, parent=None):
        super().__init__(parent)
        self.monitor_hub = monitor_hub
        self.setWindowTitle("🌐 Trung Tâm Giám Sát & Tối Ưu Hóa Mạng - PC Optimizer")
        self.resize(920, 640)
        self.setMinimumSize(800, 540)
        self.setStyleSheet("""
            QDialog {
                background-color: #0f172a;
                color: #f8fafc;
                font-family: 'Segoe UI', sans-serif;
            }
            QTabWidget::pane {
                border: 1px solid #334155;
                background-color: #0f172a;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #1e293b;
                color: #94a3b8;
                padding: 10px 18px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-size: 12px;
                font-weight: 600;
            }
            QTabBar::tab:selected {
                background-color: #0284c7;
                color: #ffffff;
            }
            QTabBar::tab:hover:!selected {
                background-color: #334155;
                color: #f8fafc;
            }
        """)

        self.init_ui()

        # Kết nối timer cập nhật tốc độ mạng
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self._refresh_live_stats)
        self.monitor_timer.start(800)
        self._refresh_live_stats()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # ── HEADER ──
        header = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("🌐 TRUNG TÂM GIÁM SÁT & TỐI ƯU HÓA MẠNG")
        lbl_title.setStyleSheet("color: #38bdf8; font-size: 16px; font-weight: 800; letter-spacing: 0.5px;")
        lbl_sub = QLabel("Giám sát băng thông trực tiếp, xóa sạch bộ nhớ đệm DNS và tăng tốc đường truyền")
        lbl_sub.setStyleSheet("color: #94a3b8; font-size: 11px;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header.addLayout(title_box)
        header.addStretch()

        self.lbl_adapter_badge = QLabel("Card mạng: Đang tải...")
        self.lbl_adapter_badge.setStyleSheet("""
            background-color: #1e293b;
            color: #38bdf8;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 11px;
            font-weight: 600;
        """)
        header.addWidget(self.lbl_adapter_badge)
        main_layout.addLayout(header)

        # ── TABS ──
        self.tabs = QTabWidget()
        self.tab_boost = QWidget()
        self.tab_benchmark = QWidget()
        self.tab_processes = QWidget()

        self.tabs.addTab(self.tab_boost, "🚀 Tối Ưu Mạng 1-Click")
        self.tabs.addTab(self.tab_benchmark, "📶 Đo Độ Trễ DNS Benchmark")
        self.tabs.addTab(self.tab_processes, "📱 Tiến Trình Dùng Mạng")

        self.init_tab_boost()
        self.init_tab_benchmark()
        self.init_tab_processes()

        main_layout.addWidget(self.tabs)

        # ── FOOTER ──
        footer = QHBoxLayout()
        self.lbl_footer_status = QLabel("Trạng thái mạng: Bình thường")
        self.lbl_footer_status.setStyleSheet("color: #64748b; font-size: 11px;")
        footer.addWidget(self.lbl_footer_status)
        footer.addStretch()

        btn_close = QPushButton("Đóng")
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 18px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_close.clicked.connect(self.close)
        footer.addWidget(btn_close)
        main_layout.addLayout(footer)

    # ─────────────────────────────────────────────────────────────
    # TAB 1: TỐI ƯU MẠNG 1-CLICK & GIÁM SÁT TRỰC TIẾP
    # ─────────────────────────────────────────────────────────────
    def init_tab_boost(self):
        layout = QVBoxLayout(self.tab_boost)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # 1. Thẻ số liệu thời gian thực (Live Speed Cards)
        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)

        self.card_down = self._create_metric_card("⬇️ Tốc Độ Tải Xuống", "0.0 KB/s", "#38bdf8", "Lưu lượng nhận")
        self.card_up = self._create_metric_card("⬆️ Tốc Độ Tải Lên", "0.0 KB/s", "#34d399", "Lưu lượng gửi")
        self.card_ping = self._create_metric_card("📶 Độ Trễ (Ping)", "-- ms", "#fbbf24", "Tới Google DNS")
        self.card_total = self._create_metric_card("📊 Phiên Làm Việc", "0 MB", "#a78bfa", "Tổng dữ liệu truyền")

        cards_row.addWidget(self.card_down)
        cards_row.addWidget(self.card_up)
        cards_row.addWidget(self.card_ping)
        cards_row.addWidget(self.card_total)
        layout.addLayout(cards_row)

        # 2. Khối Tối Ưu Hóa (Action Box)
        action_frame = QFrame()
        action_frame.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        action_layout = QVBoxLayout(action_frame)
        action_layout.setSpacing(10)

        lbl_action_title = QLabel("⚡ GÓI TỐI ƯU HÓA ĐƯỜNG TRUYỀN TOÀN DIỆN")
        lbl_action_title.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold;")
        lbl_action_desc = QLabel(
            "Tự động làm sạch bộ nhớ đệm DNS bị kẹt, làm mới cấu hình bảng định danh ARP/NetBIOS "
            "và kích hoạt cấu hình tối ưu hóa TCP Heuristics & Auto-Tuning của Windows."
        )
        lbl_action_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        lbl_action_desc.setWordWrap(True)

        self.btn_run_optimize = QPushButton("🚀 TỐI ƯU HÓA MẠNG NGAY (1-CLICK BOOST)")
        self.btn_run_optimize.setCursor(Qt.PointingHandCursor)
        self.btn_run_optimize.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #06b6d4);
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
                padding: 12px 20px;
                border-radius: 8px;
                border: 1px solid #38bdf8;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0369a1, stop:1 #0891b2);
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748b;
                border: 1px solid #475569;
            }
        """)
        self.btn_run_optimize.clicked.connect(self._run_network_optimization)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 4px;
                height: 8px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #0284c7;
                border-radius: 3px;
            }
        """)

        action_layout.addWidget(lbl_action_title)
        action_layout.addWidget(lbl_action_desc)
        action_layout.addWidget(self.btn_run_optimize)
        action_layout.addWidget(self.progress_bar)
        layout.addWidget(action_frame)

        # 3. Nhật ký tiến trình (Log Area)
        lbl_log = QLabel("📋 Nhật ký tối ưu hóa:")
        lbl_log.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")
        layout.addWidget(lbl_log)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0b1329;
                color: #38bdf8;
                border: 1px solid #1e293b;
                border-radius: 8px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                padding: 8px;
            }
        """)
        self.txt_log.setPlainText("Sẵn sàng. Nhấn 'Tối Ưu Hóa Mạng Ngay' để bắt đầu.")
        layout.addWidget(self.txt_log)

    def _create_metric_card(self, title: str, val: str, val_color: str, sub: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 10px;
            }
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(12, 10, 12, 10)
        c_layout.setSpacing(4)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600;")

        lbl_v = QLabel(val)
        lbl_v.setStyleSheet(f"color: {val_color}; font-size: 20px; font-weight: bold;")

        lbl_s = QLabel(sub)
        lbl_s.setStyleSheet("color: #64748b; font-size: 10px;")

        c_layout.addWidget(lbl_t)
        c_layout.addWidget(lbl_v)
        c_layout.addWidget(lbl_s)
        card._lbl_val = lbl_v
        card._lbl_sub = lbl_s
        return card

    def _refresh_live_stats(self):
        """Cập nhật thông số mạng thời gian thực trên Tab 1."""
        net = SystemMonitor.get_network_info()
        self.card_down._lbl_val.setText(net["down_speed_str"])
        self.card_up._lbl_val.setText(net["up_speed_str"])

        ping = net.get("ping_ms", -1)
        if ping > 0:
            self.card_ping._lbl_val.setText(f"{ping:.1f} ms")
            if ping < 50:
                self.card_ping._lbl_val.setStyleSheet("color: #34d399; font-size: 20px; font-weight: bold;")
                self.card_ping._lbl_sub.setText("Độ trễ thấp • Rất mượt 🟢")
            elif ping < 100:
                self.card_ping._lbl_val.setStyleSheet("color: #fbbf24; font-size: 20px; font-weight: bold;")
                self.card_ping._lbl_sub.setText("Độ trễ ổn định 🟡")
            else:
                self.card_ping._lbl_val.setStyleSheet("color: #f43f5e; font-size: 20px; font-weight: bold;")
                self.card_ping._lbl_sub.setText("Độ trễ cao 🔴")
        elif not net.get("ping_measured"):
            self.card_ping._lbl_val.setText("-- ms")
            self.card_ping._lbl_sub.setText("Đang đo...")
        else:
            self.card_ping._lbl_val.setText("-- ms")
            self.card_ping._lbl_val.setStyleSheet("color: #94a3b8; font-size: 20px; font-weight: bold;")
            status = net.get("ping_status") or "timeout"
            self.card_ping._lbl_sub.setText(f"Không đo được ({status}) • kiểm tra mạng")

        tot_mb = net.get("total_recv_mb", 0) + net.get("total_sent_mb", 0)
        self.card_total._lbl_val.setText(f"{tot_mb:.1f} MB")
        self.card_total._lbl_sub.setText(f"↓ {net.get('total_recv_mb', 0):.0f}MB | ↑ {net.get('total_sent_mb', 0):.0f}MB")

        adapter = net.get("adapter", "Wi-Fi")
        self.lbl_adapter_badge.setText(f"Card mạng: {adapter}")

    def _run_network_optimization(self):
        self.btn_run_optimize.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.txt_log.setPlainText("Bắt đầu quá trình tối ưu hóa mạng...")

        self.opt_worker = NetworkOptimizeWorker()
        self.opt_worker.progress.connect(self._on_optimize_progress)
        self.opt_worker.finished.connect(self._on_optimize_finished)
        self.opt_worker.start()

    def _on_optimize_progress(self, msg: str, pct: int):
        self.progress_bar.setValue(pct)
        self.txt_log.appendPlainText(f"[{pct}%] {msg}")

    def _on_optimize_finished(self, res: dict):
        self.btn_run_optimize.setEnabled(True)
        self.progress_bar.setValue(100)
        self.txt_log.appendPlainText("\n✨ KẾT QUẢ TỐI ƯU HÓA HOÀN TẤT:")
        self.txt_log.appendPlainText(f"  • DNS: {res['dns']['message']}")
        self.txt_log.appendPlainText(f"  • ARP/NetBIOS: {res['arp']['message']}")
        self.txt_log.appendPlainText(f"  • TCP Stack: {res['tcp']['message']}")
        for d in res['tcp'].get("details", []):
            self.txt_log.appendPlainText(f"    - {d}")

        QMessageBox.information(
            self,
            "Tối Ưu Thành Công",
            "Đã hoàn tất dọn dẹp bộ nhớ đệm DNS và tinh chỉnh TCP/IP stack!\n"
            "Đường truyền mạng của bạn hiện đã được làm mới và tối ưu."
        )

    # ─────────────────────────────────────────────────────────────
    # TAB 2: ĐO ĐỘ TRỄ DNS BENCHMARK
    # ─────────────────────────────────────────────────────────────
    def init_tab_benchmark(self):
        layout = QVBoxLayout(self.tab_benchmark)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        desc_box = QHBoxLayout()
        lbl_info = QLabel(
            "Đo thời gian phản hồi (Ping) tới các hệ thống máy chủ phân giải tên miền (DNS) hàng đầu thế giới.\n"
            "Máy chủ có độ trễ càng thấp sẽ giúp mở các trang web và ứng dụng trực tuyến nhanh hơn."
        )
        lbl_info.setStyleSheet("color: #94a3b8; font-size: 12px;")
        lbl_info.setWordWrap(True)

        self.btn_benchmark = QPushButton("🔍 Đo Độ Trễ DNS Ngay")
        self.btn_benchmark.setProperty("class", "btn-primary")
        self.btn_benchmark.setCursor(Qt.PointingHandCursor)
        self.btn_benchmark.setStyleSheet("""
            QPushButton {
                background-color: #0284c7;
                color: #ffffff;
                font-weight: bold;
                padding: 8px 18px;
                border-radius: 6px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #0369a1; }
        """)
        self.btn_benchmark.clicked.connect(self._run_dns_benchmark)

        desc_box.addWidget(lbl_info, stretch=1)
        desc_box.addWidget(self.btn_benchmark)
        layout.addLayout(desc_box)

        # Table
        self.table_dns = QTableWidget()
        self.table_dns.setColumnCount(5)
        self.table_dns.setHorizontalHeaderLabels([
            "Nhà Cung Cấp DNS", "Địa Chỉ IP", "Độ Trễ (ms)", "Trạng Thái", "Đặc Điểm & Khuyến Nghị"
        ])
        self.table_dns.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_dns.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_dns.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_dns.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_dns.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table_dns.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_dns.setStyleSheet("""
            QTableWidget {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                gridline-color: #334155;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #0f172a;
                color: #94a3b8;
                padding: 6px;
                border: 1px solid #334155;
                font-weight: 600;
            }
            QTableWidget::item:selected {
                background-color: #0369a1;
            }
        """)
        layout.addWidget(self.table_dns)

        # Tip Box
        tip_frame = QFrame()
        tip_frame.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 8px;")
        tip_layout = QHBoxLayout(tip_frame)
        lbl_tip_icon = QLabel("💡")
        lbl_tip_icon.setStyleSheet("font-size: 16px;")
        self.lbl_recommendation = QLabel("Mẹo: Nhấn 'Đo Độ Trễ DNS Ngay' để tìm máy chủ DNS tối ưu nhất.")
        self.lbl_recommendation.setStyleSheet("color: #38bdf8; font-size: 11px;")
        tip_layout.addWidget(lbl_tip_icon)
        tip_layout.addWidget(self.lbl_recommendation, stretch=1)
        layout.addWidget(tip_frame)

    def _run_dns_benchmark(self):
        self.btn_benchmark.setEnabled(False)
        self.btn_benchmark.setText("Đang đo đạc...")
        self.lbl_recommendation.setText("Đang đo độ trễ các máy chủ DNS qua kết nối socket TCP...")

        self.bench_worker = DnsBenchmarkWorker()
        self.bench_worker.finished.connect(self._on_dns_benchmark_finished)
        self.bench_worker.start()

    def _on_dns_benchmark_finished(self, results: list):
        self.btn_benchmark.setEnabled(True)
        self.btn_benchmark.setText("🔍 Đo Độ Trễ DNS Ngay")
        self.table_dns.setRowCount(len(results))

        best_dns = None
        for row, r in enumerate(results):
            if best_dns is None and r["latency_ms"] > 0:
                best_dns = r

            self.table_dns.setItem(row, 0, QTableWidgetItem(f"🛡️  {r['name']}"))
            self.table_dns.setItem(row, 1, QTableWidgetItem(r["ip"]))
            lat_str = f"{r['latency_ms']:.1f} ms" if r["latency_ms"] > 0 else "Timeout"
            lat_item = QTableWidgetItem(lat_str)
            lat_item.setTextAlignment(Qt.AlignCenter)
            self.table_dns.setItem(row, 2, lat_item)
            self.table_dns.setItem(row, 3, QTableWidgetItem(r["status"]))
            self.table_dns.setItem(row, 4, QTableWidgetItem(r["description"]))

        if best_dns:
            self.lbl_recommendation.setText(
                f"🌟 Khuyến nghị: {best_dns['name']} ({best_dns['ip']}) đang cho độ trễ thấp nhất "
                f"({best_dns['latency_ms']:.1f} ms). Đây là lựa chọn lý tưởng cho đường truyền của bạn!"
            )
        else:
            self.lbl_recommendation.setText("Không thể đo đạc DNS. Hãy kiểm tra kết nối mạng của bạn.")

    # ─────────────────────────────────────────────────────────────
    # TAB 3: TIẾN TRÌNH CHIẾM BĂNG THÔNG MẠNG
    # ─────────────────────────────────────────────────────────────
    def init_tab_processes(self):
        layout = QVBoxLayout(self.tab_processes)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        ctrl_row = QHBoxLayout()
        lbl_p_desc = QLabel("Các ứng dụng đang mở kết nối Internet truyền nhận dữ liệu:")
        lbl_p_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")

        btn_refresh = QPushButton("🔄 Làm Mới")
        btn_refresh.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        btn_refresh.clicked.connect(self._refresh_net_processes)

        self.btn_kill_proc = QPushButton("🛑 Đóng Tiến Trình Đã Chọn")
        self.btn_kill_proc.setStyleSheet("""
            QPushButton {
                background-color: #7f1d1d;
                color: #fecaca;
                border: 1px solid #b91c1c;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #991b1b; }
        """)
        self.btn_kill_proc.clicked.connect(self._terminate_selected_process)

        ctrl_row.addWidget(lbl_p_desc, stretch=1)
        ctrl_row.addWidget(btn_refresh)
        ctrl_row.addWidget(self.btn_kill_proc)
        layout.addLayout(ctrl_row)

        # Table
        self.table_procs = QTableWidget()
        self.table_procs.setColumnCount(7)
        self.table_procs.setHorizontalHeaderLabels([
            "Ứng Dụng", "PID", "Phân Loại", "Kết Nối Đang Mở", "Tổng Socket", "RAM (MB)", "Bảo Vệ"
        ])
        self.table_procs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_procs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table_procs.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_procs.setStyleSheet("""
            QTableWidget {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 8px;
                gridline-color: #334155;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #0f172a;
                color: #94a3b8;
                padding: 6px;
                border: 1px solid #334155;
                font-weight: 600;
            }
            QTableWidget::item:selected {
                background-color: #0369a1;
            }
        """)
        layout.addWidget(self.table_procs)
        self._refresh_net_processes()

    def _refresh_net_processes(self):
        procs = NetworkOptimizer.get_network_processes(limit=30)
        self.table_procs.setRowCount(len(procs))

        for row, p in enumerate(procs):
            icon = "🌐"
            if p["category"] == "Trình duyệt":
                icon = "🌍"
            elif p["category"] == "Trò chơi":
                icon = "🎮"
            elif p["category"] == "Đồng bộ đám mây":
                icon = "☁️"
            elif p["category"] == "Chia sẻ tệp P2P":
                icon = "📥"
            elif p["category"] == "Nhắn tin & Gọi":
                icon = "💬"
            elif p["category"] == "Hệ thống":
                icon = "⚙️"

            item_name = QTableWidgetItem(f"{icon}  {p['name']}")
            item_name.setData(Qt.UserRole, p["pid"])
            self.table_procs.setItem(row, 0, item_name)

            self.table_procs.setItem(row, 1, QTableWidgetItem(str(p["pid"])))
            self.table_procs.setItem(row, 2, QTableWidgetItem(p["category"]))

            c_est = QTableWidgetItem(str(p["established"]))
            c_est.setTextAlignment(Qt.AlignCenter)
            self.table_procs.setItem(row, 3, c_est)

            c_tot = QTableWidgetItem(str(p["total_connections"]))
            c_tot.setTextAlignment(Qt.AlignCenter)
            self.table_procs.setItem(row, 4, c_tot)

            c_ram = QTableWidgetItem(f"{p['mem_mb']:.1f}")
            c_ram.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table_procs.setItem(row, 5, c_ram)

            badge = "🛡️ Hệ thống" if p["is_protected"] else "Có thể đóng"
            b_item = QTableWidgetItem(badge)
            b_item.setTextAlignment(Qt.AlignCenter)
            if p["is_protected"]:
                b_item.setForeground(QColor("#38bdf8"))
            else:
                b_item.setForeground(QColor("#a78bfa"))
            self.table_procs.setItem(row, 6, b_item)

    def _terminate_selected_process(self):
        row = self.table_procs.currentRow()
        if row < 0:
            QMessageBox.information(self, "Chưa Chọn", "Vui lòng chọn một tiến trình trong bảng để đóng.")
            return

        item = self.table_procs.item(row, 0)
        pid = item.data(Qt.UserRole)
        name = item.text().split("  ")[-1]

        reply = QMessageBox.question(
            self,
            "Xác Nhận Đóng Ứng Dụng",
            f"Bạn có chắc muốn đóng tiến trình '{name}' (PID: {pid}) để giải phóng băng thông mạng?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            res = NetworkOptimizer.terminate_process(pid)
            if res["success"]:
                QMessageBox.information(self, "Thành Công", res["message"])
                self._refresh_net_processes()
            else:
                QMessageBox.warning(self, "Không Thể Đóng", res["message"])
