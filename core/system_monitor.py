import os
import time
import psutil
from typing import Dict, Any
from PyQt5.QtCore import QObject, QTimer, pyqtSignal

class SystemMonitor:
    _last_cpu_time = 0.0
    _last_cpu_val = 0.0

    _last_net_bytes_sent = 0
    _last_net_bytes_recv = 0
    _last_net_time = 0.0
    _last_net_speed_down = 0.0
    _last_net_speed_up = 0.0
    _cached_ping = -1.0
    _last_ping_time = 0.0
    _cached_adapter = ""

    @staticmethod
    def get_ram_info() -> Dict[str, Any]:
        """
        Lấy thông tin chi tiết về bộ nhớ RAM
        """
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024 ** 3), 2),
            "used_gb": round((mem.total - mem.available) / (1024 ** 3), 2),
            "available_gb": round(mem.available / (1024 ** 3), 2),
            "percent": mem.percent,
            "total_mb": round(mem.total / (1024 ** 2), 1),
            "available_mb": round(mem.available / (1024 ** 2), 1),
            "used_mb": round((mem.total - mem.available) / (1024 ** 2), 1)
        }

    @classmethod
    def get_cpu_info(cls) -> Dict[str, Any]:
        """
        Lấy phần trăm sử dụng CPU kèm cache 0.5s tránh bị reset đo lường về 0%
        khi nhiều widget cùng truy vấn tại một thời điểm
        """
        now = time.time()
        if now - cls._last_cpu_time < 0.5:
            percent = cls._last_cpu_val
        else:
            val = psutil.cpu_percent(interval=None)
            if val == 0.0 and cls._last_cpu_val > 0.0:
                percent = cls._last_cpu_val
            else:
                percent = val
                cls._last_cpu_val = val
            cls._last_cpu_time = now

        count = psutil.cpu_count(logical=True)
        return {
            "percent": percent,
            "core_count": count
        }

    @staticmethod
    def get_disk_info(drive: str = "C:\\") -> Dict[str, Any]:
        """
        Lấy thông tin dung lượng ổ đĩa hệ thống (mặc định C:)
        """
        try:
            usage = psutil.disk_usage(drive)
            return {
                "drive": drive,
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "used_gb": round(usage.used / (1024 ** 3), 2),
                "free_gb": round(usage.free / (1024 ** 3), 2),
                "percent": usage.percent
            }
        except Exception:
            return {
                "drive": drive,
                "total_gb": 0,
                "used_gb": 0,
                "free_gb": 0,
                "percent": 0
            }

    @staticmethod
    def format_bytes_speed(bps: float) -> str:
        """Định dạng tốc độ mạng B/s, KB/s, MB/s."""
        if bps < 1024:
            return f"{int(bps)} B/s"
        elif bps < 1024 * 1024:
            return f"{bps / 1024:.1f} KB/s"
        else:
            return f"{bps / (1024 * 1024):.2f} MB/s"

    @staticmethod
    def _measure_quick_ping() -> float:
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.35)
            t0 = time.time()
            s.connect(("8.8.8.8", 53))
            s.close()
            return round((time.time() - t0) * 1000, 1)
        except Exception:
            return -1.0

    @staticmethod
    def _detect_active_adapter() -> str:
        try:
            stats = psutil.net_if_stats()
            for name, st in stats.items():
                if st.isup and "loopback" not in name.lower() and st.speed > 0:
                    return name
            for name, st in stats.items():
                if st.isup and "loopback" not in name.lower():
                    return name
        except Exception:
            pass
        return "Mạng nội bộ"

    @classmethod
    def get_network_info(cls) -> Dict[str, Any]:
        """
        Lấy tốc độ tải xuống, tải lên theo thời gian thực và độ trễ Ping.
        """
        now = time.time()
        try:
            counters = psutil.net_io_counters()
            bytes_recv = counters.bytes_recv
            bytes_sent = counters.bytes_sent
        except Exception:
            bytes_recv = 0
            bytes_sent = 0

        if cls._last_net_time > 0 and now > cls._last_net_time:
            dt = max(now - cls._last_net_time, 0.2)
            down_bps = max(0.0, (bytes_recv - cls._last_net_bytes_recv) / dt)
            up_bps = max(0.0, (bytes_sent - cls._last_net_bytes_sent) / dt)
            cls._last_net_speed_down = down_bps
            cls._last_net_speed_up = up_bps
        else:
            down_bps = cls._last_net_speed_down
            up_bps = cls._last_net_speed_up

        cls._last_net_bytes_recv = bytes_recv
        cls._last_net_bytes_sent = bytes_sent
        cls._last_net_time = now

        # Đo ping định kỳ mỗi 4 giây
        if now - cls._last_ping_time > 4.0:
            cls._cached_ping = cls._measure_quick_ping()
            cls._last_ping_time = now

        # Xác định card mạng chính
        if not cls._cached_adapter or (int(now) % 10 == 0):
            cls._cached_adapter = cls._detect_active_adapter()

        return {
            "down_bps": down_bps,
            "up_bps": up_bps,
            "down_speed_str": cls.format_bytes_speed(down_bps),
            "up_speed_str": cls.format_bytes_speed(up_bps),
            "total_recv_mb": round(bytes_recv / (1024 ** 2), 1),
            "total_sent_mb": round(bytes_sent / (1024 ** 2), 1),
            "ping_ms": cls._cached_ping,
            "adapter": cls._cached_adapter
        }

    @staticmethod
    def get_all_stats() -> Dict[str, Any]:
        return {
            "ram": SystemMonitor.get_ram_info(),
            "cpu": SystemMonitor.get_cpu_info(),
            "disk": SystemMonitor.get_disk_info("C:\\"),
            "net": SystemMonitor.get_network_info(),
            "process_count": len(psutil.pids())
        }

class SystemMonitorHub(QObject):
    """
    Trạm điều phối thông số thời gian thực duy nhất:
    Thu thập RAM, CPU, Ổ đĩa mỗi 800ms và đồng bộ đồng thời tới cả
    Bảng Điều Khiển (MainWindow) và Widget Nổi (FloatingWidget).
    """
    stats_updated = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_stats = {}
        # Prime psutil measurement
        psutil.cpu_percent(interval=None)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_stats)
        self.timer.start(800)  # Cập nhật mỗi 0.8 giây để giao diện luôn nhảy số mượt mà
        self.poll_stats()

    def poll_stats(self):
        stats = SystemMonitor.get_all_stats()
        self._last_stats = stats
        self.stats_updated.emit(stats)

    def force_refresh(self):
        """
        Ép cập nhật tức thì (ví dụ sau khi vừa dọn dẹp hoặc tối ưu RAM xong)
        """
        self.poll_stats()

    def get_latest(self) -> Dict[str, Any]:
        if not self._last_stats:
            self._last_stats = SystemMonitor.get_all_stats()
        return self._last_stats
