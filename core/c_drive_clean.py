"""
Dọn ổ C theo quyền thật của tiến trình.

Mục user-safe xóa được khi không có quyền Administrator.
Mục needs_admin bị bỏ qua (kèm lý do tiếng Việt) nếu tiến trình chưa được nâng quyền.
Chỉ cộng byte đã xóa thật — không cộng ước lượng của mục bỏ qua hay tệp đang khóa.
"""
from __future__ import annotations

import json
import os
import re
import stat
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

ADMIN_SKIP_REASON_VI = (
    "Cần quyền Administrator — đã bỏ qua, không giải phóng và không tính dung lượng."
)
ADMIN_DEEP_DISABLED_VI = (
    "Ứng dụng chưa chạy với quyền Administrator. "
    "Dọn sâu không chạy và không tự hiện hộp thoại UAC. "
    "Hãy đóng ứng dụng và mở lại bằng Run as administrator nếu bạn muốn dọn mục hệ thống."
)
ADMIN_DEEP_ENABLED_VI = (
    "Đang có quyền Administrator. Dọn sâu xem trước rồi mới xóa: "
    "gồm rác an toàn của tài khoản này và các mục hệ thống đang bật. "
    "Không xóa WinSxS bằng tay và không dùng DISM /ResetBase."
)
PROTECTED_REASON_VI = (
    "Đường dẫn hệ thống được bảo vệ (WinSxS / System32) — không xóa."
)
TOO_BROAD_REASON_VI = (
    "Đường dẫn quá rộng (gốc ổ đĩa hoặc hồ sơ người dùng) — không xóa."
)
LOCKED_REASON_VI = "Một số tệp đang bị khóa (ứng dụng đang mở) — không tính phần chưa xóa."
DOWNLOADS_DISABLED_REASON_VI = (
    "Mục Downloads đang tắt. Không xóa tệp tải về nếu bạn chưa bật mục này."
)
SYNC_ROOT_REASON_VI = (
    "Thư mục đồng bộ OneDrive — không xóa và không tính dung lượng."
)

DEFAULT_LOW_DISK_FREE_GB = 10.0
DEFAULT_LOW_DISK_FREE_PERCENT = 10.0
DEFAULT_LOW_DISK_THRESHOLD_MODE = "gb"
DEFAULT_LOW_DISK_TOAST_COOLDOWN_SEC = 1800
DEFAULT_DOWNLOADS_MIN_AGE_DAYS = 30
DEFAULT_LARGE_FILE_MIN_BYTES = 100 * 1024 * 1024
DEFAULT_LARGE_FILE_MAX_DEPTH = 8
DEFAULT_LARGE_FILE_MAX_RESULTS = 300
DEFAULT_LARGE_FILE_MAX_VISITED = 20000
DEFAULT_LARGE_FILE_MAX_SECONDS = 12.0
CLEAN_HISTORY_KEEP = 8
CLEAN_HISTORY_ENV = "PCAUTOCLEANER_C_DRIVE_HISTORY_PATH"

# Tên thư mục không bao giờ được dọn, dù nằm sâu bên trong một mục cache.
_BLOCKED_DIR_NAMES = frozenset({
    "winsxs",
    "system32",
    "syswow64",
    "sysnative",
    "$recycle.bin",
    "system volume information",
})

_CHROMIUM_ROOTS = (
    os.path.join("Google", "Chrome", "User Data"),
    os.path.join("Google", "Chrome Beta", "User Data"),
    os.path.join("Google", "Chrome Dev", "User Data"),
    os.path.join("Google", "Chrome SxS", "User Data"),
    os.path.join("Microsoft", "Edge", "User Data"),
    os.path.join("Microsoft", "Edge Beta", "User Data"),
    os.path.join("Microsoft", "Edge Dev", "User Data"),
    os.path.join("Microsoft", "Edge SxS", "User Data"),
    os.path.join("Microsoft", "EdgeWebView", "User Data"),
    os.path.join("BraveSoftware", "Brave-Browser", "User Data"),
    os.path.join("BraveSoftware", "Brave-Browser-Beta", "User Data"),
    os.path.join("BraveSoftware", "Brave-Browser-Nightly", "User Data"),
    os.path.join("Vivaldi", "User Data"),
    os.path.join("Chromium", "User Data"),
    os.path.join("CocCoc", "Browser", "User Data"),
)
# Chỉ cache tạo lại được. Không gồm IndexedDB, cookie, Login Data, Service Worker\\Database.
_CHROMIUM_CACHE_SUBS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    os.path.join("Service Worker", "CacheStorage"),
)
_OPERA_CACHE_RELS = (
    os.path.join("Opera Software", "Opera Stable", "Cache"),
    os.path.join("Opera Software", "Opera GX Stable", "Cache"),
    os.path.join("Opera Software", "Opera Stable", "Code Cache"),
    os.path.join("Opera Software", "Opera GX Stable", "Code Cache"),
    os.path.join("Opera Software", "Opera Stable", "GPUCache"),
    os.path.join("Opera Software", "Opera GX Stable", "GPUCache"),
    os.path.join("Opera Software", "Opera Stable", "Service Worker", "CacheStorage"),
    os.path.join("Opera Software", "Opera GX Stable", "Service Worker", "CacheStorage"),
)
_SHADER_RELS = (
    "D3DSCache",
    os.path.join("NVIDIA", "DXCache"),
    os.path.join("NVIDIA", "GLCache"),
    os.path.join("NVIDIA Corporation", "NV_Cache"),
    os.path.join("AMD", "DxCache"),
    os.path.join("AMD", "GLCache"),
    os.path.join("Steam", "shadercache"),
)
# Chỉ tên thư mục cache GPU tạo lại được. Không gồm cả cây driver.
_GPU_CACHE_DIR_NAMES = frozenset({
    "dxcache",
    "glcache",
    "computecache",
    "d3dscache",
    "shadercache",
    "nv_cache",
})
_GPU_VENDOR_RELS = (
    "NVIDIA",
    "NVIDIA Corporation",
    "AMD",
    "Intel",
    "D3DSCache",
)
_GPU_VENDOR_WALK_DEPTH = 3
_DISCORD_DIR_NAMES = (
    "discord",
    "Discord",
    "discordcanary",
    "DiscordCanary",
    "discordptb",
    "DiscordPTB",
    "discorddevelopment",
    "DiscordDevelopment",
)
_DISCORD_CACHE_SUBS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "DawnGraphiteCache",
    "DawnWebGPUCache",
    os.path.join("Service Worker", "CacheStorage"),
)
_TELEGRAM_USER_CACHE_SUBS = ("cache", "media_cache", "temp")
_ZALO_ROAMING_SUBS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "logs",
    os.path.join("media", "temp"),
    os.path.join("media", "update"),
    "resp_cache",
    os.path.join("Partitions", "zalo", "Cache"),
    os.path.join("Partitions", "zalo", "Code Cache"),
    os.path.join("Partitions", "zalo", "GPUCache"),
)
_ZALO_LOCAL_ROOTS = ("Zalo", "ZaloPC", "ZaloData")
_ZALO_LOCAL_SUBS = ("Cache", "Code Cache", "GPUCache", "Temp", "tmp", "logs")
_MESSENGER_ROOTS = (
    "Messenger",
    os.path.join("Facebook", "Messenger"),
    os.path.join("Facebook", "Messenger Desktop"),
)
_MESSENGER_CACHE_SUBS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "DawnCache",
    "Temp",
    "tmp",
    os.path.join("Service Worker", "CacheStorage"),
)
_MESSENGER_PACKAGE_PREFIXES = (
    "Facebook.Messenger_",
    "Facebook.FacebookMessenger_",
)
_STEAM_CACHE_RELS = (
    "appcache",
    os.path.join("steamapps", "downloading"),
    os.path.join("steamapps", "shadercache"),
    os.path.join("steamapps", "temp"),
)
_VDF_PATH_RE = re.compile(r'"path"\s+"((?:\\.|[^"\\])*)"', re.IGNORECASE)
_VDF_LEGACY_RE = re.compile(r'^\s*"(\d+)"\s+"((?:\\.|[^"\\])*)"\s*$', re.MULTILINE)
_EMPTY_PROFILE_DIRS = ("Documents", "Downloads", "Desktop", "Pictures", "Music", "Videos")
_EMPTY_SKIP_DIR_NAMES = frozenset({
    "node_modules",
    ".git",
    ".svn",
    "pnpm",
    "pnpm-store",
    ".pnpm-store",
    "appdata",
    "application data",
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
})
DEFAULT_EMPTY_DIR_MAX_DEPTH = 6
DEFAULT_EMPTY_DIR_MAX_VISITED = 8000
DEFAULT_EMPTY_DIR_MAX_SECONDS = 4.0
_THUMB_GLOBS = ("thumbcache_*.db", "iconcache_*.db")
_ELECTRON_CACHE_SUBS = (
    "Cache",
    "Code Cache",
    "GPUCache",
    "logs",
    os.path.join("Service Worker", "CacheStorage"),
)
_CAPCUT_CACHE_RELS = (
    os.path.join("CapCut", "User Data", "Cache"),
    os.path.join("CapCut", "User Data", "Log"),
    os.path.join("CapCut", "User Data", "Logs"),
    os.path.join("CapCut", "User Data", "PerformanceLog"),
    os.path.join("CapCut", "User Data", "CEF", "Cache"),
    os.path.join("CapCut", "User Data", "CEF", "Code Cache"),
    os.path.join("CapCut", "User Data", "CEF", "GPUCache"),
    os.path.join("CapCut", "User Data", "CEF", "Service Worker", "CacheStorage"),
)
_OFFICE_SAFE_RELS = (
    os.path.join("Microsoft", "Office", "16.0", "WebServiceCache"),
    os.path.join("Microsoft", "Office", "16.0", "SmartLookupCache"),
    os.path.join("Microsoft", "Office", "16.0", "ResourceInfoCache"),
    os.path.join("Microsoft", "Office", "16.0", "MruServiceCache"),
)
_OFFICE_FILE_CACHE_REL = os.path.join("Microsoft", "Office", "16.0", "OfficeFileCache")
_ONEDRIVE_LOG_RELS = (
    os.path.join("Microsoft", "OneDrive", "logs"),
    os.path.join("Microsoft", "OneDrive", "setup", "logs"),
    os.path.join("Microsoft", "OneDrive", "StandaloneUpdater", "logs"),
)
_IDE_CACHE_SUBS = ("caches", "log", "logs", "tmp")
_SHELL_PACKAGE_PREFIXES = (
    "Microsoft.Windows.ShellExperienceHost_",
    "Microsoft.Windows.StartMenuExperienceHost_",
)
_STORE_PACKAGE_PREFIXES = (
    "Microsoft.WindowsStore_",
    "Microsoft.GamingApp_",
    "Microsoft.XboxGamingOverlay_",
    "Microsoft.XboxApp_",
    "Microsoft.XboxIdentityProvider_",
    "Microsoft.GamingServices_",
)
_STORE_CACHE_RELS = (
    "TempState",
    os.path.join("LocalCache", "Local", "Microsoft", "Windows", "INetCache"),
)
# Tên thư mục chứa dữ liệu người dùng — không bao giờ đưa vào danh sách dọn.
_SENSITIVE_DIR_NAMES = frozenset({
    "indexeddb",
    "cookies",
    "login data",
    "local storage",
    "session storage",
    "web data",
    "history",
    "database",
    "databases",
    "extensions",
    "local extension settings",
    "unsavedfiles",
    "leveldb",
    "key_datas",
    "key_data",
    "map0",
    "map1",
    "accounts",
})
_VS_TEMP_DIR_NAMES = frozenset({
    "componentmodelcache",
    "cache",
    "temporary",
    "temp",
})
_LARGE_SKIP_DIR_NAMES = frozenset({
    "node_modules",
    ".git",
    ".svn",
    "pnpm",
    "pnpm-store",
    ".pnpm-store",
    "appdata",
    "application data",
})
_BROWSER_DB_FILENAMES = frozenset({
    "cookies",
    "cookies-journal",
    "login data",
    "login data-journal",
    "login data for account",
    "login data for account-journal",
    "web data",
    "web data-journal",
    "history",
    "history-journal",
    "history provider cache",
    "favicons",
    "favicons-journal",
    "top sites",
    "top sites-journal",
    "shortcuts",
    "shortcuts-journal",
    "network action predictor",
    "places.sqlite",
    "places.sqlite-wal",
    "places.sqlite-shm",
    "cookies.sqlite",
    "cookies.sqlite-wal",
    "cookies.sqlite-shm",
    "formhistory.sqlite",
    "formhistory.sqlite-wal",
    "webappsstore.sqlite",
    "webappsstore.sqlite-wal",
    "permissions.sqlite",
    "cert9.db",
    "key4.db",
    "logins.json",
    "logins-backup.json",
    "signons.sqlite",
    "sessionstore.jsonlz4",
})
_EBWEBVIEW_SKIP = frozenset({
    "temp",
    "tmp",
    "node_modules",
    ".git",
    "steamapps",
    "packages",
    "user data",
    "cache",
    "code cache",
    "gpucache",
    "crashdumps",
    "pip",
    "npm-cache",
    "android",
    "sdk",
    "google",
    "programs",
})


def _meta(
    *,
    label_vi: str,
    description_vi: str,
    needs_admin: bool,
    scope: str,
    risk: str,
    default_enabled: bool,
    clean_mode: str,
) -> Dict[str, Any]:
    return {
        "label_vi": label_vi,
        "description_vi": description_vi,
        "needs_admin": needs_admin,
        "scope": scope,
        "risk": risk,
        "default_enabled": default_enabled,
        "clean_mode": clean_mode,
    }


# Thứ tự ổn định cho UI, quét và báo cáo.
TARGET_ORDER: Sequence[str] = (
    "user_temp",
    "thumbnail_cache",
    "shell_font_cache",
    "browser_cache",
    "inet_cache",
    "shader_cache",
    "gpu_shader_caches",
    "crash_dumps",
    "app_caches",
    "discord_cache",
    "telegram_cache",
    "zalo_cache",
    "messenger_cache",
    "steam_caches",
    "epic_caches",
    "empty_user_folders",
    "toolchain_caches",
    "nuget_packages",
    "gradle_caches",
    "cargo_cache",
    "office_cache",
    "office_file_cache",
    "store_cache",
    "delivery_cache",
    "recycle_bin",
    "downloads_old",
    "system_temp",
    "windows_update",
    "system_delivery_opt",
    "windows_setup_temp",
    "windows_logs",
    "system_wer",
    "system_dumps",
    "prefetch",
    "windows_old",
    "component_cleanup",
    "hibernate_file",
)

TARGET_CATALOG: Dict[str, Dict[str, Any]] = {
    "user_temp": _meta(
        label_vi="File tạm người dùng (%TEMP%)",
        description_vi="Temp của tài khoản này và LocalAppData\\Temp. Không cần Admin.",
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "thumbnail_cache": _meta(
        label_vi="Bộ nhớ đệm hình thu nhỏ và icon",
        description_vi=(
            "Chỉ xóa thumbcache_*.db và iconcache_*.db. Windows tạo lại sau. "
            "Tệp đang khóa sẽ được bỏ qua, không tính dung lượng."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "browser_cache": _meta(
        label_vi="Bộ nhớ đệm trình duyệt",
        description_vi=(
            "Cache, Code Cache, GPUCache và Service Worker\\CacheStorage của Chrome, Edge, "
            "Cốc Cốc, Firefox, Brave, Opera, Vivaldi và WebView2 trong hồ sơ của bạn. "
            "Không xóa mật khẩu, cookie, IndexedDB hay đăng nhập."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "inet_cache": _meta(
        label_vi="Tệp internet tạm (INetCache)",
        description_vi="Bộ nhớ đệm tạm trong hồ sơ người dùng. Không đụng cookie.",
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "shader_cache": _meta(
        label_vi="Bộ nhớ đệm shader (DirectX / NVIDIA / AMD)",
        description_vi=(
            "Cache đồ họa DirectX, NVIDIA, AMD và shadercache của Steam trong LocalAppData. "
            "Có thể tạo lại. Mục GPU riêng bổ sung Intel, ComputeCache và LocalLow. "
            "Không xóa driver hay thư mục hệ thống."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "gpu_shader_caches": _meta(
        label_vi="Cache shader GPU (NVIDIA / AMD / Intel)",
        description_vi=(
            "DXCache, GLCache, ComputeCache, ShaderCache và D3DSCache trong LocalAppData "
            "và LocalLow của tài khoản này. GPU tạo lại được. Không đụng Program Files, "
            "ProgramData hay thư mục cài driver."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "crash_dumps": _meta(
        label_vi="Báo cáo lỗi và crash dump của bạn",
        description_vi="CrashDumps và Windows Error Reporting trong LocalAppData của tài khoản này.",
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "app_caches": _meta(
        label_vi=(
            "Bộ nhớ đệm ứng dụng (VS Code, Teams, Spotify, Slack, "
            "Zoom, Notion, CapCut, JetBrains)"
        ),
        description_vi=(
            "Chỉ cache hoặc log đã biết, kể cả htmlcache của Steam. "
            "Cache Discord, Telegram, Zalo và Messenger nằm ở mục riêng. "
            "Không xóa tin nhắn, dự án CapCut, nhạc Spotify đã tải, "
            "cấu hình IDE hay thư mục AppData lạ."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "discord_cache": _meta(
        label_vi="Cache Discord (Cache / GPUCache)",
        description_vi=(
            "Chỉ Cache, Code Cache và GPUCache của Discord (kể cả Canary/PTB) "
            "trong hồ sơ của bạn. Không xóa Local Storage, IndexedDB, leveldb "
            "hay phiên đăng nhập. Không cài thì 0 B."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "telegram_cache": _meta(
        label_vi="Cache Telegram (tdata tạm)",
        description_vi=(
            "Chỉ cache, media_cache, temp và emoji trong tdata. "
            "Không xóa key_datas, map0 hay cả thư mục tdata. Không cài thì 0 B."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "zalo_cache": _meta(
        label_vi="Cache Zalo PC",
        description_vi=(
            "Chỉ Cache, Code Cache, GPUCache và Temp của Zalo trong LocalAppData hoặc Roaming. "
            "Không xóa cơ sở dữ liệu tài khoản. Không cài thì 0 B."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "messenger_cache": _meta(
        label_vi="Cache Facebook Messenger",
        description_vi=(
            "Chỉ thư mục cache của Messenger Desktop. Không xóa tin nhắn hay đăng nhập. "
            "Không cài thì 0 B."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "steam_caches": _meta(
        label_vi="Cache Steam (tắt mặc định)",
        description_vi=(
            "Chỉ appcache, shadercache, downloading và temp của Steam nếu tìm thấy thư viện. "
            "Không xóa game trong steamapps\\common. Tắt mặc định."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "epic_caches": _meta(
        label_vi="Cache Epic Games Launcher (tắt mặc định)",
        description_vi=(
            "Chỉ webcache của Epic Games Launcher trong LocalAppData. "
            "Không xóa game hay thư mục .egstore. Tắt mặc định."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "empty_user_folders": _meta(
        label_vi="Thư mục trống trong hồ sơ (tắt mặc định)",
        description_vi=(
            "Chỉ thư mục đang trống dưới Documents, Downloads, Desktop, Pictures, Music, "
            "Videos và Temp. Bỏ qua OneDrive, thư mục gốc quan trọng và cây còn tệp. "
            "Tắt mặc định — chỉ xóa sau khi xem trước và bấm «Dọn ngay»."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="empty_dirs",
    ),
    "toolchain_caches": _meta(
        label_vi="Cache công cụ build (Yarn, NuGet HTTP, Gradle tạm, Scoop, VS)",
        description_vi=(
            "Chỉ cache tạo lại được: Yarn Cache, cache HTTP của NuGet (v3-cache), "
            "pip trong .cache\\pip, npm _cacache, thư mục caches\\tmp của Gradle, "
            "cache tải về của Scoop và Chocolatey trong hồ sơ của bạn, cùng "
            "ComponentModelCache / Cache / Temporary / Temp ngay trong thư mục phiên bản "
            "Visual Studio. Không xóa kho pnpm, không xóa .nuget\\packages, không xóa cả "
            ".gradle\\caches và không xóa registry index của Cargo."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "nuget_packages": _meta(
        label_vi="Gói NuGet đã tải (tắt mặc định)",
        description_vi=(
            "Chỉ %USERPROFILE%\\.nuget\\packages. Restore có thể tải lại, nhưng sẽ chậm "
            "hoặc thất bại khi không có mạng. Tắt mặc định. Cache HTTP của NuGet nằm ở mục "
            "cache công cụ, không phải mục này."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "gradle_caches": _meta(
        label_vi="Cache Gradle đầy đủ (tắt mặc định)",
        description_vi=(
            "Cả %USERPROFILE%\\.gradle\\caches. Lần build sau sẽ tải lại phần đã xóa. "
            "Tắt mặc định vì thư mục thường rất lớn. Riêng caches\\tmp đã được dọn ở mục "
            "cache công cụ khi mục này đang tắt."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "cargo_cache": _meta(
        label_vi="Cache crate Cargo (tắt mặc định)",
        description_vi=(
            "Chỉ %USERPROFILE%\\.cargo\\registry\\cache. Không xóa registry\\index, "
            "thư mục git hay bin. Tắt mặc định vì bản đã tải giúp build khi không có mạng."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "shell_font_cache": _meta(
        label_vi="Font cache và bộ nhớ đệm Explorer",
        description_vi=(
            "FontCache của tài khoản này, cache Explorer (Windows\\Caches) và TempState "
            "của Shell Experience Host. Windows tạo lại. Không xóa font đã cài và không đụng System32."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "office_cache": _meta(
        label_vi="Cache Office và nhật ký OneDrive",
        description_vi=(
            "WebServiceCache và cache tra cứu của Office, cùng thư mục logs của OneDrive. "
            "Không xóa thư mục đồng bộ OneDrive hay tài liệu."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "office_file_cache": _meta(
        label_vi="Bản sao tạm Office (tắt mặc định)",
        description_vi=(
            "Chỉ OfficeFileCache. Có thể còn tệp chưa đồng bộ lên OneDrive hoặc SharePoint. "
            "Tắt mặc định — không chạy nếu bạn không bật. Không đụng thư mục đồng bộ."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "store_cache": _meta(
        label_vi="Cache tạm Microsoft Store và Xbox",
        description_vi=(
            "Chỉ TempState và INetCache của Store, Xbox và Gaming App. "
            "Không xóa dữ liệu game, bản cài hay LocalState."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "delivery_cache": _meta(
        label_vi="Cache phân phối của người dùng",
        description_vi=(
            "Delivery Optimization trong LocalAppData. Bản nằm trong Windows cần Admin "
            "và không thuộc mục này."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "recycle_bin": _meta(
        label_vi="Thùng rác của tài khoản này",
        description_vi=(
            "Làm trống thùng rác người dùng hiện tại qua Windows. Không cần Admin. "
            "Không đụng thùng rác tài khoản khác."
        ),
        needs_admin=False,
        scope="user",
        risk="safe",
        default_enabled=True,
        clean_mode="recycle",
    ),
    "downloads_old": _meta(
        label_vi="Tệp cũ trong Downloads (tắt mặc định)",
        description_vi=(
            "Chỉ xóa tệp (không xóa thư mục) cũ hơn số ngày bạn chọn. "
            "Mặc định tắt — không chạy nếu bạn không bật."
        ),
        needs_admin=False,
        scope="user",
        risk="caution",
        default_enabled=False,
        clean_mode="old_files",
    ),
    "system_temp": _meta(
        label_vi="File tạm hệ thống (C:\\Windows\\Temp)",
        description_vi="Cần Admin. Khi chưa nâng quyền, mục này bị bỏ qua và không tính dung lượng.",
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=True,
        clean_mode="contents",
    ),
    "windows_update": _meta(
        label_vi="Bộ nhớ đệm Windows Update",
        description_vi=(
            "Chỉ C:\\Windows\\SoftwareDistribution\\Download. Cần Admin. "
            "Không đụng WinSxS hay System32."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=True,
        clean_mode="contents",
    ),
    "system_dumps": _meta(
        label_vi="Dump lỗi hệ thống (tắt mặc định)",
        description_vi=(
            "C:\\Windows\\Minidump và MEMORY.DMP. Cần Admin. "
            "Tắt mặc định vì file này có thể cần khi sửa lỗi."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "system_delivery_opt": _meta(
        label_vi="Cache Delivery Optimization của Windows",
        description_vi=(
            "Chỉ cache hệ thống: SoftwareDistribution\\DeliveryOptimization và "
            "Cache của NetworkService. Cần Admin. Không đụng bản trong LocalAppData "
            "và không xóa WinSxS hay System32."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=True,
        clean_mode="contents",
    ),
    "windows_setup_temp": _meta(
        label_vi="File tạm bộ cài Windows",
        description_vi=(
            "Chỉ $WINDOWS.~BT và $WINDOWS.~WS nếu còn sau khi nâng cấp. Cần Admin. "
            "Không xóa thư mục Windows đang chạy."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=True,
        clean_mode="contents",
    ),
    "windows_logs": _meta(
        label_vi="Nhật ký CBS và DISM",
        description_vi=(
            "Nội dung Windows\\Logs\\CBS và Windows\\Logs\\DISM. Cần Admin. "
            "Tệp đang khóa được bỏ qua, không tính. Không đụng WinSxS."
        ),
        needs_admin=True,
        scope="system",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "system_wer": _meta(
        label_vi="Báo cáo lỗi Windows (ProgramData)",
        description_vi=(
            "ProgramData\\Microsoft\\Windows\\WER. Cần Admin. "
            "Không xóa báo cáo trong hồ sơ người dùng (mục đó đã có riêng) và không đụng WinSxS."
        ),
        needs_admin=True,
        scope="system",
        risk="safe",
        default_enabled=True,
        clean_mode="contents",
    ),
    "prefetch": _meta(
        label_vi="Prefetch (tắt mặc định)",
        description_vi=(
            "Chỉ C:\\Windows\\Prefetch. Cần Admin. Lợi ích thường thấp. "
            "Tắt mặc định — không chạy nếu bạn không bật."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "windows_old": _meta(
        label_vi="Windows.old (tắt mặc định)",
        description_vi=(
            "Chỉ thư mục Windows.old trên ổ hệ thống, nếu còn sau nâng cấp. Cần Admin. "
            "Xóa là mất bản Windows cũ, không hoàn tác được. Tắt mặc định và cần xác nhận thêm."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=False,
        clean_mode="contents",
    ),
    "component_cleanup": _meta(
        label_vi="Dọn kho thành phần (DISM, tắt mặc định)",
        description_vi=(
            "Chỉ DISM /Online /Cleanup-Image /StartComponentCleanup khi đã elevated. "
            "Không dùng /ResetBase và không xóa cây WinSxS bằng tay. "
            "Tắt mặc định. Kho thành phần không đếm từng tệp nên mục này tính 0 B."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=False,
        clean_mode="component_cleanup",
    ),
    "hibernate_file": _meta(
        label_vi="Tắt ngủ đông (hiberfil.sys, tắt mặc định)",
        description_vi=(
            "Chạy powercfg /h off để giải phóng hiberfil.sys. Cần Admin. "
            "Máy sẽ không còn Hibernate. Tắt mặc định. Không xóa file này trực tiếp."
        ),
        needs_admin=True,
        scope="system",
        risk="caution",
        default_enabled=False,
        clean_mode="hibernate",
    ),
}


def is_process_elevated() -> bool:
    """True khi tiến trình đang chạy elevated. Ngoài Windows luôn False."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


# cleanmgr / Storage Sense không được gọi: hộp thoại Windows có thể treo UI.
# DISM chỉ StartComponentCleanup. Không có /ResetBase.
COMPONENT_CLEANUP_TIMEOUT_SEC = 600
_ALWAYS_PREVIEW_KEYS = frozenset({"component_cleanup", "hibernate_file", "windows_old"})


def _under_drive(drive: str, *parts: str) -> str:
    """Ghép tên dưới ổ đĩa. 'C:' + 'Windows.old' phải ra 'C:\\Windows.old'."""
    text = str(drive or "").strip().rstrip("\\/")
    if not text:
        return ""
    tail = "\\".join(part.strip("\\/") for part in parts if part)
    if len(text) == 2 and text[1] == ":":
        return text + "\\" + tail if tail else text + "\\"
    if not tail:
        return text
    return os.path.join(text, *tuple(part.strip("\\/") for part in parts if part))


def _system_drive(environ: Optional[Dict[str, str]]) -> str:
    """Khi truyền dict, thiếu SystemDrive nghĩa là không có Windows.old / $WINDOWS.~BT."""
    if environ is None:
        drive = _env(None, "SystemDrive") or _env(None, "SYSTEMDRIVE")
        if not drive and os.name == "nt":
            drive = "C:"
        return drive
    return _env(environ, "SystemDrive") or _env(environ, "SYSTEMDRIVE")


def _program_data(environ: Optional[Dict[str, str]]) -> str:
    """Khi truyền dict, thiếu ProgramData nghĩa là không có WER hệ thống."""
    if environ is None:
        folder = _env(None, "ProgramData") or _env(None, "PROGRAMDATA")
        if not folder and os.name == "nt":
            folder = r"C:\ProgramData"
        return folder
    return _env(environ, "ProgramData") or _env(environ, "PROGRAMDATA")


def _hibernate_file_path(environ: Optional[Dict[str, str]] = None) -> str:
    drive = _system_drive(environ)
    if not drive:
        return ""
    return _under_drive(drive, "hiberfil.sys")


def default_component_cleanup() -> Dict[str, Any]:
    """
    DISM /Online /Cleanup-Image /StartComponentCleanup.
    Ngoài Windows hoặc chưa elevated: bỏ qua, 0 B, không gọi tiến trình.
    Thành công vẫn tính 0 B vì kho thành phần không đếm từng tệp.
    """
    if os.name != "nt" or not is_process_elevated():
        return {
            "success": False,
            "freed_bytes": 0,
            "skipped": True,
            "reason": (
                "Dọn kho thành phần chỉ chạy trên Windows khi tiến trình đã có quyền Administrator. "
                "Không tính dung lượng."
            ),
        }
    try:
        import subprocess
        completed = subprocess.run(
            ["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
            timeout=COMPONENT_CLEANUP_TIMEOUT_SEC,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return {
            "success": False,
            "freed_bytes": 0,
            "reason": f"Không chạy được DISM StartComponentCleanup. Không tính dung lượng. ({exc})",
        }
    if int(getattr(completed, "returncode", 1) or 0) != 0:
        return {
            "success": False,
            "freed_bytes": 0,
            "reason": "DISM StartComponentCleanup không thành công. Không tính dung lượng.",
        }
    return {
        "success": True,
        "freed_bytes": 0,
        "reason": (
            "Đã chạy DISM /StartComponentCleanup. "
            "Kho thành phần không đếm từng tệp (0 B)."
        ),
    }


def default_hibernate_off(environ: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """powercfg /h off. Không xóa hiberfil.sys bằng tay. Ngoài Windows: không làm gì."""
    if os.name != "nt" or not is_process_elevated():
        return {
            "success": False,
            "freed_bytes": 0,
            "skipped": True,
            "reason": (
                "Tắt ngủ đông chỉ chạy trên Windows khi tiến trình đã có quyền Administrator. "
                "Không xóa hiberfil.sys trực tiếp."
            ),
        }
    hiber = _hibernate_file_path(environ)
    existed = bool(hiber) and _exists(hiber) and os.path.isfile(hiber) and not path_is_forbidden(hiber)
    before = _file_size(hiber) if existed else 0
    try:
        import subprocess
        completed = subprocess.run(
            ["powercfg", "/h", "off"],
            timeout=60,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return {
            "success": False,
            "freed_bytes": 0,
            "reason": f"Không chạy được powercfg /h off. Không xóa hiberfil.sys trực tiếp. ({exc})",
        }
    if int(getattr(completed, "returncode", 1) or 0) != 0:
        return {
            "success": False,
            "freed_bytes": 0,
            "reason": "powercfg /h off không thành công. Không xóa hiberfil.sys trực tiếp.",
        }
    gone = not (hiber and _exists(hiber) and os.path.isfile(hiber))
    freed = before if existed and gone else 0
    return {
        "success": True,
        "freed_bytes": freed,
        "reason": "Đã tắt ngủ đông bằng powercfg /h off. Không xóa hiberfil.sys trực tiếp.",
    }


def default_target_flags() -> Dict[str, bool]:
    flags = {key: bool(TARGET_CATALOG[key]["default_enabled"]) for key in TARGET_ORDER}
    flags["ram_optimize"] = True
    return flags


def admin_target_keys() -> List[str]:
    return [key for key in TARGET_ORDER if TARGET_CATALOG[key]["needs_admin"]]


def user_safe_target_keys() -> List[str]:
    return [key for key in TARGET_ORDER if not TARGET_CATALOG[key]["needs_admin"]]


def path_is_forbidden(path: str) -> bool:
    """True nếu path đụng WinSxS, System32, SysWOW64 hoặc thùng rác trên đĩa."""
    if not path:
        return False
    parts = [part.lower() for part in os.path.normpath(path).split(os.sep) if part]
    return any(part in _BLOCKED_DIR_NAMES for part in parts)


def path_is_too_broad(path: str, *, user_profile: str = "", system_root: str = "") -> bool:
    """Từ chối gốc ổ đĩa, thư mục Windows và gốc hồ sơ người dùng."""
    if not path:
        return True
    try:
        abs_path = os.path.normcase(os.path.abspath(path))
    except (OSError, ValueError):
        return True
    parent = os.path.dirname(abs_path)
    if parent == abs_path:
        return True
    broad = []
    for root in (user_profile, system_root):
        if not root:
            continue
        try:
            broad.append(os.path.normcase(os.path.abspath(root)))
        except (OSError, ValueError):
            continue
    return abs_path in broad


def _within_root(path: str, root: str) -> bool:
    if not path or not root:
        return False
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(root)
        return os.path.commonpath([abs_path, abs_root]) == abs_root
    except (OSError, ValueError):
        return False


def _dedupe(paths: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for path in paths:
        if not path:
            continue
        try:
            key = os.path.normcase(os.path.abspath(path))
        except (OSError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _exists(path: str) -> bool:
    try:
        return bool(path) and os.path.exists(path)
    except OSError:
        return False


def _env(environ: Optional[Dict[str, str]], key: str) -> str:
    source = os.environ if environ is None else environ
    return str(source.get(key, "") or "")


def _chromium_caches(user_data_root: str) -> List[str]:
    if not _exists(user_data_root):
        return []
    profiles: List[str] = []
    default_profile = os.path.join(user_data_root, "Default")
    if _exists(default_profile):
        profiles.append(default_profile)
    try:
        for name in os.listdir(user_data_root):
            if name.startswith("Profile "):
                candidate = os.path.join(user_data_root, name)
                if os.path.isdir(candidate):
                    profiles.append(candidate)
    except OSError:
        pass
    found: List[str] = []
    for profile in profiles:
        for sub in _CHROMIUM_CACHE_SUBS:
            cache_dir = os.path.join(profile, sub)
            if (
                _exists(cache_dir)
                and os.path.isdir(cache_dir)
                and not os.path.islink(cache_dir)
                and not path_is_forbidden(cache_dir)
                and not path_has_sensitive_data(cache_dir)
            ):
                found.append(cache_dir)
    return found


def _path_parts(path: str) -> List[str]:
    return [part.lower() for part in os.path.normpath(path).split(os.sep) if part]


def path_has_sensitive_data(path: str) -> bool:
    """True nếu path đi qua IndexedDB, cookie, Login Data hoặc dữ liệu hồ sơ tương tự."""
    if not path:
        return False
    return any(part in _SENSITIVE_DIR_NAMES for part in _path_parts(path))


def _is_onedrive_sync_path(path: str, user_profile: str = "") -> bool:
    """True nếu path là thư mục đồng bộ OneDrive hoặc nằm bên trong nó."""
    if not path or not user_profile:
        return False
    try:
        profile = os.path.normcase(os.path.abspath(user_profile))
        target = os.path.normcase(os.path.abspath(path))
    except (OSError, ValueError):
        return False
    if target == profile:
        return False
    prefix = profile if profile.endswith(os.sep) else profile + os.sep
    if not target.startswith(prefix):
        return False
    rel = target[len(prefix):]
    first = rel.split(os.sep)[0].lower() if rel else ""
    return first == "onedrive" or first.startswith("onedrive ")


def _append_if_dir(bucket: List[str], path: str) -> None:
    if (
        _exists(path)
        and os.path.isdir(path)
        and not os.path.islink(path)
        and not path_is_forbidden(path)
        and not path_has_sensitive_data(path)
    ):
        bucket.append(path)


def _thumbnail_files(local_app_data: str) -> List[str]:
    import glob

    explorer = os.path.join(local_app_data, "Microsoft", "Windows", "Explorer")
    if not _exists(explorer):
        return []
    found: List[str] = []
    for pattern in _THUMB_GLOBS:
        for path in glob.glob(os.path.join(explorer, pattern)):
            if os.path.isfile(path) and not os.path.islink(path) and not path_is_forbidden(path):
                found.append(path)
    thumb_delete = os.path.join(explorer, "ThumbCacheToDelete")
    _append_if_dir(found, thumb_delete)
    return found


def _append_electron_caches(bucket: List[str], root: str, subs: Sequence[str] = _ELECTRON_CACHE_SUBS) -> None:
    if not root or not _exists(root) or os.path.islink(root):
        return
    for sub in subs:
        _append_if_dir(bucket, os.path.join(root, sub))


def _find_ebwebview_roots(base: str, max_listdir_depth: int = 3) -> List[str]:
    """Tìm thư mục EBWebView ở độ sâu giới hạn. Không đi theo symlink."""
    found: List[str] = []
    if not base or not _exists(base) or not os.path.isdir(base) or os.path.islink(base):
        return found
    if path_is_forbidden(base):
        return found
    stack = [(os.path.abspath(base), 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_listdir_depth:
            continue
        try:
            names = list(os.listdir(current))
        except OSError:
            continue
        for name in names:
            child = os.path.join(current, name)
            if os.path.islink(child) or not os.path.isdir(child):
                continue
            lowered = name.lower()
            if lowered in _BLOCKED_DIR_NAMES or path_is_forbidden(child):
                continue
            if lowered == "ebwebview":
                found.append(child)
                continue
            if lowered in _EBWEBVIEW_SKIP or path_has_sensitive_data(child):
                continue
            if depth < max_listdir_depth:
                stack.append((child, depth + 1))
    return found


def _append_versioned_ide_caches(
    bucket: List[str],
    parent: str,
    prefixes: Optional[Sequence[str]] = None,
) -> None:
    if not parent or not _exists(parent) or os.path.islink(parent):
        return
    try:
        names = list(os.listdir(parent))
    except OSError:
        return
    allowed = tuple(prefix.lower() for prefix in prefixes) if prefixes else None
    for name in names:
        if allowed and not name.lower().startswith(allowed):
            continue
        version_dir = os.path.join(parent, name)
        if os.path.islink(version_dir) or not os.path.isdir(version_dir) or path_is_forbidden(version_dir):
            continue
        for sub in _IDE_CACHE_SUBS:
            _append_if_dir(bucket, os.path.join(version_dir, sub))


def _package_scoped_dirs(
    local_app_data: str,
    prefixes: Sequence[str],
    rels: Sequence[str],
) -> List[str]:
    packages = os.path.join(local_app_data, "Packages")
    found: List[str] = []
    if not _exists(packages) or os.path.islink(packages):
        return found
    try:
        names = list(os.listdir(packages))
    except OSError:
        return found
    for name in names:
        if not any(name.startswith(prefix) for prefix in prefixes):
            continue
        base = os.path.join(packages, name)
        if os.path.islink(base) or not os.path.isdir(base) or path_is_forbidden(base):
            continue
        for rel in rels:
            _append_if_dir(found, os.path.join(base, rel))
    return found


def _app_cache_paths(local_app_data: str, app_data: str) -> List[str]:
    found: List[str] = []
    if app_data:
        code_base = os.path.join(app_data, "Code")
        if _exists(code_base):
            for sub in ("Cache", "CachedData", "CachedExtensionVSIXs", "GPUCache", "logs"):
                _append_if_dir(found, os.path.join(code_base, sub))
        _append_if_dir(found, os.path.join(app_data, "npm-cache"))
        teams_base = os.path.join(app_data, "Microsoft", "Teams")
        if _exists(teams_base):
            for sub in ("Cache", "Code Cache", "GPUCache", "tmp"):
                _append_if_dir(found, os.path.join(teams_base, sub))
    if local_app_data:
        _append_if_dir(found, os.path.join(local_app_data, "pip", "cache"))
        _append_if_dir(found, os.path.join(local_app_data, "npm-cache"))
        _append_if_dir(found, os.path.join(local_app_data, "Steam", "htmlcache"))
        _append_electron_caches(
            found,
            os.path.join(local_app_data, "Spotify", "Browser"),
            subs=("Cache", "Code Cache", "GPUCache", os.path.join("Service Worker", "CacheStorage")),
        )
        _append_if_dir(found, os.path.join(local_app_data, "Spotify", "logs"))
        for name in ("slack", "Slack", "Notion"):
            _append_electron_caches(found, os.path.join(local_app_data, name))
        _append_if_dir(found, os.path.join(local_app_data, "Zoom", "logs"))
        for rel in _CAPCUT_CACHE_RELS:
            _append_if_dir(found, os.path.join(local_app_data, rel))
        capcut_cef = os.path.join(local_app_data, "CapCut", "User Data", "CEF")
        found.extend(_chromium_caches(capcut_cef))
        jetbrains = os.path.join(local_app_data, "JetBrains")
        _append_versioned_ide_caches(found, jetbrains)
        _append_if_dir(found, os.path.join(jetbrains, "Toolbox", "cache"))
        _append_if_dir(found, os.path.join(jetbrains, "Toolbox", "logs"))
        _append_versioned_ide_caches(
            found,
            os.path.join(local_app_data, "Google"),
            prefixes=("AndroidStudio",),
        )
        teams_local = os.path.join(local_app_data, "Microsoft", "Teams")
        if _exists(teams_local):
            for sub in ("Cache", "Code Cache", "GPUCache", "tmp", "logs"):
                _append_if_dir(found, os.path.join(teams_local, sub))
    if app_data:
        for name in ("Slack", "slack", "Notion"):
            _append_electron_caches(found, os.path.join(app_data, name))
        _append_if_dir(found, os.path.join(app_data, "Zoom", "logs"))
    return found


def _list_child_dirs(parent: str) -> List[str]:
    if not parent or not _exists(parent) or os.path.islink(parent) or not os.path.isdir(parent):
        return []
    if path_is_forbidden(parent):
        return []
    try:
        names = list(os.listdir(parent))
    except OSError:
        return []
    found: List[str] = []
    for name in names:
        child = os.path.join(parent, name)
        if os.path.isdir(child) and not os.path.islink(child) and not path_is_forbidden(child):
            found.append(child)
    return found


def _visual_studio_temp_dirs(local_app_data: str) -> List[str]:
    """Chỉ thư mục tạm/cache ngay dưới từng phiên bản Visual Studio. Không đụng Extensions."""
    root = os.path.join(local_app_data, "Microsoft", "VisualStudio")
    found: List[str] = []
    for version_dir in _list_child_dirs(root):
        if path_has_sensitive_data(version_dir):
            continue
        try:
            names = list(os.listdir(version_dir))
        except OSError:
            continue
        for name in names:
            if name.lower() not in _VS_TEMP_DIR_NAMES:
                continue
            _append_if_dir(found, os.path.join(version_dir, name))
    return found


def _gradle_tmp_dirs(user_profile: str) -> List[str]:
    caches = os.path.join(user_profile, ".gradle", "caches")
    found: List[str] = []
    _append_if_dir(found, os.path.join(caches, "tmp"))
    for child in _list_child_dirs(caches):
        _append_if_dir(found, os.path.join(child, "tmp"))
    return found


def _toolchain_cache_paths(local_app_data: str, app_data: str, user_profile: str) -> List[str]:
    """
    Cache tạo lại được. Không gồm kho pnpm, .nuget\\packages, cả .gradle\\caches
    hay registry index của Cargo — các mục đó có khóa riêng (mặc định tắt) hoặc bị bỏ.
    """
    found: List[str] = []
    if local_app_data and not path_is_forbidden(local_app_data):
        _append_if_dir(found, os.path.join(local_app_data, "Yarn", "Cache"))
        _append_if_dir(found, os.path.join(local_app_data, "NuGet", "v3-cache"))
        _append_if_dir(found, os.path.join(local_app_data, "NuGet", "Cache"))
        _append_if_dir(found, os.path.join(local_app_data, "Chocolatey", "cache"))
        _append_if_dir(found, os.path.join(local_app_data, "scoop", "cache"))
        found.extend(_visual_studio_temp_dirs(local_app_data))
    if app_data and not path_is_forbidden(app_data):
        _append_if_dir(found, os.path.join(app_data, "Yarn", "Cache"))
    if user_profile and not path_is_forbidden(user_profile):
        _append_if_dir(found, os.path.join(user_profile, ".cache", "pip"))
        _append_if_dir(found, os.path.join(user_profile, ".npm", "_cacache"))
        _append_if_dir(found, os.path.join(user_profile, "scoop", "cache"))
        found.extend(_gradle_tmp_dirs(user_profile))
    return found


def _is_machine_vendor_tree(path: str) -> bool:
    """Program Files / ProgramData — cache GPU ở đó cần Admin, không đụng."""
    for part in _path_parts(path):
        if part in {"program files", "program files (x86)", "programdata"}:
            return True
    return False


def path_is_game_install(path: str) -> bool:
    """True nếu path là game đã cài (steamapps\\common hoặc .egstore)."""
    if not path:
        return False
    parts = _path_parts(path)
    for index, part in enumerate(parts):
        if part == ".egstore":
            return True
        if part == "steamapps" and index + 1 < len(parts) and parts[index + 1] == "common":
            return True
    return False


def _named_cache_paths(bases: Iterable[str], dir_names: Sequence[str], subs: Sequence[str]) -> List[str]:
    found: List[str] = []
    for base in bases:
        if not base or path_is_forbidden(base):
            continue
        for name in dir_names:
            root = os.path.join(base, name)
            for sub in subs:
                _append_if_dir(found, os.path.join(root, sub))
    return found


def _discord_cache_paths(local_app_data: str, app_data: str) -> List[str]:
    return _named_cache_paths(
        (app_data, local_app_data),
        _DISCORD_DIR_NAMES,
        _DISCORD_CACHE_SUBS,
    )


def _telegram_cache_paths(local_app_data: str, app_data: str) -> List[str]:
    """Chỉ cache/temp tạo lại được trong tdata. Không bao giờ cả tdata hay key_datas."""
    found: List[str] = []
    roots: List[str] = []
    if app_data:
        roots.append(os.path.join(app_data, "Telegram Desktop", "tdata"))
    if local_app_data:
        roots.append(os.path.join(local_app_data, "Telegram Desktop", "tdata"))
    for tdata in roots:
        if not _exists(tdata) or os.path.islink(tdata) or not os.path.isdir(tdata):
            continue
        if path_is_forbidden(tdata) or path_has_sensitive_data(tdata):
            continue
        _append_if_dir(found, os.path.join(tdata, "temp"))
        _append_if_dir(found, os.path.join(tdata, "emoji"))
        try:
            names = list(os.listdir(tdata))
        except OSError:
            continue
        for name in names:
            if not name.lower().startswith("user_data"):
                continue
            user_dir = os.path.join(tdata, name)
            if os.path.islink(user_dir) or not os.path.isdir(user_dir):
                continue
            if path_has_sensitive_data(user_dir) or path_is_forbidden(user_dir):
                continue
            for sub in _TELEGRAM_USER_CACHE_SUBS:
                _append_if_dir(found, os.path.join(user_dir, sub))
    return found


def _zalo_cache_paths(local_app_data: str, app_data: str) -> List[str]:
    found: List[str] = []
    if app_data:
        zalo_base = os.path.join(app_data, "ZaloData")
        for sub in _ZALO_ROAMING_SUBS:
            _append_if_dir(found, os.path.join(zalo_base, sub))
    if local_app_data:
        for root_name in _ZALO_LOCAL_ROOTS:
            base = os.path.join(local_app_data, root_name)
            for sub in _ZALO_LOCAL_SUBS:
                _append_if_dir(found, os.path.join(base, sub))
        _append_if_dir(found, os.path.join(local_app_data, "Programs", "Zalo", "logs"))
    return found


def _messenger_cache_paths(local_app_data: str, app_data: str) -> List[str]:
    found = _named_cache_paths(
        (app_data, local_app_data),
        _MESSENGER_ROOTS,
        _MESSENGER_CACHE_SUBS,
    )
    if local_app_data:
        found.extend(
            _package_scoped_dirs(local_app_data, _MESSENGER_PACKAGE_PREFIXES, ("TempState",))
        )
    return found


def _collect_gpu_cache_dirs(bucket: List[str], vendor_root: str) -> None:
    if (
        not vendor_root
        or not _exists(vendor_root)
        or os.path.islink(vendor_root)
        or not os.path.isdir(vendor_root)
        or path_is_forbidden(vendor_root)
        or path_has_sensitive_data(vendor_root)
        or _is_machine_vendor_tree(vendor_root)
    ):
        return
    if os.path.basename(vendor_root).lower() in _GPU_CACHE_DIR_NAMES:
        _append_if_dir(bucket, vendor_root)
        return
    stack = [(os.path.abspath(vendor_root), 0)]
    while stack:
        current, depth = stack.pop()
        if depth > _GPU_VENDOR_WALK_DEPTH:
            continue
        try:
            names = list(os.listdir(current))
        except OSError:
            continue
        for name in names:
            child = os.path.join(current, name)
            if os.path.islink(child) or not os.path.isdir(child):
                continue
            if (
                path_is_forbidden(child)
                or path_has_sensitive_data(child)
                or _is_machine_vendor_tree(child)
                or path_is_game_install(child)
            ):
                continue
            lowered = name.lower()
            if lowered in _GPU_CACHE_DIR_NAMES:
                _append_if_dir(bucket, child)
                continue
            if lowered in _BLOCKED_DIR_NAMES or lowered in _EMPTY_SKIP_DIR_NAMES:
                continue
            if depth < _GPU_VENDOR_WALK_DEPTH:
                stack.append((child, depth + 1))


def _local_low_dir(user_profile: str, local_app_data: str) -> str:
    if user_profile:
        return os.path.join(user_profile, "AppData", "LocalLow")
    if local_app_data:
        return os.path.join(os.path.dirname(local_app_data), "LocalLow")
    return ""


def _gpu_shader_cache_paths(local_app_data: str, user_profile: str) -> List[str]:
    found: List[str] = []
    bases = []
    if local_app_data and not _is_machine_vendor_tree(local_app_data):
        bases.append(local_app_data)
    local_low = _local_low_dir(user_profile, local_app_data)
    if local_low and not _is_machine_vendor_tree(local_low):
        bases.append(local_low)
    for base in bases:
        if path_is_forbidden(base):
            continue
        for rel in _GPU_VENDOR_RELS:
            _collect_gpu_cache_dirs(found, os.path.join(base, rel))
    return found


def _unescape_vdf(value: str) -> str:
    return str(value or "").replace("\\\\", "\\").replace("\\/", os.sep).strip()


def _accept_library_path(value: str) -> str:
    raw = _unescape_vdf(value)
    if not raw or raw in {"0", "-1"}:
        return ""
    if os.sep not in raw and "/" not in raw and "\\" not in raw:
        return ""
    return raw


def _libraries_from_vdf(steam_root: str) -> List[str]:
    found: List[str] = []
    for rel in (
        os.path.join("steamapps", "libraryfolders.vdf"),
        os.path.join("config", "libraryfolders.vdf"),
    ):
        path = os.path.join(steam_root, rel)
        if not _exists(path) or not os.path.isfile(path) or os.path.islink(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        for match in _VDF_PATH_RE.finditer(text):
            library = _accept_library_path(match.group(1))
            if library:
                found.append(library)
        for match in _VDF_LEGACY_RE.finditer(text):
            library = _accept_library_path(match.group(2))
            if library:
                found.append(library)
    return found


def _steam_root_ok(path: str) -> bool:
    if not path or not _exists(path) or os.path.islink(path) or not os.path.isdir(path):
        return False
    if path_is_forbidden(path) or path_is_too_broad(path) or path_is_game_install(path):
        return False
    markers = (
        os.path.join(path, "steamapps"),
        os.path.join(path, "appcache"),
        os.path.join(path, "steam.exe"),
        os.path.join(path, "Steam.exe"),
        os.path.join(path, "steamapps", "libraryfolders.vdf"),
        os.path.join(path, "config", "libraryfolders.vdf"),
    )
    return any(_exists(marker) for marker in markers)


def _steam_roots_from_registry() -> List[str]:
    """HKCU SteamPath. Ngoài Windows hoặc không có khóa thì bỏ qua."""
    if os.name != "nt":
        return []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _kind = winreg.QueryValueEx(key, "SteamPath")
    except Exception:
        return []
    text = str(value or "").strip()
    return [text] if text else []


def _steam_install_roots(
    environ: Optional[Dict[str, str]],
    local_app_data: str,
    user_profile: str,
) -> List[str]:
    seeds: List[str] = []
    for key in ("STEAM_PATH", "SteamPath", "STEAM_INSTALL"):
        value = _env(environ, key)
        if value:
            seeds.append(value)
    if local_app_data:
        seeds.append(os.path.join(local_app_data, "Steam"))
    if user_profile:
        seeds.append(os.path.join(user_profile, "Steam"))
    if environ is None:
        seeds.extend(_steam_roots_from_registry())
    roots: List[str] = []
    seen = set()
    for seed in seeds:
        if not _steam_root_ok(seed):
            continue
        for candidate in (seed, *_libraries_from_vdf(seed)):
            if not _steam_root_ok(candidate):
                continue
            try:
                token = os.path.normcase(os.path.abspath(candidate))
            except (OSError, ValueError):
                continue
            if token in seen:
                continue
            seen.add(token)
            roots.append(candidate)
    return roots


def _steam_cache_paths(
    environ: Optional[Dict[str, str]],
    local_app_data: str,
    user_profile: str,
) -> List[str]:
    found: List[str] = []
    for root in _steam_install_roots(environ, local_app_data, user_profile):
        for rel in _STEAM_CACHE_RELS:
            path = os.path.join(root, rel)
            if path_is_game_install(path):
                continue
            _append_if_dir(found, path)
    return found


def _epic_cache_paths(local_app_data: str) -> List[str]:
    found: List[str] = []
    if not local_app_data or path_is_forbidden(local_app_data) or _is_machine_vendor_tree(local_app_data):
        return found
    saved = os.path.join(local_app_data, "EpicGamesLauncher", "Saved")
    if not _exists(saved) or os.path.islink(saved) or not os.path.isdir(saved):
        return found
    try:
        names = list(os.listdir(saved))
    except OSError:
        return found
    for name in names:
        lowered = name.lower()
        if not (
            lowered == "webcache"
            or lowered.startswith("webcache_")
            or lowered.startswith("webcache")
            or lowered in {"cache", "gpucache", "code cache", "codecache"}
        ):
            continue
        path = os.path.join(saved, name)
        if path_is_game_install(path):
            continue
        _append_if_dir(found, path)
    return found


def _is_reparse_point(path: str) -> bool:
    """Symlink, junction hoặc điểm OneDrive. Không đi theo và không xóa."""
    if not path:
        return False
    if os.path.islink(path):
        return True
    try:
        info = os.lstat(path)
    except OSError:
        return True
    attrs = int(getattr(info, "st_file_attributes", 0) or 0)
    # FILE_ATTRIBUTE_REPARSE_POINT
    return bool(attrs & 0x400)


def _is_onedrive_dir_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return lowered == "onedrive" or lowered.startswith("onedrive ")


class _EmptyDirBudget:
    """Giới hạn thời gian và số thư mục khi tìm thư mục trống."""

    def __init__(
        self,
        *,
        max_visited: int = DEFAULT_EMPTY_DIR_MAX_VISITED,
        max_seconds: float = DEFAULT_EMPTY_DIR_MAX_SECONDS,
    ) -> None:
        self.max_visited = max(0, int(max_visited))
        self.max_seconds = float(max_seconds)
        self.visited = 0
        self.start = time.monotonic()

    def expired(self) -> bool:
        if self.visited > self.max_visited:
            return True
        return (time.monotonic() - self.start) >= self.max_seconds

    def visit(self) -> bool:
        if self.expired():
            return False
        self.visited += 1
        return self.visited <= self.max_visited


def _empty_root_allowed(path: str, *, user_profile: str = "", system_root: str = "") -> bool:
    if not path or not _exists(path) or not os.path.isdir(path):
        return False
    if os.path.islink(path) or _is_reparse_point(path):
        return False
    if path_is_forbidden(path) or path_has_sensitive_data(path) or path_is_game_install(path):
        return False
    if path_is_too_broad(path, user_profile=user_profile, system_root=system_root):
        return False
    if _is_onedrive_sync_path(path, user_profile) or _is_machine_vendor_tree(path):
        return False
    return True


def _empty_folder_roots(
    user_profile: str,
    local_app_data: str,
    user_temp: str,
    system_root: str,
) -> List[str]:
    found: List[str] = []
    if user_profile and not path_is_forbidden(user_profile):
        for name in _EMPTY_PROFILE_DIRS:
            candidate = os.path.join(user_profile, name)
            if _empty_root_allowed(candidate, user_profile=user_profile, system_root=system_root):
                found.append(candidate)
    temps = [user_temp]
    if local_app_data:
        temps.append(os.path.join(local_app_data, "Temp"))
    for candidate in temps:
        if candidate and _empty_root_allowed(candidate, user_profile=user_profile, system_root=system_root):
            found.append(candidate)
    return _dedupe(found)


def list_empty_directories(
    root: str,
    *,
    budget: Optional[_EmptyDirBudget] = None,
    user_profile: str = "",
    system_root: str = "",
    max_depth: int = DEFAULT_EMPTY_DIR_MAX_DEPTH,
) -> List[str]:
    """
    Thư mục không còn tệp bên trong root. Không gồm chính root.
    Không đi theo symlink / reparse, không vào OneDrive, node_modules, WinSxS.
    Hết giờ hoặc quá sâu thì bỏ phần chưa kiểm tra — không coi là trống.
    """
    found: List[str] = []
    if not _empty_root_allowed(root, user_profile=user_profile, system_root=system_root):
        return found
    limit = budget or _EmptyDirBudget()
    depth_cap = max(0, int(max_depth))
    try:
        root_abs = os.path.abspath(root)
    except (OSError, ValueError):
        return found

    def walk(path: str, depth: int) -> bool:
        """True khi cả cây không có tệp và đã được xem hết."""
        if limit.expired() or not limit.visit():
            return False
        if depth > depth_cap:
            return False
        if os.path.islink(path) or _is_reparse_point(path):
            return False
        if path_is_forbidden(path) or path_has_sensitive_data(path) or path_is_game_install(path):
            return False
        if _is_onedrive_sync_path(path, user_profile):
            return False
        try:
            current_abs = os.path.abspath(path)
        except (OSError, ValueError):
            return False
        if current_abs != root_abs and not _within_root(current_abs, root_abs):
            return False
        try:
            names = list(os.listdir(path))
        except OSError:
            return False
        if not names:
            return True
        fully_empty = True
        for name in names:
            lowered = name.lower()
            child = os.path.join(path, name)
            if (
                lowered in _EMPTY_SKIP_DIR_NAMES
                or lowered in _BLOCKED_DIR_NAMES
                or _is_onedrive_dir_name(name)
            ):
                fully_empty = False
                continue
            if os.path.islink(child) or _is_reparse_point(child):
                fully_empty = False
                continue
            if path_is_forbidden(child) or path_has_sensitive_data(child) or path_is_game_install(child):
                fully_empty = False
                continue
            if not os.path.isdir(child):
                fully_empty = False
                continue
            if walk(child, depth + 1):
                found.append(child)
            else:
                fully_empty = False
        return fully_empty

    walk(root_abs, 0)
    return _dedupe(found)


def clean_empty_directories(
    root: str,
    *,
    user_profile: str = "",
    system_root: str = "",
    budget: Optional[_EmptyDirBudget] = None,
) -> Dict[str, int]:
    """Xóa thư mục đang trống. Không xóa tệp, không xóa chính root, không đi theo reparse."""
    result = {
        "freed_bytes": 0,
        "deleted_files": 0,
        "skipped_locked": 0,
        "errors": 0,
        "protected": 0,
        "too_broad": 0,
        "sync_root": 0,
    }
    if path_is_forbidden(root):
        result["errors"] = 1
        result["protected"] = 1
        return result
    if path_is_too_broad(root, user_profile=user_profile, system_root=system_root):
        result["errors"] = 1
        result["too_broad"] = 1
        return result
    if _is_onedrive_sync_path(root, user_profile):
        result["errors"] = 1
        result["sync_root"] = 1
        return result
    if not _empty_root_allowed(root, user_profile=user_profile, system_root=system_root):
        return result
    try:
        root_abs = os.path.abspath(root)
    except (OSError, ValueError):
        result["errors"] = 1
        return result
    directories = list_empty_directories(
        root,
        budget=budget,
        user_profile=user_profile,
        system_root=system_root,
    )
    for path in sorted(directories, key=len, reverse=True):
        if os.path.islink(path) or _is_reparse_point(path) or path_is_forbidden(path):
            result["errors"] += 1
            result["protected"] += 1
            continue
        if path_is_game_install(path) or path_has_sensitive_data(path):
            result["errors"] += 1
            continue
        if not _within_root(path, root_abs):
            result["errors"] += 1
            continue
        try:
            if os.path.abspath(path) == root_abs:
                continue
        except (OSError, ValueError):
            result["errors"] += 1
            continue
        if _is_onedrive_sync_path(path, user_profile) or _is_onedrive_dir_name(os.path.basename(path)):
            result["sync_root"] += 1
            continue
        try:
            if os.listdir(path):
                continue
            os.rmdir(path)
        except OSError:
            result["skipped_locked"] += 1
            continue
        if _exists(path):
            result["skipped_locked"] += 1
            continue
        result["deleted_files"] += 1
    return result


def build_target_paths(environ: Optional[Dict[str, str]] = None) -> Dict[str, List[str]]:
    """
    Tập đường dẫn có thể dọn. environ=None dùng môi trường thật.
    Khi truyền dict (test), thiếu SystemRoot nghĩa là không có mục hệ thống —
    không rơi về C:\\Windows.
    """
    local_app_data = _env(environ, "LOCALAPPDATA")
    app_data = _env(environ, "APPDATA")
    user_temp = _env(environ, "TEMP") or _env(environ, "TMP")
    user_profile = _env(environ, "USERPROFILE")
    if environ is None:
        system_root = _env(None, "SystemRoot") or _env(None, "SYSTEMROOT")
        if not system_root and os.name == "nt":
            system_root = r"C:\Windows"
    else:
        system_root = _env(environ, "SystemRoot") or _env(environ, "SYSTEMROOT")
    system_drive = _system_drive(environ)
    program_data = _program_data(environ)

    targets: Dict[str, List[str]] = {key: [] for key in TARGET_ORDER if key != "recycle_bin"}

    temp_candidates = [user_temp]
    if local_app_data:
        temp_candidates.append(os.path.join(local_app_data, "Temp"))
    for candidate in temp_candidates:
        if (
            candidate
            and _exists(candidate)
            and os.path.isdir(candidate)
            and not path_is_forbidden(candidate)
            and not path_is_too_broad(candidate, user_profile=user_profile, system_root=system_root)
        ):
            targets["user_temp"].append(candidate)

    if local_app_data and not path_is_forbidden(local_app_data):
        targets["thumbnail_cache"].extend(_thumbnail_files(local_app_data))
        for rel in _CHROMIUM_ROOTS:
            targets["browser_cache"].extend(_chromium_caches(os.path.join(local_app_data, rel)))
        firefox_root = os.path.join(local_app_data, "Mozilla", "Firefox", "Profiles")
        if _exists(firefox_root):
            try:
                for name in os.listdir(firefox_root):
                    profile = os.path.join(firefox_root, name)
                    if not os.path.isdir(profile):
                        continue
                    for sub in ("cache2", "startupCache", "shader-cache"):
                        _append_if_dir(targets["browser_cache"], os.path.join(profile, sub))
            except OSError:
                pass
        for rel in _OPERA_CACHE_RELS:
            _append_if_dir(targets["browser_cache"], os.path.join(local_app_data, rel))
        for root in _find_ebwebview_roots(local_app_data, max_listdir_depth=3):
            targets["browser_cache"].extend(_chromium_caches(root))
        _append_if_dir(
            targets["shell_font_cache"],
            os.path.join(local_app_data, "Microsoft", "FontCache"),
        )
        _append_if_dir(
            targets["shell_font_cache"],
            os.path.join(local_app_data, "Microsoft", "Windows", "Caches"),
        )
        targets["shell_font_cache"].extend(
            _package_scoped_dirs(local_app_data, _SHELL_PACKAGE_PREFIXES, ("TempState",))
        )
        for rel in _OFFICE_SAFE_RELS:
            _append_if_dir(targets["office_cache"], os.path.join(local_app_data, rel))
        for rel in _ONEDRIVE_LOG_RELS:
            _append_if_dir(targets["office_cache"], os.path.join(local_app_data, rel))
        _append_if_dir(
            targets["office_file_cache"],
            os.path.join(local_app_data, _OFFICE_FILE_CACHE_REL),
        )
        targets["store_cache"].extend(
            _package_scoped_dirs(local_app_data, _STORE_PACKAGE_PREFIXES, _STORE_CACHE_RELS)
        )
        _append_if_dir(
            targets["inet_cache"],
            os.path.join(local_app_data, "Microsoft", "Windows", "INetCache"),
        )
        for rel in _SHADER_RELS:
            _append_if_dir(targets["shader_cache"], os.path.join(local_app_data, rel))
        _append_if_dir(targets["crash_dumps"], os.path.join(local_app_data, "CrashDumps"))
        _append_if_dir(
            targets["crash_dumps"],
            os.path.join(local_app_data, "Microsoft", "Windows", "WER", "ReportArchive"),
        )
        _append_if_dir(
            targets["crash_dumps"],
            os.path.join(local_app_data, "Microsoft", "Windows", "WER", "ReportQueue"),
        )
        _append_if_dir(
            targets["crash_dumps"],
            os.path.join(local_app_data, "Microsoft", "Windows", "WER", "Temp"),
        )
        _append_if_dir(
            targets["delivery_cache"],
            os.path.join(local_app_data, "Microsoft", "Windows", "DeliveryOptimization", "Cache"),
        )

    if app_data and not path_is_forbidden(app_data):
        for rel in _OPERA_CACHE_RELS:
            _append_if_dir(targets["browser_cache"], os.path.join(app_data, rel))
        for root in _find_ebwebview_roots(app_data, max_listdir_depth=4):
            targets["browser_cache"].extend(_chromium_caches(root))

    targets["app_caches"].extend(_app_cache_paths(local_app_data, app_data))
    targets["discord_cache"].extend(_discord_cache_paths(local_app_data, app_data))
    targets["telegram_cache"].extend(_telegram_cache_paths(local_app_data, app_data))
    targets["zalo_cache"].extend(_zalo_cache_paths(local_app_data, app_data))
    targets["messenger_cache"].extend(_messenger_cache_paths(local_app_data, app_data))
    targets["gpu_shader_caches"].extend(_gpu_shader_cache_paths(local_app_data, user_profile))
    targets["steam_caches"].extend(_steam_cache_paths(environ, local_app_data, user_profile))
    targets["epic_caches"].extend(_epic_cache_paths(local_app_data))
    targets["empty_user_folders"].extend(
        _empty_folder_roots(user_profile, local_app_data, user_temp, system_root)
    )
    targets["toolchain_caches"].extend(
        _toolchain_cache_paths(local_app_data, app_data, user_profile)
    )

    if user_profile and not path_is_forbidden(user_profile):
        _append_if_dir(targets["nuget_packages"], os.path.join(user_profile, ".nuget", "packages"))
        _append_if_dir(targets["gradle_caches"], os.path.join(user_profile, ".gradle", "caches"))
        _append_if_dir(
            targets["cargo_cache"],
            os.path.join(user_profile, ".cargo", "registry", "cache"),
        )
        downloads = os.path.join(user_profile, "Downloads")
        if (
            _exists(downloads)
            and os.path.isdir(downloads)
            and not path_is_too_broad(downloads, user_profile=user_profile, system_root=system_root)
        ):
            targets["downloads_old"].append(downloads)

    if system_root and not path_is_forbidden(system_root):
        sys_temp = os.path.join(system_root, "Temp")
        if _exists(sys_temp) and not path_is_too_broad(sys_temp, user_profile=user_profile, system_root=system_root):
            _append_if_dir(targets["system_temp"], sys_temp)
        _append_if_dir(
            targets["windows_update"],
            os.path.join(system_root, "SoftwareDistribution", "Download"),
        )
        _append_if_dir(targets["system_dumps"], os.path.join(system_root, "Minidump"))
        memory_dmp = os.path.join(system_root, "MEMORY.DMP")
        if _exists(memory_dmp) and os.path.isfile(memory_dmp) and not path_is_forbidden(memory_dmp):
            targets["system_dumps"].append(memory_dmp)
        _append_if_dir(
            targets["system_delivery_opt"],
            os.path.join(system_root, "SoftwareDistribution", "DeliveryOptimization"),
        )
        _append_if_dir(
            targets["system_delivery_opt"],
            os.path.join(
                system_root,
                "ServiceProfiles",
                "NetworkService",
                "AppData",
                "Local",
                "Microsoft",
                "Windows",
                "DeliveryOptimization",
                "Cache",
            ),
        )
        _append_if_dir(targets["windows_logs"], os.path.join(system_root, "Logs", "CBS"))
        _append_if_dir(targets["windows_logs"], os.path.join(system_root, "Logs", "DISM"))
        _append_if_dir(targets["prefetch"], os.path.join(system_root, "Prefetch"))

    if system_drive:
        for name in ("$WINDOWS.~BT", "$WINDOWS.~WS"):
            _append_if_dir(targets["windows_setup_temp"], _under_drive(system_drive, name))
        windows_old = _under_drive(system_drive, "Windows.old")
        if (
            windows_old
            and _exists(windows_old)
            and os.path.isdir(windows_old)
            and not os.path.islink(windows_old)
            and not path_is_forbidden(windows_old)
            and not path_is_too_broad(windows_old, user_profile=user_profile, system_root=system_root)
        ):
            targets["windows_old"].append(windows_old)

    if program_data and not path_is_forbidden(program_data):
        _append_if_dir(
            targets["system_wer"],
            os.path.join(program_data, "Microsoft", "Windows", "WER"),
        )

    for key in list(targets.keys()):
        kept = []
        for path in _dedupe(targets[key]):
            if path_is_forbidden(path) or path_has_sensitive_data(path) or path_is_game_install(path):
                continue
            if key == "gpu_shader_caches" and _is_machine_vendor_tree(path):
                continue
            if path_is_too_broad(path, user_profile=user_profile, system_root=system_root):
                continue
            if _is_onedrive_sync_path(path, user_profile):
                continue
            if key == "empty_user_folders" and not _empty_root_allowed(
                path, user_profile=user_profile, system_root=system_root
            ):
                continue
            kept.append(path)
        targets[key] = kept
    return targets


def resolve_clean_plan(
    enabled_targets: Optional[Dict[str, bool]],
    *,
    is_admin: bool,
    deep_user_safe: bool = False,
    deep_admin: bool = False,
) -> Dict[str, Any]:
    """
    Chọn mục sẽ chạy và mục bỏ qua.

    deep_user_safe: một lần bấm «Dọn ổ C» — mọi mục user-safe đang bật
    (Downloads chỉ khi bật). Mục Admin đang bật được ghi nhận là bỏ qua
    khi chưa elevated, không làm hỏng cả lượt dọn.

    deep_admin: «Dọn sâu (cần Admin)» — gồm cả mục user-safe như trên,
    cộng mục hệ thống mặc định bật. Mục hệ thống tùy chọn (dump, Prefetch,
    Windows.old, DISM, ngủ đông) chỉ vào khi người dùng bật. Chưa elevated
    thì những mục hệ thống đó bị bỏ qua, 0 B, không xóa.
    """
    enabled = enabled_targets or {}
    to_run: Dict[str, bool] = {}
    skipped: List[Dict[str, Any]] = []
    broad = bool(deep_user_safe or deep_admin)

    for key in TARGET_ORDER:
        meta = TARGET_CATALOG[key]
        user_on = bool(enabled.get(key, False))
        if broad:
            # Cache/temp user-safe (mặc định bật) luôn chạy, kể cả khi checkbox định kỳ đang tắt.
            # Thùng rác và Downloads chỉ chạy khi người dùng đang bật.
            # Mục Admin: checkbox đang bật, hoặc (dọn sâu Admin và mục mặc định bật).
            if meta["needs_admin"]:
                include = user_on or (bool(deep_admin) and bool(meta["default_enabled"]))
                if not include:
                    continue
                if not is_admin:
                    skipped.append(_skip_record(key, ADMIN_SKIP_REASON_VI))
                    continue
                to_run[key] = True
                continue
            if key in ("downloads_old", "recycle_bin"):
                if user_on:
                    to_run[key] = True
                continue
            if meta["default_enabled"] or user_on:
                to_run[key] = True
            continue

        if not user_on:
            continue
        if meta["needs_admin"] and not is_admin:
            skipped.append(_skip_record(key, ADMIN_SKIP_REASON_VI))
            continue
        to_run[key] = True

    return {
        "to_run": to_run,
        "skipped": skipped,
        "is_admin": bool(is_admin),
        "deep_user_safe": bool(deep_user_safe),
        "deep_admin": bool(deep_admin),
    }


def _skip_record(key: str, reason: str) -> Dict[str, Any]:
    meta = TARGET_CATALOG[key]
    return {
        "key": key,
        "name": meta["label_vi"],
        "reason": reason,
        "needs_admin": bool(meta["needs_admin"]),
        "freed_bytes": 0,
        "status": "skipped",
    }


def empty_detail(key: str, *, status: str, reason: str = "", **extra: Any) -> Dict[str, Any]:
    meta = TARGET_CATALOG.get(key, {})
    freed = int(extra.pop("freed_bytes", 0) or 0)
    detail = {
        "key": key,
        "name": meta.get("label_vi", key),
        "status": status,
        "reason": reason,
        "needs_admin": bool(meta.get("needs_admin", False)),
        "scope": meta.get("scope", ""),
        "risk": meta.get("risk", ""),
        "freed_bytes": freed,
        "freed_mb": round(freed / (1024 ** 2), 2),
        "deleted_files": int(extra.pop("deleted_files", 0) or 0),
        "skipped_locked": int(extra.pop("skipped_locked", 0) or 0),
        "errors": int(extra.pop("errors", 0) or 0),
    }
    detail.update(extra)
    return detail


def bytes_actually_freed(before_size: int, still_exists: bool, after_size: int = 0) -> int:
    """Chỉ tính phần biến mất khỏi đĩa. Mục còn nguyên thì 0."""
    before = max(0, int(before_size or 0))
    if not still_exists:
        return before
    after = max(0, int(after_size or 0))
    return max(0, before - after)


def _remove_readonly(func, path, _exc_info):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def _file_size(path: str) -> int:
    try:
        if os.path.islink(path):
            return 0
        return max(0, int(os.path.getsize(path)))
    except OSError:
        return 0


def scan_tree(path: str) -> Dict[str, int]:
    """Đếm byte và số tệp. Không đi theo symlink."""
    if not path or not _exists(path) or path_is_forbidden(path):
        return {"size_bytes": 0, "file_count": 0}
    if os.path.islink(path):
        return {"size_bytes": 0, "file_count": 0}
    if os.path.isfile(path):
        return {"size_bytes": _file_size(path), "file_count": 1 if _file_size(path) or _exists(path) else 0}
    total = 0
    count = 0
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [
                name for name in dirs
                if not path_is_forbidden(os.path.join(root, name))
                and not os.path.islink(os.path.join(root, name))
            ]
            for name in files:
                file_path = os.path.join(root, name)
                if os.path.islink(file_path) or path_is_forbidden(file_path):
                    continue
                size = _file_size(file_path)
                if size or _exists(file_path):
                    total += size
                    count += 1
    except OSError:
        pass
    return {"size_bytes": total, "file_count": count}


def try_delete_file(path: str) -> Dict[str, int]:
    """Xóa một tệp. Byte chỉ được cộng khi tệp không còn."""
    if not path or path_is_forbidden(path) or os.path.isdir(path) and not os.path.islink(path):
        return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 0, "errors": 1}
    if os.path.islink(path):
        try:
            os.unlink(path)
        except OSError:
            return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 1, "errors": 0}
        if os.path.lexists(path):
            return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 1, "errors": 0}
        return {"freed_bytes": 0, "deleted_files": 1, "skipped_locked": 0, "errors": 0}

    size = _file_size(path)
    try:
        os.unlink(path)
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE)
            os.unlink(path)
        except OSError:
            return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 1, "errors": 0}
    except OSError:
        return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 1, "errors": 0}
    if os.path.exists(path):
        return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 1, "errors": 0}
    return {"freed_bytes": size, "deleted_files": 1, "skipped_locked": 0, "errors": 0}


def _merge_counts(total: Dict[str, int], part: Dict[str, int]) -> None:
    for key in ("freed_bytes", "deleted_files", "skipped_locked", "errors"):
        total[key] = int(total.get(key, 0)) + int(part.get(key, 0))


def clean_children(path: str, *, user_profile: str = "", system_root: str = "") -> Dict[str, int]:
    """Xóa nội dung bên trong thư mục, giữ lại chính thư mục đó."""
    result = {
        "freed_bytes": 0,
        "deleted_files": 0,
        "skipped_locked": 0,
        "errors": 0,
        "protected": 0,
        "too_broad": 0,
        "sync_root": 0,
    }
    if path_is_forbidden(path):
        result["errors"] = 1
        result["protected"] = 1
        return result
    if path_is_too_broad(path, user_profile=user_profile, system_root=system_root):
        result["errors"] = 1
        result["too_broad"] = 1
        return result
    if _is_onedrive_sync_path(path, user_profile):
        result["errors"] = 1
        result["sync_root"] = 1
        return result
    if not _exists(path) or not os.path.isdir(path) or os.path.islink(path):
        return result
    try:
        names = list(os.listdir(path))
    except OSError:
        result["errors"] = 1
        return result
    for name in names:
        child = os.path.join(path, name)
        if path_is_forbidden(child):
            result["errors"] += 1
            result["protected"] += 1
            continue
        if os.path.islink(child):
            _merge_counts(result, try_delete_file(child))
            continue
        if os.path.isfile(child):
            _merge_counts(result, try_delete_file(child))
            continue
        if os.path.isdir(child):
            before = scan_tree(child)
            try:
                import shutil
                shutil.rmtree(child, onerror=_remove_readonly)
            except Exception:
                result["errors"] += 1
            still = _exists(child)
            after = scan_tree(child) if still else {"size_bytes": 0, "file_count": 0}
            freed = bytes_actually_freed(before["size_bytes"], still, after["size_bytes"])
            deleted = max(0, before["file_count"] - (after["file_count"] if still else 0))
            result["freed_bytes"] += freed
            result["deleted_files"] += deleted
            if still:
                result["skipped_locked"] += max(1, after["file_count"])
    return result


def file_is_old_enough(path: str, min_age_days: int, now_ts: float) -> bool:
    days = int(min_age_days or 0)
    if days <= 0:
        return False
    try:
        age = float(now_ts) - float(os.path.getmtime(path))
    except OSError:
        return False
    return age >= days * 86400


def clean_old_files(
    root: str,
    min_age_days: int,
    now_ts: float,
    *,
    user_profile: str = "",
    system_root: str = "",
) -> Dict[str, int]:
    """Chỉ xóa tệp cũ hơn N ngày. Không xóa thư mục, không đụng symlink."""
    result = {
        "freed_bytes": 0,
        "deleted_files": 0,
        "skipped_locked": 0,
        "errors": 0,
        "skipped_recent": 0,
        "too_broad": 0,
        "sync_root": 0,
        "protected": 0,
    }
    if path_is_forbidden(root):
        result["errors"] = 1
        result["protected"] = 1
        return result
    if path_is_too_broad(root, user_profile=user_profile, system_root=system_root):
        result["errors"] = 1
        result["too_broad"] = 1
        return result
    if _is_onedrive_sync_path(root, user_profile) or int(min_age_days or 0) <= 0:
        result["errors"] = 1
        if _is_onedrive_sync_path(root, user_profile):
            result["sync_root"] = 1
        return result
    if not _exists(root) or not os.path.isdir(root):
        return result
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [
            name for name in dirnames
            if not path_is_forbidden(os.path.join(dirpath, name))
            and not os.path.islink(os.path.join(dirpath, name))
        ]
        for name in filenames:
            file_path = os.path.join(dirpath, name)
            if os.path.islink(file_path) or path_is_forbidden(file_path):
                continue
            if not _within_root(file_path, root_abs):
                result["errors"] += 1
                continue
            if not file_is_old_enough(file_path, min_age_days, now_ts):
                result["skipped_recent"] += 1
                continue
            part = try_delete_file(file_path)
            _merge_counts(result, part)
    return result


def clean_one_path(
    path: str,
    *,
    clean_mode: str,
    min_age_days: int = DEFAULT_DOWNLOADS_MIN_AGE_DAYS,
    now_ts: Optional[float] = None,
    user_profile: str = "",
    system_root: str = "",
) -> Dict[str, int]:
    if path_is_forbidden(path):
        return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 0, "errors": 1, "protected": 1}
    if path_is_too_broad(path, user_profile=user_profile, system_root=system_root):
        return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 0, "errors": 1, "too_broad": 1}
    if _is_onedrive_sync_path(path, user_profile):
        return {"freed_bytes": 0, "deleted_files": 0, "skipped_locked": 0, "errors": 1, "sync_root": 1}
    if clean_mode == "empty_dirs":
        return clean_empty_directories(
            path,
            user_profile=user_profile,
            system_root=system_root,
        )
    if clean_mode == "old_files":
        return clean_old_files(
            path,
            min_age_days,
            time.time() if now_ts is None else now_ts,
            user_profile=user_profile,
            system_root=system_root,
        )
    if os.path.isfile(path) or os.path.islink(path):
        return try_delete_file(path)
    return clean_children(path, user_profile=user_profile, system_root=system_root)


def scan_old_files(root: str, min_age_days: int, now_ts: float) -> Dict[str, int]:
    total = 0
    count = 0
    if not _exists(root) or path_is_forbidden(root) or int(min_age_days or 0) <= 0:
        return {"size_bytes": 0, "file_count": 0}
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root_abs):
        dirnames[:] = [
            name for name in dirnames
            if not path_is_forbidden(os.path.join(dirpath, name))
        ]
        for name in filenames:
            file_path = os.path.join(dirpath, name)
            if os.path.islink(file_path) or not _within_root(file_path, root_abs):
                continue
            if not file_is_old_enough(file_path, min_age_days, now_ts):
                continue
            total += _file_size(file_path)
            count += 1
    return {"size_bytes": total, "file_count": count}


def normalize_downloads_min_age_days(value: Any) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DOWNLOADS_MIN_AGE_DAYS
    if days <= 0:
        return DEFAULT_DOWNLOADS_MIN_AGE_DAYS
    return min(days, 3650)


def is_disk_space_low(
    free_gb: float,
    total_gb: float,
    *,
    min_free_gb: float = DEFAULT_LOW_DISK_FREE_GB,
    min_free_percent: float = DEFAULT_LOW_DISK_FREE_PERCENT,
    mode: str = DEFAULT_LOW_DISK_THRESHOLD_MODE,
) -> bool:
    """
    Cảnh báo dung lượng trống. total không đọc được thì không cảnh báo
    (tránh báo giả khi không có ổ C:).
    mode: gb (mặc định) | percent | either.
    """
    try:
        free = float(free_gb)
        total = float(total_gb)
    except (TypeError, ValueError):
        return False
    if total <= 0:
        return False
    gb_low = free < float(min_free_gb)
    percent_free = (free / total) * 100.0 if total > 0 else 100.0
    percent_low = percent_free < float(min_free_percent)
    selected = str(mode or DEFAULT_LOW_DISK_THRESHOLD_MODE).strip().lower()
    if selected == "percent":
        return percent_low
    if selected == "either":
        return gb_low or percent_low
    return gb_low


def low_disk_settings(config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    try:
        min_gb = float(cfg.get("low_disk_free_gb", DEFAULT_LOW_DISK_FREE_GB))
    except (TypeError, ValueError):
        min_gb = DEFAULT_LOW_DISK_FREE_GB
    try:
        min_pct = float(cfg.get("low_disk_free_percent", DEFAULT_LOW_DISK_FREE_PERCENT))
    except (TypeError, ValueError):
        min_pct = DEFAULT_LOW_DISK_FREE_PERCENT
    mode = str(cfg.get("low_disk_threshold_mode", DEFAULT_LOW_DISK_THRESHOLD_MODE) or "gb").lower()
    if mode not in ("gb", "percent", "either"):
        mode = "gb"
    return {
        "enabled": bool(cfg.get("low_disk_warn_enabled", True)),
        "min_free_gb": min_gb,
        "min_free_percent": min_pct,
        "mode": mode,
    }


def build_low_disk_notice(
    disk: Optional[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Payload toast/banner tiếng Việt, hoặc None khi chưa dưới ngưỡng."""
    settings = low_disk_settings(config)
    if not settings["enabled"]:
        return None
    info = disk if isinstance(disk, dict) else {}
    try:
        free_gb = float(info.get("free_gb", 0) or 0)
        total_gb = float(info.get("total_gb", 0) or 0)
    except (TypeError, ValueError):
        return None
    if not is_disk_space_low(
        free_gb,
        total_gb,
        min_free_gb=settings["min_free_gb"],
        min_free_percent=settings["min_free_percent"],
        mode=settings["mode"],
    ):
        return None
    if settings["mode"] == "percent":
        threshold = f"{settings['min_free_percent']:.0f}%"
    elif settings["mode"] == "either":
        threshold = f"{settings['min_free_gb']:.0f} GB hoặc {settings['min_free_percent']:.0f}%"
    else:
        threshold = f"{settings['min_free_gb']:.0f} GB"
    free_pct = (free_gb / total_gb * 100.0) if total_gb > 0 else 0.0
    message = (
        f"Ổ C: còn {free_gb:.1f} GB trống / {total_gb:.1f} GB ({free_pct:.0f}%). "
        f"Ngưỡng cảnh báo: {threshold}. "
        "Bấm «Dọn ổ C (không cần Admin)» để xóa rác an toàn, không cần quyền Administrator."
    )
    return {
        "title": "Ổ C: sắp đầy",
        "message": message,
        "free_gb": round(free_gb, 2),
        "total_gb": round(total_gb, 2),
        "free_percent": round(free_pct, 1),
        "threshold_label": threshold,
        "action": "deep_user_safe_clean",
    }


class LowDiskToastGate:
    """Chặn toast ổ đầy lặp lại, cùng kiểu cooldown với cảnh báo nhiệt."""

    def __init__(self) -> None:
        self.last_toast_ts = 0.0

    def reset(self) -> None:
        self.last_toast_ts = 0.0

    def allow(self, now_ts: float, *, cooldown_sec: float = DEFAULT_LOW_DISK_TOAST_COOLDOWN_SEC) -> bool:
        now_ts = float(now_ts)
        last = float(self.last_toast_ts or 0.0)
        if last <= 0 or (now_ts - last) >= float(cooldown_sec):
            self.last_toast_ts = now_ts
            return True
        return False

    def allow_from_config(self, now_ts: float, config: Optional[Dict[str, Any]] = None) -> bool:
        cfg = config if isinstance(config, dict) else {}
        try:
            cooldown = float(cfg.get("low_disk_warn_toast_cooldown_seconds", DEFAULT_LOW_DISK_TOAST_COOLDOWN_SEC))
        except (TypeError, ValueError):
            cooldown = DEFAULT_LOW_DISK_TOAST_COOLDOWN_SEC
        return self.allow(now_ts, cooldown_sec=cooldown)


def read_c_drive_free_bytes() -> Optional[int]:
    """Byte trống trên ổ hệ thống. Ngoài Windows trả None — không đoán ổ khác."""
    if os.name != "nt":
        return None
    drive = str(os.environ.get("SystemDrive") or "C:")
    if not drive.endswith("\\"):
        drive = drive + "\\"
    try:
        import shutil
        return max(0, int(shutil.disk_usage(drive).free))
    except (OSError, ValueError):
        return None


def _estimate_target_size(
    key: str,
    meta: Dict[str, Any],
    target_paths: Dict[str, List[str]],
    *,
    min_age_days: int,
    now_ts: float,
    recycle_info: Optional[Dict[str, Any]],
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, int]:
    if key == "recycle_bin":
        info = recycle_info or {}
        return {
            "size_bytes": max(0, int(info.get("size_bytes") or 0)),
            "file_count": max(0, int(info.get("items") or info.get("file_count") or 0)),
        }
    if key == "component_cleanup":
        return {"size_bytes": 0, "file_count": 0}
    if key == "hibernate_file":
        path = _hibernate_file_path(environ)
        if path and _exists(path) and os.path.isfile(path) and not path_is_forbidden(path):
            return {"size_bytes": _file_size(path), "file_count": 1}
        return {"size_bytes": 0, "file_count": 0}
    if meta.get("clean_mode") == "empty_dirs":
        env = os.environ if environ is None else environ
        user_profile = str(env.get("USERPROFILE", "") or "")
        system_root = str(env.get("SystemRoot", "") or env.get("SYSTEMROOT", "") or "")
        budget = _EmptyDirBudget()
        count = 0
        for path in target_paths.get(key, []):
            count += len(list_empty_directories(
                path,
                budget=budget,
                user_profile=user_profile,
                system_root=system_root,
            ))
        return {"size_bytes": 0, "file_count": count}
    total = 0
    count = 0
    for path in target_paths.get(key, []):
        if meta.get("clean_mode") == "old_files":
            stat_info = scan_old_files(path, min_age_days, now_ts)
        else:
            stat_info = scan_tree(path)
        total += int(stat_info.get("size_bytes") or 0)
        count += int(stat_info.get("file_count") or 0)
    return {"size_bytes": total, "file_count": count}


def prune_nested_target_paths(
    target_paths: Dict[str, List[str]],
    active_keys: Sequence[str],
) -> Dict[str, List[str]]:
    """Bỏ đường dẫn nằm trong đường dẫn khác để không cộng byte hai lần."""
    entries: List[tuple] = []
    passthrough: List[tuple] = []
    for key in active_keys:
        mode = str(TARGET_CATALOG.get(key, {}).get("clean_mode") or "")
        for path in target_paths.get(key, []) or []:
            if not path:
                continue
            # Thư mục trống không chứa byte tệp và không được nuốt cache lồng bên trong.
            if mode == "empty_dirs":
                passthrough.append((key, path))
                continue
            try:
                abs_path = os.path.normcase(os.path.abspath(path))
            except (OSError, ValueError):
                continue
            entries.append((key, path, abs_path))
    drop = set()
    for index, (_key, _path, abs_path) in enumerate(entries):
        for other, (_other_key, _other_path, other_abs) in enumerate(entries):
            if index == other:
                continue
            if abs_path == other_abs:
                if index > other:
                    drop.add(index)
                continue
            if _within_root(abs_path, other_abs):
                drop.add(index)
                break
    pruned: Dict[str, List[str]] = {key: [] for key in active_keys}
    for index, (key, path, _abs_path) in enumerate(entries):
        if index not in drop:
            pruned[key].append(path)
    seen_pass = set()
    for key, path in passthrough:
        try:
            token = (key, os.path.normcase(os.path.abspath(path)))
        except (OSError, ValueError):
            continue
        if token in seen_pass:
            continue
        seen_pass.add(token)
        pruned.setdefault(key, []).append(path)
    return pruned


def estimate_reclaimable(
    enabled_targets: Optional[Dict[str, bool]],
    *,
    is_admin: bool,
    deep_user_safe: bool = True,
    deep_admin: bool = False,
    environ: Optional[Dict[str, str]] = None,
    downloads_min_age_days: Optional[int] = None,
    now_ts: Optional[float] = None,
    recycle_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Ước lượng byte và số tệp của đúng tập resolve_clean_plan sẽ dọn.
    Không xóa. Mục bỏ qua (Admin khi chưa elevated) có kích thước riêng
    nhưng reclaimable_bytes = 0 và không cộng vào tổng.
    """
    plan = resolve_clean_plan(
        enabled_targets,
        is_admin=bool(is_admin),
        deep_user_safe=bool(deep_user_safe),
        deep_admin=bool(deep_admin),
    )
    target_paths = build_target_paths(environ)
    days = normalize_downloads_min_age_days(
        DEFAULT_DOWNLOADS_MIN_AGE_DAYS if downloads_min_age_days is None else downloads_min_age_days
    )
    moment = time.time() if now_ts is None else float(now_ts)
    skipped_by_key = {item["key"]: item for item in plan["skipped"]}
    active_keys = [key for key in TARGET_ORDER if plan["to_run"].get(key)]
    pruned_paths = prune_nested_target_paths(target_paths, active_keys)
    rows: List[Dict[str, Any]] = []
    total_bytes = 0
    total_files = 0

    for key in TARGET_ORDER:
        will_run = bool(plan["to_run"].get(key))
        skipped = skipped_by_key.get(key)
        if not will_run and not skipped:
            continue
        meta = TARGET_CATALOG[key]
        measured = _estimate_target_size(
            key,
            meta,
            pruned_paths if will_run else target_paths,
            min_age_days=days,
            now_ts=moment,
            recycle_info=recycle_info,
            environ=environ,
        )
        if will_run:
            reclaim_bytes = measured["size_bytes"]
            reclaim_files = measured["file_count"]
            status = "ready"
            reason = ""
        else:
            reclaim_bytes = 0
            reclaim_files = 0
            status = "skipped"
            reason = str((skipped or {}).get("reason") or ADMIN_SKIP_REASON_VI)
        rows.append({
            "key": key,
            "name": meta["label_vi"],
            "status": status,
            "reason": reason,
            "needs_admin": bool(meta["needs_admin"]),
            "size_bytes": measured["size_bytes"],
            "file_count": measured["file_count"],
            "reclaimable_bytes": reclaim_bytes,
            "reclaimable_files": reclaim_files,
            "size_label_vi": format_freed_vi(reclaim_bytes if will_run else measured["size_bytes"]),
        })
        total_bytes += reclaim_bytes
        total_files += reclaim_files

    result = {
        "targets": rows,
        "total_bytes": total_bytes,
        "total_files": total_files,
        "total_label_vi": format_freed_vi(total_bytes),
        "is_admin": bool(is_admin),
        "deep_user_safe": bool(deep_user_safe),
        "deep_admin": bool(deep_admin),
        "skipped": plan["skipped"],
    }
    result["preview_vi"] = format_scan_preview_vi(result)
    return result


def format_scan_preview_vi(result: Dict[str, Any]) -> str:
    total = int(result.get("total_bytes") or 0)
    files = int(result.get("total_files") or 0)
    deep_admin = bool(result.get("deep_admin"))
    lines = ["Xem trước — chưa xóa tệp nào."]
    if deep_admin and not result.get("is_admin"):
        lines.append("Cần Admin — chưa chạy. Các mục hệ thống không nằm trong tổng (0 B).")
    lines.extend([
        f"Có thể giải phóng (ước lượng): {format_freed_vi(total)} ({files} tệp).",
        "Chỉ cộng mục sẽ dọn. Mục cần Admin không nằm trong tổng.",
        "",
    ])
    shown = 0
    for row in result.get("targets") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("key") or "Mục")
        if row.get("status") == "skipped":
            estimated = int(row.get("size_bytes") or 0)
            file_count = int(row.get("file_count") or 0)
            show_admin_pending = deep_admin and not result.get("is_admin") and row.get("needs_admin")
            if estimated <= 0 and file_count <= 0 and not show_admin_pending:
                continue
            if show_admin_pending:
                lines.append(f"• {name}: cần Admin — chưa chạy (0 B)")
            else:
                extra = f" Ước lượng {format_freed_vi(estimated)} không được tính." if estimated else ""
                reason = str(row.get("reason") or ADMIN_SKIP_REASON_VI).rstrip(".")
                lines.append(f"• {name}: đã bỏ qua — {reason}.{extra}")
            shown += 1
            continue
        size = int(row.get("reclaimable_bytes") or 0)
        count = int(row.get("reclaimable_files") or 0)
        if row.get("key") == "empty_user_folders":
            if size <= 0 and count <= 0:
                continue
            lines.append(f"• {name}: {count} thư mục trống ({format_freed_vi(size)})")
            shown += 1
            continue
        if size <= 0 and count <= 0:
            if row.get("status") == "ready" and row.get("key") in _ALWAYS_PREVIEW_KEYS:
                lines.append(f"• {name}: khoảng 0 B")
                shown += 1
            continue
        lines.append(f"• {name}: khoảng {format_freed_vi(size)} ({count} tệp)")
        shown += 1
    if shown == 0:
        lines.append("• Không có gì để xóa (0 B)")
    lines.append("")
    lines.append(
        "Bấm «Dọn ngay» để xóa các mục sẵn sàng. "
        "Thùng rác và tệp cũ trong Downloads chỉ có trong danh sách khi bạn đang bật."
    )
    return "\n".join(lines).strip()


def format_free_space_line_vi(result: Dict[str, Any]) -> str:
    """So dung lượng trống ổ C: trước/sau với số byte đã xóa thật."""
    claimed = int(result.get("total_freed_bytes") or 0)
    claimed_label = format_freed_vi(claimed)
    before = result.get("free_bytes_before")
    after = result.get("free_bytes_after")
    if before is None or after is None:
        return (
            "Không đọc được dung lượng trống ổ C: trước hoặc sau khi dọn. "
            f"Số byte đã xóa vẫn là {claimed_label}."
        )
    before_i = max(0, int(before))
    after_i = max(0, int(after))
    delta = after_i - before_i
    if delta > 0:
        delta_label = "+" + format_freed_vi(delta)
    elif delta < 0:
        delta_label = "-" + format_freed_vi(-delta)
    else:
        delta_label = "0 B"
    return (
        f"Ổ C: trống trước {format_freed_vi(before_i)} → sau {format_freed_vi(after_i)} "
        f"(thay đổi thực tế {delta_label}). "
        f"Byte đã xóa: {claimed_label}."
    )


def format_freed_vi(num_bytes: int) -> str:
    """Nhãn dung lượng không làm tròn mất phần đã xóa (tránh 0.0 MB khi vẫn xóa được KB)."""
    n = max(0, int(num_bytes or 0))
    if n >= 1024 ** 3:
        return f"{n / (1024 ** 3):.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / (1024 ** 2):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def format_target_line_vi(detail: Dict[str, Any]) -> str:
    name = str(detail.get("name") or detail.get("key") or "Mục")
    status = str(detail.get("status") or "")
    reason = str(detail.get("reason") or "").strip()
    freed_bytes = int(detail.get("freed_bytes") or 0)
    freed_label = format_freed_vi(freed_bytes)
    if status == "skipped":
        return f"{name}: đã bỏ qua — {reason or ADMIN_SKIP_REASON_VI}"
    if status == "error":
        return f"{name}: lỗi — {reason or 'không xóa được'} (0 B, không tính dung lượng)"
    locked = int(detail.get("skipped_locked") or 0)
    locked_note = f", bỏ qua {locked} tệp đang khóa" if locked else ""
    if freed_bytes <= 0 and locked:
        return f"{name}: chưa xóa được{locked_note} (0 B)"
    if freed_bytes <= 0 and reason and status == "cleaned":
        return f"{name}: {reason}"
    if freed_bytes <= 0:
        return f"{name}: không có gì để xóa (0 B)"
    return f"{name}: đã xóa {freed_label}{locked_note}"


def format_clean_report_vi(result: Dict[str, Any]) -> str:
    deep_admin = bool(result.get("deep_admin"))
    deep_user = bool(result.get("deep_user_safe"))
    deep = deep_user or deep_admin
    if deep_admin:
        header = "Dọn sâu (cần Admin) hoàn tất."
    elif deep_user:
        header = "Dọn ổ C (không cần Admin) hoàn tất."
    else:
        header = "Dọn dẹp hoàn tất."
    freed_bytes = int(result.get("total_freed_bytes") or 0)
    files = int(result.get("total_deleted_files") or 0)
    lines = [
        header,
        f"Đã giải phóng thực sự: {format_freed_vi(freed_bytes)} ({files} tệp).",
    ]
    if not result.get("is_admin"):
        lines.append("Mục cần Admin đã được bỏ qua và không cộng vào số MB ở trên.")
    if deep:
        lines.append(format_free_space_line_vi(result))
    lines.append("")
    details = result.get("details") or {}
    order = result.get("detail_order") or [key for key in TARGET_ORDER if key in details]
    for key in order:
        detail = details.get(key)
        if isinstance(detail, dict) and detail.get("name"):
            lines.append("• " + format_target_line_vi(detail))
    skipped = result.get("skipped") or []
    reported = set(order)
    for item in skipped:
        if not isinstance(item, dict):
            continue
        if item.get("key") in reported:
            continue
        lines.append("• " + format_target_line_vi(item))
    return "\n".join(lines).strip()


def path_is_browser_profile_db(path: str) -> bool:
    """True nếu tệp là DB hồ sơ trình duyệt (cookie, đăng nhập, lịch sử)."""
    if not path:
        return False
    return os.path.basename(path).lower() in _BROWSER_DB_FILENAMES


def format_age_vi(age_days: int) -> str:
    days = max(0, int(age_days or 0))
    if days <= 0:
        return "hôm nay"
    if days == 1:
        return "1 ngày"
    return f"{days} ngày"


def _large_file_skip_reason(
    path: str,
    *,
    user_profile: str,
    local_app_data: str,
    system_root: str,
) -> str:
    """Lý do tiếng Việt nếu không được xóa. Chuỗi rỗng nghĩa là tệp được phép."""
    if not path:
        return "Đường dẫn trống — không xóa."
    if os.path.islink(path):
        return "Liên kết tượng trưng — không xóa."
    if path_is_forbidden(path):
        return PROTECTED_REASON_VI
    if path_is_too_broad(path, user_profile=user_profile, system_root=system_root):
        return TOO_BROAD_REASON_VI
    if user_profile and _is_onedrive_sync_path(path, user_profile):
        return SYNC_ROOT_REASON_VI
    if path_has_sensitive_data(path) or path_is_browser_profile_db(path):
        return "Cơ sở dữ liệu trình duyệt hoặc dữ liệu hồ sơ — không xóa."
    if system_root and _within_root(path, system_root):
        return PROTECTED_REASON_VI
    under_profile = bool(user_profile) and _within_root(path, user_profile)
    under_local = bool(local_app_data) and _within_root(path, local_app_data)
    if not under_profile and not under_local:
        return "Nằm ngoài hồ sơ người dùng — không xóa."
    if os.path.isdir(path):
        return "Chỉ xóa tệp, không xóa thư mục."
    if not os.path.isfile(path):
        return "Tệp không còn trên đĩa."
    return ""


def _large_scan_skip_dir(path: str, *, user_profile: str) -> bool:
    name = os.path.basename(path).lower()
    if name in _BLOCKED_DIR_NAMES or name in _LARGE_SKIP_DIR_NAMES:
        return True
    if path_is_forbidden(path) or path_has_sensitive_data(path):
        return True
    if user_profile and _is_onedrive_sync_path(path, user_profile):
        return True
    return False


def large_file_scan_roots(
    environ: Optional[Dict[str, str]] = None,
    *,
    include_local_appdata: bool = False,
) -> List[str]:
    """Hồ sơ người dùng, và LocalAppData khi người dùng bật thêm."""
    user_profile = _env(environ, "USERPROFILE")
    local_app_data = _env(environ, "LOCALAPPDATA")
    roots: List[str] = []
    if (
        user_profile
        and _exists(user_profile)
        and os.path.isdir(user_profile)
        and not os.path.islink(user_profile)
        and not path_is_forbidden(user_profile)
    ):
        roots.append(user_profile)
    if (
        include_local_appdata
        and local_app_data
        and _exists(local_app_data)
        and os.path.isdir(local_app_data)
        and not os.path.islink(local_app_data)
        and not path_is_forbidden(local_app_data)
    ):
        roots.append(local_app_data)
    return _dedupe(roots)


def scan_large_user_files(
    *,
    environ: Optional[Dict[str, str]] = None,
    min_bytes: Optional[int] = None,
    min_age_days: int = 0,
    include_local_appdata: bool = False,
    max_depth: int = DEFAULT_LARGE_FILE_MAX_DEPTH,
    max_results: int = DEFAULT_LARGE_FILE_MAX_RESULTS,
    max_visited: int = DEFAULT_LARGE_FILE_MAX_VISITED,
    max_seconds: float = DEFAULT_LARGE_FILE_MAX_SECONDS,
    now_ts: Optional[float] = None,
    progress_callback: Optional[Callable[[str, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    """
    Tìm tệp lớn trong hồ sơ người dùng. Không xóa.
    Mỗi dòng selected=False — người dùng phải chọn rồi xác nhận mới xóa.
    """
    try:
        threshold = int(DEFAULT_LARGE_FILE_MIN_BYTES if min_bytes is None else min_bytes)
    except (TypeError, ValueError):
        threshold = DEFAULT_LARGE_FILE_MIN_BYTES
    if threshold <= 0:
        threshold = DEFAULT_LARGE_FILE_MIN_BYTES
    try:
        age_limit = int(min_age_days or 0)
    except (TypeError, ValueError):
        age_limit = 0
    if age_limit < 0:
        age_limit = 0
    depth_cap = max(1, int(max_depth or DEFAULT_LARGE_FILE_MAX_DEPTH))
    result_cap = max(1, int(max_results or DEFAULT_LARGE_FILE_MAX_RESULTS))
    visit_cap = max(1, int(max_visited or DEFAULT_LARGE_FILE_MAX_VISITED))
    try:
        time_cap = float(max_seconds if max_seconds is not None else DEFAULT_LARGE_FILE_MAX_SECONDS)
    except (TypeError, ValueError):
        time_cap = DEFAULT_LARGE_FILE_MAX_SECONDS
    if time_cap <= 0:
        time_cap = DEFAULT_LARGE_FILE_MAX_SECONDS

    user_profile = _env(environ, "USERPROFILE")
    local_app_data = _env(environ, "LOCALAPPDATA")
    system_root = _env(environ, "SystemRoot") or _env(environ, "SYSTEMROOT")
    moment = time.time() if now_ts is None else float(now_ts)
    roots = large_file_scan_roots(environ, include_local_appdata=include_local_appdata)
    found: List[Dict[str, Any]] = []
    visited = 0
    truncated = False
    truncate_reason = ""
    started = time.monotonic()
    seen_dirs = set()
    cancelled = False

    def _report(pct: int) -> None:
        if not progress_callback:
            return
        try:
            progress_callback(
                f"Đang quét… đã xem {visited} tệp, thấy {len(found)} tệp lớn.",
                max(0, min(99, int(pct))),
            )
        except Exception:
            pass

    for root in roots:
        if cancelled or truncated:
            break
        try:
            root_key = os.path.normcase(os.path.abspath(root))
        except (OSError, ValueError):
            continue
        stack = [(root, 0)]
        while stack:
            if cancel_check and cancel_check():
                cancelled = True
                truncate_reason = "Đã dừng quét theo yêu cầu."
                truncated = True
                break
            if time.monotonic() - started >= time_cap:
                truncated = True
                truncate_reason = "Đã dừng sớm để giao diện không bị đơ (hết thời gian quét)."
                break
            current, depth = stack.pop()
            try:
                current_key = os.path.normcase(os.path.abspath(current))
            except (OSError, ValueError):
                continue
            if current_key in seen_dirs:
                continue
            seen_dirs.add(current_key)
            if current != root and _large_scan_skip_dir(current, user_profile=user_profile):
                continue
            if path_is_forbidden(current) or (user_profile and _is_onedrive_sync_path(current, user_profile)):
                continue
            try:
                names = list(os.listdir(current))
            except OSError:
                continue
            for name in names:
                child = os.path.join(current, name)
                if os.path.islink(child):
                    continue
                try:
                    is_dir = os.path.isdir(child)
                except OSError:
                    continue
                if is_dir:
                    if depth >= depth_cap:
                        continue
                    if _large_scan_skip_dir(child, user_profile=user_profile):
                        continue
                    stack.append((child, depth + 1))
                    continue
                if not os.path.isfile(child):
                    continue
                visited += 1
                if visited > visit_cap:
                    truncated = True
                    truncate_reason = "Đã dừng sớm vì đã xem quá nhiều tệp."
                    break
                if visited % 250 == 0:
                    _report(int(visited * 100 / visit_cap))
                if _large_file_skip_reason(
                    child,
                    user_profile=user_profile,
                    local_app_data=local_app_data,
                    system_root=system_root,
                ):
                    continue
                size = _file_size(child)
                if size < threshold:
                    continue
                if age_limit > 0 and not file_is_old_enough(child, age_limit, moment):
                    continue
                try:
                    mtime = float(os.path.getmtime(child))
                except OSError:
                    continue
                age_days = max(0, int((moment - mtime) // 86400))
                found.append({
                    "path": child,
                    "name": name,
                    "size_bytes": size,
                    "size_label_vi": format_freed_vi(size),
                    "age_days": age_days,
                    "age_label_vi": format_age_vi(age_days),
                    "mtime": mtime,
                    "selected": False,
                })
            if truncated:
                break

    found.sort(key=lambda row: (-int(row["size_bytes"]), str(row["path"]).lower()))
    if len(found) > result_cap:
        found = found[:result_cap]
        truncated = True
        if not truncate_reason:
            truncate_reason = "Chỉ hiện các tệp lớn nhất trong giới hạn danh sách."
    if progress_callback:
        try:
            progress_callback(f"Quét xong: {len(found)} tệp lớn. Chưa xóa tệp nào.", 100)
        except Exception:
            pass
    return {
        "files": found,
        "truncated": truncated,
        "cancelled": cancelled,
        "truncate_reason_vi": truncate_reason,
        "visited_files": visited,
        "roots": roots,
        "min_bytes": threshold,
        "min_age_days": age_limit,
        "include_local_appdata": bool(include_local_appdata),
        "deleted": False,
    }


def delete_large_files(
    paths: Sequence[str],
    *,
    environ: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Xóa đúng các tệp được truyền vào. Quét không gọi hàm này."""
    user_profile = _env(environ, "USERPROFILE")
    local_app_data = _env(environ, "LOCALAPPDATA")
    system_root = _env(environ, "SystemRoot") or _env(environ, "SYSTEMROOT")
    freed = 0
    deleted_files = 0
    skipped_locked = 0
    deleted: List[str] = []
    skipped: List[Dict[str, str]] = []
    seen = set()
    for raw in paths or []:
        path = str(raw or "")
        try:
            key = os.path.normcase(os.path.abspath(path)) if path else ""
        except (OSError, ValueError):
            key = path
        if not key or key in seen:
            continue
        seen.add(key)
        reason = _large_file_skip_reason(
            path,
            user_profile=user_profile,
            local_app_data=local_app_data,
            system_root=system_root,
        )
        if reason:
            skipped.append({"path": path, "reason": reason})
            continue
        part = try_delete_file(path)
        if int(part.get("deleted_files") or 0) and int(part.get("freed_bytes") or 0) >= 0 and not os.path.exists(path):
            freed += int(part.get("freed_bytes") or 0)
            deleted_files += 1
            deleted.append(path)
            continue
        if int(part.get("skipped_locked") or 0):
            skipped_locked += 1
            skipped.append({"path": path, "reason": LOCKED_REASON_VI})
            continue
        skipped.append({"path": path, "reason": "Không xóa được tệp này. Không tính dung lượng."})
    lines = [
        f"Đã xóa {deleted_files} tệp ({format_freed_vi(freed)}).",
    ]
    if skipped_locked:
        lines.append(f"Bỏ qua {skipped_locked} tệp đang khóa — không tính phần chưa xóa.")
    other = len(skipped) - skipped_locked
    if other > 0:
        lines.append(f"Bỏ qua {other} tệp không an toàn hoặc không còn trên đĩa.")
    if deleted_files == 0 and not skipped:
        lines = ["Chưa chọn tệp nào. Không có gì bị xóa."]
    return {
        "freed_bytes": freed,
        "deleted_files": deleted_files,
        "skipped_locked": skipped_locked,
        "deleted": deleted,
        "skipped": skipped,
        "report_vi": " ".join(lines),
    }


def _bytes_to_gb(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(int(value) / (1024 ** 3), 3)
    except (TypeError, ValueError):
        return None


def _history_timestamp(now_ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(float(now_ts)))


def _display_history_timestamp(timestamp: str) -> str:
    text = str(timestamp or "").strip()
    try:
        parsed = time.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return text or "không rõ thời điểm"
    return time.strftime("%d/%m/%Y %H:%M", parsed)


def _gb_label(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "?"
    if number >= 10:
        return f"{number:.1f}"
    return f"{number:.2f}"


def clean_history_file(path: Optional[str] = None) -> str:
    if path:
        return path
    override = os.environ.get(CLEAN_HISTORY_ENV, "").strip()
    if override:
        return override
    from config_manager import user_data_dir
    return os.path.join(user_data_dir(), "c_drive_clean_history.json")


def _skipped_admin_count(result: Dict[str, Any]) -> int:
    skipped = result.get("skipped") or []
    count = 0
    if isinstance(skipped, list) and skipped:
        for item in skipped:
            if isinstance(item, dict) and item.get("needs_admin"):
                count += 1
        return count
    details = result.get("details") or {}
    if isinstance(details, dict):
        for detail in details.values():
            if (
                isinstance(detail, dict)
                and detail.get("status") == "skipped"
                and detail.get("needs_admin")
            ):
                count += 1
    return count


def history_record_from_result(
    result: Dict[str, Any],
    *,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    moment = time.time() if now_ts is None else float(now_ts)
    data = result if isinstance(result, dict) else {}
    return {
        "timestamp": _history_timestamp(moment),
        "freed_bytes": max(0, int(data.get("total_freed_bytes") or 0)),
        "free_gb_before": _bytes_to_gb(data.get("free_bytes_before")),
        "free_gb_after": _bytes_to_gb(data.get("free_bytes_after")),
        "skipped_admin_count": _skipped_admin_count(data),
        "deep_admin": bool(data.get("deep_admin")),
    }


def load_clean_history(path: Optional[str] = None) -> List[Dict[str, Any]]:
    file_path = clean_history_file(path)
    if not file_path or not os.path.isfile(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            freed = max(0, int(item.get("freed_bytes") or 0))
        except (TypeError, ValueError):
            freed = 0
        try:
            skipped = max(0, int(item.get("skipped_admin_count") or 0))
        except (TypeError, ValueError):
            skipped = 0
        rows.append({
            "timestamp": str(item.get("timestamp") or ""),
            "freed_bytes": freed,
            "free_gb_before": item.get("free_gb_before"),
            "free_gb_after": item.get("free_gb_after"),
            "skipped_admin_count": skipped,
            "deep_admin": bool(item.get("deep_admin")),
        })
    return rows[:CLEAN_HISTORY_KEEP]


def append_clean_history(
    result: Dict[str, Any],
    *,
    path: Optional[str] = None,
    now_ts: Optional[float] = None,
    limit: int = CLEAN_HISTORY_KEEP,
) -> List[Dict[str, Any]]:
    """Ghi một lần dọn ổ C vào JSON cục bộ. Giữ tối đa `limit` bản mới nhất."""
    keep = max(1, int(limit or CLEAN_HISTORY_KEEP))
    record = history_record_from_result(result, now_ts=now_ts)
    rows = [record] + load_clean_history(path)
    rows = rows[:keep]
    file_path = clean_history_file(path)
    payload = {"version": 1, "items": rows}
    try:
        parent = os.path.dirname(os.path.abspath(file_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        temporary = file_path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, file_path)
    except OSError:
        return rows
    return rows


def format_clean_history_line_vi(row: Dict[str, Any]) -> str:
    freed = format_freed_vi(int(row.get("freed_bytes") or 0))
    before = row.get("free_gb_before")
    after = row.get("free_gb_after")
    if before is not None and after is not None:
        space = f"trống {_gb_label(before)} → {_gb_label(after)} GB"
    else:
        space = "không đọc được dung lượng trống"
    skipped = int(row.get("skipped_admin_count") or 0)
    prefix = "dọn sâu Admin — " if row.get("deep_admin") else ""
    return (
        f"{_display_history_timestamp(str(row.get('timestamp') or ''))} — "
        f"{prefix}đã xóa {freed} — {space} — bỏ qua {skipped} mục cần Admin"
    )


def format_clean_history_vi(rows: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    items = list(rows or [])
    if not items:
        return "Chưa có lần dọn ổ C nào trên máy này."
    return "\n".join("• " + format_clean_history_line_vi(row) for row in items[:CLEAN_HISTORY_KEEP])
