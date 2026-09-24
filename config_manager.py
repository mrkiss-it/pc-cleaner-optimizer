import os
import sys
import copy
import json
import re
from typing import Dict, Any, Optional

# Gemini 2.5 Flash 404s for many new AI Studio keys (Sep 2026). Never persist it.
DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
COPILOT_PROVIDERS = ("auto", "gemini")
# Dropped Ollama / Hybrid-local keys — never re-save them.
RETIRED_COPILOT_KEYS = frozenset({
    "ai_copilot_ollama_base_url",
    "ai_copilot_ollama_model",
    "ai_copilot_ollama_host",
    "ai_copilot_ollama_enabled",
})
RETIRED_GEMINI_MODELS = frozenset({
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro-latest",
})
_GEMINI_MODEL_ID_RE = re.compile(r"[A-Za-z0-9._-]+")


def canonicalize_gemini_model(model: Optional[str]) -> str:
    """Return a persistable Gemini model id. Retired 2.5/1.5 ids become the default."""
    raw = str(model or "").strip()
    if raw.lower().startswith("models/"):
        raw = raw[7:]
    if not raw or not _GEMINI_MODEL_ID_RE.fullmatch(raw):
        return DEFAULT_GEMINI_MODEL
    if raw.lower() in RETIRED_GEMINI_MODELS or raw in RETIRED_GEMINI_MODELS:
        return DEFAULT_GEMINI_MODEL
    return raw


def canonicalize_copilot_provider(value: Optional[str]) -> str:
    """Persistable Copilot backend: auto | gemini (retired Ollama aliases → auto)."""
    raw = str(value or "").strip().lower()
    aliases = {
        "tu dong": "auto",
        "tự động": "auto",
        "automatic": "auto",
        "hybrid": "auto",
        "google": "gemini",
        "cloud": "gemini",
        "online": "gemini",
        "ollama": "auto",
        "local": "auto",
        "offline": "auto",
        "localhost": "auto",
    }
    raw = aliases.get(raw, raw)
    if raw in COPILOT_PROVIDERS:
        return raw
    return "auto"


DEFAULT_CONFIG = {
    "auto_clean_enabled": True,
    "interval_minutes": 60,
    "auto_ram_optimize_enabled": True,
    "ram_threshold_percent": 80,
    "thermal_monitor_enabled": True,
    "thermal_warn_toast_enabled": True,
    "thermal_warn_celsius": 90,
    "thermal_warn_toast_cooldown_seconds": 1800,
    "floating_widget_enabled": True,
    "run_on_startup": False,
    "minimize_to_tray_on_close": True,
    "show_notifications": True,
    "email_report_enabled": False,
    "email_report_to": "",
    "email_report_frequency": "weekly",
    "email_report_send_hour": 8,
    "email_report_send_minute": 0,
    "email_report_smtp_host": "",
    "email_report_smtp_port": 587,
    "email_report_smtp_username": "",
    "email_report_smtp_use_tls": True,
    "email_report_smtp_use_ssl": False,
    "email_report_from_name": "",
    "email_report_from_address": "",
    "email_report_last_sent_at": "",
    "email_report_last_attempt_at": "",
    "email_report_last_error": "",
    "instant_screen_notifications_enabled": True,
    "notification_sound_enabled": False,
    "notification_duration_ms": 4500,
    "targets": {
        "user_temp": True,
        "thumbnail_cache": True,
        "shell_font_cache": True,
        "browser_cache": True,
        "inet_cache": True,
        "shader_cache": True,
        "gpu_shader_caches": True,
        "crash_dumps": True,
        "app_caches": True,
        "discord_cache": True,
        "telegram_cache": True,
        "zalo_cache": True,
        "messenger_cache": True,
        "teams_cache": True,
        "tiktok_cache": True,
        "viber_cache": True,
        "steam_caches": False,
        "adobe_caches": False,
        "blender_caches": False,
        "unity_caches": False,
        "epic_caches": False,
        "empty_user_folders": False,
        "toolchain_caches": True,
        "nuget_packages": False,
        "gradle_caches": False,
        "cargo_cache": False,
        "office_cache": True,
        "office_file_cache": False,
        "store_cache": True,
        "delivery_cache": True,
        "recycle_bin": False,
        "downloads_old": False,
        "system_temp": True,
        "windows_update": True,
        "system_delivery_opt": True,
        "windows_setup_temp": True,
        "windows_logs": True,
        "system_wer": True,
        "system_dumps": False,
        "prefetch": False,
        "windows_old": False,
        "component_cleanup": False,
        "hibernate_file": False,
        "ram_optimize": True,
    },
    "downloads_old_min_days": 30,
    "c_drive_min_clean_mb": 10,
    "c_drive_exclude_paths": [],
    "low_disk_warn_enabled": True,
    "low_disk_free_gb": 10.0,
    "low_disk_free_percent": 10.0,
    "low_disk_threshold_mode": "gb",
    "low_disk_warn_toast_cooldown_seconds": 1800,
    "history": [],
    "memory_leak_detection_enabled": True,
    "memory_leak_threshold_mb": 150,
    "process_whitelist": ["obs64.exe", "premiere.exe", "photoshop.exe", "vmware.exe", "virtualbox.exe"],
    "auto_network_optimize_enabled": True,
    "auto_network_ping_threshold_ms": 180,
    "auto_network_ping_fix_enabled": True,
    "auto_network_ping_fail_streak": 1,
    "auto_network_ping_fix_first_cooldown_seconds": 8,
    "auto_network_ping_fix_cooldown_seconds": 300,
    "auto_network_wifi_fix_first_cooldown_seconds": 12,
    "auto_network_wifi_fix_cooldown_seconds": 300,
    "auto_network_recovery_success_toast_cooldown_seconds": 180,
    "auto_network_recovery_min_outage_retoast_seconds": 60,
    "auto_network_recovery_failure_toast_cooldown_seconds": 45,
    "auto_network_recovery_cta_toast_cooldown_seconds": 0,
    "auto_network_wifi_stability_tip_cooldown_seconds": 1800,
    "auto_best_dns_enabled": False,
    "auto_best_dns_interval_hours": 2,
    "auto_security_scan_enabled": True,
    "auto_security_scan_interval_hours": 24,
    "last_security_scan_result": {},
    "window_geometry": {
        "x": -1,
        "y": -1,
        "width": 1000,
        "height": 680,
        "is_maximized": False
    },
    "last_active_tab": 0,
    "ai_copilot_cloud_enabled": False,
    "ai_copilot_provider": "auto",
    "ai_copilot_gemini_model": DEFAULT_GEMINI_MODEL,
    "ai_autopilot_enabled": True,
    "ai_autopilot_mode": "auto",
    "companion_enabled": True,
    "companion_reflection_enabled": True,
    "companion_may_propose_actions": True,
    "companion_nudges_enabled": True,
    "companion_reflection_hour": 20,
    "check_for_updates_enabled": True,
    "github_owner": "mrkiss-it",
    "github_repo": "pc-cleaner-optimizer",
    "update_check_interval_hours": 6,
    "last_update_check_ts": 0.0,
    "last_update_check_etag": "",
    "last_update_check_status": 0,
    "cached_release_payload": {},
    "dismissed_update_tag": "",
    "eula_accepted": False,
    "eula_accepted_version": 0,
    "eula_accepted_at": "",
}

# Bump when in-app EULA / LICENSE terms change so users re-accept.
EULA_VERSION = 1

# Keys that must never be written to tracked/shared config.json
SECRET_KEYS = frozenset({
    "ai_copilot_gemini_api_key",
    "email_report_smtp_password",
})


def _user_data_dir() -> str:
    """%%APPDATA%%\\PCAutoCleaner on Windows, ~/.config/PCAutoCleaner elsewhere."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, "PCAutoCleaner")
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(xdg, "PCAutoCleaner")


def user_data_dir() -> str:
    """Public alias for the per-user AppData / XDG config directory."""
    return _user_data_dir()


def companion_dir() -> str:
    """Local companion memory (diary, skills, sổ tay) under AppData, overridable for tests."""
    override = os.environ.get("PCAUTOCLEANER_COMPANION_DIR", "").strip()
    if override:
        return override
    return os.path.join(_user_data_dir(), "companion")


def secrets_file_path() -> str:
    """User-local secrets file, outside the git tree (%%APPDATA%% or ~/.config)."""
    override = os.environ.get("PCAUTOCLEANER_SECRETS_PATH", "").strip()
    if override:
        return override
    return os.path.join(_user_data_dir(), "secrets.json")


def eula_file_path() -> str:
    """Persisted EULA acceptance (%%APPDATA%%\\PCAutoCleaner\\eula.json, overridable)."""
    override = os.environ.get("PCAUTOCLEANER_EULA_PATH", "").strip()
    if override:
        return override
    return os.path.join(_user_data_dir(), "eula.json")


def _deep_merge(target: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    """Gộp đệ quy từ src vào target, giữ nguyên tất cả giá trị tùy chỉnh của người dùng."""
    for k, v in src.items():
        if k in target and isinstance(target[k], dict) and isinstance(v, dict):
            target[k] = _deep_merge(target[k], v)
        else:
            target[k] = v
    return target


class ConfigManager:
    """
    Quản lý cấu hình tập trung và bền vững cho PC Auto Cleaner:
    - Chuẩn Windows: Lưu trữ trong %APPDATA%\\PCAutoCleaner\\config.json khi chạy bản cài đặt.
    - Chế độ Phát triển/Portable: Tự động nhận diện thư mục cục bộ của ứng dụng.
    - Deep Merge: Bảo toàn toàn bộ tùy chọn quét, lịch trình, whitelist khi cập nhật phiên bản mới.
    - Quản lý trạng thái cửa sổ (Geometry) và Tab đang làm việc.
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            if getattr(sys, 'frozen', False):
                # Khi chạy từ file EXE độc lập đã đóng gói:
                appdata = os.environ.get("APPDATA")
                appdata_dir = os.path.join(appdata, "PCAutoCleaner") if appdata else None
                if appdata_dir:
                    os.makedirs(appdata_dir, exist_ok=True)
                    appdata_cfg = os.path.join(appdata_dir, "config.json")
                else:
                    appdata_cfg = None

                base_dir = os.path.dirname(sys.executable)
                local_cfg = os.path.join(base_dir, "config.json")

                # Ưu tiên sử dụng AppData để không bị giới hạn quyền ghi (như trong C:\Program Files)
                if appdata_cfg and os.path.exists(appdata_cfg):
                    config_path = appdata_cfg
                elif appdata_cfg and os.path.exists(local_cfg):
                    # Tự động di chuyển (migrate) cấu hình cũ sang AppData
                    try:
                        import shutil
                        shutil.copy2(local_cfg, appdata_cfg)
                        config_path = appdata_cfg
                    except Exception:
                        config_path = local_cfg
                else:
                    config_path = appdata_cfg if appdata_cfg else local_cfg
            else:
                # Khi chạy từ mã nguồn Python (Dev / Tests): Lưu tại thư mục dự án
                base_dir = os.path.dirname(os.path.abspath(__file__))
                config_path = os.path.join(base_dir, "config.json")

        self.config_path = config_path
        self._secrets: Dict[str, Any] = {}
        self._secrets_path = secrets_file_path()
        self.config = self.load_config()
        self._load_secrets()
        self._migrate_secrets_from_config()
        self._migrate_retired_gemini_model()
        self._migrate_retired_copilot_keys()

    def _sanitize_gemini_model_in(self, data: Dict[str, Any]) -> bool:
        """Coerce retired Gemini ids so dist/AppData config can never re-save 2.5-flash."""
        current = data.get("ai_copilot_gemini_model", DEFAULT_GEMINI_MODEL)
        fixed = canonicalize_gemini_model(current)
        if data.get("ai_copilot_gemini_model") != fixed:
            data["ai_copilot_gemini_model"] = fixed
            return True
        return False

    def _migrate_retired_gemini_model(self) -> None:
        """Rewrite dist/AppData config if it still stores a retired Gemini id."""
        self._sanitize_gemini_model_in(self.config)
        disk_stale = False
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    disk = json.load(f)
                if isinstance(disk, dict) and "ai_copilot_gemini_model" in disk:
                    raw = str(disk.get("ai_copilot_gemini_model") or "").strip()
                    if canonicalize_gemini_model(raw) != raw:
                        disk_stale = True
            except Exception:
                pass
        if disk_stale:
            self.save_config()

    def _strip_retired_copilot_keys(self, data: Dict[str, Any]) -> bool:
        """Drop Ollama Hybrid keys and coerce retired provider ids to auto/gemini."""
        dirty = False
        for key in RETIRED_COPILOT_KEYS:
            if key in data:
                data.pop(key, None)
                dirty = True
        if "ai_copilot_provider" in data:
            fixed = canonicalize_copilot_provider(data.get("ai_copilot_provider"))
            if data.get("ai_copilot_provider") != fixed:
                data["ai_copilot_provider"] = fixed
                dirty = True
        return dirty

    def _migrate_retired_copilot_keys(self) -> None:
        """Rewrite dist/AppData config if it still stores Ollama Hybrid fields."""
        dirty = self._strip_retired_copilot_keys(self.config)
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    disk = json.load(f)
                if isinstance(disk, dict) and self._strip_retired_copilot_keys(disk):
                    dirty = True
            except Exception:
                pass
        if dirty:
            self.save_config()

    def load_config(self) -> Dict[str, Any]:
        """Tải cấu hình với cơ chế Deep Merge để bảo toàn mọi thiết lập cũ."""
        merged = copy.deepcopy(DEFAULT_CONFIG)
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    _deep_merge(merged, data)
            except Exception as e:
                print(f"[ConfigManager] Lỗi khi đọc file cấu hình: {e}")
        self._sanitize_gemini_model_in(merged)
        self._strip_retired_copilot_keys(merged)
        return merged

    def save_config(self) -> bool:
        """Lưu cấu hình an toàn. Không ghi khóa bí mật vào config.json."""
        try:
            parent_dir = os.path.dirname(os.path.abspath(self.config_path))
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            self._sanitize_gemini_model_in(self.config)
            self._strip_retired_copilot_keys(self.config)
            to_write = copy.deepcopy(self.config)
            for k in SECRET_KEYS:
                to_write.pop(k, None)
            self._sanitize_gemini_model_in(to_write)
            self._strip_retired_copilot_keys(to_write)

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(to_write, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ConfigManager] Lỗi khi lưu cấu hình: {e}")
            return False

    def _load_secrets(self) -> None:
        self._secrets = {}
        path = getattr(self, "_secrets_path", "") or secrets_file_path()
        if not path or not os.path.exists(path):
            return
        try:
            if os.path.getsize(path) == 0:
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._secrets = {k: v for k, v in data.items() if k in SECRET_KEYS}
        except Exception as e:
            print(f"[ConfigManager] Lỗi khi đọc secrets: {e}")

    def _save_secrets(self) -> bool:
        path = getattr(self, "_secrets_path", "") or secrets_file_path()
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            payload = {k: v for k, v in self._secrets.items() if k in SECRET_KEYS and str(v).strip()}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ConfigManager] Lỗi khi lưu secrets: {e}")
            return False

    def _migrate_secrets_from_config(self) -> None:
        """Move any secret keys out of config.json into the user-local secrets file."""
        dirty = False
        for k in SECRET_KEYS:
            if k not in self.config:
                continue
            val = self.config.pop(k)
            dirty = True
            if str(val).strip() and not str(self._secrets.get(k, "")).strip():
                self._secrets[k] = str(val).strip()
                self._save_secrets()
        if dirty:
            self.save_config()

    def get(self, key: str, default: Any = None) -> Any:
        if key in SECRET_KEYS:
            if key in self._secrets:
                return self._secrets.get(key)
            return default if default is not None else ""
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if key in SECRET_KEYS:
            val = str(value).strip() if value is not None else ""
            if val:
                self._secrets[key] = val
            else:
                self._secrets.pop(key, None)
            self._save_secrets()
            if key in self.config:
                self.config.pop(key, None)
                self.save_config()
            return
        if key in RETIRED_COPILOT_KEYS:
            if key in self.config:
                self.config.pop(key, None)
                self.save_config()
            return
        if key == "ai_copilot_gemini_model":
            value = canonicalize_gemini_model(value)
        elif key == "ai_copilot_provider":
            value = canonicalize_copilot_provider(value)
        self.config[key] = value
        self.save_config()

    def get_targets(self) -> Dict[str, bool]:
        """Trả về từ điển trạng thái chọn các mục tiêu dọn dẹp."""
        return self.config.get("targets", copy.deepcopy(DEFAULT_CONFIG.get("targets", {})))

    def set_targets(self, targets: Dict[str, bool]) -> None:
        """Cập nhật trạng thái các mục tiêu dọn dẹp và lưu cấu hình."""
        self.set("targets", targets)

    # ------------------------------------------------------------------
    # Quản lý Trạng Thái Giao Diện & Cửa Sổ (Window State & Tab Memory)
    # ------------------------------------------------------------------

    def get_window_state(self) -> Dict[str, Any]:
        """Lấy thông số hình học cửa sổ đã lưu."""
        geom = self.config.get("window_geometry", {})
        merged = copy.deepcopy(DEFAULT_CONFIG["window_geometry"])
        if isinstance(geom, dict):
            merged.update(geom)
        return {
            "geometry": merged,
            "last_active_tab": self.config.get("last_active_tab", 0),
            "x": merged.get("x", 100),
            "y": merged.get("y", 100),
            "width": merged.get("width", 1050),
            "height": merged.get("height", 680),
            "is_maximized": merged.get("is_maximized", False),
            "maximized": merged.get("is_maximized", False),
        }

    def save_window_state(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        is_maximized: bool = False,
        active_tab: Optional[int] = None,
        **kwargs
    ) -> None:
        """Lưu lại tọa độ, kích cỡ cửa sổ và tab người dùng đang làm việc."""
        max_flag = is_maximized or kwargs.get("maximized", False)
        self.config["window_geometry"] = {
            "x": int(x),
            "y": int(y),
            "width": int(width),
            "height": int(height),
            "is_maximized": bool(max_flag)
        }
        if active_tab is not None:
            self.config["last_active_tab"] = int(active_tab)
        self.save_config()

    # ------------------------------------------------------------------
    # Lịch Sử Dọn Dẹp & Thống Kê
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Danh Sách Tiến Trình Tin Cậy (Whitelist)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # EULA / Điều khoản sử dụng (persisted in AppData + local config)
    # ------------------------------------------------------------------

    def _read_eula_file(self) -> Dict[str, Any]:
        path = eula_file_path()
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[ConfigManager] Lỗi khi đọc EULA: {e}")
            return {}

    def _write_eula_file(self, payload: Dict[str, Any]) -> bool:
        path = eula_file_path()
        try:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[ConfigManager] Lỗi khi lưu EULA: {e}")
            return False

    def is_eula_accepted(self) -> bool:
        """True if the current EULA version was accepted and stored on disk."""
        data = self._read_eula_file()
        try:
            file_ver = int(data.get("version") or 0)
        except (TypeError, ValueError):
            file_ver = 0
        if data.get("accepted") is True and file_ver >= EULA_VERSION:
            return True
        try:
            cfg_ver = int(self.config.get("eula_accepted_version") or 0)
        except (TypeError, ValueError):
            cfg_ver = 0
        return bool(self.config.get("eula_accepted")) and cfg_ver >= EULA_VERSION

    def accept_eula(self) -> bool:
        """Persist EULA acceptance to AppData eula.json and local config.json."""
        from datetime import datetime
        accepted_at = datetime.now().isoformat(timespec="seconds")
        payload = {
            "accepted": True,
            "version": EULA_VERSION,
            "accepted_at": accepted_at,
            "copyright_holder": "mrkiss-it",
        }
        ok_file = self._write_eula_file(payload)
        self.config["eula_accepted"] = True
        self.config["eula_accepted_version"] = EULA_VERSION
        self.config["eula_accepted_at"] = accepted_at
        ok_cfg = self.save_config()
        return bool(ok_file or ok_cfg)
