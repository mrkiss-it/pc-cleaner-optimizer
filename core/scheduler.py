import time
from datetime import datetime, timedelta
from typing import Callable, Optional
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from core.cleaner import JunkCleaner
from core.memory_optimizer import MemoryOptimizer
from core.system_monitor import SystemMonitor
from core.leak_detector import MemoryLeakDetector
from config_manager import ConfigManager
from core.wifi_recovery import RecoveryToastGate
from core.thermal_monitor import ThermalToastGate

class BackgroundScheduler(QObject):
    # Signals for UI notifications
    clean_completed = pyqtSignal(dict)
    ram_optimized = pyqtSignal(dict)
    leak_detected = pyqtSignal(dict)
    network_optimized = pyqtSignal(dict)
    dns_switched = pyqtSignal(dict)
    security_scan_completed = pyqtSignal(dict)   # Auto Security Scanner signal
    thermal_warning = pyqtSignal(dict)
    thermal_snapshot_ready = pyqtSignal(dict)

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        self.last_scheduled_clean = datetime.now()
        self.last_ram_trigger = datetime.now() - timedelta(minutes=10)
        self.ram_cooldown_seconds = 180
        self.last_net_trigger = datetime.now() - timedelta(minutes=10)
        self.net_cooldown_seconds = 300
        self.last_ping_fix_trigger = datetime.now() - timedelta(minutes=30)
        self.ping_fix_cooldown_seconds = 300
        self.ping_fix_first_cooldown_seconds = 8
        self.ping_fix_unrecovered = 0
        self.ping_fix_max_unrecovered = 2
        self.last_wifi_fix_trigger = datetime.now() - timedelta(minutes=30)
        self.wifi_fix_cooldown_seconds = 300
        self.wifi_fix_first_cooldown_seconds = 12
        self.wifi_fix_unrecovered = 0
        self.wifi_fix_max_unrecovered = 2
        self.recovery_toast_gate = RecoveryToastGate()
        self.thermal_toast_gate = ThermalToastGate()
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
        net_info = SystemMonitor.get_network_info()
        ping = net_info.get("ping_ms", -1)
        if ping > 0:
            self.ping_fix_unrecovered = 0

        wifi_snap = {}
        try:
            from core.wifi_recovery import WifiRecovery
            wifi_snap = WifiRecovery.detect_wifi_instability(include_events=True)
            if not wifi_snap.get("unstable"):
                self.wifi_fix_unrecovered = 0
        except Exception:
            wifi_snap = {}

        try:
            self.recovery_toast_gate.observe_wifi(
                bool(wifi_snap.get("unstable")), now.timestamp()
            )
            self.recovery_toast_gate.observe_ping(float(ping or 0) > 0, now.timestamp())
        except Exception:
            pass

        if config.get("auto_network_optimize_enabled", True):
            ping_threshold = config.get("auto_network_ping_threshold_ms", 180)
            if ping > ping_threshold and ping > 0:
                cooldown_elapsed = (now - self.last_net_trigger).total_seconds()
                if cooldown_elapsed >= self.net_cooldown_seconds:
                    self.last_net_trigger = now
                    self.run_auto_network_boost(ping, ping_threshold)

        # 3b. Wi-Fi rớt / vòng reconnect — ưu tiên hơn missing-ping nếu cùng tick
        wifi_first_cd = float(config.get(
            "auto_network_wifi_fix_first_cooldown_seconds",
            self.wifi_fix_first_cooldown_seconds
        ))
        wifi_repeat_cd = float(config.get(
            "auto_network_wifi_fix_cooldown_seconds",
            self.wifi_fix_cooldown_seconds
        ))
        ping_fix_enabled = bool(config.get("auto_network_ping_fix_enabled", True))
        wifi_fix_due = False
        try:
            from core.wifi_recovery import WifiRecovery
            wifi_fix_due = WifiRecovery.should_trigger_wifi_drop_fix(
                enabled=ping_fix_enabled,
                unstable=bool(wifi_snap.get("unstable")),
                now_ts=now.timestamp(),
                last_trigger_ts=self.last_wifi_fix_trigger.timestamp(),
                cooldown_sec=wifi_repeat_cd,
                unrecovered_repairs=self.wifi_fix_unrecovered,
                max_unrecovered=self.wifi_fix_max_unrecovered,
                first_cooldown_sec=wifi_first_cd,
            )
        except Exception:
            wifi_fix_due = False

        # 3c. Missing / failed ping → diagnose + escalating repair (first fix almost immediate)
        first_cd = float(config.get(
            "auto_network_ping_fix_first_cooldown_seconds",
            self.ping_fix_first_cooldown_seconds
        ))
        repeat_cd = float(config.get(
            "auto_network_ping_fix_cooldown_seconds",
            self.ping_fix_cooldown_seconds
        ))
        ping_fix_due = self.should_trigger_missing_ping_fix(
            enabled=ping_fix_enabled,
            ping_ms=float(ping),
            ping_measured=bool(net_info.get("ping_measured", False)),
            fail_streak=int(net_info.get("ping_fail_streak", 0)),
            min_streak=int(config.get("auto_network_ping_fail_streak", 1)),
            now_ts=now.timestamp(),
            last_trigger_ts=self.last_ping_fix_trigger.timestamp(),
            cooldown_sec=repeat_cd,
            unrecovered_repairs=self.ping_fix_unrecovered,
            max_unrecovered=self.ping_fix_max_unrecovered,
            first_cooldown_sec=first_cd,
        )
        if wifi_fix_due:
            self.last_wifi_fix_trigger = now
            wifi_outage = self.recovery_toast_gate.wifi_outage_sec(now.timestamp())
            self.run_auto_wifi_drop_fix(wifi_snap, outage_seconds=wifi_outage)
        elif ping_fix_due:
            self.last_ping_fix_trigger = now
            ping_outage = self.recovery_toast_gate.ping_outage_sec(now.timestamp())
            self.run_auto_missing_ping_fix(outage_seconds=ping_outage)
        else:
            self._maybe_emit_wifi_stability_tip(wifi_snap, now, config)

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

        # 6. Laptop thermal warning (cached WMI / nvidia-smi / psutil — never fake)
        self._maybe_emit_thermal_warning(now, config)

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

    @staticmethod
    def effective_missing_ping_cooldown(
        unrecovered_repairs: int,
        first_cooldown_sec: float,
        repeat_cooldown_sec: float,
        max_cooldown_sec: float = 600.0,
    ) -> float:
        """
        Lần sửa đầu: cổng rất ngắn. Các lần sau không hồi phục: backoff
        (repeat * số lần thất bại), chặn vòng lặp vô hạn ở max_unrecovered.
        """
        if int(unrecovered_repairs) <= 0:
            return max(0.0, float(first_cooldown_sec))
        return min(float(repeat_cooldown_sec) * int(unrecovered_repairs), float(max_cooldown_sec))

    @staticmethod
    def should_trigger_missing_ping_fix(
        enabled: bool,
        ping_ms: float,
        ping_measured: bool,
        fail_streak: int,
        min_streak: int,
        now_ts: float,
        last_trigger_ts: float,
        cooldown_sec: float,
        unrecovered_repairs: int,
        max_unrecovered: int = 2,
        first_cooldown_sec: float = None,
    ) -> bool:
        """
        Quyết định có chạy auto-fix khi Ping không đo được hay không.

        Không kích hoạt khi:
          - tính năng tắt
          - đồng hồ chưa đo lần nào (tránh 'sửa' vì meter chưa chạy)
          - ping_ms > 0 (mạng ổn)
          - chưa đủ chuỗi thất bại liên tiếp
          - đang trong cooldown (lần đầu dùng first_cooldown_sec rất ngắn)
          - đã sửa N lần liên tiếp mà Ping vẫn không về
        """
        if not enabled:
            return False
        if not ping_measured:
            return False
        if ping_ms is None:
            return False
        try:
            ping_val = float(ping_ms)
        except (TypeError, ValueError):
            ping_val = -1.0
        if ping_val > 0:
            return False
        if int(fail_streak) < int(min_streak):
            return False
        if int(unrecovered_repairs) >= int(max_unrecovered):
            return False
        effective_cd = (
            BackgroundScheduler.effective_missing_ping_cooldown(
                unrecovered_repairs,
                first_cooldown_sec,
                cooldown_sec,
            )
            if first_cooldown_sec is not None
            else float(cooldown_sec)
        )
        if last_trigger_ts > 0 and (now_ts - last_trigger_ts) < float(effective_cd):
            return False
        return True

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

    def run_auto_missing_ping_fix(self, outage_seconds: float = 0.0):
        """
        Tự động chẩn đoán + sửa an toàn khi Ping timeout / unreachable / -1.
        Chạy nền để không đóng băng UI.
        """
        import threading
        outage_sec = float(outage_seconds or 0.0)

        def _worker():
            try:
                from core.network_optimizer import NetworkOptimizer
                from core.logger import logger
                result = NetworkOptimizer.diagnose_and_repair_missing_ping(
                    apply_dns=False,
                    escalate_dns=True,
                )
                recovered = bool(result.get("recovered"))
                if recovered:
                    self.ping_fix_unrecovered = 0
                elif result.get("repaired"):
                    self.ping_fix_unrecovered += 1
                    logger.info(
                        f"[Scheduler] Missing-ping repair chưa khôi phục Ping "
                        f"(lần {self.ping_fix_unrecovered}/{self.ping_fix_max_unrecovered})."
                    )
                self.network_optimized.emit({
                    "type": "ping_missing",
                    "success": result.get("success", False),
                    "repaired": result.get("repaired", False),
                    "recovered": recovered,
                    "ping_before": result.get("ping_before", -1),
                    "ping_after": result.get("ping_after", -1),
                    "issues": result.get("issues", []),
                    "cause": result.get("cause", ""),
                    "cause_label": result.get("cause_label", ""),
                    "applied_summary": result.get("applied_summary", ""),
                    "needs_dns_confirm": result.get("needs_dns_confirm", False),
                    "needs_location_unlock": result.get("needs_location_unlock", False),
                    "location_gpo_locked": result.get("location_gpo_locked", False),
                    "steps": result.get("steps", []),
                    "skipped": result.get("skipped", []),
                    "details": result,
                    "outage_seconds": outage_sec,
                    "message": result.get(
                        "message",
                        "Đã kiểm tra mạng vì Ping không đo được."
                    ),
                })
            except Exception as e:
                from core.logger import logger
                logger.error(f"[Scheduler] Lỗi khi tự sửa mạng (Ping missing): {e}")

        threading.Thread(target=_worker, daemon=True, name="MissingPingFix").start()

    def run_auto_wifi_drop_fix(self, wifi_snap=None, outage_seconds: float = 0.0):
        """
        Tự động sửa Wi-Fi rớt / vòng reconnect (DHCP, SSID, tắt tiết kiệm pin).
        Ưu tiên hơn missing-ping khi cả hai cùng đến hạn.
        """
        import threading
        outage_sec = float(outage_seconds or 0.0)

        def _worker():
            try:
                from core.network_optimizer import NetworkOptimizer
                from core.wifi_recovery import WifiRecovery
                from core.logger import logger
                result = WifiRecovery.diagnose_and_repair_wifi_drop(
                    apply_dns=False,
                    snapshot=wifi_snap,
                )
                recovered = bool(result.get("recovered"))
                if recovered:
                    self.wifi_fix_unrecovered = 0
                    self.ping_fix_unrecovered = 0
                elif result.get("repaired"):
                    self.wifi_fix_unrecovered += 1
                    logger.info(
                        f"[Scheduler] Wi-Fi drop repair chưa ổn định "
                        f"(lần {self.wifi_fix_unrecovered}/{self.wifi_fix_max_unrecovered})."
                    )
                NetworkOptimizer.last_wifi_drop_report = result
                self.network_optimized.emit({
                    "type": "wifi_drop",
                    "success": result.get("success", False),
                    "repaired": result.get("repaired", False),
                    "recovered": recovered,
                    "ping_before": result.get("ping_before", -1),
                    "ping_after": result.get("ping_after", -1),
                    "issues": result.get("issues", []),
                    "cause": result.get("cause", ""),
                    "cause_label": result.get("cause_label", ""),
                    "applied_summary": result.get("applied_summary", ""),
                    "needs_dns_confirm": result.get("needs_dns_confirm", False),
                    "needs_location_unlock": result.get("needs_location_unlock", False),
                    "needs_wifi_stability_guidance": result.get(
                        "needs_wifi_stability_guidance", not recovered
                    ),
                    "location_gpo_locked": result.get("location_gpo_locked", False),
                    "steps": result.get("steps", []),
                    "skipped": result.get("skipped", []),
                    "details": result,
                    "outage_seconds": outage_sec,
                    "message": result.get(
                        "message",
                        "Đã kiểm tra Wi-Fi vì phát hiện rớt / vòng reconnect."
                    ),
                })
            except Exception as e:
                from core.logger import logger
                logger.error(f"[Scheduler] Lỗi khi tự sửa Wi-Fi: {e}")

        threading.Thread(target=_worker, daemon=True, name="WifiDropFix").start()

    def _maybe_emit_wifi_stability_tip(self, wifi_snap, now, config):
        """Surface Ổn định Wi-Fi CTA when detect is weak/flapping and no repair this tick."""
        try:
            from core.network_optimizer import NetworkOptimizer
            from core.wifi_recovery import WifiRecovery
            from core.wifi_stability import build_wifi_stability_toast_payload

            last_report = (
                getattr(NetworkOptimizer, "last_wifi_drop_report", None)
                or getattr(WifiRecovery, "last_wifi_drop_report", None)
            )
            payload = build_wifi_stability_toast_payload(
                detect=wifi_snap if isinstance(wifi_snap, dict) else {},
                last_report=last_report,
                unrecovered_repairs=int(self.wifi_fix_unrecovered or 0),
                repair_running=False,
            )
            if not payload:
                return
            if not self.recovery_toast_gate.allow_stability_tip_from_config(
                now.timestamp(),
                config if isinstance(config, dict) else {},
            ):
                return
            self.network_optimized.emit(payload)
        except Exception:
            pass

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

    def _maybe_emit_thermal_warning(self, now, config):
        """Probe temps off the UI thread; toast when hot, with cooldown."""
        cfg = config if isinstance(config, dict) else {}
        if not cfg.get("thermal_monitor_enabled", True):
            return
        try:
            warn = float(cfg.get("thermal_warn_celsius", 90))
        except (TypeError, ValueError):
            warn = 90.0

        def _done(snap):
            try:
                self.thermal_snapshot_ready.emit(snap if isinstance(snap, dict) else {})
            except Exception:
                pass
            if not cfg.get("thermal_warn_toast_enabled", True):
                return
            try:
                from core.thermal_monitor import build_thermal_toast_payload
                payload = build_thermal_toast_payload(snap, warn_celsius=warn)
            except Exception:
                payload = None
            if not payload:
                return
            try:
                if not self.thermal_toast_gate.allow_from_config(time.time(), cfg):
                    return
            except Exception:
                return
            self.thermal_warning.emit(payload)

        try:
            from core.thermal_monitor import ensure_snapshot_async
            ensure_snapshot_async(_done, force_refresh=False, warn_celsius=warn)
        except Exception:
            pass
