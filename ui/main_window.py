import os
from datetime import datetime
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QColor
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QTabWidget, QFrame, QProgressBar, QTableWidget, 
    QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox, QComboBox, 
    QMessageBox, QPlainTextEdit, QLineEdit, QListWidget, QListWidgetItem,
    QScrollArea, QSplitter
)

from config_manager import ConfigManager
from startup_manager import StartupManager
from core.system_monitor import SystemMonitor
from core.cleaner import JunkCleaner
from core.memory_optimizer import MemoryOptimizer
from core.game_booster import GameBooster
from core.process_manager import ProcessManager
from core.analytics_reporter import AnalyticsReporter
from ui.widgets import CircularGauge, StatCard, CleanerTargetRow
from ui.styles import DARK_THEME
from ui.large_files_dialog import LargeFilesDialog
from ui.disk_analyzer_dialog import DiskAnalyzerDialog
from ui.network_dialog import NetworkOptimizerDialog
from ui.disk_registry_dialog import DiskRegistryDialog
from ui.hardware_dialog import HardwareMonitorDialog
from ui.ai_advisor_dialog import AIAdvisorDialog
from ui.service_context_dialog import ServiceContextDialog
from core.ai_advisor import AIAdvisor
from core.system_tweaker import SystemTweaker


# Worker Thread for Background Scan & Clean to keep GUI completely smooth
class CleanWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(dict)

    def __init__(self, targets: dict, is_scan_only: bool = False, whitelist: set = None):
        super().__init__()
        self.targets = targets
        self.is_scan_only = is_scan_only
        self.whitelist = whitelist or set()

    def run(self):
        if self.is_scan_only:
            self.progress.emit("Đang quét các vị trí rác...", 30)
            res = JunkCleaner.scan(self.targets)
            self.progress.emit("Quét hoàn tất!", 100)
            self.finished.emit({"type": "scan", "data": res})
        else:
            self.progress.emit("Đang bắt đầu dọn dẹp...", 5)
            # Dọn rác file
            clean_res = JunkCleaner.clean(self.targets, progress_callback=lambda msg, pct: self.progress.emit(msg, pct))
            
            # Tối ưu RAM nếu được chọn
            ram_res = {}
            if self.targets.get("ram_optimize", True):
                self.progress.emit("Đang tối ưu hóa bộ nhớ RAM...", 90)
                ram_res = MemoryOptimizer.optimize_ram(whitelist=self.whitelist)

            self.progress.emit("Hoàn thành dọn dẹp!", 100)
            self.finished.emit({
                "type": "clean", 
                "clean_res": clean_res, 
                "ram_res": ram_res
            })


class SecurityScanWorker(QThread):
    step_started = pyqtSignal(dict)
    step_finished = pyqtSignal(dict)
    all_finished = pyqtSignal(dict)

    def run(self):
        from core.security_scanner import SecurityScanner
        def _cb(ev_type, data):
            if ev_type == "start_check":
                self.step_started.emit(data)
            elif ev_type == "check_done":
                self.step_finished.emit(data)

        summary = SecurityScanner.run_full_scan(progress_callback=_cb)
        self.all_finished.emit(summary)


class ApplyBestDnsWorker(QThread):
    finished = pyqtSignal(dict)

    def run(self):
        try:
            from core.network_optimizer import NetworkOptimizer
            res = NetworkOptimizer.apply_best_dns(allow_elevation=True)
            self.finished.emit(res)
        except Exception as e:
            self.finished.emit({
                "success": False,
                "message": f"Lỗi trong quá trình benchmark và áp dụng DNS: {e}"
            })


class MainWindow(QMainWindow):
    floating_widget_toggled = pyqtSignal(bool)
    floating_widget_opacity_changed = pyqtSignal(int)

    def __init__(self, config_manager: ConfigManager, tray_manager=None, monitor_hub=None):
        super().__init__()
        self.config_manager = config_manager
        self.tray_manager = tray_manager
        self.monitor_hub = monitor_hub
        self.worker = None
        self.first_minimize_notified = False
        self.system_tweaker = SystemTweaker()

        # AI Advisor – khởi tạo rule engine
        self._ai_advisor = AIAdvisor(
            config_path=self.config_manager.config_path,
            config_manager=self.config_manager
        )

        from core.network_optimizer import NetworkOptimizer
        if NetworkOptimizer.is_admin():
            self.setWindowTitle("PC Auto Cleaner & RAM Optimizer [Administrator]")
        else:
            self.setWindowTitle("PC Auto Cleaner & RAM Optimizer")
        self.resize(1000, 680)
        self.setMinimumSize(880, 580)
        self.setStyleSheet(DARK_THEME)

        if self.tray_manager:
            self.setWindowIcon(self.tray_manager.icon())

        self.init_ui()
        self.load_settings_into_ui()
        self.refresh_history_table()

        # Đồng bộ hóa dữ liệu thời gian thực từ trạm điều phối trung tâm
        if self.monitor_hub:
            self.monitor_hub.stats_updated.connect(self.update_system_stats)
            self.monitor_hub.stats_updated.connect(self._ai_advisor.feed_snapshot)
            self.update_system_stats(self.monitor_hub.get_latest())
        else:
            self.monitor_timer = QTimer(self)
            self.monitor_timer.timeout.connect(self.update_system_stats)
            self.monitor_timer.start(1000)
            self.update_system_stats()

        # Feed AI với dữ liệu bảo mật từ config
        try:
            self._ai_advisor.update_security_info(
                self.config_manager.config.get("last_security_scan_result", {})
            )
        except Exception:
            pass

        # Timer cập nhật badge AI button mỗi 10 giây
        self._ai_badge_timer = QTimer(self)
        self._ai_badge_timer.timeout.connect(self._update_ai_badge)
        self._ai_badge_timer.start(10_000)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 16, 18, 16)
        main_layout.setSpacing(14)

        # 1. Top Header Bar
        main_layout.addLayout(self.create_header())

        # 2. Main Tab Widget
        self.tabs = QTabWidget()
        self.tab_dashboard = QWidget()
        self.tab_performance = QWidget()
        self.tab_targets = QWidget()
        self.tab_automation = QWidget()
        self.tab_history = QWidget()
        self.tab_analytics = QWidget()   # Phase 4
        self.tab_security = QWidget()    # Security Scanner
        self.tab_tweaks = QWidget()      # System Tweaks & Privacy Shield

        self.init_tab_dashboard()
        self.init_tab_performance()
        self.init_tab_targets()
        self.init_tab_automation()
        self.init_tab_history()
        self.init_tab_analytics()  # Phase 4
        self.init_tab_security()   # Security Scanner
        self.init_tab_tweaks()     # System Tweaks & Privacy Shield

        self.tabs.addTab(self.tab_dashboard, "⚡ Bảng Điều Khiển")
        self.tabs.addTab(self.tab_performance, "🚀 Tiến Trình && Game Boost")
        self.tabs.addTab(self.tab_targets, "🧹 Tùy Chọn Dọn Dẹp")
        self.tabs.addTab(self.tab_automation, "⚙️ Tự Động && Lịch Trình")
        self.tabs.addTab(self.tab_history, "📊 Lịch Sử && Nhật Ký")
        self.tabs.addTab(self.tab_analytics, "🧠 Phân Tích Thông Minh")
        self.tabs.addTab(self.tab_security, "🔒 Bảo Mật")
        self.tabs.addTab(self.tab_tweaks, "🛡️ Tinh Chỉnh && Riêng Tư")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        main_layout.addWidget(self.tabs)

        # 3. Bottom Status Bar / Mini Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status = QLabel("Hệ thống hoạt động bình thường • Đang chạy ngầm tự động")
        self.lbl_status.setStyleSheet("color: #64748b; font-size: 11px;")

        status_layout = QHBoxLayout()
        status_layout.addWidget(self.lbl_status)
        status_layout.addStretch()
        status_layout.addWidget(self.progress_bar)
        main_layout.addLayout(status_layout)

    def create_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 0, 4, 4)

        # Title & Subtitle
        title_box = QVBoxLayout()
        lbl_app_title = QLabel("PC AUTO CLEANER & OPTIMIZER")
        lbl_app_title.setStyleSheet("color: #f8fafc; font-size: 18px; font-weight: 800; letter-spacing: 0.5px;")
        lbl_app_sub = QLabel("Tự động dọn rác, giải phóng RAM và duy trì tốc độ tối đa cho Windows")
        lbl_app_sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
        title_box.addWidget(lbl_app_title)
        title_box.addWidget(lbl_app_sub)

        # Background running badge
        self.badge_status = QLabel("● CHẠY NGẦM BẢO VỆ")
        self.badge_status.setStyleSheet("""
            background-color: #064e3b;
            color: #34d399;
            font-size: 11px;
            font-weight: bold;
            padding: 6px 14px;
            border-radius: 20px;
            border: 1px solid #059669;
        """)

        layout.addLayout(title_box)
        layout.addStretch()
        layout.addWidget(self.badge_status)
        return layout

    def init_tab_dashboard(self):
        layout = QVBoxLayout(self.tab_dashboard)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Row 1: Circular Gauges (RAM, CPU, DISK)
        gauge_layout = QHBoxLayout()
        gauge_layout.setSpacing(16)

        self.gauge_ram = CircularGauge(title="RAM", unit="%")
        self.gauge_cpu = CircularGauge(title="CPU", unit="%")
        self.gauge_disk = CircularGauge(title="Ổ ĐĨA C:", unit="%")

        gauge_layout.addStretch()
        gauge_layout.addWidget(self.gauge_ram)
        gauge_layout.addSpacing(20)
        gauge_layout.addWidget(self.gauge_cpu)
        gauge_layout.addSpacing(20)
        gauge_layout.addWidget(self.gauge_disk)
        gauge_layout.addStretch()

        layout.addLayout(gauge_layout)

        # Row 2: Primary Quick Action Buttons
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(12)

        self.btn_boost_now = QPushButton("🚀 DỌN DẸP && TỐI ƯU NGAY (1-CLICK)")
        self.btn_boost_now.setProperty("class", "btn-primary")
        self.btn_boost_now.setCursor(Qt.PointingHandCursor)
        self.btn_boost_now.clicked.connect(self.start_full_clean)

        self.btn_ram_only = QPushButton("⚡ Tối Ưu RAM Ngay")
        self.btn_ram_only.setProperty("class", "btn-success")
        self.btn_ram_only.setCursor(Qt.PointingHandCursor)
        self.btn_ram_only.clicked.connect(self.optimize_ram_only)

        self.btn_scan_only = QPushButton("🔍 Quét Thử Dung Lượng Rác")
        self.btn_scan_only.setProperty("class", "btn-secondary")
        self.btn_scan_only.setCursor(Qt.PointingHandCursor)
        self.btn_scan_only.clicked.connect(self.start_scan_only)

        btn_row1.addWidget(self.btn_boost_now, stretch=3)
        btn_row1.addWidget(self.btn_ram_only, stretch=2)
        btn_row1.addWidget(self.btn_scan_only, stretch=2)
        layout.addLayout(btn_row1)

        # Row 3: Specialized Utility & Optimization Tools
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(10)

        self.btn_network = QPushButton("🌐 Tối Ưu Mạng")
        self.btn_network.setProperty("class", "btn-secondary")
        self.btn_network.setCursor(Qt.PointingHandCursor)
        self.btn_network.clicked.connect(self.open_network_dialog)

        self.btn_game_boost = QPushButton("🎮 Game Boost: TẮT")
        self.btn_game_boost.setProperty("class", "btn-purple")
        self.btn_game_boost.setCursor(Qt.PointingHandCursor)
        self.btn_game_boost.clicked.connect(self.toggle_game_boost)

        self.btn_disk_reg = QPushButton("💽 Ổ Cứng && Registry")
        self.btn_disk_reg.setProperty("class", "btn-warning")
        self.btn_disk_reg.setCursor(Qt.PointingHandCursor)
        self.btn_disk_reg.clicked.connect(self.open_disk_registry_dialog)

        self.btn_large_files = QPushButton("📁 File Lớn (>100MB)")
        self.btn_large_files.setProperty("class", "btn-secondary")
        self.btn_large_files.setCursor(Qt.PointingHandCursor)
        self.btn_large_files.clicked.connect(self.open_large_files_dialog)

        self.btn_tweaks = QPushButton("🛡️ Tinh Chỉnh && Privacy")
        self.btn_tweaks.setProperty("class", "btn-secondary")
        self.btn_tweaks.setCursor(Qt.PointingHandCursor)
        self.btn_tweaks.clicked.connect(lambda: self.tabs.setCurrentWidget(self.tab_tweaks))

        self.btn_disk_analyzer = QPushButton("📊 Phân Tích Ổ Đĩa")
        self.btn_disk_analyzer.setProperty("class", "btn-secondary")
        self.btn_disk_analyzer.setCursor(Qt.PointingHandCursor)
        self.btn_disk_analyzer.clicked.connect(self.open_disk_analyzer)


        self.btn_hardware = QPushButton("🔋 Pin && Phần Cứng")
        self.btn_hardware.setProperty("class", "btn-secondary")
        self.btn_hardware.setCursor(Qt.PointingHandCursor)
        self.btn_hardware.clicked.connect(self.open_hardware_dialog)

        self.btn_ai_advisor = QPushButton("🤖 AI Gợi Ý")
        self.btn_ai_advisor.setProperty("class", "btn-secondary")
        self.btn_ai_advisor.setCursor(Qt.PointingHandCursor)
        self.btn_ai_advisor.clicked.connect(self.open_ai_advisor_dialog)
        # Badge style sẽ được cập nhật bởi _update_ai_badge()

        self.btn_services = QPushButton("⚙️ Dịch Vụ && Menu")
        self.btn_services.setProperty("class", "btn-secondary")
        self.btn_services.setCursor(Qt.PointingHandCursor)
        self.btn_services.clicked.connect(self.open_services_context_dialog)

        btn_row2.addWidget(self.btn_network, stretch=1)
        btn_row2.addWidget(self.btn_game_boost, stretch=1)
        btn_row2.addWidget(self.btn_disk_reg, stretch=1)
        btn_row2.addWidget(self.btn_hardware, stretch=1)
        btn_row2.addWidget(self.btn_services, stretch=1)
        btn_row2.addWidget(self.btn_ai_advisor, stretch=1)
        btn_row2.addWidget(self.btn_tweaks, stretch=1)
        btn_row2.addWidget(self.btn_large_files, stretch=1)
        btn_row2.addWidget(self.btn_disk_analyzer, stretch=1)
        layout.addLayout(btn_row2)


        # Row 3: Stat Cards
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(12)

        stats = self.config_manager.get_stats()
        self.card_junk = StatCard("🗑️", "Rác Đã Dọn", f"{stats['total_junk_freed_mb']:.1f} MB", "Dung lượng ổ cứng thu hồi")
        self.card_ram = StatCard("⚡", "RAM Đã Tối Ưu", f"{stats['total_ram_freed_mb']:.1f} MB", "Bộ nhớ RAM thu hồi")
        self.card_count = StatCard("🔄", "Tổng Số Lần Dọn", f"{stats['total_cleanups']} lần", "Bao gồm cả chạy ngầm tự động")
        self.card_net = StatCard("🌐", "Tốc Độ Mạng", "↓ 0.0 KB/s", "Tải lên: ↑ 0.0 KB/s • Ping: --")

        stats_layout.addWidget(self.card_junk)
        stats_layout.addWidget(self.card_ram)
        stats_layout.addWidget(self.card_count)
        stats_layout.addWidget(self.card_net)
        layout.addLayout(stats_layout)

    def init_tab_targets(self):
        outer_layout = QVBoxLayout(self.tab_targets)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        lbl_info = QLabel("Chọn các mục bạn muốn quét và dọn dẹp:")
        lbl_info.setStyleSheet("color: #94a3b8; font-weight: 600; margin-bottom: 4px;")
        layout.addWidget(lbl_info)

        cfg_targets = self.config_manager.get("targets", {})

        self.target_rows = {}
        target_defs = [
            ("user_temp", "File tạm người dùng (%TEMP%)", "Dữ liệu đệm phát sinh từ các ứng dụng đang chạy"),
            ("system_temp", "File tạm hệ thống (C:\\Windows\\Temp)", "File tạm được Windows tích lũy theo thời gian"),
            ("recycle_bin", "Thùng rác hệ thống (Recycle Bin)", "Các file đã bị xóa tạm thời nhưng chưa dọn sạch"),
            ("browser_cache", "Bộ nhớ đệm trình duyệt", "Cache của Chrome, Microsoft Edge, Firefox, Brave"),
            ("crash_dumps", "Báo cáo lỗi & Crash Dumps", "File ghi nhận lỗi ứng dụng và sự cố Windows (WER)"),
            ("windows_update", "Bộ nhớ đệm cập nhật Windows Update", "Tệp tải về trong C:\\Windows\\SoftwareDistribution\\Download"),
            ("app_caches", "Bộ nhớ đệm ứng dụng (Zalo, VS Code, Discord, Pip, Npm)", "Dọn dẹp an toàn các file tạm và cache không làm mất dữ liệu cá nhân"),
            ("ram_optimize", "Tối ưu hóa bộ nhớ RAM (EmptyWorkingSet)", "Thu hồi bộ nhớ không dùng từ các tiến trình nhàn rỗi")
        ]

        for key, title, desc in target_defs:
            checked = cfg_targets.get(key, True)
            row = CleanerTargetRow(key, title, desc, checked=checked)
            self.target_rows[key] = row
            layout.addWidget(row)

        layout.addStretch()
        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll, 1)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(16, 8, 16, 12)
        bottom_bar.addStretch()
        btn_save_targets = QPushButton("💾 Lưu Tùy Chọn Dọn Dẹp")
        btn_save_targets.setProperty("class", "btn-secondary")
        btn_save_targets.setCursor(Qt.PointingHandCursor)
        btn_save_targets.clicked.connect(self.save_targets_config)
        bottom_bar.addWidget(btn_save_targets)
        outer_layout.addLayout(bottom_bar)

    def init_tab_automation(self):
        outer_layout = QVBoxLayout(self.tab_automation)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        card_style = """
            QFrame#SettingCard {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
            }
        """

        # Card 1: Periodic Auto Clean
        card_periodic = QFrame()
        card_periodic.setObjectName("SettingCard")
        card_periodic.setStyleSheet(card_style)
        layout_periodic = QVBoxLayout(card_periodic)
        layout_periodic.setContentsMargins(18, 16, 18, 16)
        layout_periodic.setSpacing(10)

        self.chk_auto_clean = QCheckBox("Bật tự động dọn dẹp định kỳ chạy ngầm")
        self.chk_auto_clean.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        row_interval = QHBoxLayout()
        lbl_interval = QLabel("Chu kỳ dọn dẹp tự động:")
        lbl_interval.setStyleSheet("color: #94a3b8;")
        self.combo_interval = QComboBox()
        self.combo_interval.addItems(["Mỗi 15 phút", "Mỗi 30 phút", "Mỗi 1 giờ", "Mỗi 2 giờ", "Mỗi 4 giờ", "Mỗi 8 giờ"])
        row_interval.addWidget(lbl_interval)
        row_interval.addWidget(self.combo_interval)
        row_interval.addStretch()

        layout_periodic.addWidget(self.chk_auto_clean)
        layout_periodic.addLayout(row_interval)
        layout.addWidget(card_periodic)

        # Card 2: Smart RAM Threshold
        card_ram = QFrame()
        card_ram.setObjectName("SettingCard")
        card_ram.setStyleSheet(card_style)
        layout_ram = QVBoxLayout(card_ram)
        layout_ram.setContentsMargins(18, 16, 18, 16)
        layout_ram.setSpacing(10)

        self.chk_auto_ram = QCheckBox("Bật tự động tối ưu hóa RAM khi chạm ngưỡng quá tải")
        self.chk_auto_ram.setStyleSheet("font-weight: bold; font-size: 14px;")

        row_ram_spin = QHBoxLayout()
        lbl_ram_spin = QLabel("Ngưỡng phần trăm RAM kích hoạt:")
        lbl_ram_spin.setStyleSheet("color: #94a3b8;")
        self.spin_ram_threshold = QSpinBox()
        self.spin_ram_threshold.setRange(50, 95)
        self.spin_ram_threshold.setSuffix(" %")
        self.spin_ram_threshold.setValue(80)
        row_ram_spin.addWidget(lbl_ram_spin)
        row_ram_spin.addWidget(self.spin_ram_threshold)
        row_ram_spin.addStretch()

        layout_ram.addWidget(self.chk_auto_ram)
        layout_ram.addLayout(row_ram_spin)
        layout.addWidget(card_ram)

        # Card 3: Smart Auto Network Optimization
        card_network = QFrame()
        card_network.setObjectName("SettingCard")
        card_network.setStyleSheet(card_style)
        layout_network = QVBoxLayout(card_network)
        layout_network.setContentsMargins(18, 16, 18, 16)
        layout_network.setSpacing(10)

        self.chk_auto_net = QCheckBox("Bật tự động tối ưu hóa mạng (Flush DNS định kỳ & khi Ping cao)")
        self.chk_auto_net.setStyleSheet("font-weight: bold; font-size: 14px; color: #38bdf8;")

        row_ping_spin = QHBoxLayout()
        lbl_ping_spin = QLabel("Ngưỡng Ping tự động kích hoạt tối ưu:")
        lbl_ping_spin.setStyleSheet("color: #94a3b8;")
        self.spin_ping_threshold = QSpinBox()
        self.spin_ping_threshold.setRange(80, 500)
        self.spin_ping_threshold.setSingleStep(10)
        self.spin_ping_threshold.setSuffix(" ms")
        self.spin_ping_threshold.setValue(self.config_manager.get("auto_network_ping_threshold_ms", 180))

        lbl_net_desc = QLabel(
            "Tự động xóa sạch bộ nhớ đệm DNS bị kẹt khi dọn dẹp định kỳ hoặc khi độ trễ Ping vượt ngưỡng."
        )
        lbl_net_desc.setStyleSheet("color: #64748b; font-size: 11px;")
        lbl_net_desc.setWordWrap(True)

        row_ping_spin.addWidget(lbl_ping_spin)
        row_ping_spin.addWidget(self.spin_ping_threshold)
        row_ping_spin.addStretch()

        layout_network.addWidget(self.chk_auto_net)
        layout_network.addLayout(row_ping_spin)
        layout_network.addWidget(lbl_net_desc)
        layout.addWidget(card_network)

        # Card 4: Auto Best-DNS Switcher
        card_dns = QFrame()
        card_dns.setObjectName("SettingCard")
        card_dns.setStyleSheet(card_style)
        layout_dns = QVBoxLayout(card_dns)
        layout_dns.setContentsMargins(18, 16, 18, 16)
        layout_dns.setSpacing(10)

        self.chk_auto_best_dns = QCheckBox(
            "🌐 Tự động Benchmark && Chuyển DNS Tốt Nhất Định Kỳ"
        )
        self.chk_auto_best_dns.setStyleSheet("font-weight: bold; font-size: 14px; color: #a78bfa;")

        from core.network_optimizer import NetworkOptimizer
        admin_hint = "" if NetworkOptimizer.is_admin() else " (Yêu cầu quyền Administrator nếu chưa cấp)."
        lbl_dns_desc = QLabel(
            f"Tự động đo độ trễ định kỳ các máy chủ DNS (Cloudflare, Google, NextDNS, Quad9, AdGuard...) "
            f"rồi áp dụng DNS phản hồi nhanh nhất cho card mạng.{admin_hint}"
        )
        lbl_dns_desc.setStyleSheet("color: #64748b; font-size: 11px;")
        lbl_dns_desc.setWordWrap(True)

        row_dns_interval = QHBoxLayout()
        lbl_dns_interval = QLabel("Đo lường lại sau mỗi:")
        lbl_dns_interval.setStyleSheet("color: #94a3b8;")
        self.combo_dns_interval = QComboBox()
        self.combo_dns_interval.addItems([
            "Mỗi 1 giờ", "Mỗi 2 giờ", "Mỗi 4 giờ", "Mỗi 8 giờ", "Mỗi 12 giờ", "Mỗi 24 giờ"
        ])
        row_dns_interval.addWidget(lbl_dns_interval)
        row_dns_interval.addWidget(self.combo_dns_interval)
        row_dns_interval.addStretch()

        # Quick Apply Button with explicit high-contrast styling
        self.btn_apply_best_dns = QPushButton("⚡ Benchmark && Áp Dụng DNS Tốt Nhất Ngay")
        self.btn_apply_best_dns.setCursor(Qt.PointingHandCursor)
        self.btn_apply_best_dns.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
                padding: 10px 20px;
                border-radius: 8px;
                border: 1px solid #475569;
            }
            QPushButton:hover {
                background-color: #475569;
                border-color: #38bdf8;
            }
            QPushButton:pressed {
                background-color: #1e293b;
            }
            QPushButton:disabled {
                background-color: #1e293b;
                color: #94a3b8;
                border: 1px solid #334155;
            }
        """)
        self.btn_apply_best_dns.clicked.connect(self._apply_best_dns_now)

        self.lbl_dns_status = QLabel("● Sẵn sàng")
        self.lbl_dns_status.setStyleSheet("color: #64748b; font-size: 11px;")
        self.lbl_dns_status.setWordWrap(True)

        layout_dns.addWidget(self.chk_auto_best_dns)
        layout_dns.addWidget(lbl_dns_desc)
        layout_dns.addLayout(row_dns_interval)
        layout_dns.addWidget(self.btn_apply_best_dns)
        layout_dns.addWidget(self.lbl_dns_status)
        layout.addWidget(card_dns)

        # Card: Auto Security Scanner
        card_security = QFrame()
        card_security.setObjectName("SettingCard")
        card_security.setStyleSheet(card_style)
        layout_sec = QVBoxLayout(card_security)
        layout_sec.setContentsMargins(18, 16, 18, 16)
        layout_sec.setSpacing(10)

        self.chk_auto_sec_scan = QCheckBox(
            "🛡️ Tự Động Rà Soát Lỗi Bảo Mật Hệ Thống Định Kỳ"
        )
        self.chk_auto_sec_scan.setStyleSheet("font-weight: bold; font-size: 14px; color: #38bdf8;")

        lbl_sec_desc = QLabel(
            "Tự động rà soát Windows Firewall, Antivirus, UAC, RDP, cổng mở bất thường, autorun đáng ngờ "
            "và cảnh báo khi phát hiện nguy cơ bảo mật."
        )
        lbl_sec_desc.setStyleSheet("color: #64748b; font-size: 11px;")
        lbl_sec_desc.setWordWrap(True)

        row_sec_interval = QHBoxLayout()
        lbl_sec_interval = QLabel("Chu kỳ rà soát tự động:")
        lbl_sec_interval.setStyleSheet("color: #94a3b8;")
        self.combo_sec_interval = QComboBox()
        self.combo_sec_interval.addItems([
            "Mỗi 6 giờ", "Mỗi 12 giờ", "Mỗi 24 giờ (Khuyến nghị)", "Mỗi 48 giờ"
        ])
        row_sec_interval.addWidget(lbl_sec_interval)
        row_sec_interval.addWidget(self.combo_sec_interval)
        row_sec_interval.addStretch()

        layout_sec.addWidget(self.chk_auto_sec_scan)
        layout_sec.addWidget(lbl_sec_desc)
        layout_sec.addLayout(row_sec_interval)
        layout.addWidget(card_security)

        # Card 5: Windows Startup & Tray Behavior
        card_system = QFrame()
        card_system.setObjectName("SettingCard")
        card_system.setStyleSheet(card_style)
        layout_system = QVBoxLayout(card_system)
        layout_system.setContentsMargins(18, 16, 18, 16)
        layout_system.setSpacing(10)

        self.chk_startup = QCheckBox("Tự động khởi động cùng Windows (Run on Windows Startup)")
        self.chk_minimize_tray = QCheckBox("Thu nhỏ xuống khay hệ thống khi bấm nút đóng [X] (Không tắt ứng dụng)")
        self.chk_notifications = QCheckBox("Hiển thị thông báo Windows sau khi dọn dẹp ngầm thành công")
        self.chk_floating_widget = QCheckBox("Hiển thị Widget mini nổi trên màn hình Desktop (Kéo thả & Tối ưu RAM nhanh)")
        self.chk_leak_detection = QCheckBox("Bật phát hiện rò rỉ bộ nhớ RAM (Memory Leak Detection – giám sát mỗi 30 giây)")

        layout_system.addWidget(self.chk_startup)
        layout_system.addWidget(self.chk_minimize_tray)
        layout_system.addWidget(self.chk_notifications)
        layout_system.addWidget(self.chk_floating_widget)
        layout_system.addWidget(self.chk_leak_detection)

        # Widget Opacity Setting
        row_opacity = QHBoxLayout()
        lbl_opacity = QLabel("Độ trong suốt của Widget Desktop:")
        lbl_opacity.setStyleSheet("color: #94a3b8;")
        self.spin_opacity = QSpinBox()
        self.spin_opacity.setRange(40, 100)
        self.spin_opacity.setSuffix(" %")
        self.spin_opacity.setValue(self.config_manager.get("floating_widget_opacity", 92))
        self.spin_opacity.valueChanged.connect(self._on_opacity_changed)
        row_opacity.addWidget(lbl_opacity)
        row_opacity.addWidget(self.spin_opacity)
        row_opacity.addStretch()
        layout_system.addLayout(row_opacity)

        # Create Desktop Shortcut Button
        self.btn_create_desktop_shortcut = QPushButton("📌 Tạo Biểu Tượng Lối Tắt (Shortcut) Ra Màn Hình Desktop")
        self.btn_create_desktop_shortcut.setProperty("class", "btn-secondary")
        self.btn_create_desktop_shortcut.setCursor(Qt.PointingHandCursor)
        self.btn_create_desktop_shortcut.clicked.connect(self.create_desktop_shortcut)
        layout_system.addWidget(self.btn_create_desktop_shortcut)

        layout.addWidget(card_system)
        layout.addStretch()
        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll, 1)

        # Fixed Bottom Action Bar for Quick Apply
        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(16, 8, 16, 12)
        btn_apply = QPushButton("💾 Áp Dụng Cài Đặt Tự Động Hóa")
        btn_apply.setProperty("class", "btn-primary")
        btn_apply.setCursor(Qt.PointingHandCursor)
        btn_apply.clicked.connect(self.save_automation_settings)
        bottom_bar.addWidget(btn_apply)
        outer_layout.addLayout(bottom_bar)

    def init_tab_history(self):
        layout = QVBoxLayout(self.tab_history)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header_layout = QHBoxLayout()
        lbl_title = QLabel("Nhật ký các lần dọn dẹp và tối ưu gần đây:")
        lbl_title.setStyleSheet("color: #94a3b8; font-weight: 600;")
        
        btn_health = QPushButton("🩺 Chẩn Đoán")
        btn_health.setProperty("class", "btn-secondary")
        btn_health.setStyleSheet("padding: 6px 12px; font-size: 12px;")
        btn_health.clicked.connect(self.run_system_health_check)

        btn_open_log = QPushButton("📄 File app.log")
        btn_open_log.setProperty("class", "btn-secondary")
        btn_open_log.setStyleSheet("padding: 6px 12px; font-size: 12px;")
        btn_open_log.clicked.connect(self.open_log_file)

        btn_refresh_log = QPushButton("🔄 Làm Mới")
        btn_refresh_log.setProperty("class", "btn-secondary")
        btn_refresh_log.setStyleSheet("padding: 6px 12px; font-size: 12px;")
        btn_refresh_log.clicked.connect(self.refresh_log_viewer)

        btn_clear_hist = QPushButton("🗑️ Xóa Lịch Sử")
        btn_clear_hist.setProperty("class", "btn-secondary")
        btn_clear_hist.setStyleSheet("padding: 6px 12px; font-size: 12px;")
        btn_clear_hist.clicked.connect(self.clear_history)

        header_layout.addWidget(lbl_title)
        header_layout.addStretch()
        header_layout.addWidget(btn_health)
        header_layout.addWidget(btn_open_log)
        header_layout.addWidget(btn_refresh_log)
        header_layout.addWidget(btn_clear_hist)
        layout.addLayout(header_layout)

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(4)
        self.table_history.setHorizontalHeaderLabels(["Thời Gian", "Loại Dọn Dẹp", "Rác Giải Phóng", "RAM Thu Hồi"])
        self.table_history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_history.verticalHeader().setVisible(False)
        layout.addWidget(self.table_history, stretch=1)

        # Live Log Terminal Viewer
        lbl_live_log = QLabel("Nhật ký chi tiết các sự kiện chạy của hệ thống (Live App Logs):")
        lbl_live_log.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600; margin-top: 4px;")
        layout.addWidget(lbl_live_log)

        self.txt_log_viewer = QPlainTextEdit()
        self.txt_log_viewer.setReadOnly(True)
        self.txt_log_viewer.setMaximumHeight(130)
        self.txt_log_viewer.setStyleSheet("""
            QPlainTextEdit {
                background-color: #020617;
                color: #38bdf8;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        layout.addWidget(self.txt_log_viewer)
        self.refresh_log_viewer()

    def load_settings_into_ui(self):
        cfg = self.config_manager.config

        # Automation
        self.chk_auto_clean.setChecked(cfg.get("auto_clean_enabled", True))
        self.chk_auto_ram.setChecked(cfg.get("auto_ram_optimize_enabled", True))
        self.spin_ram_threshold.setValue(cfg.get("ram_threshold_percent", 80))
        self.chk_minimize_tray.setChecked(cfg.get("minimize_to_tray_on_close", True))
        self.chk_notifications.setChecked(cfg.get("show_notifications", True))
        self.chk_floating_widget.setChecked(cfg.get("floating_widget_enabled", True))
        self.chk_leak_detection.setChecked(cfg.get("memory_leak_detection_enabled", True))
        self.chk_auto_net.setChecked(cfg.get("auto_network_optimize_enabled", True))
        self.spin_ping_threshold.setValue(cfg.get("auto_network_ping_threshold_ms", 180))

        # Auto Best-DNS
        self.chk_auto_best_dns.setChecked(cfg.get("auto_best_dns_enabled", False))
        dns_h_map = {1: 0, 2: 1, 4: 2, 8: 3, 12: 4, 24: 5}
        self.combo_dns_interval.setCurrentIndex(dns_h_map.get(cfg.get("auto_best_dns_interval_hours", 2), 1))

        # Auto Security Scan
        self.chk_auto_sec_scan.setChecked(cfg.get("auto_security_scan_enabled", True))
        sec_h_map = {6: 0, 12: 1, 24: 2, 48: 3}
        self.combo_sec_interval.setCurrentIndex(sec_h_map.get(cfg.get("auto_security_scan_interval_hours", 24), 2))

        # Windows Startup
        is_startup = StartupManager.is_startup_enabled()
        self.chk_startup.setChecked(is_startup)

        # Interval combo
        min_val = cfg.get("interval_minutes", 60)
        min_map = {15: 0, 30: 1, 60: 2, 120: 3, 240: 4, 480: 5}
        self.combo_interval.setCurrentIndex(min_map.get(min_val, 2))

    def save_targets_config(self):
        new_targets = {}
        for key, row in self.target_rows.items():
            new_targets[key] = row.is_checked()
        self.config_manager.set("targets", new_targets)
        QMessageBox.information(self, "Đã Lưu", "Đã lưu tùy chọn mục tiêu dọn dẹp thành công!")

    def save_automation_settings(self):
        interval_idx = self.combo_interval.currentIndex()
        min_lookup = [15, 30, 60, 120, 240, 480]
        interval_min = min_lookup[interval_idx]

        self.config_manager.set("auto_clean_enabled", self.chk_auto_clean.isChecked())
        self.config_manager.set("interval_minutes", interval_min)
        self.config_manager.set("auto_ram_optimize_enabled", self.chk_auto_ram.isChecked())
        self.config_manager.set("ram_threshold_percent", self.spin_ram_threshold.value())
        self.config_manager.set("auto_network_optimize_enabled", self.chk_auto_net.isChecked())
        self.config_manager.set("auto_network_ping_threshold_ms", self.spin_ping_threshold.value())

        # Auto Best-DNS
        dns_h_list = [1, 2, 4, 8, 12, 24]
        dns_interval_h = dns_h_list[self.combo_dns_interval.currentIndex()]
        self.config_manager.set("auto_best_dns_enabled", self.chk_auto_best_dns.isChecked())
        self.config_manager.set("auto_best_dns_interval_hours", dns_interval_h)

        # Auto Security Scanner
        sec_h_list = [6, 12, 24, 48]
        sec_interval_h = sec_h_list[self.combo_sec_interval.currentIndex()]
        self.config_manager.set("auto_security_scan_enabled", self.chk_auto_sec_scan.isChecked())
        self.config_manager.set("auto_security_scan_interval_hours", sec_interval_h)
        self.config_manager.set("minimize_to_tray_on_close", self.chk_minimize_tray.isChecked())
        self.config_manager.set("show_notifications", self.chk_notifications.isChecked())
        
        fw_enabled = self.chk_floating_widget.isChecked()
        self.config_manager.set("floating_widget_enabled", fw_enabled)
        self.floating_widget_toggled.emit(fw_enabled)

        self.config_manager.set("memory_leak_detection_enabled", self.chk_leak_detection.isChecked())

        # Update Windows Startup
        startup_enabled = self.chk_startup.isChecked()
        StartupManager.set_startup(startup_enabled)
        self.config_manager.set("run_on_startup", startup_enabled)

        QMessageBox.information(self, "Đã Cập Nhật", "Cấu hình tự động hóa và lịch trình đã được lưu!")

    def _apply_best_dns_now(self):
        """
        Thực hiện benchmark DNS ngay lập tức và áp dụng DNS tốt nhất tìm được.
        - Nếu chạy bằng Admin: Thực thi trực tiếp trong ~0.5s, không hỏi hay xin quyền.
        - Nếu không chạy quyền Admin: Hỏi xác nhận trước để người dùng chủ động quyết định.
        """
        from core.network_optimizer import NetworkOptimizer
        is_admin = NetworkOptimizer.is_admin()

        if not is_admin:
            reply = QMessageBox.question(
                self,
                "Xác Nhận Đổi DNS Hệ Thống",
                "Tính năng đặt cấu hình DNS cho card mạng yêu cầu quyền Administrator của Windows.\n\n"
                "Bạn có muốn tiếp tục đo và cấp quyền UAC khi Windows yêu cầu không?\n\n"
                "(Lưu ý: Bạn hoàn toàn có thể sử dụng ứng dụng bình thường mà không cần quyền Admin).",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                self.lbl_dns_status.setText("● Đã hủy áp dụng DNS. Bạn có thể đo tốc độ DNS trong Hộp thoại Mạng.")
                self.lbl_dns_status.setStyleSheet("color: #94a3b8; font-size: 11px;")
                return

        if hasattr(self, "btn_apply_best_dns"):
            self.btn_apply_best_dns.setEnabled(False)
            self.btn_apply_best_dns.setText("⏳ Đang Benchmark && Đặt DNS...")
        if is_admin:
            self.lbl_dns_status.setText("⏳ Đang đo DNS song song và cập nhật trực tiếp (Admin Mode)...")
        else:
            self.lbl_dns_status.setText("⏳ Đang đo DNS song song (Vui lòng bấm 'Yes' nếu Windows hỏi cấp quyền UAC)...")
        self.lbl_dns_status.setStyleSheet("color: #fbbf24; font-size: 11px;")
        self.lbl_status.setText("🌐 Đang benchmark DNS servers và tự động chọn DNS nhanh nhất...")

        self.dns_apply_worker = ApplyBestDnsWorker()
        self.dns_apply_worker.finished.connect(self._on_best_dns_applied)
        self.dns_apply_worker.start()

        # Watchdog timeout phòng ngừa trường hợp treo ngoài ý muốn
        def _watchdog():
            if hasattr(self, "btn_apply_best_dns") and not self.btn_apply_best_dns.isEnabled():
                self.btn_apply_best_dns.setEnabled(True)
                self.btn_apply_best_dns.setText("⚡ Benchmark && Áp Dụng DNS Tốt Nhất Ngay")
                if "⏳" in self.lbl_dns_status.text():
                    self.lbl_dns_status.setText("⚠️ Quá trình kiểm tra mất nhiều thời gian hơn dự kiến.")
                    self.lbl_dns_status.setStyleSheet("color: #f87171; font-size: 11px;")
        QTimer.singleShot(20000, _watchdog)

    def _on_best_dns_applied(self, result: dict):
        if hasattr(self, "btn_apply_best_dns"):
            self.btn_apply_best_dns.setEnabled(True)
            self.btn_apply_best_dns.setText("⚡ Benchmark && Áp Dụng DNS Tốt Nhất Ngay")

        if result.get("success"):
            msg = result.get("message", "Đã áp dụng DNS tốt nhất thành công!")
            self.lbl_dns_status.setText(f"✅ {msg}")
            self.lbl_dns_status.setStyleSheet("color: #34d399; font-size: 11px;")
            self.lbl_status.setText(f"🌐 {msg}")
            if self.config_manager.get("show_notifications", True) and self.tray_manager:
                self.tray_manager.notify(
                    "Đã Chuyển DNS Tốt Nhất",
                    msg
                )
        else:
            err = result.get("message", "Không thể áp dụng DNS. Cần quyền Administrator.")
            self.lbl_dns_status.setText(f"⚠️ {err}")
            self.lbl_dns_status.setStyleSheet("color: #f87171; font-size: 11px;")
            self.lbl_status.setText(f"⚠️ {err}")

    def update_system_stats(self, stats: dict = None):
        if stats is None:
            stats = self.monitor_hub.get_latest() if self.monitor_hub else SystemMonitor.get_all_stats()

        ram = stats["ram"]
        cpu = stats["cpu"]
        disk = stats["disk"]

        # Update gauges
        self.gauge_ram.set_value(ram["percent"], f"{ram['used_gb']:.1f}/{ram['total_gb']:.1f} GB")
        self.gauge_cpu.set_value(cpu["percent"], f"{cpu['core_count']} Cores")
        self.gauge_disk.set_value(disk["percent"], f"Còn trống {disk['free_gb']:.1f} GB")

        # Update network speed card
        net = stats.get("net")
        if net and hasattr(self, "card_net"):
            down_str = net.get("down_speed_str", "0.0 KB/s")
            up_str = net.get("up_speed_str", "0.0 KB/s")
            ping = net.get("ping_ms", -1)
            ping_str = f"{ping:.0f} ms" if ping > 0 else "--"
            self.card_net.set_value(f"↓ {down_str}", f"Tải lên: ↑ {up_str} • Ping: {ping_str}")

        # Update tray tooltip
        if self.tray_manager:
            self.tray_manager.update_tooltip(ram["percent"], cpu["percent"])

    def refresh_history_table(self):
        history = self.config_manager.get("history", [])
        self.table_history.setRowCount(len(history))

        type_map = {
            "manual": "Thủ công (1-Click)",
            "auto_periodic": "Tự động (Định kỳ)",
            "ram_threshold": "Tự động (Ngưỡng RAM)",
            "quick_tray": "Khay hệ thống",
            "game_boost": "Game Boost"
        }

        for row_idx, item in enumerate(history):
            t_item = QTableWidgetItem(item.get("timestamp", ""))
            type_str = type_map.get(item.get("trigger_type", ""), item.get("trigger_type", ""))
            type_item = QTableWidgetItem(type_str)
            junk_item = QTableWidgetItem(f"{item.get('junk_freed_mb', 0):.1f} MB")
            ram_item = QTableWidgetItem(f"{item.get('ram_freed_mb', 0):.1f} MB")

            t_item.setTextAlignment(Qt.AlignCenter)
            type_item.setTextAlignment(Qt.AlignCenter)
            junk_item.setTextAlignment(Qt.AlignCenter)
            ram_item.setTextAlignment(Qt.AlignCenter)

            self.table_history.setItem(row_idx, 0, t_item)
            self.table_history.setItem(row_idx, 1, type_item)
            self.table_history.setItem(row_idx, 2, junk_item)
            self.table_history.setItem(row_idx, 3, ram_item)

        # Update summary stat cards
        stats = self.config_manager.get_stats()
        self.card_junk.set_value(f"{stats['total_junk_freed_mb']:.1f} MB")
        self.card_ram.set_value(f"{stats['total_ram_freed_mb']:.1f} MB")
        self.card_count.set_value(f"{stats['total_cleanups']} lần")

    def clear_history(self):
        confirm = QMessageBox.question(
            self, "Xác Nhận", 
            "Bạn có chắc chắn muốn xóa toàn bộ lịch sử dọn dẹp không?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.config_manager.set("history", [])
            self.refresh_history_table()

    def open_log_file(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_path = os.path.join(base_dir, "app.log")
        if os.path.exists(log_path):
            os.system(f'start "" notepad.exe "{log_path}"')
        else:
            QMessageBox.information(self, "Thông Báo", "Chưa có file app.log. File sẽ được tạo khi ứng dụng chạy.")

    def refresh_log_viewer(self):
        from core.logger import get_recent_logs
        logs = get_recent_logs(max_lines=60)
        self.txt_log_viewer.setPlainText(logs)
        self.txt_log_viewer.verticalScrollBar().setValue(
            self.txt_log_viewer.verticalScrollBar().maximum()
        )

    def run_system_health_check(self):
        from core.health_monitor import HealthMonitor
        report = HealthMonitor.run_health_check()
        self.refresh_log_viewer()

        status_icon = "✅" if report["status"] == "HEALTHY" else "⚠️"
        details = report.get("details", {})
        ram = details.get("ram", {})
        disk = details.get("disk", {})
        
        msg = (
            f"{status_icon} KẾT QUẢ CHẨN ĐOÁN HỆ THỐNG:\n\n"
            f"• Trạng thái tổng quan: {report['status']}\n"
            f"• Bộ nhớ RAM: {ram.get('percent', 0)}% (Trống {ram.get('available_gb', 0)} GB)\n"
            f"• Ổ đĩa hệ thống C:: Trống {disk.get('free_gb', 0)} GB / {disk.get('total_gb', 0)} GB\n"
            f"• Cấu hình config.json: {details.get('config', 'OK')}\n"
            f"• Cơ chế thu hồi RAM (Win32): {details.get('win32_empty_working_set', 'OK')}\n"
            f"• Số lỗi phát hiện trong log: {details.get('errors_in_log', 0)}\n\n"
        )
        if report.get("issues"):
            msg += "Cảnh báo:\n" + "\n".join(f"- {issue}" for issue in report["issues"]) + "\n\n"
        if report.get("fixes_applied"):
            msg += "Đã tự động sửa chữa:\n" + "\n".join(f"- {f}" for f in report["fixes_applied"]) + "\n\n"
        
        msg += "Chi tiết đã được ghi vào file app.log!"
        QMessageBox.information(self, "Chẩn Đoán Hệ Thống Hoàn Tất", msg)

    def start_scan_only(self):
        targets = {k: r.is_checked() for k, r in self.target_rows.items()}
        self._set_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(10)
        self.lbl_status.setText("Đang phân tích và quét rác hệ thống...")

        self.worker = CleanWorker(targets, is_scan_only=True)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def start_full_clean(self):
        targets = {k: r.is_checked() for k, r in self.target_rows.items()}
        whitelist = self.config_manager.get_whitelist_set()
        self._set_buttons_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(5)
        self.lbl_status.setText("Đang thực thi dọn dẹp và tối ưu hóa hệ thống...")

        self.worker = CleanWorker(targets, is_scan_only=False, whitelist=whitelist)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def optimize_ram_only(self):
        self.lbl_status.setText("Đang giải phóng bộ nhớ RAM...")
        whitelist = self.config_manager.get_whitelist_set()
        res = MemoryOptimizer.optimize_ram(whitelist=whitelist)
        freed = res.get("freed_mb", 0.0)
        p_before = res.get("percent_before", 0)
        p_after = res.get("percent_after", 0)

        self.config_manager.add_history(0.0, freed, trigger_type="manual")
        self.refresh_history_table()
        if hasattr(self, "_ai_advisor"):
            self._ai_advisor.invalidate_cache()
            self._update_ai_badge()
        if self.monitor_hub:
            self.monitor_hub.force_refresh()
        else:
            self.update_system_stats()

        msg = f"Đã giải phóng thành công {freed:.1f} MB RAM!\n(Mức sử dụng RAM giảm từ {p_before:.1f}% xuống {p_after:.1f}%)"
        self.lbl_status.setText(f"Tối ưu RAM hoàn tất: Thu hồi {freed:.1f} MB")
        QMessageBox.information(self, "Tối Ưu RAM Hoàn Tất", msg)

    def _on_worker_progress(self, msg: str, pct: int):
        self.lbl_status.setText(msg)
        self.progress_bar.setValue(pct)

    def _on_worker_finished(self, result: dict):
        self._set_buttons_enabled(True)
        self.progress_bar.setVisible(False)

        res_type = result.get("type")
        if res_type == "scan":
            data = result.get("data", {})
            total_mb = data.get("total_mb", 0.0)
            total_files = data.get("total_files", 0)
            
            # Update badges on targets tab
            for cat_key, info in data.get("categories", {}).items():
                if cat_key in self.target_rows:
                    mb = info.get("size_mb", 0)
                    cnt = info.get("file_count", 0)
                    self.target_rows[cat_key].set_badge(f"{mb:.1f} MB ({cnt} files)", is_warning=(mb > 100))

            self.lbl_status.setText(f"Quét hoàn tất: Phát hiện {total_mb:.1f} MB rác ({total_files} files)")
            QMessageBox.information(
                self, "Kết Quả Quét Rác", 
                f"Phát hiện tổng cộng {total_mb:.1f} MB dữ liệu rác ({total_files} files) có thể dọn dẹp an toàn!"
            )
        elif res_type == "clean":
            clean_res = result.get("clean_res", {})
            ram_res = result.get("ram_res", {})

            freed_junk_mb = clean_res.get("total_freed_mb", 0.0)
            freed_ram_mb = ram_res.get("freed_mb", 0.0)
            del_files = clean_res.get("total_deleted_files", 0)

            # Record history
            self.config_manager.add_history(freed_junk_mb, freed_ram_mb, trigger_type="manual")
            self.refresh_history_table()
            if hasattr(self, "_ai_advisor"):
                self._ai_advisor.invalidate_cache()
                self._update_ai_badge()
            if self.monitor_hub:
                self.monitor_hub.force_refresh()
            else:
                self.update_system_stats()

            msg = (
                f"✨ Dọn Dẹp & Tối Ưu Hoàn Tất!\n\n"
                f"• Dung lượng rác đã xóa: {freed_junk_mb:.1f} MB ({del_files} files)\n"
                f"• Bộ nhớ RAM đã giải phóng: {freed_ram_mb:.1f} MB\n"
            )
            self.lbl_status.setText(f"Đã giải phóng: {freed_junk_mb:.1f} MB rác và {freed_ram_mb:.1f} MB RAM")
            
            if self.tray_manager and self.config_manager.get("show_notifications", True):
                self.tray_manager.notify("PC Cleaner: Hoàn tất dọn dẹp", f"Đã giải phóng {freed_junk_mb:.1f} MB rác và {freed_ram_mb:.1f} MB RAM!")
            
            QMessageBox.information(self, "Thành Công", msg)

    def _set_buttons_enabled(self, enabled: bool):
        self.btn_boost_now.setEnabled(enabled)
        self.btn_scan_only.setEnabled(enabled)
        self.btn_ram_only.setEnabled(enabled)
        if hasattr(self, "btn_large_files"):
            self.btn_large_files.setEnabled(enabled)
        if hasattr(self, "btn_disk_analyzer"):
            self.btn_disk_analyzer.setEnabled(enabled)
        if hasattr(self, "btn_network"):
            self.btn_network.setEnabled(enabled)
        if hasattr(self, "btn_game_boost"):
            self.btn_game_boost.setEnabled(enabled)
        if hasattr(self, "btn_disk_reg"):
            self.btn_disk_reg.setEnabled(enabled)
        if hasattr(self, "btn_hardware"):
            self.btn_hardware.setEnabled(enabled)
        if hasattr(self, "btn_tweaks"):
            self.btn_tweaks.setEnabled(enabled)


    def open_large_files_dialog(self):
        dialog = LargeFilesDialog(self)
        dialog.exec_()

    def open_disk_analyzer(self):
        """Mở hộp thoại Phân Tích Ổ Đĩa (Phase 4)."""
        dialog = DiskAnalyzerDialog(self)
        dialog.exec_()

    def open_network_dialog(self):
        """Mở hộp thoại Giám Sát & Tối Ưu Hóa Mạng."""
        dialog = NetworkOptimizerDialog(monitor_hub=self.monitor_hub, parent=self)
        dialog.exec_()

    def open_disk_registry_dialog(self):
        """Mở hộp thoại Quản Lý Sức Khỏe Ổ Đĩa, SSD TRIM & Dọn Dẹp Registry."""
        dialog = DiskRegistryDialog(self)
        dialog.exec_()

    def open_hardware_dialog(self):
        """Mở hộp thoại Quản Lý Sức Khỏe Pin Laptop & Cảm Biến Phần Cứng (v3.2 Pro)."""
        dialog = HardwareMonitorDialog(self)
        dialog.exec_()

    def open_ai_advisor_dialog(self):
        """Mở hộp thoại AI Smart Suggestions (v3.3 Pro)."""
        dialog = AIAdvisorDialog(
            advisor=self._ai_advisor,
            action_dispatcher=self._ai_action_dispatcher,
            parent=self,
        )
        dialog.exec_()

    def open_services_context_dialog(self):
        """Mở hộp thoại Quản lý Dịch vụ Windows & Menu Chuột Phải (v3.4 Pro)."""
        dialog = ServiceContextDialog(self)
        dialog.exec_()

    def _ai_action_dispatcher(self, action_key: str):
        """Xử lý action từ AI Advisor khi user click 'Áp Dụng Ngay'."""
        try:
            self.raise_()
            self.activateWindow()
            if action_key == "optimize_ram":
                self.tabs.setCurrentWidget(self.tab_dashboard)
                self.optimize_ram_only()
            elif action_key == "clean_junk":
                self.tabs.setCurrentWidget(self.tab_dashboard)
                self.start_full_clean()
            elif action_key == "open_network_dialog":
                self.open_network_dialog()
            elif action_key == "open_hardware_dialog":
                self.open_hardware_dialog()
            elif action_key == "open_services_dialog":
                self.open_services_context_dialog()
            elif action_key == "open_security_dialog":
                if hasattr(self, "tab_security"):
                    self.tabs.setCurrentWidget(self.tab_security)
            elif action_key == "open_process_tab":
                if hasattr(self, "tab_performance"):
                    self.tabs.setCurrentWidget(self.tab_performance)
        except Exception as e:
            import logging
            logging.error(f"[AI Advisor] Action dispatch error: {e}")

    def _update_ai_badge(self):
        """Cập nhật màu/text button AI theo số lượng suggestions nghiêm trọng."""
        try:
            counts = self._ai_advisor.get_suggestions_count_by_priority()
            critical = counts.get("CRITICAL", 0)
            warning  = counts.get("WARNING", 0)
            if critical > 0:
                self.btn_ai_advisor.setText(f"🤖 AI Gợi Ý 🔴{critical}")
                self.btn_ai_advisor.setStyleSheet(
                    "QPushButton { color: #f85149; border: 1px solid #f85149; "
                    "border-radius: 8px; padding: 4px 8px; background: #f8514922; }"
                    "QPushButton:hover { background: #f8514944; }"
                )
            elif warning > 0:
                self.btn_ai_advisor.setText(f"🤖 AI Gợi Ý 🟡{warning}")
                self.btn_ai_advisor.setStyleSheet(
                    "QPushButton { color: #e3b341; border: 1px solid #e3b341; "
                    "border-radius: 8px; padding: 4px 8px; background: #e3b34122; }"
                    "QPushButton:hover { background: #e3b34144; }"
                )
            else:
                self.btn_ai_advisor.setText("🤖 AI Gợi Ý")
                self.btn_ai_advisor.setStyleSheet("")
                self.btn_ai_advisor.setProperty("class", "btn-secondary")
        except Exception:
            pass

    def show_leak_alert(self, info: dict):
        """
        Hiển thị thông báo cảnh báo rò rỉ bộ nhớ cho tiến trình.
        """
        name = info.get("name", "Unknown")
        growth = info.get("growth_mb", 0)
        current = info.get("current_mb", 0)
        msg = (
            f"⚠️ Phát hiện tiến trình có dấu hiệu rò rỉ bộ nhớ:\n\n"
            f"• Tiến trình: {name} (PID {info.get('pid')})\n"
            f"• RAM hiện tại: {current:.1f} MB\n"
            f"• Tăng liên tục: +{growth:.1f} MB trong {info.get('window_checks', 4)} lần kiểm tra\n\n"
            f"Gợi ý: Hãy vào tab 'Tiến Trình & Game Boost' để thu hồi hoặc khởi động lại tiến trình này."
        )
        if self.tray_manager and self.config_manager.get("show_notifications", True):
            self.tray_manager.notify(
                f"⚠️ Cảnh Báo Rò Rỉ Bộ Nhớ",
                f"{name} tăng liên tục +{growth:.1f} MB RAM. Click để xem chi tiết."
            )
        self.lbl_status.setText(f"⚠️ Rò rỉ bộ nhớ: {name} tăng +{growth:.1f} MB")

    def init_tab_performance(self):
        layout = QVBoxLayout(self.tab_performance)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Card 1: Game Booster Center
        card_gb = QFrame()
        card_gb.setStyleSheet("""
            QFrame {
                background-color: #1e1b4b;
                border: 1px solid #4f46e5;
                border-radius: 12px;
            }
        """)
        layout_gb = QHBoxLayout(card_gb)
        layout_gb.setContentsMargins(18, 14, 18, 14)
        layout_gb.setSpacing(16)

        info_gb = QVBoxLayout()
        info_gb.setSpacing(4)
        lbl_gb_title = QLabel("🎮 CHẾ ĐỘ TĂNG TỐC GAMING (GAME BOOST MODE)")
        lbl_gb_title.setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: bold; background: transparent; border: none;")
        self.lbl_gb_desc = QLabel("Thu hồi toàn bộ RAM nhàn rỗi, hạ độ ưu tiên các tác vụ nền (Search, Update, Telemetry) để dồn 100% CPU & RAM cho trò chơi mượt mà nhất.")
        self.lbl_gb_desc.setStyleSheet("color: #cbd5e1; font-size: 11px; background: transparent; border: none;")
        self.lbl_gb_desc.setWordWrap(True)
        info_gb.addWidget(lbl_gb_title)
        info_gb.addWidget(self.lbl_gb_desc)

        right_gb = QVBoxLayout()
        right_gb.setAlignment(Qt.AlignCenter)
        self.badge_gb = QLabel("● Đang Tắt (Bình thường)")
        self.badge_gb.setStyleSheet("""
            background-color: #312e81;
            color: #c7d2fe;
            font-size: 11px;
            font-weight: bold;
            padding: 5px 14px;
            border-radius: 12px;
            border: 1px solid #4f46e5;
        """)
        self.badge_gb.setAlignment(Qt.AlignCenter)

        self.btn_gb_toggle = QPushButton("🎮 BẬT GAME BOOST")
        self.btn_gb_toggle.setProperty("class", "btn-purple")
        self.btn_gb_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_gb_toggle.clicked.connect(self.toggle_game_boost)

        right_gb.addWidget(self.badge_gb)
        right_gb.addWidget(self.btn_gb_toggle)

        layout_gb.addLayout(info_gb, stretch=3)
        layout_gb.addLayout(right_gb, stretch=1)
        layout.addWidget(card_gb)

        # Card 2: Top Resource Eaters Table
        card_procs = QFrame()
        card_procs.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
            }
        """)
        layout_procs = QVBoxLayout(card_procs)
        layout_procs.setContentsMargins(16, 14, 16, 14)
        layout_procs.setSpacing(10)

        ctrl_bar = QHBoxLayout()
        lbl_table_title = QLabel("⚡ TIẾN TRÌNH CHIẾM DỤNG TÀI NGUYÊN (TOP PROCESSES)")
        lbl_table_title.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: bold; border: none; background: transparent;")

        self.combo_proc_sort = QComboBox()
        self.combo_proc_sort.addItem("Xếp theo RAM (Bộ nhớ)", "ram")
        self.combo_proc_sort.addItem("Xếp theo CPU (%)", "cpu")
        self.combo_proc_sort.currentIndexChanged.connect(self.refresh_process_table)

        self.chk_auto_refresh_procs = QCheckBox("Tự động làm mới (3s)")
        self.chk_auto_refresh_procs.setChecked(True)
        self.chk_auto_refresh_procs.stateChanged.connect(self._on_proc_auto_refresh_changed)

        self.btn_refresh_procs = QPushButton("🔄 Làm Mới")
        self.btn_refresh_procs.setProperty("class", "btn-secondary")
        self.btn_refresh_procs.clicked.connect(self.refresh_process_table)

        ctrl_bar.addWidget(lbl_table_title)
        ctrl_bar.addStretch()
        ctrl_bar.addWidget(self.combo_proc_sort)
        ctrl_bar.addWidget(self.chk_auto_refresh_procs)
        ctrl_bar.addWidget(self.btn_refresh_procs)
        layout_procs.addLayout(ctrl_bar)

        # Table
        self.table_procs = QTableWidget()
        self.table_procs.setColumnCount(6)
        self.table_procs.setHorizontalHeaderLabels([
            "Tiến Trình", "PID", "Dung Lượng RAM", "Mức CPU", "Phân Loại", "Thao Tác Nhanh"
        ])
        self.table_procs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_procs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_procs.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.table_procs.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_procs.setSelectionMode(QTableWidget.SingleSelection)
        self.table_procs.setAlternatingRowColors(True)
        layout_procs.addWidget(self.table_procs)

        layout.addWidget(card_procs)

        self.proc_timer = QTimer(self)
        self.proc_timer.timeout.connect(self.refresh_process_table)
        self.proc_timer.start(3000)

    def _on_tab_changed(self, idx: int):
        if hasattr(self, "tabs") and self.tabs.widget(idx) == self.tab_performance:
            self.refresh_process_table()
        elif hasattr(self, "tabs") and self.tabs.widget(idx) == self.tab_analytics:
            self._refresh_analytics_cards()
        elif hasattr(self, "tabs") and hasattr(self, "tab_tweaks") and self.tabs.widget(idx) == self.tab_tweaks:
            self.refresh_tweaks_ui()


    def _on_proc_auto_refresh_changed(self, state):
        if state == Qt.Checked:
            self.proc_timer.start(3000)
        else:
            self.proc_timer.stop()

    def refresh_process_table(self):
        if hasattr(self, "tabs") and self.tabs.currentWidget() != self.tab_performance:
            return

        sort_by = self.combo_proc_sort.currentData() if hasattr(self, "combo_proc_sort") else "ram"
        procs = ProcessManager.get_top_processes(limit=8, sort_by=sort_by)

        self.table_procs.setRowCount(len(procs))
        for row_idx, p in enumerate(procs):
            pid = p["pid"]
            name = p["name"]
            ram_mb = p["ram_mb"]
            cpu_pct = p["cpu_percent"]
            cat = p["category"]
            is_prot = p["is_protected"]

            item_name = QTableWidgetItem(name)
            item_name.setForeground(QColor("#f8fafc"))
            item_name.setFont(QFont("Segoe UI", 9, QFont.Bold))

            item_pid = QTableWidgetItem(str(pid))
            item_pid.setTextAlignment(Qt.AlignCenter)
            item_pid.setForeground(QColor("#64748b"))

            item_ram = QTableWidgetItem(f"{ram_mb:.1f} MB")
            item_ram.setTextAlignment(Qt.AlignCenter)
            item_ram.setForeground(QColor("#38bdf8"))
            item_ram.setFont(QFont("Segoe UI", 9, QFont.Bold))

            item_cpu = QTableWidgetItem(f"{cpu_pct:.1f}%")
            item_cpu.setTextAlignment(Qt.AlignCenter)
            cpu_color = "#34d399" if cpu_pct < 15 else ("#fbbf24" if cpu_pct < 50 else "#f43f5e")
            item_cpu.setForeground(QColor(cpu_color))

            item_cat = QTableWidgetItem(cat)
            item_cat.setTextAlignment(Qt.AlignCenter)
            item_cat.setForeground(QColor("#a855f7"))

            # Action buttons widget
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(6)

            btn_opt = QPushButton("⚡ Thu hồi")
            btn_opt.setStyleSheet("""
                QPushButton {
                    background-color: #065f46;
                    color: #34d399;
                    border-radius: 4px;
                    padding: 3px 8px;
                    font-size: 10px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #047857;
                }
            """)
            btn_opt.setToolTip(f"Thu hồi bộ nhớ RAM nhàn rỗi từ {name}")
            btn_opt.clicked.connect(lambda _, target_pid=pid: self.optimize_single_process(target_pid))
            action_layout.addWidget(btn_opt)

            if not is_prot:
                btn_kill = QPushButton("❌ Đóng")
                btn_kill.setStyleSheet("""
                    QPushButton {
                        background-color: #881337;
                        color: #fda4af;
                        border-radius: 4px;
                        padding: 3px 8px;
                        font-size: 10px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #9f1239;
                    }
                """)
                btn_kill.setToolTip(f"Đóng tiến trình {name}")
                btn_kill.clicked.connect(lambda _, target_pid=pid, p_name=name: self.terminate_single_process(target_pid, p_name))
                action_layout.addWidget(btn_kill)

            self.table_procs.setItem(row_idx, 0, item_name)
            self.table_procs.setItem(row_idx, 1, item_pid)
            self.table_procs.setItem(row_idx, 2, item_ram)
            self.table_procs.setItem(row_idx, 3, item_cpu)
            self.table_procs.setItem(row_idx, 4, item_cat)
            self.table_procs.setCellWidget(row_idx, 5, action_widget)

    def optimize_single_process(self, pid: int):
        res = ProcessManager.optimize_process_ram(pid)
        if res.get("success"):
            freed = res.get("freed_mb", 0.0)
            self.lbl_status.setText(f"Đã thu hồi {freed:.1f} MB RAM từ {res.get('name')}")
            self.refresh_process_table()
            if self.monitor_hub:
                self.monitor_hub.force_refresh()
        else:
            QMessageBox.warning(self, "Không Thể Tối Ưu", f"Lỗi: {res.get('error')}")

    def terminate_single_process(self, pid: int, name: str):
        confirm = QMessageBox.question(
            self, "Xác Nhận Đóng Tiến Trình",
            f"Bạn có chắc chắn muốn đóng tiến trình '{name}' (PID: {pid}) không?\n\n"
            f"Lưu ý: Mọi dữ liệu chưa lưu của tiến trình này có thể bị mất.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            res = ProcessManager.terminate_process(pid)
            if res.get("success"):
                self.lbl_status.setText(f"Đã đóng tiến trình {name} (PID {pid})")
                self.refresh_process_table()
                if self.monitor_hub:
                    self.monitor_hub.force_refresh()
            else:
                QMessageBox.critical(self, "Lỗi", f"Không thể đóng tiến trình: {res.get('error')}")

    def toggle_game_boost(self):
        if GameBooster.is_active():
            res = GameBooster.disable_game_boost()
            self.btn_game_boost.setText("🎮 Game Boost: TẮT")
            if hasattr(self, "btn_gb_toggle"):
                self.btn_gb_toggle.setText("🎮 BẬT GAME BOOST")
                self.badge_gb.setText("● Đang Tắt (Bình thường)")
                self.badge_gb.setStyleSheet("""
                    background-color: #312e81;
                    color: #c7d2fe;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 5px 14px;
                    border-radius: 12px;
                    border: 1px solid #4f46e5;
                """)
            self.lbl_status.setText(f"Đã tắt Game Boost: Khôi phục {res.get('restored_count', 0)} tiến trình.")
            if self.tray_manager:
                self.tray_manager.notify("Game Boost Đã Tắt", "Hệ thống đã khôi phục về trạng thái bình thường.")
        else:
            whitelist = self.config_manager.get_whitelist_set()
            res = GameBooster.enable_game_boost(whitelist=whitelist)
            freed = res.get("freed_ram_mb", 0.0)
            self.btn_game_boost.setText("🎮 Game Boost: BẬT")
            if hasattr(self, "btn_gb_toggle"):
                self.btn_gb_toggle.setText("🛑 TẮT GAME BOOST")
                self.badge_gb.setText("● ĐANG TĂNG TỐC TỐI ĐA")
                self.badge_gb.setStyleSheet("""
                    background-color: #065f46;
                    color: #34d399;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 5px 14px;
                    border-radius: 12px;
                    border: 1px solid #059669;
                """)
            self.lbl_status.setText(f"🎮 Game Boost đã bật! Đã giải phóng {freed:.1f} MB RAM & tối ưu TCP mạng.")
            if self.tray_manager:
                self.tray_manager.notify("🎮 Game Boost Đã Bật", f"Đã dồn 100% tài nguyên và giải phóng {freed:.1f} MB RAM & tối ưu mạng cho Gaming!")

            # Tự động tối ưu hóa mạng cho Gaming (giảm ping & jitter)
            try:
                from core.network_optimizer import NetworkOptimizer
                NetworkOptimizer.optimize_tcp_stack()
                NetworkOptimizer.flush_dns()
            except Exception:
                pass

        if self.monitor_hub:
            self.monitor_hub.force_refresh()

    def create_desktop_shortcut(self):
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "create_shortcut.ps1")
        try:
            import subprocess
            res = subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path], capture_output=True, text=True)
            if res.returncode == 0:
                QMessageBox.information(
                    self, "Thành Công",
                    "Đã tạo biểu tượng lối tắt 'PC Auto Cleaner' thành công trên màn hình Desktop của bạn!"
                )
            else:
                QMessageBox.warning(self, "Chú Ý", f"Lỗi tạo shortcut: {res.stderr}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể thực thi tạo shortcut: {e}")

    def _on_opacity_changed(self, val: int):
        self.config_manager.set("floating_widget_opacity", val)
        self.floating_widget_opacity_changed.emit(val)

    def init_tab_analytics(self):
        """
        Tab Phân Tích Thông Minh (Phase 4):
        - Báo cáo tổng hợp 7 ngày / 30 ngày / toàn thời gian
        - Quản lý Whitelist tiến trình (bảo vệ khỏi tối ưu/demote)
        - Cảnh báo Memory Leak
        """
        outer_layout = QVBoxLayout(self.tab_analytics)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ── TIÊU ĐỀ ──
        lbl_title = QLabel("🧠 PHÂN TÍCH THÔNG MINH & QUẢN LÝ WHITELIST")
        lbl_title.setStyleSheet("color: #38bdf8; font-size: 15px; font-weight: 800; letter-spacing: 0.5px;")
        lbl_sub = QLabel("Tổng hợp hiệu quả dọn dẹp, phân tích xu hướng, và cấu hình tiến trình được bảo vệ")
        lbl_sub.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_sub)

        # ── ANALYTICS CARDS ──
        analytics_title = QLabel("📊 TỔNG QUAN HIỆU QUẢ TỐI ƯU HÓA")
        analytics_title.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 700; margin-top: 6px;")
        layout.addWidget(analytics_title)

        card_style = "QFrame { background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; }"
        analytics_row = QHBoxLayout()
        analytics_row.setSpacing(10)

        self._analytics_card_labels = {}  # {days: {count, junk, ram, health, health_desc}}
        for period_label, days in [("7 NGÀY QUA", 7), ("30 NGÀY QUA", 30), ("TOÀN THỜI GIAN", None)]:
            card = QFrame()
            card.setStyleSheet(card_style)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(6)

            lbl_period = QLabel(f"📅 {period_label}")
            lbl_period.setStyleSheet("color: #64748b; font-size: 10px; font-weight: 700; border: none;")

            history = self.config_manager.get("history", [])
            summary = AnalyticsReporter.generate_summary(history, days)

            lbl_count = QLabel(f"{summary['total_cleanups']} lần dọn dẹp")
            lbl_count.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 800; border: none;")

            lbl_junk = QLabel(f"🗑️ Rác: {summary['total_junk_mb']:.1f} MB")
            lbl_junk.setStyleSheet("color: #34d399; font-size: 11px; border: none;")

            lbl_ram = QLabel(f"⚡ RAM: {summary['total_ram_mb']:.1f} MB")
            lbl_ram.setStyleSheet("color: #38bdf8; font-size: 11px; border: none;")

            lbl_health = QLabel(summary['health_score'])
            lbl_health.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: 700; margin-top: 4px; border: none;")

            lbl_health_desc = QLabel(summary['health_desc'])
            lbl_health_desc.setWordWrap(True)
            lbl_health_desc.setStyleSheet("color: #64748b; font-size: 10px; border: none;")

            card_layout.addWidget(lbl_period)
            card_layout.addWidget(lbl_count)
            card_layout.addWidget(lbl_junk)
            card_layout.addWidget(lbl_ram)
            card_layout.addWidget(lbl_health)
            card_layout.addWidget(lbl_health_desc)
            analytics_row.addWidget(card)

            # Lưu reference để có thể refresh sau
            self._analytics_card_labels[days] = {
                "count": lbl_count,
                "junk": lbl_junk,
                "ram": lbl_ram,
                "health": lbl_health,
                "health_desc": lbl_health_desc,
            }

        layout.addLayout(analytics_row)

        # ── NÚT XUẤT BÁO CÁO ──
        btn_export_report = QPushButton("📄 Xuất Báo Cáo Hiệu Quả (.txt) ra Desktop")
        btn_export_report.setProperty("class", "btn-secondary")
        btn_export_report.setCursor(Qt.PointingHandCursor)
        btn_export_report.clicked.connect(self._export_analytics_report)
        layout.addWidget(btn_export_report)

        # ── WHITELIST MANAGER ──
        wl_frame = QFrame()
        wl_frame.setStyleSheet("QFrame { background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; }")
        wl_layout = QVBoxLayout(wl_frame)
        wl_layout.setContentsMargins(16, 14, 16, 14)
        wl_layout.setSpacing(8)

        wl_hdr = QHBoxLayout()
        lbl_wl_title = QLabel("🛡️ WHITELIST TIẾN TRÌNH (Bảo vệ khỏi tối ưu RAM & GameBoost)")
        lbl_wl_title.setStyleSheet("color: #f8fafc; font-size: 13px; font-weight: 700; border: none;")
        lbl_wl_desc = QLabel("Các tiến trình trong danh sách này sẽ KHÔNG bị tối ưu, thu hồi bộ nhớ, hay hạ độ ưu tiên.")
        lbl_wl_desc.setStyleSheet("color: #64748b; font-size: 11px; border: none;")
        wl_hdr.addWidget(lbl_wl_title)
        wl_hdr.addStretch()
        wl_layout.addLayout(wl_hdr)
        wl_layout.addWidget(lbl_wl_desc)

        # Input row
        input_row = QHBoxLayout()
        self.wl_input = QLineEdit()
        self.wl_input.setPlaceholderText("Nhập tên tiến trình (vd: obs64.exe, chrome.exe)...")
        self.wl_input.setStyleSheet(
            "QLineEdit { background-color: #0f172a; color: #f8fafc; border: 1px solid #334155; "
            "border-radius: 6px; padding: 6px 10px; font-size: 12px; }"
        )
        self.wl_input.returnPressed.connect(self._add_to_whitelist)

        btn_wl_add = QPushButton("➕ Thêm")
        btn_wl_add.setProperty("class", "btn-primary")
        btn_wl_add.setFixedWidth(90)
        btn_wl_add.clicked.connect(self._add_to_whitelist)

        input_row.addWidget(self.wl_input)
        input_row.addWidget(btn_wl_add)
        wl_layout.addLayout(input_row)

        # Whitelist list view
        self.wl_list = QListWidget()
        self.wl_list.setMaximumHeight(140)
        self.wl_list.setStyleSheet("""
            QListWidget {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                font-size: 12px;
                padding: 4px;
            }
            QListWidget::item:selected { background-color: #0369a1; }
            QListWidget::item:hover { background-color: #1e293b; }
        """)
        self._populate_whitelist()
        wl_layout.addWidget(self.wl_list)

        btn_wl_remove = QPushButton("🗑️ Xóa tiến trình đã chọn khỏi Whitelist")
        btn_wl_remove.setProperty("class", "btn-secondary")
        btn_wl_remove.clicked.connect(self._remove_from_whitelist)
        wl_layout.addWidget(btn_wl_remove)

        layout.addWidget(wl_frame)
        layout.addStretch()
        scroll.setWidget(scroll_content)
        outer_layout.addWidget(scroll, 1)

    def _populate_whitelist(self):
        """Điền danh sách whitelist vào QListWidget."""
        if not hasattr(self, "wl_list"):
            return
        self.wl_list.clear()
        for name in self.config_manager.get("process_whitelist", []):
            item = QListWidgetItem(f"🛡️  {name}")
            self.wl_list.addItem(item)

    def _add_to_whitelist(self):
        name = self.wl_input.text().strip()
        if not name:
            return
        if self.config_manager.add_to_whitelist(name):
            self._populate_whitelist()
            self.wl_input.clear()
            self.lbl_status.setText(f"Đã thêm '{name}' vào Whitelist bảo vệ.")
        else:
            QMessageBox.information(self, "Đã có trong danh sách", f"'{name}' đã có trong Whitelist rồi.")

    def _remove_from_whitelist(self):
        selected = self.wl_list.currentItem()
        if not selected:
            QMessageBox.information(self, "Chưa chọn", "Hãy chọn một tiến trình trong danh sách để xóa.")
            return
        # Remove "🛡️  " prefix
        raw = selected.text().replace("🛡️  ", "").strip()
        if self.config_manager.remove_from_whitelist(raw):
            self._populate_whitelist()
            self.lbl_status.setText(f"Đã xóa '{raw}' khỏi Whitelist.")

    def _refresh_analytics_cards(self):
        """Cập nhật lại các thẻ Analytics khi người dùng chuyển sang tab này."""
        if not hasattr(self, "_analytics_card_labels"):
            return
        history = self.config_manager.get("history", [])
        for days, labels in self._analytics_card_labels.items():
            summary = AnalyticsReporter.generate_summary(history, days)
            labels["count"].setText(f"{summary['total_cleanups']} lần dọn dẹp")
            labels["junk"].setText(f"🗑️ Rác: {summary['total_junk_mb']:.1f} MB")
            labels["ram"].setText(f"⚡ RAM: {summary['total_ram_mb']:.1f} MB")
            labels["health"].setText(summary["health_score"])
            labels["health_desc"].setText(summary["health_desc"])

    def _export_analytics_report(self):
        """Xuất báo cáo hiệu quả dưới dạng file .txt ra Desktop."""
        import os
        try:
            report_text = AnalyticsReporter.generate_report_text(self.config_manager)
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            from datetime import datetime
            fname = f"PCCleaner_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            out_path = os.path.join(desktop, fname)
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(report_text)
            QMessageBox.information(
                self, "Xuất Báo Cáo Thành Công",
                f"Báo cáo đã được lưu tại:\n{out_path}"
            )
            self.lbl_status.setText(f"📄 Đã xuất báo cáo: {fname}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi Xuất Báo Cáo", f"Không thể xuất báo cáo: {e}")

    def init_tab_security(self):
        """Tab rà soát và giám sát bảo mật hệ thống."""
        layout = QVBoxLayout(self.tab_security)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── Header ────────────────────────────────────────────────────────────
        header = QHBoxLayout()

        self.lbl_security_badge = QLabel("🔒 CHƯA QUÉT")
        self.lbl_security_badge.setStyleSheet("""
            background-color: #1e293b; color: #94a3b8;
            font-size: 13px; font-weight: bold; padding: 8px 18px;
            border-radius: 20px; border: 1px solid #334155;
        """)

        self.lbl_security_last_scan = QLabel("Chưa thực hiện quét lần nào.")
        self.lbl_security_last_scan.setStyleSheet("color: #64748b; font-size: 11px;")

        self.btn_security_scan_now = QPushButton("🔍  Quét Bảo Mật Ngay")
        self.btn_security_scan_now.setProperty("class", "btn-primary")
        self.btn_security_scan_now.setCursor(Qt.PointingHandCursor)
        self.btn_security_scan_now.clicked.connect(self.run_security_scan_now)

        header.addWidget(self.lbl_security_badge)
        header.addWidget(self.lbl_security_last_scan)
        header.addStretch()
        header.addWidget(self.btn_security_scan_now)
        layout.addLayout(header)

        # ── Summary Bar ───────────────────────────────────────────────────────
        summary_frame = QFrame()
        summary_frame.setStyleSheet("""
            QFrame { background-color: #0f172a; border: 1px solid #1e293b;
                     border-radius: 10px; }
        """)
        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(16, 10, 16, 10)

        self.lbl_sec_critical = QLabel("🔴  0 CRITICAL")
        self.lbl_sec_warning  = QLabel("🟡  0 Cảnh báo")
        self.lbl_sec_ok       = QLabel("🟢  0 An toàn")

        for lbl, color in [
            (self.lbl_sec_critical, "#f43f5e"),
            (self.lbl_sec_warning,  "#fbbf24"),
            (self.lbl_sec_ok,       "#34d399"),
        ]:
            lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold; background: transparent;")
            summary_layout.addWidget(lbl)
            summary_layout.addStretch()

        layout.addWidget(summary_frame)

        # ── Live Scan Status & Progress Panel ──────────────────────────────────
        self.frame_sec_progress = QFrame()
        self.frame_sec_progress.setStyleSheet("""
            QFrame {
                background-color: #0b1329;
                border: 1px solid #1e3a8a;
                border-radius: 10px;
            }
        """)
        progress_layout = QVBoxLayout(self.frame_sec_progress)
        progress_layout.setContentsMargins(14, 10, 14, 10)
        progress_layout.setSpacing(6)

        step_header = QHBoxLayout()
        self.lbl_sec_current_step = QLabel("● Sẵn sàng rà soát bảo mật hệ thống")
        self.lbl_sec_current_step.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: bold;")

        self.lbl_sec_progress_pct = QLabel("0%")
        self.lbl_sec_progress_pct.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: bold;")

        step_header.addWidget(self.lbl_sec_current_step)
        step_header.addStretch()
        step_header.addWidget(self.lbl_sec_progress_pct)
        progress_layout.addLayout(step_header)

        self.progress_security = QProgressBar()
        self.progress_security.setRange(0, 100)
        self.progress_security.setValue(0)
        self.progress_security.setTextVisible(False)
        self.progress_security.setFixedHeight(8)
        self.progress_security.setStyleSheet("""
            QProgressBar {
                background-color: #1e293b;
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #0284c7, stop:0.5 #38bdf8, stop:1 #34d399);
                border-radius: 4px;
            }
        """)
        progress_layout.addWidget(self.progress_security)
        layout.addWidget(self.frame_sec_progress)

        # ── Results Table ─────────────────────────────────────────────────────
        self.table_security = QTableWidget()
        self.table_security.setColumnCount(4)
        self.table_security.setHorizontalHeaderLabels(["Hạng Mục", "Trạng Thái", "Chi Tiết", "Sửa"])
        self.table_security.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_security.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_security.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_security.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_security.verticalHeader().setVisible(False)
        self.table_security.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_security.setAlternatingRowColors(True)
        self.table_security.setStyleSheet("""
            QTableWidget { background-color: #0f172a; color: #e2e8f0;
                           gridline-color: #1e293b; border: none; font-size: 12px; }
            QTableWidget::item { padding: 6px 8px; }
            QTableWidget::item:alternate { background-color: #111827; }
            QHeaderView::section { background-color: #1e293b; color: #94a3b8;
                                   font-weight: bold; padding: 6px; border: none; }
        """)
        self.table_security.setMinimumHeight(160)
        layout.addWidget(self.table_security, stretch=1)

        # ── Scan Log Terminal ─────────────────────────────────────────────────
        lbl_log = QLabel("Log rà soát bảo mật:")
        lbl_log.setStyleSheet("color: #64748b; font-size: 11px; font-weight: 600;")
        layout.addWidget(lbl_log)

        self.txt_security_log = QPlainTextEdit()
        self.txt_security_log.setReadOnly(True)
        self.txt_security_log.setMaximumHeight(85)
        self.txt_security_log.setStyleSheet("""
            QPlainTextEdit {
                background-color: #020617; color: #a78bfa;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px; border: 1px solid #1e293b;
                border-radius: 6px; padding: 6px;
            }
        """)
        layout.addWidget(self.txt_security_log)

        # Khôi phục kết quả quét gần nhất nếu có
        last_res = self.config_manager.get("last_security_scan_result", {})
        if last_res and last_res.get("timestamp"):
            overall = last_res.get("overall", "SAFE")
            crit = last_res.get("critical_count", 0)
            warn = last_res.get("warning_count", 0)
            ok = last_res.get("ok_count", 0)
            ts = last_res.get("timestamp", "")
            badge_styles = {
                "SAFE":     ("🟢 AN TOÀN",  "#064e3b", "#34d399", "#059669"),
                "WARNING":  ("🟡 CẢNH BÁO", "#422006", "#fbbf24", "#d97706"),
                "CRITICAL": ("🔴 NGUY HIỂM", "#4c0519", "#f43f5e", "#e11d48"),
            }
            badge_text, bg, fg, border = badge_styles.get(overall, badge_styles["SAFE"])
            self.lbl_security_badge.setText(badge_text)
            self.lbl_security_badge.setStyleSheet(f"""
                background-color: {bg}; color: {fg};
                font-size: 13px; font-weight: bold; padding: 8px 18px;
                border-radius: 20px; border: 1px solid {border};
            """)
            self.lbl_security_last_scan.setText(f"Lần quét gần nhất: {ts} (Đã lưu)")
            self.lbl_sec_critical.setText(f"🔴  {crit} CRITICAL")
            self.lbl_sec_warning.setText(f"🟡  {warn} Cảnh báo")
            self.lbl_sec_ok.setText(f"🟢  {ok} An toàn")
            self.txt_security_log.appendPlainText(f"ℹ️ Đã tải kết quả quét gần nhất ({ts}).")

    def _add_security_table_row(self, row_data: dict):
        """Thêm một hàng kết quả vào bảng bảo mật kèm nút Sửa nếu có fix."""
        level_colors = {
            "CRITICAL": "#f43f5e", "WARNING": "#fbbf24",
            "INFO": "#60a5fa",    "OK": "#34d399"
        }
        row = self.table_security.rowCount()
        self.table_security.insertRow(row)

        level  = row_data.get("level", "OK")
        color  = level_colors.get(level, "#94a3b8")

        item_check  = QTableWidgetItem(row_data.get("check", ""))
        item_status = QTableWidgetItem(row_data.get("status", ""))
        item_detail = QTableWidgetItem(row_data.get("detail", "").replace("\n", " "))

        item_check.setForeground(QColor(color))
        item_status.setForeground(QColor(color))
        item_detail.setForeground(QColor("#94a3b8"))

        self.table_security.setItem(row, 0, item_check)
        self.table_security.setItem(row, 1, item_status)
        self.table_security.setItem(row, 2, item_detail)

        # Nút Sửa nhanh
        fix_key = row_data.get("fix")
        if fix_key:
            btn_fix = QPushButton("🔧 Sửa")
            btn_fix.setStyleSheet(
                "QPushButton { background: #1e3a5f; color: #38bdf8; border: 1px solid #0284c7;"
                " border-radius: 4px; padding: 3px 10px; font-size: 11px; }"
                "QPushButton:hover { background: #0284c7; color: #fff; }"
            )
            btn_fix.clicked.connect(
                lambda _, k=fix_key, c=row_data.get("check",""): self._apply_security_fix(k, c)
            )
            self.table_security.setCellWidget(row, 3, btn_fix)
        else:
            self.table_security.setItem(row, 3, QTableWidgetItem(""))

        self.table_security.scrollToBottom()

    def run_security_scan_now(self):
        """Chạy quét bảo mật với hiển thị tiến trình chi tiết từng bước thời gian thực."""
        if hasattr(self, "_sec_worker") and self._sec_worker and self._sec_worker.isRunning():
            return

        self.btn_security_scan_now.setEnabled(False)
        self.btn_security_scan_now.setText("⏳ Đang Quét...")
        self.lbl_security_badge.setText("⏳ ĐANG QUÉT...")
        self.lbl_security_badge.setStyleSheet("""
            background-color: #1e3a5f; color: #38bdf8;
            font-size: 13px; font-weight: bold; padding: 8px 18px;
            border-radius: 20px; border: 1px solid #0284c7;
        """)
        self.lbl_sec_current_step.setText("🔄 Khởi động trình rà soát bảo mật...")
        self.lbl_sec_progress_pct.setText("0%")
        self.progress_security.setValue(0)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("🔒 Đang rà soát bảo mật hệ thống...")

        # Reset bộ đếm và bảng kết quả
        self._scan_crit_count = 0
        self._scan_warn_count = 0
        self._scan_ok_count = 0
        self.lbl_sec_critical.setText("🔴  0 CRITICAL")
        self.lbl_sec_warning.setText("🟡  0 Cảnh báo")
        self.lbl_sec_ok.setText("🟢  0 An toàn")
        self.table_security.setRowCount(0)

        self.txt_security_log.appendPlainText("▶ Bắt đầu quét bảo mật toàn diện...")

        self._sec_worker = SecurityScanWorker()
        self._sec_worker.step_started.connect(self._on_security_step_started)
        self._sec_worker.step_finished.connect(self._on_security_step_finished)
        self._sec_worker.all_finished.connect(self._on_security_all_finished)
        self._sec_worker.start()

    def _on_security_step_started(self, data: dict):
        step = data.get("step", 1)
        total = data.get("total", 11)
        name = data.get("name", "")
        pct = data.get("percent", 0)

        step_text = f"🔄 [{step}/{total}] Đang kiểm tra: {name}..."
        self.lbl_sec_current_step.setText(step_text)
        self.lbl_sec_progress_pct.setText(f"{pct}%")
        self.progress_security.setValue(pct)
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(f"🔒 [{step}/{total}] {name}...")
        self.txt_security_log.appendPlainText(f"▶ [{step}/{total}] Đang kiểm tra: {name}...")

    def _on_security_step_finished(self, data: dict):
        step = data.get("step", 1)
        total = data.get("total", 11)
        name = data.get("name", "")
        pct = data.get("percent", 0)
        r = data.get("result", {})

        self.lbl_sec_progress_pct.setText(f"{pct}%")
        self.progress_security.setValue(pct)
        self.progress_bar.setValue(pct)

        # Chèn trực tiếp hàng kết quả vào bảng ngay khi bước hoàn thành
        self._add_security_table_row(r)

        # Cập nhật số đếm theo thời gian thực
        level = r.get("level", "OK")
        if level == "CRITICAL":
            self._scan_crit_count += 1
        elif level == "WARNING":
            self._scan_warn_count += 1
        else:
            self._scan_ok_count += 1

        self.lbl_sec_critical.setText(f"🔴  {self._scan_crit_count} CRITICAL")
        self.lbl_sec_warning.setText(f"🟡  {self._scan_warn_count} Cảnh báo")
        self.lbl_sec_ok.setText(f"🟢  {self._scan_ok_count} An toàn")

        # Ghi log chi tiết
        status_txt = r.get("status", "")
        detail_txt = r.get("detail", "")
        self.txt_security_log.appendPlainText(f"   ↳ {status_txt} — {detail_txt}")

    def _on_security_all_finished(self, summary: dict):
        self.progress_security.setValue(100)
        self.lbl_sec_progress_pct.setText("100%")
        self.lbl_sec_current_step.setText(f"✅ Hoàn tất rà soát {summary.get('total_checks', 11)} hạng mục bảo mật ({summary.get('duration_s', 0)}s)!")
        self.btn_security_scan_now.setEnabled(True)
        self.btn_security_scan_now.setText("🔍  Quét Bảo Mật Ngay")
        self.progress_bar.setVisible(False)
        self.update_security_tab_result(summary)

    def update_security_tab_result(self, result: dict):
        """Cập nhật toàn bộ Tab Bảo Mật với kết quả quét mới nhất."""
        overall       = result.get("overall", "SAFE")
        overall_icon  = result.get("overall_icon", "🟢")
        critical_count = result.get("critical_count", 0)
        warning_count  = result.get("warning_count", 0)
        ok_count       = result.get("ok_count", 0)
        timestamp      = result.get("timestamp", "")
        results        = result.get("results", [])

        # Badge
        badge_styles = {
            "SAFE":     ("🟢 AN TOÀN",  "#064e3b", "#34d399", "#059669"),
            "WARNING":  ("🟡 CẢNH BÁO", "#422006", "#fbbf24", "#d97706"),
            "CRITICAL": ("🔴 NGUY HIỂM", "#4c0519", "#f43f5e", "#e11d48"),
        }
        badge_text, bg, fg, border = badge_styles.get(overall, badge_styles["SAFE"])
        self.lbl_security_badge.setText(badge_text)
        self.lbl_security_badge.setStyleSheet(f"""
            background-color: {bg}; color: {fg};
            font-size: 13px; font-weight: bold; padding: 8px 18px;
            border-radius: 20px; border: 1px solid {border};
        """)
        self.lbl_security_last_scan.setText(f"Lần quét gần nhất: {timestamp}")

        # Summary counts
        self.lbl_sec_critical.setText(f"🔴  {critical_count} CRITICAL")
        self.lbl_sec_warning.setText(f"🟡  {warning_count} Cảnh báo")
        self.lbl_sec_ok.setText(f"🟢  {ok_count} An toàn")

        # Status bar
        self.lbl_status.setText(
            f"{overall_icon} Quét bảo mật xong: {critical_count} CRITICAL, "
            f"{warning_count} cảnh báo, {ok_count} an toàn."
        )

        # Nếu bảng chưa có kết quả (ví dụ gọi từ background scheduler hoặc nạp lại), hiển thị lại
        if self.table_security.rowCount() == 0 or self.table_security.rowCount() != len(results):
            self.table_security.setRowCount(0)
            for row_data in results:
                self._add_security_table_row(row_data)

        # Log
        duration = result.get("duration_s", 0)
        self.txt_security_log.appendPlainText(
            f"✅ Quét hoàn tất trong {duration}s — "
            f"{critical_count} CRITICAL | {warning_count} WARNING | {ok_count} OK"
        )

        # Cập nhật nhãn trạng thái hoàn tất
        self.lbl_sec_current_step.setText(f"✅ Hoàn tất lúc {timestamp} — {duration}s")
        self.lbl_sec_progress_pct.setText("100%")
        self.progress_security.setValue(100)

        # Lưu kết quả vào config để hiển thị lại sau khi restart
        self.config_manager.set("last_security_scan_result", {
            "overall": overall, "critical_count": critical_count,
            "warning_count": warning_count, "ok_count": ok_count,
            "timestamp": timestamp
        })

    def _apply_security_fix(self, fix_key: str, check_name: str):
        """
        Áp dụng auto-fix cho một vấn đề bảo mật.
        - Khi chạy chế độ Admin: Thực thi trực tiếp ngay lập tức, KHÔNG hỏi tiếp.
        - Khi chạy chế độ thường: Hỏi xác nhận như hiện tại trước khi gọi UAC.
        """
        from core.security_scanner import SecurityScanner
        is_elevated = SecurityScanner.is_admin()

        # Khi chạy chế độ thường (chưa có quyền admin): Giữ nguyên xác nhận như hiện tại
        if not is_elevated:
            reply = QMessageBox.question(
                self, "Xác Nhận Sửa Bảo Mật",
                f"Bạn có muốn tự động sửa:\n\n'{check_name}'?\n\n"
                "Thao tác này thay đổi thiết lập hệ thống Windows và yêu cầu quyền Administrator.\n"
                "Khi hộp thoại Windows UAC xuất hiện, vui lòng chọn 'Yes' để cấp quyền.\n\n"
                "Một số thay đổi cài đặt hệ thống cần khởi động lại máy để có hiệu lực hoàn toàn.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        # Khi chạy với quyền Admin: Thực thi trực tiếp ngay, không hỏi tiếp
        self.txt_security_log.appendPlainText(f"🔧 Đang sửa lỗi [{check_name}]...")
        self.lbl_status.setText(f"🔧 Đang áp dụng sửa lỗi: {check_name}...")

        result = SecurityScanner.apply_fix(fix_key)
        if result.get("success"):
            if not is_elevated:
                QMessageBox.information(self, "Sửa Thành Công ✅", result["message"])
            else:
                self.lbl_status.setText(f"✅ Đã sửa xong [{check_name}]: {result['message']}")
            self.txt_security_log.appendPlainText(f"✅ Đã sửa [{check_name}]: {result['message']}")
            # Tự động quét lại để cập nhật bảng trạng thái
            self.run_security_scan_now()
        else:
            QMessageBox.warning(self, "Sửa Thất Bại ⚠️",
                result["message"] + ("\n\nLưu ý: Bạn cần bấm 'Yes' trên hộp thoại Windows UAC để cấp quyền sửa đổi thiết lập hệ thống." if not is_elevated else ""))
            self.txt_security_log.appendPlainText(f"⚠️ Thất bại [{check_name}]: {result['message']}")

    # ──────────────────────────────────────────────────────────────────────────
    # TAB 8: TINH CHỈNH HỆ THỐNG & BẢO VỆ QUYỀN RIÊNG TƯ (v3.1 PRO)
    # ──────────────────────────────────────────────────────────────────────────
    def init_tab_tweaks(self):
        """Khởi tạo Tab thứ 8: Tinh Chỉnh Hệ Thống & Bảo Vệ Quyền Riêng Tư (v3.1 Pro)."""
        layout = QVBoxLayout(self.tab_tweaks)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ── 1. Top Action & Summary Bar ───────────────────────────────────────
        header = QHBoxLayout()

        self.lbl_tweak_badge = QLabel("🛡️ ĐÃ TỐI ƯU 0/15")
        self.lbl_tweak_badge.setStyleSheet("""
            background-color: #064e3b; color: #34d399;
            font-size: 13px; font-weight: bold; padding: 8px 18px;
            border-radius: 20px; border: 1px solid #059669;
        """)

        self.lbl_tweak_rec_count = QLabel("Đang tải dữ liệu tinh chỉnh...")
        self.lbl_tweak_rec_count.setStyleSheet("color: #94a3b8; font-size: 12px; background: transparent;")

        self.btn_apply_rec_tweaks = QPushButton("⚡  Tối Ưu Khuyên Dùng (1-Click)")
        self.btn_apply_rec_tweaks.setProperty("class", "btn-success")
        self.btn_apply_rec_tweaks.setCursor(Qt.PointingHandCursor)
        self.btn_apply_rec_tweaks.clicked.connect(self.apply_all_recommended_tweaks)

        self.btn_revert_all_tweaks = QPushButton("🔄  Khôi Phục Mặc Định")
        self.btn_revert_all_tweaks.setProperty("class", "btn-secondary")
        self.btn_revert_all_tweaks.setCursor(Qt.PointingHandCursor)
        self.btn_revert_all_tweaks.clicked.connect(self.revert_all_tweaks)

        self.btn_restart_explorer = QPushButton("🚀  Khởi Động Lại Explorer")
        self.btn_restart_explorer.setProperty("class", "btn-purple")
        self.btn_restart_explorer.setCursor(Qt.PointingHandCursor)
        self.btn_restart_explorer.clicked.connect(self.restart_explorer_clicked)

        header.addWidget(self.lbl_tweak_badge)
        header.addWidget(self.lbl_tweak_rec_count)
        header.addStretch()
        header.addWidget(self.btn_apply_rec_tweaks)
        header.addWidget(self.btn_revert_all_tweaks)
        header.addWidget(self.btn_restart_explorer)
        layout.addLayout(header)

        # ── 2. Filter & Search Toolbar ─────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.btn_filter_all = QPushButton("Tất Cả (15)")
        self.btn_filter_privacy = QPushButton("🛡️ Quyền Riêng Tư (8)")
        self.btn_filter_perf = QPushButton("⚡ Hiệu Năng (4)")
        self.btn_filter_ui = QPushButton("🖱️ Giao Diện (3)")

        self.filter_buttons = [
            ("all", self.btn_filter_all),
            ("privacy", self.btn_filter_privacy),
            ("performance", self.btn_filter_perf),
            ("ui", self.btn_filter_ui)
        ]

        self.current_tweak_category = "all"

        for cat_id, btn in self.filter_buttons:
            btn.setCursor(Qt.PointingHandCursor)
            btn.setProperty("class", "btn-secondary")
            btn.clicked.connect(lambda checked, c=cat_id: self._set_tweak_category_filter(c))
            toolbar.addWidget(btn)

        self.btn_filter_all.setStyleSheet("background-color: #0284c7; color: #ffffff; font-weight: bold;")

        toolbar.addStretch()

        self.txt_tweak_search = QLineEdit()
        self.txt_tweak_search.setPlaceholderText("🔍 Tìm kiếm tinh chỉnh (vd: telemetry, bing, menu, pin...)")
        self.txt_tweak_search.setFixedWidth(320)
        self.txt_tweak_search.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px 12px;
                color: #f1f5f9;
            }
            QLineEdit:focus {
                border-color: #38bdf8;
            }
        """)
        self.txt_tweak_search.textChanged.connect(self._filter_tweaks)
        toolbar.addWidget(self.txt_tweak_search)

        layout.addLayout(toolbar)

        # ── 3. Scroll Area with Tweak Cards ────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        cards_container = QWidget()
        cards_container.setStyleSheet("background: transparent;")
        self.tweak_cards_layout = QVBoxLayout(cards_container)
        self.tweak_cards_layout.setContentsMargins(0, 4, 8, 4)
        self.tweak_cards_layout.setSpacing(10)

        self.tweak_card_widgets = {}

        for tid, info in SystemTweaker.TWEAKS_DEF.items():
            card = QFrame()
            card.setProperty("class", "tweak-card")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 12, 14, 12)
            card_layout.setSpacing(8)

            # Top Row: Icon, Title, Badges, Button
            top_row = QHBoxLayout()
            top_row.setSpacing(10)

            lbl_icon = QLabel(info.get("icon", "⚙️"))
            lbl_icon.setStyleSheet("font-size: 18px; background: transparent;")

            lbl_title = QLabel(info.get("name", tid))
            lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #f1f5f9; background: transparent;")

            top_row.addWidget(lbl_icon)
            top_row.addWidget(lbl_title)
            top_row.addStretch()

            # Badge
            if info.get("recommended"):
                badge = QLabel("⭐ Khuyên Dùng")
                badge.setProperty("class", "badge-rec")
            else:
                badge = QLabel("⚡ Nâng Cao")
                badge.setProperty("class", "badge-adv")
            top_row.addWidget(badge)

            if info.get("requires_admin"):
                lbl_admin = QLabel("🔒 Cần Admin")
                lbl_admin.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; padding: 2px 6px; background: transparent;")
                top_row.addWidget(lbl_admin)

            btn_toggle = QPushButton("Đang kiểm tra...")
            btn_toggle.setCursor(Qt.PointingHandCursor)
            btn_toggle.setProperty("class", "btn-tweak-off")
            btn_toggle.clicked.connect(lambda checked, t=tid: self.toggle_tweak(t))
            top_row.addWidget(btn_toggle)

            card_layout.addLayout(top_row)

            # Description Row
            lbl_desc = QLabel(info.get("description", ""))
            lbl_desc.setWordWrap(True)
            lbl_desc.setStyleSheet("color: #94a3b8; font-size: 12px; line-height: 1.4; background: transparent;")
            card_layout.addWidget(lbl_desc)

            self.tweak_cards_layout.addWidget(card)

            self.tweak_card_widgets[tid] = {
                "card": card,
                "btn_toggle": btn_toggle,
                "info": info
            }

        self.tweak_cards_layout.addStretch()
        scroll.setWidget(cards_container)
        layout.addWidget(scroll)

        # Lần đầu hiển thị
        self.refresh_tweaks_ui()

    def _set_tweak_category_filter(self, category: str):
        self.current_tweak_category = category
        for cat_id, btn in self.filter_buttons:
            if cat_id == category:
                btn.setStyleSheet("background-color: #0284c7; color: #ffffff; font-weight: bold;")
            else:
                btn.setStyleSheet("")
        self._filter_tweaks()

    def _filter_tweaks(self):
        query = self.txt_tweak_search.text().lower().strip()
        cat = self.current_tweak_category

        for tid, data in self.tweak_card_widgets.items():
            info = data["info"]
            matches_cat = (cat == "all" or info.get("category") == cat)
            matches_query = (
                not query or 
                query in info.get("name", "").lower() or 
                query in info.get("description", "").lower() or 
                query in tid.lower()
            )
            data["card"].setVisible(matches_cat and matches_query)

    def refresh_tweaks_ui(self):
        """Cập nhật trạng thái hiển thị của toàn bộ 15 tinh chỉnh."""
        if not hasattr(self, "system_tweaker") or not hasattr(self, "tweak_card_widgets"):
            return

        stats = self.system_tweaker.get_summary_stats()
        self.lbl_tweak_badge.setText(f"🛡️ ĐÃ TỐI ƯU {stats['applied']}/{stats['total']}")
        self.lbl_tweak_rec_count.setText(f"({stats['recommended_applied']}/{stats['recommended_total']} mục khuyên dùng đã kích hoạt)")

        for tid, data in self.tweak_card_widgets.items():
            btn = data["btn_toggle"]
            is_on = self.system_tweaker.is_applied(tid)
            if is_on:
                btn.setText("✅  Đang Bật")
                btn.setProperty("class", "btn-tweak-on")
            else:
                btn.setText("Bật Ngay")
                btn.setProperty("class", "btn-tweak-off")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def toggle_tweak(self, tweak_id: str):
        """Bật hoặc tắt một tinh chỉnh cụ thể."""
        data = self.tweak_card_widgets.get(tweak_id)
        if not data:
            return

        info = data["info"]
        is_on = self.system_tweaker.is_applied(tweak_id)
        is_elevated = SystemTweaker.is_admin()

        if is_on:
            # Muốn hoàn tác
            if info.get("requires_admin") and not is_elevated:
                reply = QMessageBox.question(
                    self, "Xác Nhận Hoàn Tác",
                    f"Bạn có muốn khôi phục tinh chỉnh:\n\n'{info['name']}'\n\nvề mặc định của Windows?\n\n"
                    "Thao tác này yêu cầu quyền Administrator.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

            ok, msg = self.system_tweaker.revert_tweak(tweak_id)
            if ok:
                self.lbl_status.setText(msg)
            else:
                QMessageBox.warning(self, "Không Thể Hoàn Tác", msg)
        else:
            # Muốn bật
            if info.get("requires_admin") and not is_elevated:
                reply = QMessageBox.question(
                    self, "Xác Nhận Kích Hoạt",
                    f"Bạn có muốn kích hoạt tinh chỉnh:\n\n'{info['name']}'?\n\n"
                    f"{info['description']}\n\n"
                    "Thao tác này thay đổi thiết lập hệ thống và yêu cầu quyền Administrator (chọn 'Yes' khi Windows hỏi).",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

            ok, msg = self.system_tweaker.apply_tweak(tweak_id)
            if ok:
                self.lbl_status.setText(msg)
            else:
                QMessageBox.warning(self, "Không Thể Kích Hoạt", msg)

        self.refresh_tweaks_ui()

    def apply_all_recommended_tweaks(self):
        """Kích hoạt toàn bộ các mục khuyên dùng."""
        is_elevated = SystemTweaker.is_admin()
        if not is_elevated:
            reply = QMessageBox.question(
                self, "Xác Nhận Tối Ưu Khuyên Dùng",
                "Bạn có muốn tự động kích hoạt TOÀN BỘ các mục khuyên dùng?\n\n"
                "• Chặn Telemetry, DiagTrack, Activity History\n"
                "• Tắt Bing Search trên Start Menu & gợi ý quảng cáo\n"
                "• Giảm độ trễ mở Menu xuống 50ms\n"
                "• Hiện đuôi file & mở This PC trên Explorer\n"
                "• Khôi phục menu chuột phải đầy đủ trên Windows 11\n\n"
                "Một số mục yêu cầu quyền Administrator. Bạn có đồng ý tiếp tục?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return

        self.lbl_status.setText("⏳ Đang áp dụng các tinh chỉnh khuyên dùng...")
        res = self.system_tweaker.apply_all_recommended()
        self.refresh_tweaks_ui()

        msg = f"✅ Đã kích hoạt thành công {res['applied_count']} mục khuyên dùng!"
        if res['failed_count'] > 0:
            msg += f"\n⚠️ {res['failed_count']} mục cần cấp quyền Administrator."
        QMessageBox.information(self, "Kết Quả Tối Ưu", msg)
        self.lbl_status.setText(msg)

    def revert_all_tweaks(self):
        """Khôi phục toàn bộ các tinh chỉnh về mặc định."""
        reply = QMessageBox.question(
            self, "Xác Nhận Khôi Phục",
            "Bạn có chắc chắn muốn khôi phục TẤT CẢ các tinh chỉnh về cấu hình mặc định của Windows?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        self.lbl_status.setText("⏳ Đang hoàn tác các tinh chỉnh về mặc định Windows...")
        res = self.system_tweaker.revert_all()
        self.refresh_tweaks_ui()

        msg = f"🔄 Đã khôi phục thành công {res['reverted_count']} tinh chỉnh về mặc định!"
        QMessageBox.information(self, "Khôi Phục Hoàn Tất", msg)
        self.lbl_status.setText(msg)

    def restart_explorer_clicked(self):
        """Khởi động lại Windows Explorer."""
        self.lbl_status.setText("⏳ Đang khởi động lại Windows Explorer...")
        ok = SystemTweaker.restart_explorer()
        if ok:
            QMessageBox.information(self, "Khởi Động Lại Explorer", "✅ Đã khởi động lại Windows Explorer thành công!")
            self.lbl_status.setText("✅ Windows Explorer đã được khởi động lại.")
        else:
            QMessageBox.warning(self, "Lỗi", "Không thể khởi động lại Windows Explorer.")

    def closeEvent(self, event):

        """
        Bắt sự kiện đóng cửa sổ: Nếu người dùng bật thu nhỏ xuống khay, ẩn cửa sổ thay vì tắt
        """
        if self.config_manager.get("minimize_to_tray_on_close", True):
            event.ignore()
            self.hide()
            if not self.first_minimize_notified and self.tray_manager:
                self.first_minimize_notified = True
                self.tray_manager.notify(
                    "PC Auto Cleaner Đang Chạy Ngầm",
                    "Ứng dụng vẫn đang chạy ngầm trong khay hệ thống để tự động dọn rác và tối ưu máy tính."
                )
        else:
            event.accept()
