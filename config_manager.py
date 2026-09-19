import os
import sys
import json
from typing import Dict, Any

DEFAULT_CONFIG = {
    "auto_clean_enabled": True,
    "interval_minutes": 60,
    "auto_ram_optimize_enabled": True,
    "ram_threshold_percent": 80,
    "floating_widget_enabled": True,
    "run_on_startup": False,
    "minimize_to_tray_on_close": True,
    "show_notifications": True,
    "targets": {
        "user_temp": True,
        "system_temp": True,
        "recycle_bin": True,
        "browser_cache": True,
        "crash_dumps": True,
        "windows_update": True,
        "app_caches": True,
        "ram_optimize": True
    },
    "history": [],
    "memory_leak_detection_enabled": True,
    "memory_leak_threshold_mb": 150,
    "process_whitelist": ["obs64.exe", "premiere.exe", "photoshop.exe", "vmware.exe", "virtualbox.exe"],
    "auto_network_optimize_enabled": True,
    "auto_network_ping_threshold_ms": 180,
    "auto_best_dns_enabled": False,
    "auto_best_dns_interval_hours": 2,
    "auto_security_scan_enabled": True,
    "auto_security_scan_interval_hours": 24,
    "last_security_scan_result": {}
}

class ConfigManager:
    def __init__(self, config_path: str = None):
        if config_path is None:
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(base_dir, "config.json")
        self.config_path = config_path
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Merge with defaults in case of missing keys
                    merged = DEFAULT_CONFIG.copy()
                    merged.update(data)
                    merged["targets"] = {**DEFAULT_CONFIG["targets"], **data.get("targets", {})}
                    return merged
            except Exception as e:
                print(f"[ConfigManager] Error reading config: {e}")
        return DEFAULT_CONFIG.copy()

    def save_config(self) -> bool:
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ConfigManager] Error saving config: {e}")
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.config[key] = value
        self.save_config()

    def add_history(self, junk_freed_mb: float, ram_freed_mb: float, trigger_type: str = "manual"):
        from datetime import datetime
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "junk_freed_mb": round(junk_freed_mb, 2),
            "ram_freed_mb": round(ram_freed_mb, 2),
            "trigger_type": trigger_type
        }
        history = self.config.get("history", [])
        history.insert(0, record)
        # Keep latest 100 entries
        self.config["history"] = history[:100]
        self.save_config()

    def get_stats(self) -> Dict[str, Any]:
        history = self.config.get("history", [])
        total_junk = sum(h.get("junk_freed_mb", 0) for h in history)
        total_ram = sum(h.get("ram_freed_mb", 0) for h in history)
        return {
            "total_cleanups": len(history),
            "total_junk_freed_mb": round(total_junk, 2),
            "total_ram_freed_mb": round(total_ram, 2)
        }

    def get_whitelist_set(self) -> set:
        """Trả về whitelist tiến trình dưới dạng set chữ thường để so sánh nhanh."""
        return set(n.lower() for n in self.config.get("process_whitelist", []))

    def add_to_whitelist(self, process_name: str) -> bool:
        """Thêm tiến trình vào whitelist."""
        whitelist = self.config.get("process_whitelist", [])
        name_lower = process_name.strip().lower()
        if name_lower not in [n.lower() for n in whitelist]:
            whitelist.append(process_name.strip())
            self.set("process_whitelist", whitelist)
            return True
        return False

    def remove_from_whitelist(self, process_name: str) -> bool:
        """Xóa tiến trình khỏi whitelist."""
        whitelist = self.config.get("process_whitelist", [])
        name_lower = process_name.strip().lower()
        new_list = [n for n in whitelist if n.lower() != name_lower]
        if len(new_list) < len(whitelist):
            self.set("process_whitelist", new_list)
            return True
        return False
