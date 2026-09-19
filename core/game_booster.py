import os
import psutil
import ctypes
from typing import Dict, Any, List
from core.logger import logger
from core.memory_optimizer import MemoryOptimizer

# Windows Priority Classes
IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020
ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
HIGH_PRIORITY_CLASS = 0x00000080

# Known background processes safe to demote during gaming
BACKGROUND_HOGS = {
    "searchindexer.exe", "onedrive.exe", "googledrivesync.exe", 
    "dropbox.exe", "cortana.exe", "phoneexperiencehost.exe",
    "microsoftedgeupdate.exe", "googleupdate.exe", "gameloop.exe"
}

# Known game executables / game launchers
GAME_KEYWORDS = [
    "game", "steam", "riot", "valorant", "league", "dota", 
    "csgo", "cs2", "pubg", "genshin", "fifa", "gta", "minecraft",
    "epicgames", "fortnite", "overwatch", "apex"
]

class GameBooster:
    """
    Chế độ Tăng Tốc Gaming (Game Boost Mode):
    Tối ưu hóa toàn diện RAM, hạ độ ưu tiên các tác vụ nền không cần thiết,
    tập trung tài nguyên CPU/RAM tối đa cho trò chơi hoặc ứng dụng đồ họa nặng.
    """
    _is_active: bool = False
    _saved_priorities: Dict[int, int] = {}

    @classmethod
    def is_active(cls) -> bool:
        return cls._is_active

    @classmethod
    def enable_game_boost(cls, whitelist: set = None) -> Dict[str, Any]:
        """
        Kích hoạt chế độ Game Boost:
        1. Quét dọn và giải phóng bộ nhớ RAM sâu toàn hệ thống
        2. Hạ độ ưu tiên của các tiến trình chạy ngầm
        3. Tăng độ ưu tiên cho các trò chơi / tác vụ nặng đang mở

        Args:
            whitelist: Tập hợp tên tiến trình (chữ thường) được bảo vệ khỏi thay đổi ưu tiên.
        """
        if cls._is_active:
            return {"success": True, "already_active": True, "message": "Game Boost đã đang bật"}

        logger.info("[GameBooster] Đang kích hoạt Chế độ Tăng Tốc Gaming...")
        cls._saved_priorities.clear()
        safe_whitelist = whitelist or set()

        # 1. Giải phóng RAM tối đa (truyền whitelist vào optimizer)
        ram_res = MemoryOptimizer.optimize_ram(whitelist=safe_whitelist)
        freed_ram_mb = ram_res.get("freed_mb", 0.0)

        # 2. Quét và điều chỉnh độ ưu tiên
        demoted_count = 0
        boosted_count = 0

        for proc in psutil.process_iter(['pid', 'name']):
            try:
                pid = proc.info['pid']
                name = (proc.info['name'] or "").lower()

                if pid in (0, 4):
                    continue
                # Bỏ qua tiến trình trong whitelist
                if name in safe_whitelist:
                    continue

                # Hạ độ ưu tiên các tiến trình chạy ngầm
                if name in BACKGROUND_HOGS:
                    try:
                        old_prio = proc.nice()
                        cls._saved_priorities[pid] = old_prio
                        proc.nice(psutil.IDLE_PRIORITY_CLASS)
                        demoted_count += 1
                    except Exception:
                        pass

                # Tăng độ ưu tiên cho các tiến trình game
                elif any(kw in name for kw in GAME_KEYWORDS):
                    try:
                        old_prio = proc.nice()
                        cls._saved_priorities[pid] = old_prio
                        proc.nice(psutil.HIGH_PRIORITY_CLASS)
                        boosted_count += 1
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            except Exception:
                continue

        cls._is_active = True
        logger.info(
            f"[GameBooster] Game Boost đã kích hoạt: Giải phóng {freed_ram_mb:.1f} MB RAM, "
            f"hạ độ ưu tiên {demoted_count} tác vụ nền, tăng tốc {boosted_count} trò chơi."
        )

        return {
            "success": True,
            "is_active": True,
            "freed_ram_mb": freed_ram_mb,
            "demoted_count": demoted_count,
            "boosted_count": boosted_count
        }

    @classmethod
    def disable_game_boost(cls) -> Dict[str, Any]:
        """
        Tắt chế độ Game Boost và khôi phục độ ưu tiên mặc định cho các tiến trình
        """
        if not cls._is_active:
            return {"success": True, "already_inactive": True, "message": "Game Boost chưa được bật"}

        logger.info("[GameBooster] Đang tắt Chế độ Game Boost, khôi phục hệ thống...")
        restored_count = 0

        for pid, old_prio in cls._saved_priorities.items():
            try:
                proc = psutil.Process(pid)
                proc.nice(old_prio)
                restored_count += 1
            except Exception:
                continue

        cls._saved_priorities.clear()
        cls._is_active = False

        logger.info(f"[GameBooster] Đã khôi phục {restored_count} tiến trình về trạng thái bình thường.")
        return {
            "success": True,
            "is_active": False,
            "restored_count": restored_count
        }
