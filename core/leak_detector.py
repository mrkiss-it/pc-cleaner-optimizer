"""
Memory Leak Detector - Phát hiện các tiến trình có dấu hiệu rò rỉ bộ nhớ RAM.

Thuật toán: Theo dõi chuỗi thời gian (time-series sliding window) cho từng tiến trình.
Nếu RAM tăng liên tục trong N lần kiểm tra liên tiếp VÀ đạt ngưỡng tuyệt đối,
hệ thống phát cảnh báo và gợi ý 1-click thu hồi.

Thiết kế:
  - Cực kỳ nhẹ: chỉ đọc thông tin có sẵn từ psutil (dùng lại vòng lặp tiến trình)
  - Cooldown 10 phút mỗi tiến trình để tránh spam thông báo
  - Tự động bỏ qua các tiến trình trong Whitelist và System
"""
import time
import psutil
from collections import defaultdict
from typing import Dict, Any, List, Optional, Callable
from PyQt5.QtCore import QObject, pyqtSignal, QTimer
from core.logger import logger
from core.process_manager import PROTECTED_PROCESSES


# Cấu hình ngưỡng phát hiện rò rỉ
LEAK_WINDOW_SIZE = 4          # Số lần kiểm tra liên tiếp cần tăng (sliding window)
LEAK_MIN_GROWTH_MB = 80.0     # Mức tăng ròng tối thiểu trong cửa sổ (MB)
LEAK_MIN_TOTAL_MB = 200.0     # RAM hiện tại tối thiểu của tiến trình để theo dõi (MB)
COOLDOWN_SECONDS = 600        # 10 phút giữa 2 cảnh báo cho cùng 1 tiến trình
CHECK_INTERVAL_MS = 30000     # Kiểm tra mỗi 30 giây


class MemoryLeakDetector(QObject):
    """
    Bộ phát hiện rò rỉ bộ nhớ chạy ngầm trong nền.
    Phát tín hiệu `leak_detected` khi phát hiện tiến trình có dấu hiệu tràn bộ nhớ.
    """
    leak_detected = pyqtSignal(dict)    # {pid, name, start_mb, current_mb, growth_mb}
    status_updated = pyqtSignal(str)    # Trạng thái ngắn gọn cho UI

    def __init__(self, config_manager=None, parent=None):
        super().__init__(parent)
        self.config_manager = config_manager
        # {pid: [ram_mb_t0, ram_mb_t1, ...]} - lịch sử RAM theo chuỗi thời gian
        self._ram_history: Dict[int, List[float]] = defaultdict(list)
        # {pid: last_alert_timestamp}
        self._alert_cooldown: Dict[int, float] = {}
        # Danh sách PID đã từng được cảnh báo trong phiên này
        self._alerted_pids: set = set()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_leaks)
        self._is_running = False

    def start(self):
        """Bắt đầu theo dõi Memory Leak."""
        if self._is_running:
            return
        self._is_running = True
        self._timer.start(CHECK_INTERVAL_MS)
        logger.info("[LeakDetector] Bắt đầu giám sát rò rỉ bộ nhớ (mỗi 30 giây).")

    def stop(self):
        """Dừng theo dõi Memory Leak."""
        self._timer.stop()
        self._is_running = False
        logger.info("[LeakDetector] Đã dừng giám sát rò rỉ bộ nhớ.")

    def get_whitelist(self) -> set:
        """Lấy danh sách whitelist từ cấu hình."""
        if self.config_manager:
            return set(n.lower() for n in self.config_manager.get("process_whitelist", []))
        return set()

    def check_leaks(self) -> List[Dict[str, Any]]:
        """
        Kiểm tra một lần toàn bộ tiến trình đang chạy.
        Trả về danh sách các tiến trình bị phát hiện là rò rỉ trong lần kiểm tra này.
        """
        if self.config_manager and not self.config_manager.get("memory_leak_detection_enabled", True):
            return []

        whitelist = self.get_whitelist()
        now = time.time()
        leaks_found = []
        active_pids = set()

        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                pid = proc.info['pid']
                name = (proc.info['name'] or f"pid-{pid}")
                name_lower = name.lower()
                mem_info = proc.info.get('memory_info')

                if not mem_info:
                    continue

                # Bỏ qua: System, Protected, Whitelist, bản thân ứng dụng
                if pid <= 4:
                    continue
                if name_lower in PROTECTED_PROCESSES:
                    continue
                if name_lower in whitelist:
                    continue

                rss_mb = mem_info.rss / (1024 ** 2)

                # Chỉ theo dõi tiến trình dùng ít nhất LEAK_MIN_TOTAL_MB
                if rss_mb < LEAK_MIN_TOTAL_MB:
                    continue

                active_pids.add(pid)
                history = self._ram_history[pid]
                history.append(rss_mb)

                # Giữ cửa sổ trượt tối đa LEAK_WINDOW_SIZE+1 mẫu
                if len(history) > LEAK_WINDOW_SIZE + 1:
                    history.pop(0)

                # Chưa đủ dữ liệu
                if len(history) < LEAK_WINDOW_SIZE:
                    continue

                # Kiểm tra xu hướng tăng liên tục
                is_monotone_growing = all(
                    history[i] < history[i + 1] for i in range(len(history) - 1)
                )
                growth_mb = history[-1] - history[0]

                if not is_monotone_growing:
                    continue
                if growth_mb < LEAK_MIN_GROWTH_MB:
                    continue

                # Kiểm tra cooldown
                last_alert = self._alert_cooldown.get(pid, 0)
                if now - last_alert < COOLDOWN_SECONDS:
                    continue

                # Phát cảnh báo
                self._alert_cooldown[pid] = now
                self._alerted_pids.add(pid)

                leak_info = {
                    "pid": pid,
                    "name": name,
                    "start_mb": round(history[0], 1),
                    "current_mb": round(rss_mb, 1),
                    "growth_mb": round(growth_mb, 1),
                    "window_checks": len(history)
                }
                leaks_found.append(leak_info)
                logger.warning(
                    f"[LeakDetector] Phát hiện rò rỉ bộ nhớ: {name} (PID {pid}) "
                    f"tăng từ {history[0]:.1f} MB → {rss_mb:.1f} MB "
                    f"(+{growth_mb:.1f} MB trong {len(history)} lần kiểm tra)"
                )
                self.leak_detected.emit(leak_info)

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        # Dọn dẹp lịch sử cho các tiến trình đã thoát
        stale_pids = set(self._ram_history.keys()) - active_pids
        for pid in stale_pids:
            self._ram_history.pop(pid, None)
            self._alert_cooldown.pop(pid, None)

        return leaks_found

    def get_monitored_summary(self) -> Dict[str, Any]:
        """Trả về tóm tắt trạng thái theo dõi hiện tại cho UI."""
        return {
            "is_running": self._is_running,
            "monitored_count": len(self._ram_history),
            "alerted_pids_count": len(self._alerted_pids),
            "check_interval_seconds": CHECK_INTERVAL_MS // 1000,
        }
