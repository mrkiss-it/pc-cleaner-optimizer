import time
from datetime import datetime, timedelta
from typing import Callable, Optional
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from core.cleaner import JunkCleaner
from core.memory_optimizer import MemoryOptimizer
from core.system_monitor import SystemMonitor
from core.leak_detector import MemoryLeakDetector
from config_manager import ConfigManager

class BackgroundScheduler(QObject):
    # Signals for UI notifications
    clean_completed = pyqtSignal(dict)
    ram_optimized = pyqtSignal(dict)
    leak_detected = pyqtSignal(dict)
    network_optimized = pyqtSignal(dict)
    dns_switched = pyqtSignal(dict)
    security_scan_completed = pyqtSignal(dict)   # Auto Security Scanner signal

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.last_scheduled_clean = datetime.now()
        self.last_ram_trigger = datetime.now() - timedelta(minutes=10)
        self.ram_cooldown_seconds = 180
        self.last_net_trigger = datetime.now() - timedelta(minutes=10)
        self.net_cooldown_seconds = 300
        self.last_dns_trigger = datetime.now() - timedelta(hours=2)
        self.dns_cooldown_seconds = 7200
        self.last_security_trigger = datetime.now() - timedelta(hours=23)  # Run first scan sooner
        self.security_cooldown_seconds = 3600 * 24  # Default 24h

        # Phase 4: Memory Leak Detector
        self.leak_detector = MemoryLeakDetector(config_manager=config_manager)
        self.leak_detector.leak_detected.connect(self.leak_detected.emit)
        self.leak_detector.start()

        # Timer checks every 15 seconds
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(15000)

    def _tick(self):
        config = self.config_manager.config
        now = datetime.now()

        # 1. Check Periodic Auto Clean
        if config.get("auto_clean_enabled", True):
            interval_min = config.get("interval_minutes", 60)
            elapsed_min = (now - self.last_scheduled_clean).total_seconds() / 60.0
            if elapsed_min >= interval_min:
                self.last_scheduled_clean = now
                self.run_scheduled_clean()

        # 2. Check RAM Threshold Auto Optimization
        if config.get("auto_ram_optimize_enabled", True):
            threshold = config.get("ram_threshold_percent", 80)
            ram_info = SystemMonitor.get_ram_info()
            if ram_info["percent"] >= threshold:
                cooldown_elapsed = (now - self.last_ram_trigger).total_seconds()
                if cooldown_elapsed >= self.ram_cooldown_seconds:
                    self.last_ram_trigger = now
                    self.run_auto_ram_boost()

        # 3. Check High Ping Network Auto-Optimization
        if config.get("auto_network_optimize_enabled", True):
            net_info = SystemMonitor.get_network_info()
            ping = net_info.get("ping_ms", -1)
            ping_threshold = config.get("auto_network_ping_threshold_ms", 180)
            if ping > ping_threshold and ping > 0:
                cooldown_elapsed = (now - self.last_net_trigger).total_seconds()
                if cooldown_elapsed >= self.net_cooldown_seconds:
                    self.last_net_trigger = now
                    self.run_auto_network_boost(ping, ping_threshold)

        # 4. Check Auto Best-DNS Switcher
        if config.get("auto_best_dns_enabled", False):
            interval_hours = config.get("auto_best_dns_interval_hours", 2)
            dns_cooldown = interval_hours * 3600
            dns_elapsed = (now - self.last_dns_trigger).total_seconds()
            if dns_elapsed >= dns_cooldown:
                self.last_dns_trigger = now
                self.run_auto_best_dns()

        # 5. Check Auto Security Scanner
        if config.get("auto_security_scan_enabled", True):
            interval_hours = config.get("auto_security_scan_interval_hours", 24)
            sec_cooldown = interval_hours * 3600
            sec_elapsed = (now - self.last_security_trigger).total_seconds()
            if sec_elapsed >= sec_cooldown:
                self.last_security_trigger = now
                self.run_auto_security_scan()

    def run_scheduled_clean(self):
        """
        Dọn dẹp định kỳ theo lịch
        """
        config = self.config_manager.config
        targets = config.get("targets", {})
        whitelist = self.config_manager.get_whitelist_set()
        
        # Dọn rác
        clean_res = JunkCleaner.clean(targets)
        junk_mb = clean_res.get("total_freed_mb", 0.0)

        # Tối ưu RAM nếu bật (truyền whitelist)
        ram_mb = 0.0
        if targets.get("ram_optimize", True):
            ram_res = MemoryOptimizer.optimize_ram(whitelist=whitelist)
            ram_mb = ram_res.get("freed_mb", 0.0)

        # Lưu lịch sử
        self.config_manager.add_history(junk_mb, ram_mb, trigger_type="auto_periodic")

        # Tự động tối ưu mạng định kỳ (Flush DNS & ARP) nếu bật
        if config.get("auto_network_optimize_enabled", True):
            try:
                from core.network_optimizer import NetworkOptimizer
                NetworkOptimizer.flush_dns()
                NetworkOptimizer.purge_arp_netbios()
            except Exception:
                pass

        # Phát signal
        self.clean_completed.emit({
            "type": "periodic",
            "junk_freed_mb": junk_mb,
            "ram_freed_mb": ram_mb
        })

    def run_auto_ram_boost(self):
        """
        Tối ưu hóa RAM khẩn cấp khi vượt ngưỡng
        """
        whitelist = self.config_manager.get_whitelist_set()
        ram_res = MemoryOptimizer.optimize_ram(whitelist=whitelist)
        freed_mb = ram_res.get("freed_mb", 0.0)
        
        self.config_manager.add_history(0.0, freed_mb, trigger_type="ram_threshold")

        self.ram_optimized.emit({
            "type": "threshold",
            "freed_mb": freed_mb,
            "percent_before": ram_res.get("percent_before", 0),
            "percent_after": ram_res.get("percent_after", 0)
        })

    def run_auto_network_boost(self, ping: float, threshold: float):
        """
        Tự động làm mới đường truyền và giải phóng DNS cache khi Ping vượt ngưỡng.
        """
        try:
            from core.network_optimizer import NetworkOptimizer
            res = NetworkOptimizer.full_optimize()
            self.network_optimized.emit({
                "type": "ping_threshold",
                "ping": ping,
                "threshold": threshold,
                "details": res,
                "message": f"Phát hiện Ping cao ({ping:.0f} ms > {threshold:.0f} ms). Đã tự động dọn sạch DNS và tối ưu TCP stack!"
            })
        except Exception as e:
            from core.logger import logger
            logger.error(f"[Scheduler] Lỗi khi tự động tối ưu mạng: {e}")

    def run_auto_best_dns(self):
        """
        Tự động benchmark tất cả DNS servers và chuyển sang DNS có độ trễ thấp nhất.
        Chạy trong thread riêng để không chặn UI.
        """
        import threading
        def _worker():
            try:
                from core.network_optimizer import NetworkOptimizer
                from core.logger import logger
                result = NetworkOptimizer.apply_best_dns(allow_elevation=False)
                self.dns_switched.emit({
                    "type": "auto_dns_switch",
                    "success": result.get("success", False),
                    "best_dns_name": result.get("best_dns_name", "N/A"),
                    "best_dns_ip": result.get("best_dns_ip", "N/A"),
                    "best_dns_latency_ms": result.get("best_dns_latency_ms", -1),
                    "adapters_updated": result.get("adapters_updated", 0),
                    "message": result.get("message", "")
                })
            except Exception as e:
                from core.logger import logger
                logger.error(f"[Scheduler] Lỗi khi tự động chuyển DNS: {e}")
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def run_auto_security_scan(self):
        """
        Tự động rà soát bảo mật toàn diện theo lịch.
        Chạy trong thread riêng để không chặn UI.
        Chỉ phát thông báo khi phát hiện vấn đề CRITICAL hoặc WARNING.
        """
        import threading
        def _worker():
            try:
                from core.security_scanner import SecurityScanner
                from core.logger import logger
                logger.info("[Scheduler] Bắt đầu rà soát bảo mật tự động định kỳ...")
                result = SecurityScanner.run_full_scan()
                self.security_scan_completed.emit({
                    "type": "auto_security_scan",
                    "overall": result.get("overall", "SAFE"),
                    "overall_icon": result.get("overall_icon", "🟢"),
                    "critical_count": result.get("critical_count", 0),
                    "warning_count": result.get("warning_count", 0),
                    "ok_count": result.get("ok_count", 0),
                    "total_checks": result.get("total_checks", 0),
                    "timestamp": result.get("timestamp", ""),
                    "results": result.get("results", []),
                    "message": (
                        f"{result.get('overall_icon', '')} Quét bảo mật hoàn tất: "
                        f"{result.get('critical_count', 0)} CRITICAL, "
                        f"{result.get('warning_count', 0)} cảnh báo, "
                        f"{result.get('ok_count', 0)} an toàn."
                    )
                })
            except Exception as e:
                from core.logger import logger
                logger.error(f"[Scheduler] Lỗi khi rà soát bảo mật: {e}")
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
