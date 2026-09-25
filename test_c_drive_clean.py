"""
Dọn ổ C không cần Admin: chọn mục, bỏ qua mục Admin, cộng byte thật.
Chạy được trên Linux CI — không cần quyền Administrator.
"""
import inspect
import os
import shutil
import sys
import tempfile
import types

if sys.platform != "win32" and "winreg" not in sys.modules:
    winreg = types.ModuleType("winreg")
    winreg.HKEY_CURRENT_USER = 1
    winreg.HKEY_LOCAL_MACHINE = 2
    winreg.KEY_READ = 0
    winreg.KEY_WRITE = 0
    winreg.KEY_SET_VALUE = 0
    winreg.KEY_ALL_ACCESS = 0
    winreg.REG_DWORD = 4
    winreg.REG_SZ = 1
    winreg.KEY_WOW64_64KEY = 0x0100
    winreg.error = OSError
    winreg.OpenKey = lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError("winreg stub"))
    winreg.CreateKey = winreg.OpenKey
    winreg.CloseKey = lambda *_a, **_k: None
    winreg.QueryValueEx = winreg.OpenKey
    winreg.SetValueEx = winreg.OpenKey
    winreg.DeleteValue = winreg.OpenKey
    winreg.EnumKey = winreg.OpenKey
    sys.modules["winreg"] = winreg

from app_meta import APP_VERSION
from config_manager import DEFAULT_CONFIG
from core.c_drive_clean import (
    ADMIN_DEEP_DISABLED_VI,
    ADMIN_SKIP_REASON_VI,
    DEFAULT_MIN_CLEAN_MB,
    SYNC_ROOT_REASON_VI,
    LowDiskToastGate,
    TARGET_CATALOG,
    TARGET_GROUPS,
    TARGET_ORDER,
    category_offered_by_default,
    format_scan_preview_vi,
    normalize_min_clean_mb,
    preview_rows_for_display,
    append_clean_history,
    build_low_disk_notice,
    build_target_paths,
    clean_one_path,
    _under_drive,
    default_component_cleanup,
    default_hibernate_off,
    default_target_flags,
    delete_large_files,
    _EmptyDirBudget,
    estimate_reclaimable,
    format_clean_history_line_vi,
    format_clean_history_vi,
    is_disk_space_low,
    is_process_elevated,
    list_empty_directories,
    load_clean_history,
    path_is_forbidden,
    path_is_game_install,
    resolve_clean_plan,
    scan_large_user_files,
)
from core.cleaner import JunkCleaner


def _write(path, payload: bytes):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(payload)


def _tree(root):
    """Hồ sơ giả: alice là người dùng hiện tại, bob là người khác."""
    home = os.path.join(root, "Users", "alice")
    bob = os.path.join(root, "Users", "bob")
    local = os.path.join(home, "AppData", "Local")
    roaming = os.path.join(home, "AppData", "Roaming")
    windows = os.path.join(root, "Windows")
    temp = os.path.join(local, "Temp")
    _write(os.path.join(temp, "keep.tmp"), b"U" * 100)
    _write(os.path.join(temp, "WinSxS", "must-stay.bin"), b"NO" * 20)
    _write(os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache", "a.bin"), b"C" * 40)
    _write(os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cookies"), b"SECRET")
    _write(os.path.join(local, "Microsoft", "Windows", "Explorer", "thumbcache_32.db"), b"T" * 30)
    _write(os.path.join(local, "Microsoft", "Windows", "Explorer", "notes.txt"), b"keep-me")
    _write(os.path.join(local, "CrashDumps", "app.dmp"), b"D" * 10)
    _write(os.path.join(windows, "Temp", "sys.tmp"), b"S" * 80)
    _write(os.path.join(windows, "SoftwareDistribution", "Download", "upd.cab"), b"W" * 60)
    _write(os.path.join(windows, "WinSxS", "pending.manifest"), b"X" * 50)
    _write(os.path.join(windows, "System32", "note.txt"), b"Y" * 50)
    _write(os.path.join(home, "Downloads", "old.bin"), b"O" * 70)
    _write(os.path.join(home, "Downloads", "Notes", "ancient.txt"), b"A" * 15)
    _write(os.path.join(home, "Downloads", "new.bin"), b"N" * 25)
    _write(os.path.join(bob, "AppData", "Local", "Temp", "bob.tmp"), b"B" * 90)
    _write(os.path.join(bob, "AppData", "Local", "Google", "Chrome", "User Data", "Default", "Cache", "bob.bin"), b"Z" * 33)
    now = 1_700_000_000
    os.utime(os.path.join(home, "Downloads", "old.bin"), (now - 40 * 86400, now - 40 * 86400))
    os.utime(os.path.join(home, "Downloads", "Notes", "ancient.txt"), (now - 40 * 86400, now - 40 * 86400))
    os.utime(os.path.join(home, "Downloads", "new.bin"), (now - 86400, now - 86400))
    env = {
        "USERPROFILE": home,
        "LOCALAPPDATA": local,
        "APPDATA": roaming,
        "TEMP": temp,
        "SystemRoot": windows,
    }
    return {
        "env": env,
        "home": home,
        "bob": bob,
        "temp": temp,
        "local": local,
        "windows": windows,
        "now": now,
    }


def test_version_stays_387():
    assert APP_VERSION == "3.8.7"


def test_catalog_defaults_match_config():
    flags = default_target_flags()
    assert DEFAULT_CONFIG["targets"] == flags
    assert "toolchain_caches" in TARGET_ORDER
    assert flags["toolchain_caches"] is True
    assert flags["nuget_packages"] is False
    assert flags["gradle_caches"] is False
    assert flags["cargo_cache"] is False
    assert flags["user_temp"] is True
    assert flags["thumbnail_cache"] is True
    assert flags["browser_cache"] is True
    assert flags["downloads_old"] is False
    assert flags["recycle_bin"] is False
    assert TARGET_CATALOG["recycle_bin"]["default_enabled"] is False
    assert DEFAULT_CONFIG["c_drive_exclude_paths"] == []
    assert DEFAULT_CONFIG["downloads_old_min_days"] == 30
    assert flags["system_dumps"] is False
    assert flags["system_temp"] is True
    assert flags["windows_update"] is True
    assert TARGET_CATALOG["system_temp"]["needs_admin"] is True
    assert TARGET_CATALOG["user_temp"]["needs_admin"] is False
    assert TARGET_CATALOG["recycle_bin"]["scope"] == "user"
    assert DEFAULT_CONFIG["low_disk_free_gb"] == 10
    assert DEFAULT_CONFIG["low_disk_threshold_mode"] == "gb"
    assert is_process_elevated() is False


def test_paths_stay_inside_current_user_and_skip_protected():
    root = tempfile.mkdtemp(prefix="pca-paths-")
    try:
        info = _tree(root)
        paths = build_target_paths(info["env"])
        flat = [path for group in paths.values() for path in group]
        blob = "\n".join(flat)
        assert info["temp"] in paths["user_temp"]
        assert any(path.endswith(os.path.join("Default", "Cache")) for path in paths["browser_cache"])
        assert not any(path.endswith("Cookies") for path in flat)
        assert any(path.endswith("thumbcache_32.db") for path in paths["thumbnail_cache"])
        assert not any(path.endswith("notes.txt") for path in paths["thumbnail_cache"])
        assert any(path.endswith(os.path.join("Windows", "Temp")) for path in paths["system_temp"])
        assert any("SoftwareDistribution" in path and path.endswith("Download") for path in paths["windows_update"])
        assert "WinSxS" not in blob
        assert "System32" not in blob
        assert info["bob"] not in blob
        assert "bob.tmp" not in blob
        assert all(not path_is_forbidden(path) for path in flat)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_non_admin_skips_system_targets_and_counts_only_deleted_bytes():
    root = tempfile.mkdtemp(prefix="pca-clean-")
    try:
        info = _tree(root)
        enabled = {
            "user_temp": True,
            "system_temp": True,
            "windows_update": True,
            "browser_cache": True,
            "thumbnail_cache": True,
            "downloads_old": False,
            "recycle_bin": False,
        }
        scan = JunkCleaner.scan(
            enabled,
            is_admin=False,
            environ=info["env"],
            now_ts=info["now"],
        )
        assert scan["categories"]["system_temp"]["will_skip"] is True
        assert scan["categories"]["user_temp"]["will_skip"] is False
        assert scan["admin_only_bytes"] >= 80
        assert scan["total_bytes"] == 100 + 40 + 30
        assert scan["total_bytes"] < scan["admin_only_bytes"] + scan["total_bytes"]

        result = JunkCleaner.clean(
            enabled,
            is_admin=False,
            environ=info["env"],
            now_ts=info["now"],
        )
        assert result["total_freed_bytes"] == 100 + 40 + 30
        assert not os.path.exists(os.path.join(info["temp"], "keep.tmp"))
        assert os.path.exists(os.path.join(info["temp"], "WinSxS", "must-stay.bin"))
        assert os.path.exists(os.path.join(info["windows"], "Temp", "sys.tmp"))
        assert os.path.exists(os.path.join(info["windows"], "SoftwareDistribution", "Download", "upd.cab"))
        assert os.path.exists(os.path.join(info["windows"], "WinSxS", "pending.manifest"))
        assert os.path.exists(os.path.join(info["windows"], "System32", "note.txt"))
        assert os.path.exists(os.path.join(info["local"], "Microsoft", "Windows", "Explorer", "notes.txt"))
        assert os.path.exists(os.path.join(info["bob"], "AppData", "Local", "Temp", "bob.tmp"))
        assert result["details"]["system_temp"]["status"] == "skipped"
        assert result["details"]["system_temp"]["freed_bytes"] == 0
        assert ADMIN_SKIP_REASON_VI in result["details"]["system_temp"]["reason"]
        assert "Cần quyền Administrator" in result["report_vi"]
        assert "80" not in str(result["total_freed_bytes"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_admin_cleans_system_temp_and_counts_it():
    root = tempfile.mkdtemp(prefix="pca-admin-")
    try:
        info = _tree(root)
        result = JunkCleaner.clean(
            {"system_temp": True, "user_temp": False, "windows_update": False},
            is_admin=True,
            environ=info["env"],
        )
        assert not os.path.exists(os.path.join(info["windows"], "Temp", "sys.tmp"))
        assert os.path.exists(os.path.join(info["temp"], "keep.tmp"))
        assert result["total_freed_bytes"] == 80
        assert result["details"]["system_temp"]["status"] == "cleaned"
        assert os.path.exists(os.path.join(info["windows"], "WinSxS", "pending.manifest"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_deep_user_safe_maximizes_caches_but_not_downloads_or_admin():
    root = tempfile.mkdtemp(prefix="pca-deep-")
    try:
        info = _tree(root)
        calls = []

        def _recycle():
            calls.append("recycle")
            return {"success": False, "freed_bytes": 99999, "items": 4, "status": "error", "reason": "fail"}

        result = JunkCleaner.clean(
            {
                "user_temp": False,
                "browser_cache": False,
                "system_temp": True,
                "windows_update": True,
                "downloads_old": False,
                "recycle_bin": False,
            },
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
            now_ts=info["now"],
            downloads_min_age_days=30,
            recycle_empty=_recycle,
        )
        assert calls == []
        assert not os.path.exists(os.path.join(info["temp"], "keep.tmp"))
        assert not os.path.exists(os.path.join(info["local"], "Google", "Chrome", "User Data", "Default", "Cache", "a.bin"))
        assert os.path.exists(os.path.join(info["home"], "Downloads", "old.bin"))
        assert os.path.exists(os.path.join(info["windows"], "Temp", "sys.tmp"))
        assert result["details"]["system_temp"]["freed_bytes"] == 0
        # temp 100 + cache 40 + thumbnail 30 + crash dump 10 (mục user-safe mặc định)
        assert result["total_freed_bytes"] == 180
        assert result["deep_user_safe"] is True
        assert "Dọn ổ C (không cần Admin)" in result["report_vi"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_downloads_old_only_when_enabled_and_only_old_files():
    root = tempfile.mkdtemp(prefix="pca-dl-")
    try:
        info = _tree(root)
        off = JunkCleaner.clean(
            {"downloads_old": False, "user_temp": False},
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
            now_ts=info["now"],
        )
        assert os.path.exists(os.path.join(info["home"], "Downloads", "old.bin"))
        assert off["total_freed_bytes"] == 180
        assert "downloads_old" not in off["details"] or off["details"]["downloads_old"].get("freed_bytes", 0) == 0

        # user temp already gone; run downloads alone
        result = JunkCleaner.clean(
            {"downloads_old": True},
            is_admin=False,
            environ=info["env"],
            now_ts=info["now"],
            downloads_min_age_days=30,
        )
        assert not os.path.exists(os.path.join(info["home"], "Downloads", "old.bin"))
        assert not os.path.exists(os.path.join(info["home"], "Downloads", "Notes", "ancient.txt"))
        assert os.path.isdir(os.path.join(info["home"], "Downloads", "Notes"))
        assert os.path.exists(os.path.join(info["home"], "Downloads", "new.bin"))
        assert result["total_freed_bytes"] == 70 + 15
        assert result["details"]["downloads_old"]["freed_bytes"] == 85
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_locked_file_is_not_counted(monkeypatch=None):
    root = tempfile.mkdtemp(prefix="pca-lock-")
    try:
        info = _tree(root)
        locked = os.path.join(info["temp"], "locked.tmp")
        _write(locked, b"L" * 55)
        real_unlink = os.unlink

        def flaky(path, *args, **kwargs):
            if str(path).endswith("locked.tmp"):
                raise PermissionError("locked")
            return real_unlink(path, *args, **kwargs)

        import core.c_drive_clean as mod
        original = mod.os.unlink
        mod.os.unlink = flaky
        try:
            result = JunkCleaner.clean(
                {"user_temp": True},
                is_admin=False,
                environ=info["env"],
            )
        finally:
            mod.os.unlink = original
        assert os.path.exists(locked)
        assert not os.path.exists(os.path.join(info["temp"], "keep.tmp"))
        assert result["total_freed_bytes"] == 100
        assert result["details"]["user_temp"]["skipped_locked"] >= 1
        assert "khóa" in result["report_vi"].lower() or result["details"]["user_temp"]["freed_bytes"] == 100
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_partial_directory_delete_counts_only_removed_bytes():
    root = tempfile.mkdtemp(prefix="pca-partial-")
    try:
        info = _tree(root)
        sub = os.path.join(info["temp"], "sub")
        _write(os.path.join(sub, "a.txt"), b"A" * 100)
        _write(os.path.join(sub, "b.txt"), b"B" * 50)
        import shutil as shutil_mod

        real_rmtree = shutil_mod.rmtree

        def partial(path, onerror=None):
            target = os.path.join(path, "a.txt")
            if os.path.exists(target):
                os.remove(target)
            else:
                real_rmtree(path, onerror=onerror)

        shutil_mod.rmtree = partial
        try:
            result = JunkCleaner.clean(
                {"user_temp": True},
                is_admin=False,
                environ=info["env"],
            )
        finally:
            shutil_mod.rmtree = real_rmtree
        assert os.path.exists(os.path.join(sub, "b.txt"))
        assert not os.path.exists(os.path.join(sub, "a.txt"))
        # keep.tmp (100) + a.txt (100); b.txt (50) remains. WinSxS child untouched.
        assert result["total_freed_bytes"] == 200
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_symlink_is_unlinked_without_deleting_the_target():
    root = tempfile.mkdtemp(prefix="pca-link-")
    try:
        info = _tree(root)
        outside = os.path.join(root, "outside.bin")
        _write(outside, b"P" * 80)
        link = os.path.join(info["temp"], "escape")
        os.symlink(outside, link)
        result = JunkCleaner.clean(
            {"user_temp": True},
            is_admin=False,
            environ=info["env"],
        )
        assert os.path.exists(outside)
        assert os.path.getsize(outside) == 80
        assert not os.path.lexists(link)
        assert result["total_freed_bytes"] == 100
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_failed_recycle_bin_does_not_invent_freed_bytes():
    root = tempfile.mkdtemp(prefix="pca-rb-")
    try:
        info = _tree(root)

        def liar():
            return {"success": False, "freed_bytes": 999999, "items": 12, "status": "error", "reason": "từ chối"}

        result = JunkCleaner.clean(
            {"recycle_bin": True, "user_temp": False},
            is_admin=False,
            environ=info["env"],
            recycle_empty=liar,
        )
        assert result["total_freed_bytes"] == 0
        assert result["details"]["recycle_bin"]["freed_bytes"] == 0
        assert result["details"]["recycle_bin"]["status"] == "error"
        assert os.path.exists(os.path.join(info["temp"], "keep.tmp"))

        def ok():
            return {"success": True, "freed_bytes": 128, "items": 2}

        ok_res = JunkCleaner.clean(
            {"recycle_bin": True, "user_temp": False},
            is_admin=False,
            environ=info["env"],
            recycle_empty=ok,
        )
        assert ok_res["total_freed_bytes"] == 128
        assert ok_res["total_deleted_files"] == 2
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_low_disk_threshold_and_toast_cooldown():
    assert is_disk_space_low(0, 0) is False
    assert is_disk_space_low(9, 256, min_free_gb=10, mode="gb") is True
    assert is_disk_space_low(12, 256, min_free_gb=10, mode="gb") is False
    assert is_disk_space_low(50, 100, min_free_percent=10, mode="percent") is False
    assert is_disk_space_low(5, 100, min_free_percent=10, mode="percent") is True
    assert is_disk_space_low(50, 1000, min_free_gb=10, min_free_percent=10, mode="either") is True
    notice = build_low_disk_notice(
        {"free_gb": 4.5, "total_gb": 128},
        {"low_disk_warn_enabled": True, "low_disk_free_gb": 10, "low_disk_threshold_mode": "gb"},
    )
    assert notice is not None
    assert "Dọn ổ C (không cần Admin)" in notice["message"]
    assert notice["free_gb"] == 4.5
    assert build_low_disk_notice({"free_gb": 40, "total_gb": 128}, {"low_disk_free_gb": 10}) is None
    assert build_low_disk_notice({"free_gb": 1, "total_gb": 128}, {"low_disk_warn_enabled": False}) is None

    gate = LowDiskToastGate()
    assert gate.allow(1000, cooldown_sec=1800) is True
    assert gate.allow(1100, cooldown_sec=1800) is False
    assert gate.allow(2800, cooldown_sec=1800) is True


def _extended_tree(root):
    """Cache/log phổ biến trên máy Windows, cộng các đường dẫn không được đụng."""
    home = os.path.join(root, "Users", "alice")
    local = os.path.join(home, "AppData", "Local")
    roaming = os.path.join(home, "AppData", "Roaming")
    windows = os.path.join(root, "Windows")

    def put(rel_parts, payload, base=local):
        path = os.path.join(base, *rel_parts)
        _write(path, payload)
        return path

    files = {
        "coccoc_cache": put(["CocCoc", "Browser", "User Data", "Default", "Cache", "a.bin"], b"A" * 10),
        "coccoc_cookies": put(["CocCoc", "Browser", "User Data", "Default", "Cookies"], b"SECRET"),
        "coccoc_sw": put(
            ["CocCoc", "Browser", "User Data", "Default", "Service Worker", "CacheStorage", "sw.bin"],
            b"S" * 8,
        ),
        "coccoc_sw_db": put(
            ["CocCoc", "Browser", "User Data", "Default", "Service Worker", "Database", "db.bin"],
            b"D" * 9,
        ),
        "coccoc_idb": put(
            ["CocCoc", "Browser", "User Data", "Default", "IndexedDB", "idb.bin"],
            b"I" * 7,
        ),
        "webview_cache": put(
            ["Contoso", "Widget", "EBWebView", "Default", "Cache", "c.bin"],
            b"W" * 11,
        ),
        "webview_sw": put(
            ["Contoso", "Widget", "EBWebView", "Default", "Service Worker", "CacheStorage", "sw2.bin"],
            b"E" * 6,
        ),
        "webview_idb": put(
            ["Contoso", "Widget", "EBWebView", "Default", "IndexedDB", "secret.bin"],
            b"X" * 4,
        ),
        "spotify": put(["Spotify", "Browser", "Cache", "s.bin"], b"P" * 12),
        "spotify_storage": put(["Spotify", "Storage", "offline.bin"], b"M" * 20),
        "slack": put(["Slack", "Cache", "sl.bin"], b"K" * 13, roaming),
        "zoom": put(["Zoom", "logs", "z.log"], b"Z" * 3, roaming),
        "notion": put(["Notion", "Cache", "n.bin"], b"N" * 4, roaming),
        "capcut": put(["CapCut", "User Data", "Cache", "cc.bin"], b"C" * 15),
        "capcut_project": put(["CapCut", "User Data", "Projects", "draft.bin"], b"R" * 40),
        "idea": put(["JetBrains", "IntelliJIdea2024.3", "caches", "idea.bin"], b"J" * 16),
        "idea_index": put(["JetBrains", "IntelliJIdea2024.3", "index", "idx.bin"], b"Q" * 17),
        "studio": put(["Google", "AndroidStudio2024.2", "caches", "as.bin"], b"G" * 18),
        "studio_plugins": put(["Google", "AndroidStudio2024.2", "plugins", "plug.bin"], b"U" * 19),
        "font": put(["Microsoft", "FontCache", "font.dat"], b"F" * 6),
        "fonts_user": put(["Microsoft", "Windows", "Fonts", "myfont.ttf"], b"T" * 14),
        "explorer_cache": put(["Microsoft", "Windows", "Caches", "shell.db"], b"H" * 7),
        "shell_temp": put(
            ["Packages", "Microsoft.Windows.ShellExperienceHost_abc", "TempState", "t.bin"],
            b"Y" * 5,
        ),
        "shell_local": put(
            ["Packages", "Microsoft.Windows.ShellExperienceHost_abc", "LocalState", "keep.bin"],
            b"L" * 21,
        ),
        "store_temp": put(
            ["Packages", "Microsoft.WindowsStore_8wekyb3d8bbwe", "TempState", "st.bin"],
            b"B" * 9,
        ),
        "store_local": put(
            ["Packages", "Microsoft.WindowsStore_8wekyb3d8bbwe", "LocalState", "keep2.bin"],
            b"V" * 22,
        ),
        "office_web": put(["Microsoft", "Office", "16.0", "WebServiceCache", "ws.bin"], b"O" * 8),
        "office_file": put(["Microsoft", "Office", "16.0", "OfficeFileCache", "pending.docx"], b"D" * 30),
        "onedrive_log": put(["Microsoft", "OneDrive", "logs", "od.log"], b"L" * 2),
        "onedrive_sync": put(["OneDrive", "doc.txt"], b"S" * 50, home),
        "poison": put(["WinSxS", "EBWebView", "Default", "Cache", "poison.bin"], b"P" * 99),
        "sys_temp": put(["Temp", "sys.tmp"], b"S" * 80, windows),
        "download": put(["Downloads", "old.bin"], b"O" * 70, home),
    }
    env = {
        "USERPROFILE": home,
        "LOCALAPPDATA": local,
        "APPDATA": roaming,
        "TEMP": os.path.join(local, "Temp"),
        "SystemRoot": windows,
    }
    os.makedirs(env["TEMP"], exist_ok=True)
    return {"env": env, "home": home, "windows": windows, "files": files}


def _path_parts(path):
    return [part.lower() for part in os.path.normpath(path).split(os.sep) if part]


def test_expanded_user_safe_paths_scan_without_deleting():
    root = tempfile.mkdtemp(prefix="pca-ext-")
    try:
        info = _extended_tree(root)
        paths = build_target_paths(info["env"])
        flat = [path for group in paths.values() for path in group]
        joined = "\n".join(flat).lower()

        assert any(path.endswith(os.path.join("Default", "Cache")) and "coccoc" in path.lower() for path in paths["browser_cache"])
        assert any("cachestorage" in path.lower() for path in paths["browser_cache"])
        assert any(path.endswith(os.path.join("EBWebView", "Default", "Cache")) for path in paths["browser_cache"])
        assert any(path.endswith(os.path.join("Spotify", "Browser", "Cache")) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("Slack", "Cache")) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("Zoom", "logs")) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("Notion", "Cache")) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("CapCut", "User Data", "Cache")) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("IntelliJIdea2024.3", "caches")) for path in paths["app_caches"])
        assert any("androidstudio2024.2" in path.lower() and path.endswith("caches") for path in paths["app_caches"])
        assert any(path.endswith("FontCache") for path in paths["shell_font_cache"])
        assert any(path.endswith(os.path.join("Windows", "Caches")) for path in paths["shell_font_cache"])
        assert any(path.endswith("TempState") and "ShellExperienceHost" in path for path in paths["shell_font_cache"])
        assert any(path.endswith("TempState") and "WindowsStore" in path for path in paths["store_cache"])
        assert any(path.endswith("WebServiceCache") for path in paths["office_cache"])
        assert any(path.endswith(os.path.join("OneDrive", "logs")) for path in paths["office_cache"])
        assert any(path.endswith("OfficeFileCache") for path in paths["office_file_cache"])

        for path in flat:
            parts = _path_parts(path)
            assert "winsxs" not in parts
            assert "system32" not in parts
            assert "indexeddb" not in parts
            assert "cookies" not in parts
            assert "database" not in parts
            assert "projects" not in parts
            assert "localstate" not in parts
            assert "fonts" not in parts
            assert "index" not in parts
            assert "plugins" not in parts
            assert not path_is_forbidden(path)
        assert "offline.bin" not in joined
        assert info["files"]["onedrive_sync"].lower() not in joined
        assert "doc.txt" not in joined
        assert TARGET_CATALOG["shell_font_cache"]["needs_admin"] is False
        assert TARGET_CATALOG["office_cache"]["needs_admin"] is False
        assert TARGET_CATALOG["store_cache"]["needs_admin"] is False
        assert TARGET_CATALOG["office_file_cache"]["needs_admin"] is False
        assert TARGET_CATALOG["office_file_cache"]["default_enabled"] is False
        assert TARGET_CATALOG["shell_font_cache"]["default_enabled"] is True

        flags = default_target_flags()
        flags["recycle_bin"] = False
        flags["downloads_old"] = False
        before = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        scan = estimate_reclaimable(
            flags,
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
        )
        after = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        assert before == after
        assert os.path.getsize(info["files"]["coccoc_cookies"]) == 6
        ready = {row["key"]: row for row in scan["targets"] if row["status"] == "ready"}
        skipped = {row["key"]: row for row in scan["targets"] if row["status"] == "skipped"}
        assert "office_file_cache" not in ready
        assert "downloads_old" not in ready
        assert skipped["system_temp"]["reclaimable_bytes"] == 0
        assert skipped["system_temp"]["size_bytes"] == 80
        assert ADMIN_SKIP_REASON_VI in skipped["system_temp"]["reason"]
        # 17 tệp cache/log an toàn, không gồm OfficeFileCache (30) hay temp hệ thống (80).
        assert scan["total_bytes"] == 153
        assert scan["total_files"] == 17
        assert "chưa xóa" in scan["preview_vi"].lower()
        assert "153 B" in scan["preview_vi"]

        opted = dict(flags)
        opted["office_file_cache"] = True
        opted_scan = estimate_reclaimable(
            opted,
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
        )
        assert opted_scan["total_bytes"] == 183
        assert os.path.exists(info["files"]["office_file"])

        calls = []

        def _recycle():
            calls.append("recycle")
            return {"success": True, "freed_bytes": 99999, "items": 1}

        result = JunkCleaner.clean(
            flags,
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
            recycle_empty=_recycle,
            disk_free_bytes=lambda: None,
        )
        assert calls == []
        assert result["total_freed_bytes"] == 153
        assert result["details"]["system_temp"]["status"] == "skipped"
        assert result["details"]["system_temp"]["freed_bytes"] == 0
        for key in (
            "coccoc_cookies", "coccoc_sw_db", "coccoc_idb", "webview_idb",
            "spotify_storage", "capcut_project", "idea_index", "studio_plugins",
            "fonts_user", "shell_local", "store_local", "office_file",
            "onedrive_sync", "poison", "sys_temp", "download",
        ):
            assert os.path.exists(info["files"][key]), key
        for key in (
            "coccoc_cache", "coccoc_sw", "webview_cache", "spotify", "slack",
            "capcut", "idea", "studio", "font", "office_web", "onedrive_log",
        ):
            assert not os.path.exists(info["files"][key]), key
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_forbidden_and_sync_root_stay_blocked():
    root = tempfile.mkdtemp(prefix="pca-block-")
    try:
        info = _extended_tree(root)
        home = info["home"]
        windows = info["windows"]
        broad = clean_one_path(home, clean_mode="contents", user_profile=home, system_root=windows)
        assert broad["too_broad"] == 1
        assert broad["freed_bytes"] == 0
        assert os.path.exists(info["files"]["onedrive_sync"])

        sync = clean_one_path(
            os.path.dirname(info["files"]["onedrive_sync"]),
            clean_mode="contents",
            user_profile=home,
            system_root=windows,
        )
        assert sync["sync_root"] == 1
        assert sync["freed_bytes"] == 0
        assert os.path.exists(info["files"]["onedrive_sync"])

        system = clean_one_path(windows, clean_mode="contents", user_profile=home, system_root=windows)
        assert system["too_broad"] == 1
        assert os.path.exists(info["files"]["sys_temp"])
        assert os.path.exists(info["files"]["poison"])

        protected = clean_one_path(
            os.path.join(windows, "WinSxS"),
            clean_mode="contents",
            user_profile=home,
            system_root=windows,
        )
        assert protected.get("protected") == 1
        assert protected["freed_bytes"] == 0

        direct = JunkCleaner.clean(
            {"user_temp": False, "system_temp": True, "windows_update": True},
            is_admin=False,
            environ=info["env"],
        )
        assert direct["details"]["system_temp"]["status"] == "skipped"
        assert direct["details"]["system_temp"]["freed_bytes"] == 0
        assert direct["total_freed_bytes"] == 0
        assert os.path.exists(info["files"]["sys_temp"])
        assert "OneDrive" in SYNC_ROOT_REASON_VI
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_deep_report_shows_free_space_delta_and_claimed_bytes():
    root = tempfile.mkdtemp(prefix="pca-free-")
    try:
        info = _tree(root)
        samples = {"i": 0, "values": [5000, 5100]}

        def reader():
            value = samples["values"][samples["i"]]
            samples["i"] += 1
            return value

        result = JunkCleaner.clean(
            {
                "user_temp": False,
                "browser_cache": False,
                "system_temp": True,
                "downloads_old": False,
                "recycle_bin": False,
            },
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
            disk_free_bytes=reader,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 1},
        )
        assert result["total_freed_bytes"] == 180
        assert result["free_bytes_before"] == 5000
        assert result["free_bytes_after"] == 5100
        assert result["free_bytes_delta"] == 100
        assert "trống trước" in result["report_vi"]
        assert "thay đổi thực tế +100 B" in result["report_vi"]
        assert "Byte đã xóa: 180 B" in result["report_vi"]

        unread = JunkCleaner.clean(
            {"user_temp": False, "recycle_bin": False, "downloads_old": False},
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1},
        )
        assert "Không đọc được dung lượng trống ổ C:" in unread["report_vi"]
        assert unread["free_bytes_delta"] is None

        plain_root = tempfile.mkdtemp(prefix="pca-plain-")
        try:
            plain_info = _tree(plain_root)
            plain = JunkCleaner.clean(
                {"user_temp": True},
                is_admin=False,
                deep_user_safe=False,
                environ=plain_info["env"],
                disk_free_bytes=reader,
            )
        finally:
            shutil.rmtree(plain_root, ignore_errors=True)
        assert plain["free_bytes_delta"] is None
        assert "trống trước" not in plain["report_vi"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _toolchain_tree(root):
    home = os.path.join(root, "Users", "alice")
    local = os.path.join(home, "AppData", "Local")
    roaming = os.path.join(home, "AppData", "Roaming")
    windows = os.path.join(root, "Windows")

    def put(parts, payload, base=local):
        path = os.path.join(base, *parts)
        _write(path, payload)
        return path

    files = {
        "yarn": put(["Yarn", "Cache", "a.bin"], b"Y" * 21),
        "yarn_poison": put(["Yarn", "Cache", "WinSxS", "poison.bin"], b"P" * 99),
        "nuget_http": put(["NuGet", "v3-cache", "b.bin"], b"H" * 22),
        "pip": put([".cache", "pip", "d.bin"], b"I" * 23, home),
        "npm": put([".npm", "_cacache", "e.bin"], b"N" * 24, home),
        "gradle_tmp": put([".gradle", "caches", "tmp", "f.bin"], b"T" * 25, home),
        "gradle_modules": put([".gradle", "caches", "modules-2", "g.bin"], b"G" * 200, home),
        "nuget_packages": put([".nuget", "packages", "h.bin"], b"U" * 300, home),
        "cargo_cache": put([".cargo", "registry", "cache", "i.bin"], b"C" * 26, home),
        "cargo_index": put([".cargo", "registry", "index", "j.bin"], b"X" * 400, home),
        "scoop_cache": put(["scoop", "cache", "k.bin"], b"S" * 27, home),
        "scoop_apps": put(["scoop", "apps", "app", "l.bin"], b"A" * 500, home),
        "choco": put(["Chocolatey", "cache", "m.bin"], b"O" * 28),
        "vs_component": put(
            ["Microsoft", "VisualStudio", "17.0_abc", "ComponentModelCache", "n.bin"],
            b"V" * 29,
        ),
        "vs_cache": put(["Microsoft", "VisualStudio", "17.0_abc", "Cache", "o.bin"], b"Q" * 7),
        "vs_ext": put(["Microsoft", "VisualStudio", "17.0_abc", "Extensions", "ext.bin"], b"E" * 600),
        "pnpm": put(["pnpm", "store", "p.bin"], b"M" * 700),
        "pnpm_home": put([".pnpm-store", "q.bin"], b"R" * 701, home),
        "desktop": put(["Desktop", "video.bin"], b"D" * 500, home),
    }
    env = {
        "USERPROFILE": home,
        "LOCALAPPDATA": local,
        "APPDATA": roaming,
        "TEMP": os.path.join(local, "Temp"),
        "SystemRoot": windows,
    }
    os.makedirs(env["TEMP"], exist_ok=True)
    return {"env": env, "home": home, "local": local, "windows": windows, "files": files}


def test_toolchain_caches_use_safe_defaults_and_skip_package_stores():
    root = tempfile.mkdtemp(prefix="pca-tool-")
    try:
        info = _toolchain_tree(root)
        paths = build_target_paths(info["env"])
        flat = [path for group in paths.values() for path in group]
        joined = "\n".join(flat).lower()
        assert any(path.endswith(os.path.join("Yarn", "Cache")) for path in paths["toolchain_caches"])
        assert any(path.endswith(os.path.join("NuGet", "v3-cache")) for path in paths["toolchain_caches"])
        assert any(path.endswith(os.path.join(".cache", "pip")) for path in paths["toolchain_caches"])
        assert any(path.endswith("_cacache") for path in paths["toolchain_caches"])
        assert any(path.endswith(os.path.join("caches", "tmp")) for path in paths["toolchain_caches"])
        assert any(path.endswith(os.path.join("scoop", "cache")) for path in paths["toolchain_caches"])
        assert any(path.endswith(os.path.join("Chocolatey", "cache")) for path in paths["toolchain_caches"])
        assert any(path.endswith("ComponentModelCache") for path in paths["toolchain_caches"])
        assert any(
            path.endswith(os.path.join("17.0_abc", "Cache")) for path in paths["toolchain_caches"]
        )
        assert any(path.endswith(os.path.join(".nuget", "packages")) for path in paths["nuget_packages"])
        assert not any("nuget" in path.lower() and path.endswith("packages") for path in paths["toolchain_caches"])
        assert any(path.endswith(os.path.join(".gradle", "caches")) for path in paths["gradle_caches"])
        assert any(path.endswith(os.path.join("registry", "cache")) for path in paths["cargo_cache"])
        assert "pnpm" not in joined
        assert "extensions" not in joined
        assert not any(path.endswith(os.path.join("registry", "index")) for path in flat)
        assert not any("scoop" in path.lower() and path.endswith("apps") for path in flat)
        assert all(not path_is_forbidden(path) for path in flat)
        assert TARGET_CATALOG["toolchain_caches"]["default_enabled"] is True
        assert TARGET_CATALOG["toolchain_caches"]["needs_admin"] is False
        assert TARGET_CATALOG["nuget_packages"]["default_enabled"] is False
        assert TARGET_CATALOG["gradle_caches"]["default_enabled"] is False
        assert TARGET_CATALOG["cargo_cache"]["default_enabled"] is False
        assert TARGET_CATALOG["office_file_cache"]["default_enabled"] is False

        flags = default_target_flags()
        flags["recycle_bin"] = False
        flags["downloads_old"] = False
        before = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        scan = estimate_reclaimable(
            flags,
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
        )
        after = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        assert before == after
        ready = {row["key"]: row for row in scan["targets"] if row["status"] == "ready"}
        assert ready["toolchain_caches"]["reclaimable_bytes"] == 206
        assert "nuget_packages" not in ready
        assert "gradle_caches" not in ready
        assert "cargo_cache" not in ready
        assert scan["total_bytes"] == 206

        opted = dict(flags)
        opted["nuget_packages"] = True
        opted["gradle_caches"] = True
        opted["cargo_cache"] = True
        opted_scan = estimate_reclaimable(
            opted,
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
        )
        # tmp nằm trong .gradle\\caches nên chỉ tính một lần.
        assert opted_scan["total_bytes"] == 732
        assert os.path.exists(info["files"]["gradle_tmp"])

        result = JunkCleaner.clean(
            flags,
            is_admin=False,
            deep_user_safe=True,
            environ=info["env"],
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 1},
        )
        assert result["total_freed_bytes"] == 206
        assert result["details"]["toolchain_caches"]["freed_bytes"] == 206
        for key in (
            "yarn", "nuget_http", "pip", "npm", "gradle_tmp", "scoop_cache",
            "choco", "vs_component", "vs_cache",
        ):
            assert not os.path.exists(info["files"][key]), key
        for key in (
            "yarn_poison", "gradle_modules", "nuget_packages", "cargo_cache",
            "cargo_index", "scoop_apps", "vs_ext", "pnpm", "pnpm_home", "desktop",
        ):
            assert os.path.exists(info["files"][key]), key
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_large_file_scan_does_not_delete_until_confirmed_paths():
    root = tempfile.mkdtemp(prefix="pca-large-")
    try:
        home = os.path.join(root, "Users", "alice")
        local = os.path.join(home, "AppData", "Local")
        windows = os.path.join(root, "Windows")
        now = 1_700_000_000
        movie = os.path.join(home, "Desktop", "movie.bin")
        keep = os.path.join(home, "Documents", "keep.bin")
        fresh = os.path.join(home, "Desktop", "fresh.bin")
        tiny = os.path.join(home, "Desktop", "tiny.bin")
        cloud = os.path.join(home, "OneDrive", "cloud.bin")
        blocked = os.path.join(home, "WinSxS", "sys.bin")
        cookies = os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cookies")
        cache_file = os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache", "huge.bin")
        outside = os.path.join(root, "outside.bin")
        _write(movie, b"M" * 200)
        _write(keep, b"K" * 180)
        _write(fresh, b"F" * 200)
        _write(tiny, b"t" * 10)
        _write(cloud, b"C" * 500)
        _write(blocked, b"B" * 500)
        _write(cookies, b"S" * 400)
        _write(cache_file, b"H" * 350)
        _write(outside, b"O" * 900)
        old = now - 40 * 86400
        for path in (movie, keep, cloud, blocked, cookies, cache_file, outside):
            os.utime(path, (old, old))
        os.utime(fresh, (now - 86400, now - 86400))
        env = {
            "USERPROFILE": home,
            "LOCALAPPDATA": local,
            "SystemRoot": windows,
        }
        before = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        scan = scan_large_user_files(
            environ=env,
            min_bytes=100,
            min_age_days=30,
            include_local_appdata=False,
            now_ts=now,
        )
        after = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        assert before == after
        assert scan["deleted"] is False
        found = {row["path"] for row in scan["files"]}
        assert movie in found
        assert keep in found
        assert fresh not in found
        assert tiny not in found
        assert cloud not in found
        assert blocked not in found
        assert cookies not in found
        assert cache_file not in found
        assert outside not in found
        assert all(row["selected"] is False for row in scan["files"])

        with_local = scan_large_user_files(
            environ=env,
            min_bytes=100,
            min_age_days=30,
            include_local_appdata=True,
            now_ts=now,
        )
        local_found = {row["path"] for row in with_local["files"]}
        assert cache_file in local_found
        assert cookies not in local_found
        assert os.path.exists(cache_file)
        assert os.path.exists(cookies)

        removed = delete_large_files([movie], environ=env)
        assert removed["freed_bytes"] == 200
        assert removed["deleted_files"] == 1
        assert not os.path.exists(movie)
        assert os.path.exists(keep)

        import core.c_drive_clean as clean_mod
        original_unlink = clean_mod.os.unlink

        def locked_unlink(path, *args, **kwargs):
            if str(path).endswith("keep.bin"):
                raise PermissionError("locked")
            return original_unlink(path, *args, **kwargs)

        clean_mod.os.unlink = locked_unlink
        try:
            locked = delete_large_files([keep], environ=env)
        finally:
            clean_mod.os.unlink = original_unlink
        assert os.path.exists(keep)
        assert locked["freed_bytes"] == 0
        assert locked["skipped_locked"] == 1
        assert "khóa" in locked["report_vi"].lower()

        blocked_delete = delete_large_files(
            [blocked, cloud, cookies, outside, home, windows],
            environ=env,
        )
        assert blocked_delete["freed_bytes"] == 0
        assert blocked_delete["deleted_files"] == 0
        assert os.path.exists(blocked)
        assert os.path.exists(cloud)
        assert os.path.exists(cookies)
        assert os.path.exists(outside)
        assert os.path.isdir(home)

        capped = scan_large_user_files(
            environ=env,
            min_bytes=100,
            min_age_days=0,
            include_local_appdata=False,
            max_results=1,
            now_ts=now,
        )
        assert capped["truncated"] is True
        assert len(capped["files"]) == 1
        assert capped["files"][0]["path"] == fresh
        assert capped["files"][0]["selected"] is False
        assert os.path.exists(fresh)
        assert os.path.exists(keep)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_clean_history_round_trip():
    root = tempfile.mkdtemp(prefix="pca-hist-")
    try:
        path = os.path.join(root, "c_drive_clean_history.json")
        gb = 1024 ** 3
        result = {
            "total_freed_bytes": 4096,
            "free_bytes_before": int(12.5 * gb),
            "free_bytes_after": int(12.75 * gb),
            "skipped": [
                {"key": "system_temp", "needs_admin": True, "status": "skipped"},
                {"key": "windows_update", "needs_admin": True, "status": "skipped"},
                {"key": "user_temp", "needs_admin": False, "status": "cleaned"},
            ],
        }
        rows = append_clean_history(result, path=path, now_ts=1_700_000_000)
        loaded = load_clean_history(path)
        assert loaded == rows
        assert loaded[0]["freed_bytes"] == 4096
        assert loaded[0]["skipped_admin_count"] == 2
        assert loaded[0]["free_gb_before"] == round(12.5, 3)
        assert loaded[0]["free_gb_after"] == round(12.75, 3)
        text = format_clean_history_vi(loaded)
        assert text.startswith("• ")
        assert "đã xóa" in text
        assert "bỏ qua 2 mục cần Admin" in text
        assert "trống" in text
        for index in range(10):
            append_clean_history(
                {"total_freed_bytes": index, "skipped": []},
                path=path,
                now_ts=1_700_000_000 + index + 1,
            )
        trimmed = load_clean_history(path)
        assert len(trimmed) == 8
        assert trimmed[0]["freed_bytes"] == 9
        assert trimmed[-1]["freed_bytes"] == 2
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{")
        assert load_clean_history(path) == []
        assert format_clean_history_vi([]) == "Chưa có lần dọn ổ C nào trên máy này."
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_admin_deep_plan_respects_elevation_and_forbidden_paths():
    assert _under_drive("C:", "Windows.old") == "C:\\Windows.old"
    dism_source = inspect.getsource(default_component_cleanup)
    assert "StartComponentCleanup" in dism_source
    assert "/ResetBase" not in dism_source
    assert "cleanmgr" not in dism_source.lower()

    root = tempfile.mkdtemp(prefix="pca-admin-")
    try:
        info = _tree(root)
        drive = os.path.join(root, "Drive")
        program_data = os.path.join(root, "ProgramData")
        windows = info["windows"]
        delivery = os.path.join(windows, "SoftwareDistribution", "DeliveryOptimization", "a.bin")
        ns_cache = os.path.join(
            windows, "ServiceProfiles", "NetworkService", "AppData", "Local",
            "Microsoft", "Windows", "DeliveryOptimization", "Cache", "b.bin",
        )
        setup = os.path.join(drive, "$WINDOWS.~BT", "c.bin")
        cbs = os.path.join(windows, "Logs", "CBS", "cbs.log")
        wer = os.path.join(program_data, "Microsoft", "Windows", "WER", "report.wer")
        prefetch = os.path.join(windows, "Prefetch", "APP.pf")
        old = os.path.join(drive, "Windows.old", "Windows", "explorer.exe")
        poison = os.path.join(
            windows, "SoftwareDistribution", "DeliveryOptimization", "WinSxS", "nope.bin",
        )
        hiber = os.path.join(drive, "hiberfil.sys")
        sys32 = os.path.join(windows, "System32", "note.txt")
        winsxs = os.path.join(windows, "WinSxS", "pending.manifest")
        _write(delivery, b"D" * 40)
        _write(ns_cache, b"N" * 20)
        _write(setup, b"B" * 30)
        _write(cbs, b"L" * 10)
        _write(wer, b"W" * 15)
        _write(prefetch, b"P" * 12)
        _write(old, b"O" * 50)
        _write(poison, b"X" * 25)
        _write(hiber, b"H" * 80)
        env = dict(info["env"])
        env["SystemDrive"] = drive
        env["ProgramData"] = program_data

        paths = build_target_paths(env)
        flat = [path for group in paths.values() for path in group]
        blob = "\n".join(flat)
        assert any(
            path.endswith(os.path.join("SoftwareDistribution", "DeliveryOptimization"))
            for path in paths["system_delivery_opt"]
        )
        assert any(
            path.endswith(os.path.join("DeliveryOptimization", "Cache"))
            for path in paths["system_delivery_opt"]
        )
        assert any(path.endswith("$WINDOWS.~BT") for path in paths["windows_setup_temp"])
        assert any(path.endswith(os.path.join("Logs", "CBS")) for path in paths["windows_logs"])
        assert any(path.endswith(os.path.join("Windows", "WER")) for path in paths["system_wer"])
        assert any(path.endswith("Prefetch") for path in paths["prefetch"])
        assert any(path.endswith("Windows.old") for path in paths["windows_old"])
        assert "WinSxS" not in blob
        assert "System32" not in blob
        assert "hiberfil.sys" not in blob
        assert all(not path_is_forbidden(path) for path in flat)

        sparse = build_target_paths(info["env"])
        assert sparse["windows_old"] == []
        assert sparse["windows_setup_temp"] == []
        assert sparse["system_wer"] == []

        flags = default_target_flags()
        flags["recycle_bin"] = False
        flags["downloads_old"] = False
        plan_off = resolve_clean_plan(flags, is_admin=False, deep_user_safe=True, deep_admin=True)
        skipped_keys = {item["key"] for item in plan_off["skipped"]}
        assert "system_temp" not in plan_off["to_run"]
        assert "system_delivery_opt" not in plan_off["to_run"]
        assert "system_temp" in skipped_keys
        assert "system_delivery_opt" in skipped_keys
        for opt_in in ("windows_old", "prefetch", "component_cleanup", "hibernate_file", "system_dumps"):
            assert opt_in not in plan_off["to_run"]
            assert opt_in not in skipped_keys

        narrow = resolve_clean_plan(
            {"user_temp": True, "system_temp": True},
            is_admin=False,
            deep_user_safe=True,
        )
        assert "system_delivery_opt" not in narrow["to_run"]
        assert "system_delivery_opt" not in {item["key"] for item in narrow["skipped"]}

        plan_on = resolve_clean_plan(flags, is_admin=True, deep_user_safe=True, deep_admin=True)
        for key in (
            "user_temp", "system_temp", "windows_update", "system_delivery_opt",
            "windows_setup_temp", "windows_logs", "system_wer",
        ):
            assert key in plan_on["to_run"], key
        for opt_in in ("windows_old", "prefetch", "component_cleanup", "hibernate_file", "system_dumps"):
            assert opt_in not in plan_on["to_run"]

        scan = estimate_reclaimable(
            flags,
            is_admin=False,
            deep_user_safe=True,
            deep_admin=True,
            environ=env,
        )
        skipped = {row["key"]: row for row in scan["targets"] if row["status"] == "skipped"}
        assert skipped["system_temp"]["reclaimable_bytes"] == 0
        assert skipped["system_temp"]["size_bytes"] == 80
        assert scan["total_bytes"] == 180
        assert "Cần Admin — chưa chạy" in scan["preview_vi"]
        assert "cần Admin — chưa chạy" in scan["preview_vi"]

        calls = {"dism": 0, "hiber": 0}

        def dism_runner():
            calls["dism"] += 1
            return {"success": True, "freed_bytes": 999}

        def hibernate_runner(environ=None):
            calls["hiber"] += 1
            return {"success": True, "freed_bytes": 50}

        cold = JunkCleaner.clean(
            flags,
            is_admin=False,
            deep_user_safe=True,
            deep_admin=True,
            environ=env,
            disk_free_bytes=lambda: 1000,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 1},
            component_cleanup=dism_runner,
            hibernate_off=hibernate_runner,
        )
        assert calls == {"dism": 0, "hiber": 0}
        for path in (delivery, ns_cache, setup, cbs, wer, prefetch, old, hiber, sys32, winsxs, poison):
            assert os.path.exists(path), path
        assert not os.path.exists(os.path.join(info["temp"], "keep.tmp"))
        assert ADMIN_SKIP_REASON_VI in cold["details"]["system_delivery_opt"]["reason"]
        assert cold["details"]["system_temp"]["freed_bytes"] == 0
        assert cold["deep_admin"] is True
        assert cold["free_bytes_before"] == 1000
        assert "Dọn sâu (cần Admin) hoàn tất." in cold["report_vi"]

        hot = JunkCleaner.clean(
            flags,
            is_admin=True,
            deep_user_safe=True,
            deep_admin=True,
            environ=env,
            disk_free_bytes=lambda: 2000,
            recycle_empty=lambda: {"success": False, "freed_bytes": 9, "items": 1},
            component_cleanup=dism_runner,
            hibernate_off=hibernate_runner,
        )
        assert calls == {"dism": 0, "hiber": 0}
        for path in (delivery, ns_cache, setup, cbs, wer):
            assert not os.path.exists(path), path
        assert not os.path.exists(os.path.join(windows, "Temp", "sys.tmp"))
        assert not os.path.exists(os.path.join(windows, "SoftwareDistribution", "Download", "upd.cab"))
        for path in (poison, sys32, winsxs, prefetch, old, hiber):
            assert os.path.exists(path), path
        assert hot["total_freed_bytes"] == 40 + 20 + 30 + 10 + 15 + 80 + 60
        assert hot["free_bytes_before"] == 2000
        assert hot["free_bytes_after"] == 2000

        opted = dict(flags)
        opted["component_cleanup"] = True
        opted["hibernate_file"] = True
        opted["windows_old"] = True
        opted["prefetch"] = True
        still_off = JunkCleaner.clean(
            opted,
            is_admin=False,
            deep_admin=True,
            environ=env,
            disk_free_bytes=lambda: None,
            component_cleanup=dism_runner,
            hibernate_off=hibernate_runner,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 0},
        )
        assert calls == {"dism": 0, "hiber": 0}
        assert os.path.exists(old)
        assert os.path.exists(prefetch)
        assert still_off["details"]["windows_old"]["freed_bytes"] == 0

        opted_on = JunkCleaner.clean(
            opted,
            is_admin=True,
            deep_admin=True,
            environ=env,
            disk_free_bytes=lambda: None,
            component_cleanup=dism_runner,
            hibernate_off=hibernate_runner,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 0},
        )
        assert calls == {"dism": 1, "hiber": 1}
        assert opted_on["details"]["component_cleanup"]["freed_bytes"] == 0
        assert opted_on["details"]["component_cleanup"]["status"] == "cleaned"
        assert opted_on["details"]["hibernate_file"]["freed_bytes"] == 50
        assert not os.path.exists(old)
        assert os.path.isdir(os.path.join(drive, "Windows.old"))
        assert not os.path.exists(prefetch)

        linux_hiber = default_hibernate_off({"SystemDrive": drive})
        assert linux_hiber["freed_bytes"] == 0
        assert linux_hiber.get("skipped") is True
        assert os.path.exists(hiber)
        linux_dism = default_component_cleanup()
        assert linux_dism["freed_bytes"] == 0
        assert linux_dism.get("skipped") is True

        hist_path = os.path.join(root, "hist.json")
        rows = append_clean_history(hot, path=hist_path, now_ts=1_700_000_100)
        loaded = load_clean_history(hist_path)
        assert loaded[0]["deep_admin"] is True
        assert "dọn sâu Admin" in format_clean_history_line_vi(loaded[0])
        assert rows[0]["deep_admin"] is True

        preview_flags = dict(flags)
        preview_flags["windows_old"] = True
        preview_flags["component_cleanup"] = True
        preview_flags["hibernate_file"] = True
        seen = estimate_reclaimable(
            preview_flags,
            is_admin=True,
            deep_admin=True,
            environ=env,
        )
        ready = {row["key"] for row in seen["targets"] if row["status"] == "ready"}
        assert "component_cleanup" in ready
        assert "hibernate_file" in ready
        assert "windows_old" in ready
        assert "Dọn kho thành phần" in seen["preview_vi"]
        assert "khoảng 0 B" in seen["preview_vi"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_chat_gpu_launcher_and_empty_folders_do_not_double_count():
    """Cache chat/GPU mới, launcher tắt mặc định, thư mục trống — không cộng byte hai lần."""
    root = tempfile.mkdtemp(prefix="pca-v4-")
    basic_root = tempfile.mkdtemp(prefix="pca-v4-missing-")
    try:
        home = os.path.join(root, "Users", "alice")
        local = os.path.join(home, "AppData", "Local")
        roaming = os.path.join(home, "AppData", "Roaming")
        local_low = os.path.join(home, "AppData", "LocalLow")
        windows = os.path.join(root, "Windows")
        program_data = os.path.join(root, "ProgramData")
        program_files = os.path.join(root, "Program Files")
        steam_root = os.path.join(root, "Steam")
        steam_lib = os.path.join(root, "SteamLibrary")
        outside = os.path.join(root, "outside.bin")

        def put(path, payload):
            _write(path, payload)
            return path

        files = {
            "discord_cache": put(os.path.join(roaming, "discord", "Cache", "a.bin"), b"D" * 11),
            "discord_code": put(os.path.join(roaming, "discord", "Code Cache", "b.bin"), b"D" * 12),
            "discord_gpu": put(os.path.join(roaming, "discord", "GPUCache", "c.bin"), b"D" * 13),
            "discord_dawn": put(os.path.join(roaming, "discord", "DawnCache", "d.bin"), b"D" * 1),
            "discord_canary": put(os.path.join(roaming, "discordcanary", "Cache", "e.bin"), b"D" * 7),
            "discord_leveldb": put(
                os.path.join(roaming, "discord", "Local Storage", "leveldb", "data.ldb"),
                b"L" * 500,
            ),
            "discord_idb": put(os.path.join(roaming, "discord", "IndexedDB", "idb.bin"), b"I" * 40),
            "tele_cache": put(
                os.path.join(roaming, "Telegram Desktop", "tdata", "user_data", "cache", "m.bin"),
                b"T" * 9,
            ),
            "tele_media": put(
                os.path.join(roaming, "Telegram Desktop", "tdata", "user_data", "media_cache", "m2.bin"),
                b"T" * 8,
            ),
            "tele_temp": put(os.path.join(roaming, "Telegram Desktop", "tdata", "temp", "t.bin"), b"T" * 6),
            "tele_emoji": put(os.path.join(roaming, "Telegram Desktop", "tdata", "emoji", "e.bin"), b"T" * 5),
            "tele_user2": put(
                os.path.join(roaming, "Telegram Desktop", "tdata", "user_data#2", "cache", "u.bin"),
                b"T" * 4,
            ),
            "tele_key": put(os.path.join(roaming, "Telegram Desktop", "tdata", "key_datas"), b"K" * 400),
            "tele_map": put(os.path.join(roaming, "Telegram Desktop", "tdata", "map0"), b"M" * 50),
            "tele_account": put(
                os.path.join(roaming, "Telegram Desktop", "tdata", "D877F783D5D3EF8C", "msgs.bin"),
                b"A" * 80,
            ),
            "zalo_cache": put(os.path.join(roaming, "ZaloData", "Cache", "z.bin"), b"Z" * 10),
            "zalo_temp": put(os.path.join(local, "ZaloPC", "Temp", "z.bin"), b"Z" * 4),
            "zalo_logs": put(os.path.join(local, "Programs", "Zalo", "logs", "z.log"), b"Z" * 2),
            "zalo_db": put(os.path.join(roaming, "ZaloData", "accounts", "accounts.db"), b"Z" * 300),
            "zalo_ls": put(
                os.path.join(roaming, "ZaloData", "Partitions", "zalo", "Local Storage", "leveldb", "a.ldb"),
                b"Z" * 20,
            ),
            "zalo_exe": put(os.path.join(local, "Programs", "Zalo", "Zalo.exe"), b"E" * 30),
            "msgr_cache": put(os.path.join(roaming, "Messenger", "Cache", "m.bin"), b"F" * 14),
            "msgr_ls": put(os.path.join(roaming, "Messenger", "Local Storage", "leveldb", "m.ldb"), b"F" * 21),
            "msgr_pkg": put(
                os.path.join(local, "Packages", "Facebook.Messenger_abc", "TempState", "t.bin"),
                b"F" * 3,
            ),
            "msgr_state": put(
                os.path.join(local, "Packages", "Facebook.Messenger_abc", "LocalState", "keep.bin"),
                b"F" * 22,
            ),
            "dx": put(os.path.join(local, "NVIDIA", "DXCache", "dx.bin"), b"N" * 100),
            "amd": put(os.path.join(local, "AMD", "DxCache", "amd.bin"), b"A" * 20),
            "intel": put(os.path.join(local, "Intel", "ShaderCache", "i.bin"), b"I" * 40),
            "compute": put(
                os.path.join(local_low, "NVIDIA", "PerDriverVersion", "ComputeCache", "c.bin"),
                b"C" * 30,
            ),
            "steam_shader_local": put(os.path.join(local, "Steam", "shadercache", "s.bin"), b"S" * 15),
            "html": put(os.path.join(local, "Steam", "htmlcache", "h.bin"), b"H" * 8),
            "decoy_dx": put(os.path.join(local, "SomeApp", "DXCache", "nope.bin"), b"X" * 77),
            "pd_dx": put(os.path.join(program_data, "NVIDIA", "DXCache", "pd.bin"), b"P" * 999),
            "pf_dx": put(os.path.join(program_files, "NVIDIA Corporation", "DXCache", "pf.bin"), b"P" * 999),
            "sys_temp": put(os.path.join(windows, "Temp", "sys.tmp"), b"S" * 80),
            "steam_app": put(os.path.join(steam_root, "appcache", "app.bin"), b"A" * 16),
            "steam_down": put(os.path.join(steam_lib, "steamapps", "downloading", "part.bin"), b"D" * 17),
            "steam_shader": put(os.path.join(steam_lib, "steamapps", "shadercache", "sh.bin"), b"S" * 18),
            "steam_temp": put(os.path.join(steam_lib, "steamapps", "temp", "tmp.bin"), b"S" * 2),
            "steam_game": put(os.path.join(steam_lib, "steamapps", "common", "Game", "data.bin"), b"G" * 1000),
            "epic_web": put(
                os.path.join(local, "EpicGamesLauncher", "Saved", "webcache", "w.bin"),
                b"E" * 19,
            ),
            "epic_web2": put(
                os.path.join(local, "EpicGamesLauncher", "Saved", "webcache_4430", "w.bin"),
                b"E" * 6,
            ),
            "epic_cfg": put(
                os.path.join(local, "EpicGamesLauncher", "Saved", "Config", "settings.ini"),
                b"C" * 33,
            ),
            "egstore": put(os.path.join(local, "EpicGames", "Game", ".egstore", "manifest"), b"E" * 44),
            "keep_doc": put(os.path.join(home, "Documents", "keep", "note.txt"), b"K" * 12),
            "keep_dl": put(os.path.join(home, "Downloads", "new.bin"), b"N" * 9),
            "node_mod": put(os.path.join(home, "Documents", "node_modules", "pkg", "index.js"), b"J" * 11),
            "onedrive_secret": put(os.path.join(home, "Documents", "OneDrive", "secret.txt"), b"O" * 13),
        }
        _write(outside, b"O" * 7)
        os.makedirs(os.path.join(home, "Documents", "empty_leaf"), exist_ok=True)
        os.makedirs(os.path.join(home, "Documents", "empty_parent", "empty_child"), exist_ok=True)
        os.makedirs(os.path.join(home, "Desktop", "empty_desk"), exist_ok=True)
        os.makedirs(os.path.join(home, "Downloads", "empty_dl"), exist_ok=True)
        os.makedirs(os.path.join(local, "Temp", "empty_tmp"), exist_ok=True)
        os.makedirs(os.path.join(roaming, "EmptyNope"), exist_ok=True)
        os.symlink(outside, os.path.join(home, "Documents", "jump"))
        vdf = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
        os.makedirs(os.path.dirname(vdf), exist_ok=True)
        with open(vdf, "w", encoding="utf-8") as handle:
            handle.write(
                '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"'
                + steam_root.replace("\\", "\\\\")
                + '"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"'
                + steam_lib.replace("\\", "\\\\")
                + '"\n\t}\n}\n'
            )
        os.makedirs(os.path.join(steam_root, "appcache"), exist_ok=True)

        env = {
            "USERPROFILE": home,
            "LOCALAPPDATA": local,
            "APPDATA": roaming,
            "TEMP": os.path.join(local, "Temp"),
            "SystemRoot": windows,
            "STEAM_PATH": steam_root,
        }
        paths = build_target_paths(env)
        flat = [path for group in paths.values() for path in group]
        for path in flat:
            parts = _path_parts(path)
            assert "winsxs" not in parts
            assert "system32" not in parts
            assert "leveldb" not in parts
            assert "accounts" not in parts
            assert "key_datas" not in parts
            assert "key_data" not in parts
            assert "map0" not in parts
            assert "indexeddb" not in parts
            assert "local storage" not in parts
            assert not path_is_forbidden(path)
            assert not path_is_game_install(path)
        assert any(path.endswith(os.path.join("discord", "Cache")) for path in paths["discord_cache"])
        assert any(path.endswith(os.path.join("discordcanary", "Cache")) for path in paths["discord_cache"])
        assert not any("discord" in _path_parts(path) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("user_data", "cache")) for path in paths["telegram_cache"])
        assert any(path.endswith(os.path.join("media_cache")) for path in paths["telegram_cache"])
        assert any(path.endswith(os.path.join("user_data#2", "cache")) for path in paths["telegram_cache"])
        assert not any(path.rstrip("\\/").endswith(os.path.join("Telegram Desktop", "tdata")) for path in flat)
        assert any(path.endswith(os.path.join("ZaloData", "Cache")) for path in paths["zalo_cache"])
        assert any(path.endswith(os.path.join("ZaloPC", "Temp")) for path in paths["zalo_cache"])
        assert not any("zalo" in _path_parts(path) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("Messenger", "Cache")) for path in paths["messenger_cache"])
        assert any("Facebook.Messenger_" in path and path.endswith("TempState") for path in paths["messenger_cache"])
        assert any(path.endswith(os.path.join("NVIDIA", "DXCache")) for path in paths["gpu_shader_caches"])
        assert any(path.endswith(os.path.join("Intel", "ShaderCache")) for path in paths["gpu_shader_caches"])
        assert any("perdriverversion" in path.lower() and path.endswith("ComputeCache") for path in paths["gpu_shader_caches"])
        assert not any("programdata" in _path_parts(path) or "program files" in _path_parts(path) for path in paths["gpu_shader_caches"])
        assert not any("someapp" in _path_parts(path) for path in flat)
        assert any(path.endswith("htmlcache") for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("Steam", "shadercache")) for path in paths["shader_cache"])
        assert any(path.endswith("appcache") for path in paths["steam_caches"])
        assert any(path.endswith("downloading") for path in paths["steam_caches"])
        assert any(path.endswith(os.path.join("steamapps", "shadercache")) for path in paths["steam_caches"])
        assert not any(path.endswith("common") or "common" in _path_parts(path) for path in paths["steam_caches"])
        assert any(path.endswith("webcache") for path in paths["epic_caches"])
        assert any(path.endswith("webcache_4430") for path in paths["epic_caches"])
        assert not any("config" in _path_parts(path) for path in paths["epic_caches"])
        assert not any(".egstore" in _path_parts(path) for path in flat)
        assert os.path.join(home, "Documents") in paths["empty_user_folders"]
        assert os.path.join(local, "Temp") in paths["empty_user_folders"]
        assert home not in paths["empty_user_folders"]

        for key in (
            "discord_cache", "telegram_cache", "zalo_cache", "messenger_cache", "gpu_shader_caches",
            "steam_caches", "epic_caches", "empty_user_folders",
        ):
            assert TARGET_CATALOG[key]["needs_admin"] is False
        for key in ("discord_cache", "telegram_cache", "zalo_cache", "messenger_cache", "gpu_shader_caches"):
            assert TARGET_CATALOG[key]["default_enabled"] is True
            assert DEFAULT_CONFIG["targets"][key] is True
        for key in ("steam_caches", "epic_caches", "empty_user_folders"):
            assert TARGET_CATALOG[key]["default_enabled"] is False
            assert DEFAULT_CONFIG["targets"][key] is False
        assert "Cache Discord" in TARGET_CATALOG["discord_cache"]["label_vi"]
        assert "Telegram" in TARGET_CATALOG["telegram_cache"]["label_vi"]
        assert "Zalo" in TARGET_CATALOG["zalo_cache"]["label_vi"]
        assert "Messenger" in TARGET_CATALOG["messenger_cache"]["label_vi"]
        assert "GPU" in TARGET_CATALOG["gpu_shader_caches"]["label_vi"]
        assert "tắt mặc định" in TARGET_CATALOG["steam_caches"]["label_vi"]
        assert "tắt mặc định" in TARGET_CATALOG["empty_user_folders"]["label_vi"]

        flags = default_target_flags()
        flags["recycle_bin"] = False
        flags["downloads_old"] = False
        plan = resolve_clean_plan(flags, is_admin=False, deep_user_safe=True)
        assert "discord_cache" in plan["to_run"]
        assert "gpu_shader_caches" in plan["to_run"]
        assert "steam_caches" not in plan["to_run"]
        assert "epic_caches" not in plan["to_run"]
        assert "empty_user_folders" not in plan["to_run"]
        assert "system_temp" not in plan["to_run"]

        before = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        scan = estimate_reclaimable(flags, is_admin=False, deep_user_safe=True, environ=env)
        after = {
            os.path.join(dirpath, filename)
            for dirpath, _dirs, filenames in os.walk(root)
            for filename in filenames
        }
        assert before == after
        ready = {row["key"]: row for row in scan["targets"] if row["status"] == "ready"}
        shader_bytes = 100 + 20 + 15
        gpu_bytes = 40 + 30
        assert ready["shader_cache"]["reclaimable_bytes"] == shader_bytes
        assert ready["gpu_shader_caches"]["reclaimable_bytes"] == gpu_bytes
        assert ready["discord_cache"]["reclaimable_bytes"] == 11 + 12 + 13 + 1 + 7
        assert ready["telegram_cache"]["reclaimable_bytes"] == 9 + 8 + 6 + 5 + 4
        assert ready["zalo_cache"]["reclaimable_bytes"] == 10 + 4 + 2
        assert ready["messenger_cache"]["reclaimable_bytes"] == 14 + 3
        assert ready["app_caches"]["reclaimable_bytes"] == 8
        assert "steam_caches" not in ready
        assert "epic_caches" not in ready
        assert "empty_user_folders" not in ready
        default_gone = (
            "discord_cache", "discord_code", "discord_gpu", "discord_dawn", "discord_canary",
            "tele_cache", "tele_media", "tele_temp", "tele_emoji", "tele_user2",
            "zalo_cache", "zalo_temp", "zalo_logs",
            "msgr_cache", "msgr_pkg",
            "dx", "amd", "intel", "compute", "steam_shader_local", "html",
        )
        assert scan["total_bytes"] == sum(len(open(files[key], "rb").read()) for key in default_gone)
        assert "Cache Discord" in scan["preview_vi"]
        assert "Cache shader GPU" in scan["preview_vi"]
        quick = JunkCleaner.scan(flags, is_admin=False, environ=env)
        assert quick["total_bytes"] == scan["total_bytes"]

        only_gpu = estimate_reclaimable(
            {"gpu_shader_caches": True},
            is_admin=False,
            deep_user_safe=False,
            environ=env,
        )
        only_gpu_ready = {row["key"]: row for row in only_gpu["targets"] if row["status"] == "ready"}
        assert only_gpu_ready["gpu_shader_caches"]["reclaimable_bytes"] == 100 + 20 + 40 + 30
        assert only_gpu["total_bytes"] == 100 + 20 + 40 + 30
        only_shader = estimate_reclaimable(
            {"shader_cache": True},
            is_admin=False,
            deep_user_safe=False,
            environ=env,
        )
        only_shader_ready = {row["key"]: row for row in only_shader["targets"] if row["status"] == "ready"}
        assert only_shader_ready["shader_cache"]["reclaimable_bytes"] == shader_bytes
        assert "gpu_shader_caches" not in only_shader_ready

        opted = dict(flags)
        opted["steam_caches"] = True
        opted["epic_caches"] = True
        opted["empty_user_folders"] = True
        opted_scan = estimate_reclaimable(opted, is_admin=False, deep_user_safe=True, environ=env)
        opted_ready = {row["key"]: row for row in opted_scan["targets"] if row["status"] == "ready"}
        assert opted_ready["steam_caches"]["reclaimable_bytes"] == 16 + 17 + 18 + 2
        assert opted_ready["epic_caches"]["reclaimable_bytes"] == 19 + 6
        assert opted_ready["empty_user_folders"]["reclaimable_bytes"] == 0
        assert opted_ready["empty_user_folders"]["reclaimable_files"] >= 4
        assert "thư mục trống" in opted_scan["preview_vi"]
        extra = 16 + 17 + 18 + 2 + 19 + 6
        assert opted_scan["total_bytes"] == scan["total_bytes"] + extra

        shallow = list_empty_directories(
            os.path.join(home, "Documents"),
            user_profile=home,
            system_root=windows,
            max_depth=1,
        )
        assert os.path.join(home, "Documents", "empty_leaf") in shallow
        assert not any(path.endswith("empty_child") for path in shallow)
        assert list_empty_directories(
            os.path.join(home, "Documents"),
            budget=_EmptyDirBudget(max_seconds=0),
            user_profile=home,
            system_root=windows,
        ) == []

        result = JunkCleaner.clean(
            opted,
            is_admin=False,
            deep_user_safe=True,
            environ=env,
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 1},
        )
        assert result["total_freed_bytes"] == scan["total_bytes"] + extra
        assert "Đã xóa" in result["details"]["empty_user_folders"]["reason"]
        assert "thư mục trống" in result["details"]["empty_user_folders"]["reason"]
        for key in default_gone + ("steam_app", "steam_down", "steam_shader", "steam_temp", "epic_web", "epic_web2"):
            assert not os.path.exists(files[key]), key
        for key in (
            "discord_leveldb", "discord_idb", "tele_key", "tele_map", "tele_account",
            "zalo_db", "zalo_ls", "zalo_exe", "msgr_ls", "msgr_state",
            "decoy_dx", "pd_dx", "pf_dx", "sys_temp", "steam_game", "epic_cfg", "egstore",
            "keep_doc", "keep_dl", "node_mod", "onedrive_secret",
        ):
            assert os.path.exists(files[key]), key
        assert os.path.exists(outside)
        assert os.path.islink(os.path.join(home, "Documents", "jump"))
        assert os.path.isdir(home)
        assert os.path.isdir(os.path.join(home, "Documents"))
        assert os.path.isdir(os.path.join(home, "Documents", "keep"))
        assert os.path.isdir(os.path.join(home, "Documents", "node_modules"))
        assert os.path.isdir(os.path.join(home, "Documents", "OneDrive"))
        assert os.path.isdir(os.path.join(roaming, "EmptyNope"))
        assert not os.path.isdir(os.path.join(home, "Documents", "empty_leaf"))
        assert not os.path.isdir(os.path.join(home, "Documents", "empty_parent"))
        assert not os.path.isdir(os.path.join(home, "Desktop", "empty_desk"))
        assert not os.path.isdir(os.path.join(home, "Downloads", "empty_dl"))
        assert os.path.exists(files["sys_temp"])
        assert result["details"]["system_temp"]["status"] == "skipped"
        assert result["details"]["system_temp"]["freed_bytes"] == 0

        info = _tree(basic_root)
        missing = build_target_paths(info["env"])
        for key in ("discord_cache", "telegram_cache", "zalo_cache", "messenger_cache", "steam_caches", "epic_caches"):
            assert missing[key] == []
        ui = open(os.path.join(os.path.dirname(__file__), "ui", "main_window.py"), encoding="utf-8").read()
        assert "Discord, Telegram, Zalo, Messenger" in ui
        assert "cache Steam/Epic" in ui
        assert "thư mục trống" in ui
        module = open(os.path.join(os.path.dirname(__file__), "core", "c_drive_clean.py"), encoding="utf-8").read()
        assert "runas" not in module.lower()
        assert "shellexecute" not in module.lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(basic_root, ignore_errors=True)


def test_v5_caches_groups_sort_and_min_size_filter():
    """Cache Adobe/TikTok/Viber/Teams/Blender/Unity, nhóm, xếp size, ngưỡng Dọn ngay."""
    grouped = [key for _group_id, _label, keys in TARGET_GROUPS for key in keys]
    assert len(grouped) == len(set(grouped)) == len(TARGET_ORDER)
    assert set(grouped) == set(TARGET_ORDER)
    labels = [label for _group_id, label, _keys in TARGET_GROUPS]
    for expected in ("Trình duyệt & Web", "Chat", "GPU & Game", "Công cụ lập trình", "Khác"):
        assert expected in labels
    assert DEFAULT_CONFIG["c_drive_min_clean_mb"] == DEFAULT_MIN_CLEAN_MB == 10
    assert normalize_min_clean_mb(None) == 10
    assert normalize_min_clean_mb("nope") == 10
    assert normalize_min_clean_mb(-3) == 10
    assert normalize_min_clean_mb(0) == 0
    assert normalize_min_clean_mb(99999) == 10240

    for key, enabled in (
        ("adobe_caches", False),
        ("tiktok_cache", True),
        ("viber_cache", True),
        ("teams_cache", True),
        ("blender_caches", False),
        ("unity_caches", False),
    ):
        assert TARGET_CATALOG[key]["needs_admin"] is False
        assert TARGET_CATALOG[key]["default_enabled"] is enabled
        assert DEFAULT_CONFIG["targets"][key] is enabled
        assert "tắt mặc định" in TARGET_CATALOG[key]["label_vi"] or enabled

    small = {
        "key": "tiktok_cache",
        "status": "ready",
        "reclaimable_bytes": 1024,
        "reclaimable_files": 1,
    }
    large = {
        "key": "adobe_caches",
        "status": "ready",
        "reclaimable_bytes": 11 * 1024 * 1024,
        "reclaimable_files": 2,
    }
    assert category_offered_by_default(large, 10) is True
    assert category_offered_by_default(small, 10) is False
    assert category_offered_by_default(small, 0) is True
    assert category_offered_by_default(
        {"key": "component_cleanup", "status": "ready", "reclaimable_bytes": 0, "reclaimable_files": 0},
        10,
    ) is True
    assert category_offered_by_default({"key": "user_temp", "status": "skipped", "reclaimable_bytes": 999999}, 0) is False

    preview = format_scan_preview_vi({
        "total_bytes": 500,
        "total_files": 3,
        "is_admin": False,
        "deep_admin": False,
        "targets": [
            {
                "key": "browser_cache",
                "name": "Bộ nhớ đệm trình duyệt",
                "group_vi": "Trình duyệt & Web",
                "status": "ready",
                "reclaimable_bytes": 100,
                "reclaimable_files": 1,
                "size_bytes": 100,
            },
            {
                "key": "zalo_cache",
                "name": "Cache Zalo",
                "group_vi": "Chat",
                "status": "ready",
                "reclaimable_bytes": 200,
                "reclaimable_files": 1,
                "size_bytes": 200,
            },
            {
                "key": "discord_cache",
                "name": "Cache Discord",
                "group_vi": "Chat",
                "status": "ready",
                "reclaimable_bytes": 200,
                "reclaimable_files": 1,
                "size_bytes": 200,
            },
        ],
    })
    assert preview.find("Cache Discord") < preview.find("Cache Zalo") < preview.find("Bộ nhớ đệm trình duyệt")
    assert "[Chat]" in preview
    assert "lớn đến nhỏ" in preview
    assert "chưa xóa" in preview.lower()
    ordered = [row["key"] for row in preview_rows_for_display({
        "targets": [
            {"key": "b_key", "status": "ready", "reclaimable_bytes": 50, "reclaimable_files": 1, "size_bytes": 50},
            {"key": "a_key", "status": "ready", "reclaimable_bytes": 50, "reclaimable_files": 1, "size_bytes": 50},
            {"key": "z_key", "status": "ready", "reclaimable_bytes": 80, "reclaimable_files": 1, "size_bytes": 80},
        ],
    })]
    assert ordered == ["z_key", "a_key", "b_key"]

    root = tempfile.mkdtemp(prefix="pca-v5-")
    basic_root = tempfile.mkdtemp(prefix="pca-v5-missing-")
    try:
        home = os.path.join(root, "Users", "alice")
        local = os.path.join(home, "AppData", "Local")
        roaming = os.path.join(home, "AppData", "Roaming")
        windows = os.path.join(root, "Windows")
        program_files = os.path.join(root, "Program Files")

        def put(path, payload):
            _write(path, payload)
            return path

        files = {
            "adobe_media": put(os.path.join(local, "Adobe", "Common", "Media Cache", "a.bin"), b"A" * 51),
            "adobe_files": put(os.path.join(local, "Adobe", "Common", "Media Cache Files", "b.bin"), b"A" * 52),
            "adobe_peak": put(os.path.join(roaming, "Adobe", "Common", "Peak Files", "c.bin"), b"A" * 53),
            "adobe_common": put(os.path.join(roaming, "Adobe", "Common", "Cache", "d.bin"), b"A" * 54),
            "adobe_lib": put(
                os.path.join(roaming, "Adobe", "Creative Cloud Libraries", "library.bin"),
                b"L" * 80,
            ),
            "adobe_doc": put(os.path.join(home, "Documents", "Adobe", "poster.psd"), b"P" * 90),
            "adobe_pf": put(
                os.path.join(program_files, "Adobe", "Common", "Media Cache", "pf.bin"),
                b"Z" * 70,
            ),
            "tiktok": put(os.path.join(local, "TikTok", "Cache", "t.bin"), b"T" * 31),
            "tiktok_profile": put(
                os.path.join(local, "TikTok", "User Data", "Default", "Cache", "p.bin"),
                b"T" * 32,
            ),
            "tiktok_idb": put(
                os.path.join(local, "TikTok", "User Data", "Default", "IndexedDB", "idb.bin"),
                b"I" * 40,
            ),
            "tiktok_ls": put(
                os.path.join(local, "TikTok", "User Data", "Default", "Local Storage", "leveldb", "a.ldb"),
                b"S" * 33,
            ),
            "capcut": put(os.path.join(local, "CapCut", "User Data", "Cache", "cc.bin"), b"C" * 15),
            "viber_media": put(os.path.join(roaming, "ViberPC", "8490", "Media Cache", "m.bin"), b"V" * 41),
            "viber_temp": put(os.path.join(roaming, "ViberPC", "8490", "Temp", "t.bin"), b"V" * 42),
            "viber_db": put(os.path.join(roaming, "ViberPC", "8490", "viber.db"), b"D" * 120),
            "viber_root_db": put(os.path.join(roaming, "ViberPC", "viber.db"), b"D" * 60),
            "teams_classic": put(os.path.join(roaming, "Microsoft", "Teams", "Cache", "c.bin"), b"M" * 21),
            "teams_idb": put(os.path.join(roaming, "Microsoft", "Teams", "IndexedDB", "idb.bin"), b"I" * 44),
            "teams_level": put(
                os.path.join(roaming, "Microsoft", "Teams", "Local Storage", "leveldb", "x.ldb"),
                b"L" * 28,
            ),
            "teams_wv": put(
                os.path.join(
                    local, "Packages", "MSTeams_8wekyb3d8bbwe", "LocalCache", "Microsoft",
                    "MSTeams", "EBWebView", "Default", "Cache", "a.bin",
                ),
                b"M" * 22,
            ),
            "teams_wv2": put(
                os.path.join(
                    local, "Packages", "MSTeams_8wekyb3d8bbwe", "LocalCache", "Microsoft",
                    "MSTeams", "EBWebView", "WV2Profile_tfw", "GPUCache", "g.bin",
                ),
                b"M" * 23,
            ),
            "teams_wv_idb": put(
                os.path.join(
                    local, "Packages", "MSTeams_8wekyb3d8bbwe", "LocalCache", "Microsoft",
                    "MSTeams", "EBWebView", "Default", "IndexedDB", "secret.bin",
                ),
                b"I" * 55,
            ),
            "webview_other": put(
                os.path.join(local, "Contoso", "Widget", "EBWebView", "Default", "Cache", "w.bin"),
                b"W" * 11,
            ),
            "blend_cache": put(
                os.path.join(roaming, "Blender Foundation", "Blender", "4.2", "cache", "c.bin"),
                b"B" * 61,
            ),
            "blend_config": put(
                os.path.join(roaming, "Blender Foundation", "Blender", "4.2", "config", "startup.blend"),
                b"B" * 48,
            ),
            "blend_doc": put(os.path.join(home, "Documents", "scene.blend"), b"B" * 77),
            "unity_cache": put(os.path.join(local, "Unity", "cache", "pkg.bin"), b"U" * 71),
            "unity_gi": put(os.path.join(local, "Unity", "Caches", "GiCache", "g.bin"), b"U" * 72),
            "unity_lib": put(os.path.join(home, "Documents", "MyGame", "Library", "Artifact.bin"), b"U" * 200),
            "unity_temp": put(os.path.join(home, "Documents", "MyGame", "Temp", "tmp.bin"), b"U" * 88),
            "unity_asset": put(os.path.join(home, "Documents", "MyGame", "Assets", "hero.fbx"), b"U" * 66),
            "winsxs": put(os.path.join(windows, "WinSxS", "pending.bin"), b"X" * 40),
        }
        env = {
            "USERPROFILE": home,
            "LOCALAPPDATA": local,
            "APPDATA": roaming,
            "TEMP": os.path.join(local, "Temp"),
            "SystemRoot": windows,
        }
        os.makedirs(env["TEMP"], exist_ok=True)
        paths = build_target_paths(env)
        flat = [path for group in paths.values() for path in group]
        for path in flat:
            parts = _path_parts(path)
            assert "winsxs" not in parts
            assert "system32" not in parts
            assert "indexeddb" not in parts
            assert "leveldb" not in parts
            assert "local storage" not in parts
            assert "library" not in parts
            assert "assets" not in parts
            assert not path_is_forbidden(path)
            assert not path_is_game_install(path)
        for key in (
            "adobe_caches", "tiktok_cache", "viber_cache", "teams_cache",
            "blender_caches", "unity_caches", "browser_cache", "app_caches",
        ):
            assert not any("documents" in _path_parts(path) for path in paths[key]), key
        assert any(path.endswith(os.path.join("Media Cache")) for path in paths["adobe_caches"])
        assert any(path.endswith("Peak Files") for path in paths["adobe_caches"])
        assert any(path.endswith(os.path.join("Common", "Cache")) for path in paths["adobe_caches"])
        assert not any("creative cloud libraries" in _path_parts(path) for path in flat)
        assert not any("program files" in _path_parts(path) for path in paths["adobe_caches"])
        assert any(path.endswith(os.path.join("TikTok", "Cache")) for path in paths["tiktok_cache"])
        assert any(path.endswith(os.path.join("Default", "Cache")) and "tiktok" in _path_parts(path) for path in paths["tiktok_cache"])
        assert not any("capcut" in _path_parts(path) for path in paths["tiktok_cache"])
        assert any("capcut" in _path_parts(path) for path in paths["app_caches"])
        assert any(path.endswith("Media Cache") and "viberpc" in _path_parts(path) for path in paths["viber_cache"])
        assert any(path.endswith("Temp") and "viberpc" in _path_parts(path) for path in paths["viber_cache"])
        assert not any(path.endswith("viber.db") for path in flat)
        assert any(path.endswith(os.path.join("Teams", "Cache")) for path in paths["teams_cache"])
        assert any(
            any(part.startswith("msteams_") for part in _path_parts(path)) and path.endswith("Cache")
            for path in paths["teams_cache"]
        )
        assert any("wv2profile_tfw" in _path_parts(path) and path.endswith("GPUCache") for path in paths["teams_cache"])
        def _teams_owned(path):
            parts = _path_parts(path)
            if any(part.startswith("msteams_") for part in parts):
                return True
            return any(
                part in {"teams", "msteams"} and index > 0 and parts[index - 1] == "microsoft"
                for index, part in enumerate(parts)
            )
        assert not any(_teams_owned(path) for path in paths["browser_cache"])
        assert not any(_teams_owned(path) for path in paths["app_caches"])
        assert not any("teams" in _path_parts(path) for path in paths["app_caches"])
        assert any("contoso" in _path_parts(path) for path in paths["browser_cache"])
        assert any(path.endswith("cache") and "blender" in _path_parts(path) for path in paths["blender_caches"])
        assert not any(path.endswith("config") for path in paths["blender_caches"])
        assert any(path.endswith("cache") and "unity" in _path_parts(path) for path in paths["unity_caches"])
        assert any(path.endswith("GiCache") for path in paths["unity_caches"])
        assert not any(path.endswith("Library") or path.endswith("Assets") for path in flat)

        flags = default_target_flags()
        flags["recycle_bin"] = False
        flags["downloads_old"] = False
        plan = resolve_clean_plan(flags, is_admin=False, deep_user_safe=True)
        assert "teams_cache" in plan["to_run"]
        assert "tiktok_cache" in plan["to_run"]
        assert "viber_cache" in plan["to_run"]
        assert "adobe_caches" not in plan["to_run"]
        assert "blender_caches" not in plan["to_run"]
        assert "unity_caches" not in plan["to_run"]
        scan = estimate_reclaimable(flags, is_admin=False, deep_user_safe=True, environ=env)
        ready = {row["key"]: row for row in scan["targets"] if row["status"] == "ready"}
        assert ready["teams_cache"]["reclaimable_bytes"] == 21 + 22 + 23
        assert ready["tiktok_cache"]["reclaimable_bytes"] == 31 + 32
        assert ready["viber_cache"]["reclaimable_bytes"] == 41 + 42
        assert ready["app_caches"]["reclaimable_bytes"] == 15
        assert ready["browser_cache"]["reclaimable_bytes"] == 11
        assert "adobe_caches" not in ready
        default_sum = 21 + 22 + 23 + 31 + 32 + 41 + 42 + 15 + 11
        assert scan["total_bytes"] == default_sum
        assert "Cache Microsoft Teams" in scan["preview_vi"] or "Cache TikTok" in scan["preview_vi"]
        assert os.path.exists(files["adobe_media"])
        assert os.path.exists(files["teams_wv_idb"])

        opted = dict(flags)
        opted["adobe_caches"] = True
        opted["blender_caches"] = True
        opted["unity_caches"] = True
        opted_scan = estimate_reclaimable(opted, is_admin=False, deep_user_safe=True, environ=env)
        opted_ready = {row["key"]: row for row in opted_scan["targets"] if row["status"] == "ready"}
        assert opted_ready["adobe_caches"]["reclaimable_bytes"] == 51 + 52 + 53 + 54
        assert opted_ready["blender_caches"]["reclaimable_bytes"] == 61
        assert opted_ready["unity_caches"]["reclaimable_bytes"] == 71 + 72
        extra = 51 + 52 + 53 + 54 + 61 + 71 + 72
        assert opted_scan["total_bytes"] == default_sum + extra

        only = JunkCleaner.clean(
            opted,
            is_admin=False,
            deep_user_safe=True,
            environ=env,
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 0},
            only_keys=["tiktok_cache"],
        )
        assert only["total_freed_bytes"] == 31 + 32
        assert not os.path.exists(files["tiktok"])
        assert not os.path.exists(files["tiktok_profile"])
        assert os.path.exists(files["teams_classic"])
        assert os.path.exists(files["adobe_media"])
        assert os.path.exists(files["capcut"])
        assert os.path.exists(files["tiktok_idb"])
        assert os.path.exists(files["tiktok_ls"])

        result = JunkCleaner.clean(
            opted,
            is_admin=False,
            deep_user_safe=True,
            environ=env,
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 0},
        )
        assert result["total_freed_bytes"] == default_sum + extra - (31 + 32)
        for key in (
            "adobe_lib", "adobe_doc", "adobe_pf", "tiktok_idb", "tiktok_ls", "viber_db",
            "viber_root_db", "teams_idb", "teams_level", "teams_wv_idb", "blend_config",
            "blend_doc", "unity_lib", "unity_temp", "unity_asset", "winsxs",
        ):
            assert os.path.exists(files[key]), key
        for key in (
            "adobe_media", "adobe_files", "adobe_peak", "adobe_common",
            "viber_media", "viber_temp", "teams_classic", "teams_wv", "teams_wv2",
            "webview_other", "capcut", "blend_cache", "unity_cache", "unity_gi",
        ):
            assert not os.path.exists(files[key]), key

        info = _tree(basic_root)
        missing = build_target_paths(info["env"])
        for key in (
            "adobe_caches", "tiktok_cache", "viber_cache", "teams_cache",
            "blender_caches", "unity_caches",
        ):
            assert missing[key] == [], key

        ui = open(os.path.join(os.path.dirname(__file__), "ui", "main_window.py"), encoding="utf-8").read()
        preview_ui = open(os.path.join(os.path.dirname(__file__), "ui", "c_drive_preview_dialog.py"), encoding="utf-8").read()
        module = open(os.path.join(os.path.dirname(__file__), "core", "c_drive_clean.py"), encoding="utf-8").read()
        assert "TARGET_GROUPS" in ui
        assert "spin_min_clean_mb" in ui
        assert "only_keys" in ui
        assert "c_drive_min_clean_mb" in ui
        assert "Discord, Telegram, Zalo, Messenger" in ui
        assert "selected_keys" in preview_ui
        assert "dưới ngưỡng" in preview_ui
        assert "Dọn ngay" in preview_ui
        assert "chưa xóa" in preview_ui.lower()
        assert "runas" not in module.lower()
        assert "shellexecute" not in module.lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(basic_root, ignore_errors=True)


def test_exclude_paths_downloads_age_and_recycle_bin():
    from core.c_drive_clean import (
        RECYCLE_SIZE_UNKNOWN_VI,
        delete_large_files,
        estimate_reclaimable,
        normalize_exclude_paths,
        path_is_excluded,
        scan_large_user_files,
    )
    import core.c_drive_clean as mod

    assert normalize_exclude_paths(["relative\\keep", "", None]) == []
    root = tempfile.mkdtemp(prefix="pca-exclude-")
    try:
        info = _tree(root)
        keep_dir = os.path.join(info["temp"], "Keep")
        _write(os.path.join(keep_dir, "secret.bin"), b"K" * 40)
        _write(os.path.join(info["temp"], "KeepExtra", "still.bin"), b"E" * 12)
        old_keep = os.path.join(info["home"], "Downloads", "Keep", "archive.bin")
        _write(old_keep, b"D" * 20)
        os.utime(old_keep, (info["now"] - 40 * 86400, info["now"] - 40 * 86400))
        onedrive_old = os.path.join(info["home"], "Downloads", "OneDrive Backup", "cloud.bin")
        _write(onedrive_old, b"C" * 9)
        os.utime(onedrive_old, (info["now"] - 40 * 86400, info["now"] - 40 * 86400))
        reparse_old = os.path.join(info["home"], "Downloads", "Junction", "link.bin")
        _write(reparse_old, b"R" * 8)
        os.utime(reparse_old, (info["now"] - 40 * 86400, info["now"] - 40 * 86400))

        exclude = [keep_dir.lower(), os.path.join(info["home"], "Downloads", "Keep")]
        assert path_is_excluded(os.path.join(keep_dir, "secret.bin"), exclude)
        assert not path_is_excluded(os.path.join(info["temp"], "KeepExtra", "still.bin"), exclude)

        scan = JunkCleaner.scan(
            {"user_temp": True, "downloads_old": True},
            is_admin=False,
            environ=info["env"],
            now_ts=info["now"],
            downloads_min_age_days=30,
            exclude_paths=exclude,
        )
        # keep.tmp 100 + KeepExtra 12. Excluded Keep/secret.bin (40) is not sized.
        assert scan["categories"]["user_temp"]["size_bytes"] == 100 + 12

        real_reparse = mod._is_reparse_point

        def fake_reparse(path):
            if os.path.basename(path) == "Junction" or path.endswith(os.path.join("Downloads", "Junction")):
                return True
            return real_reparse(path)

        mod._is_reparse_point = fake_reparse
        try:
            preview = estimate_reclaimable(
                {"user_temp": True, "downloads_old": True, "recycle_bin": False},
                is_admin=False,
                deep_user_safe=True,
                environ=info["env"],
                now_ts=info["now"],
                downloads_min_age_days=30,
                exclude_paths=exclude,
            )
            ready = {row["key"]: row for row in preview["targets"] if row["status"] == "ready"}
            assert ready["downloads_old"]["reclaimable_bytes"] == 70 + 15
            assert ready["downloads_old"]["reclaimable_files"] == 2
            assert "cũ hơn 30 ngày" in preview["preview_vi"]
            assert any(path.lower().endswith(os.path.join("temp", "keep").lower()) or "Keep" in path for path in preview["excluded_paths"])
            assert "Đã bỏ qua" in preview["preview_vi"]

            result = JunkCleaner.clean(
                {"user_temp": True, "downloads_old": True},
                is_admin=False,
                environ=info["env"],
                now_ts=info["now"],
                downloads_min_age_days=30,
                exclude_paths=exclude,
            )
        finally:
            mod._is_reparse_point = real_reparse

        assert os.path.exists(os.path.join(keep_dir, "secret.bin"))
        assert os.path.exists(old_keep)
        assert os.path.exists(onedrive_old)
        assert os.path.exists(reparse_old)
        assert os.path.exists(os.path.join(info["home"], "Downloads", "new.bin"))
        assert not os.path.exists(os.path.join(info["temp"], "keep.tmp"))
        assert not os.path.exists(os.path.join(info["temp"], "KeepExtra", "still.bin"))
        assert not os.path.exists(os.path.join(info["home"], "Downloads", "old.bin"))
        assert result["details"]["user_temp"]["freed_bytes"] == 100 + 12
        assert result["details"]["downloads_old"]["freed_bytes"] == 70 + 15

        big_keep = os.path.join(info["home"], "Documents")
        os.makedirs(big_keep, exist_ok=True)
        kept = os.path.join(big_keep, "video.bin")
        other = os.path.join(info["home"], "video-ok.bin")
        _write(kept, b"V" * 200)
        _write(other, b"V" * 180)
        found = scan_large_user_files(
            environ=info["env"],
            min_bytes=100,
            max_depth=3,
            max_seconds=5,
            exclude_paths=[big_keep],
        )
        paths = [row["path"] for row in found["files"]]
        assert other in paths
        assert kept not in paths
        blocked = delete_large_files([kept, other], environ=info["env"], exclude_paths=[big_keep])
        assert os.path.exists(kept)
        assert not os.path.exists(other)
        assert blocked["freed_bytes"] == 180

        unknown = estimate_reclaimable(
            {"recycle_bin": True, "user_temp": False, "downloads_old": False},
            is_admin=False,
            deep_user_safe=False,
            environ=info["env"],
            recycle_info={"size_known": False},
        )
        recycle_rows = [row for row in unknown["targets"] if row["key"] == "recycle_bin"]
        assert recycle_rows and recycle_rows[0]["size_unknown"] is True
        assert recycle_rows[0]["reclaimable_bytes"] == 0
        assert unknown["total_bytes"] == 0
        assert RECYCLE_SIZE_UNKNOWN_VI in unknown["preview_vi"]
        shown = [row["key"] for row in __import__("core.c_drive_clean", fromlist=["preview_rows_for_display"]).preview_rows_for_display(unknown)]
        assert "recycle_bin" in shown

        calls = []

        def _empty():
            calls.append("bin")
            return {"success": True, "freed_bytes": 64, "items": 1}

        cleaned = JunkCleaner.clean(
            {"recycle_bin": True, "user_temp": False},
            is_admin=False,
            environ=info["env"],
            recycle_empty=_empty,
            exclude_paths=exclude,
        )
        assert calls == ["bin"]
        assert cleaned["total_freed_bytes"] == 64
        assert cleaned["details"]["recycle_bin"]["status"] == "cleaned"
    finally:
        shutil.rmtree(root, ignore_errors=True)

    ui = open(os.path.join(os.path.dirname(__file__), "ui", "main_window.py"), encoding="utf-8").read()
    preview_ui = open(os.path.join(os.path.dirname(__file__), "ui", "c_drive_preview_dialog.py"), encoding="utf-8").read()
    assert "Không bao giờ quét hoặc xóa" in ui
    assert "c_drive_exclude_paths" in ui
    assert "Chọn thư mục" in ui
    assert "spin_downloads_age" in preview_ui
    assert "chưa ước lượng được dung lượng" in preview_ui
    assert "Đã bỏ qua" in preview_ui


def test_ui_exposes_deep_clean_and_admin_label():
    base = os.path.dirname(__file__)
    text = open(os.path.join(base, "ui", "main_window.py"), encoding="utf-8").read()
    preview = open(os.path.join(base, "ui", "c_drive_preview_dialog.py"), encoding="utf-8").read()
    assert "Dọn ổ C (không cần Admin)" in text
    assert "Quét ổ C" in text
    assert "Cần Admin" in text
    assert "start_deep_c_clean" in text
    assert "start_deep_c_preview" in text
    assert "deep_preview" in text
    assert "Dọn ngay" in preview
    assert "chưa xóa" in preview.lower() or "Chưa xóa" in preview
    assert "Tìm file lớn" in text
    assert "Dọn sâu (cần Admin)" in text
    assert "start_admin_deep_clean" in text
    assert ADMIN_DEEP_DISABLED_VI.split(".")[0] in text or "ADMIN_DEEP_DISABLED_VI" in text
    admin_handler = text.split("def start_admin_deep_clean")[1].split("\n    def ")[0]
    assert "ShellExecute" not in admin_handler
    assert "runas" not in admin_handler.lower()
    assert "Lần dọn gần đây" in text
    assert "open_large_file_finder" in text
    assert "append_clean_history" in text
    assert "scan_large_user_files" not in text
    finder = open(os.path.join(base, "ui", "large_file_finder_dialog.py"), encoding="utf-8").read()
    assert "Xác nhận xóa file lớn" in finder
    assert "setChecked(False)" in finder
    assert "Quét thêm LocalAppData" in finder
    assert "delete_large_files" in finder
    scheduler = open(os.path.join(base, "core", "scheduler.py"), encoding="utf-8").read()
    assert "low_disk_warning" in scheduler
    assert "LowDiskToastGate" in scheduler


def test_v7_profile_caches_and_performance_preset():
    """WhatsApp/Signal/Skype/OBS/Zoom sâu, DaVinci và Flutter tắt mặc định, preset hiệu năng."""
    from core.c_drive_clean import (
        DAVINCI_OFFER_MIN_MB,
        DEV_BUILD_OFFER_MIN_MB,
        OBS_LOG_MIN_AGE_DAYS,
        apply_performance_preset,
        performance_priority_keys,
        target_group_id,
        target_group_label_vi,
    )

    assert APP_VERSION == "3.8.6"
    grouped = [key for _group_id, _label, keys in TARGET_GROUPS for key in keys]
    assert set(grouped) == set(TARGET_ORDER)
    for key, enabled, group in (
        ("whatsapp_cache", True, "chat"),
        ("signal_cache", True, "chat"),
        ("skype_cache", True, "chat"),
        ("zoom_cache", True, "apps"),
        ("obs_cache", True, "apps"),
        ("davinci_caches", False, "creative"),
        ("flutter_android_caches", False, "dev_tools"),
    ):
        meta = TARGET_CATALOG[key]
        assert meta["needs_admin"] is False
        assert meta["default_enabled"] is enabled
        assert DEFAULT_CONFIG["targets"][key] is enabled
        assert target_group_id(key) == group
        assert target_group_label_vi(key)
        if not enabled:
            assert "tắt mặc định" in meta["label_vi"]
    assert TARGET_CATALOG["davinci_caches"]["offer_min_mb"] == DAVINCI_OFFER_MIN_MB == 256
    assert TARGET_CATALOG["flutter_android_caches"]["offer_min_mb"] == DEV_BUILD_OFFER_MIN_MB == 100
    assert TARGET_CATALOG["obs_cache"]["log_min_age_days"] == OBS_LOG_MIN_AGE_DAYS == 7
    assert TARGET_CATALOG["recycle_bin"]["default_enabled"] is False
    assert "whatsapp_cache" in performance_priority_keys()
    assert "obs_cache" in performance_priority_keys()
    assert "davinci_caches" not in performance_priority_keys()
    assert "flutter_android_caches" not in performance_priority_keys()
    assert "recycle_bin" not in performance_priority_keys()
    assert "system_temp" not in performance_priority_keys()
    preset = apply_performance_preset({
        "recycle_bin": True,
        "downloads_old": True,
        "davinci_caches": True,
        "flutter_android_caches": True,
        "adobe_caches": True,
        "nuget_packages": True,
        "steam_caches": True,
        "system_temp": True,
        "windows_update": True,
        "whatsapp_cache": False,
        "ram_optimize": False,
    })
    assert preset["whatsapp_cache"] is True
    assert preset["signal_cache"] is True
    assert preset["skype_cache"] is True
    assert preset["zoom_cache"] is True
    assert preset["obs_cache"] is True
    assert preset["user_temp"] is True
    assert preset["browser_cache"] is True
    assert preset["discord_cache"] is True
    assert preset["recycle_bin"] is False
    assert preset["downloads_old"] is False
    assert preset["davinci_caches"] is False
    assert preset["flutter_android_caches"] is False
    assert preset["adobe_caches"] is False
    assert preset["nuget_packages"] is False
    assert preset["steam_caches"] is False
    assert preset["empty_user_folders"] is False
    assert preset["system_temp"] is False
    assert preset["windows_update"] is False
    assert preset["ram_optimize"] is True

    small_davinci = {
        "key": "davinci_caches",
        "status": "ready",
        "reclaimable_bytes": 200 * 1024 * 1024,
        "reclaimable_files": 2,
    }
    large_davinci = {
        "key": "davinci_caches",
        "status": "ready",
        "reclaimable_bytes": 300 * 1024 * 1024,
        "reclaimable_files": 2,
    }
    assert category_offered_by_default(small_davinci, 0) is False
    assert category_offered_by_default(large_davinci, 0) is True
    assert category_offered_by_default(large_davinci, 400) is False
    assert category_offered_by_default(
        {"key": "flutter_android_caches", "status": "ready", "reclaimable_bytes": 50 * 1024 * 1024, "reclaimable_files": 1},
        0,
    ) is False
    assert category_offered_by_default(
        {"key": "whatsapp_cache", "status": "ready", "reclaimable_bytes": 11 * 1024 * 1024, "reclaimable_files": 1},
        10,
    ) is True

    root = tempfile.mkdtemp(prefix="pca-v7-")
    basic_root = tempfile.mkdtemp(prefix="pca-v7-missing-")
    try:
        home = os.path.join(root, "Users", "alice")
        local = os.path.join(home, "AppData", "Local")
        roaming = os.path.join(home, "AppData", "Roaming")
        windows = os.path.join(root, "Windows")
        program_files = os.path.join(root, "Program Files")
        now = 1_700_000_000

        def put(path, payload, age_days=None):
            _write(path, payload)
            if age_days is not None:
                stamp = now - int(age_days) * 86400
                os.utime(path, (stamp, stamp))
            return path

        files = {
            "wa_cache": put(os.path.join(roaming, "WhatsApp", "Cache", "a.bin"), b"W" * 11),
            "wa_gpu": put(os.path.join(local, "WhatsApp", "GPUCache", "g.bin"), b"W" * 12),
            "wa_idb": put(os.path.join(roaming, "WhatsApp", "IndexedDB", "idb.bin"), b"I" * 40),
            "wa_state": put(
                os.path.join(local, "Packages", "5319275A.WhatsAppDesktop_abc", "LocalState", "Cache", "keep.bin"),
                b"K" * 33,
            ),
            "wa_temp": put(
                os.path.join(local, "Packages", "5319275A.WhatsAppDesktop_abc", "TempState", "t.bin"),
                b"W" * 13,
            ),
            "sig_cache": put(os.path.join(roaming, "Signal", "Cache", "s.bin"), b"S" * 14),
            "sig_sql": put(os.path.join(roaming, "Signal", "sql", "db.sqlite"), b"Q" * 200),
            "sig_att": put(os.path.join(roaming, "Signal", "attachments.noindex", "photo.bin"), b"A" * 80),
            "sky_cache": put(
                os.path.join(roaming, "Microsoft", "Skype for Desktop", "Code Cache", "c.bin"),
                b"Y" * 15,
            ),
            "sky_db": put(os.path.join(roaming, "Skype", "live_user", "main.db"), b"D" * 90),
            "sky_idb": put(
                os.path.join(roaming, "Microsoft", "Skype for Desktop", "IndexedDB", "idb.bin"),
                b"I" * 28,
            ),
            "sky_pkg": put(
                os.path.join(local, "Packages", "Microsoft.SkypeApp_kzf8qxf38zg5c", "TempState", "p.bin"),
                b"Y" * 16,
            ),
            "zoom_log": put(os.path.join(roaming, "Zoom", "logs", "z.log"), b"Z" * 3),
            "zoom_web": put(os.path.join(roaming, "Zoom", "data", "WebviewCache", "w.bin"), b"Z" * 21),
            "zoom_wait": put(os.path.join(roaming, "Zoom", "data", "WaitingRoom", "r.bin"), b"Z" * 4),
            "zoom_custom": put(
                os.path.join(roaming, "Zoom", "data", "VirtualBkgnd_Custom", "Cache", "me.jpg"),
                b"C" * 50,
            ),
            "zoom_default": put(
                os.path.join(roaming, "Zoom", "data", "VirtualBkgnd_Default", "stock.jpg"),
                b"Z" * 6,
            ),
            "obs_old": put(os.path.join(roaming, "obs-studio", "logs", "old.log"), b"O" * 17, age_days=10),
            "obs_new": put(os.path.join(roaming, "obs-studio", "logs", "new.log"), b"O" * 18, age_days=1),
            "obs_cache": put(
                os.path.join(roaming, "obs-studio", "plugin_config", "obs-browser", "Cache", "b.bin"),
                b"B" * 19,
                age_days=1,
            ),
            "obs_scene": put(os.path.join(roaming, "obs-studio", "basic", "scenes", "live.json"), b"N" * 60),
            "obs_plug": put(
                os.path.join(roaming, "obs-studio", "plugin_config", "obs-websocket", "config.json"),
                b"P" * 22,
            ),
            "cursor": put(os.path.join(roaming, "Cursor", "Cache", "c.bin"), b"R" * 8),
            "figma": put(os.path.join(roaming, "Figma", "Cache", "f.bin"), b"F" * 9),
            "dv_cache": put(
                os.path.join(local, "Blackmagic Design", "DaVinci Resolve", "Cache", "c.bin"),
                b"V" * 31,
            ),
            "dv_log_old": put(
                os.path.join(roaming, "Blackmagic Design", "DaVinci Resolve", "Support", "logs", "old.log"),
                b"V" * 5,
                age_days=10,
            ),
            "dv_log_new": put(
                os.path.join(roaming, "Blackmagic Design", "DaVinci Resolve", "Support", "logs", "new.log"),
                b"V" * 6,
                age_days=1,
            ),
            "dv_db": put(
                os.path.join(
                    roaming, "Blackmagic Design", "DaVinci Resolve", "Support",
                    "Resolve Disk Database", "db.bin",
                ),
                b"D" * 70,
            ),
            "dv_pf": put(
                os.path.join(program_files, "Blackmagic Design", "DaVinci Resolve", "Cache", "pf.bin"),
                b"P" * 99,
            ),
            "pub": put(os.path.join(local, "Pub", "Cache", "hosted", "pkg.bin"), b"U" * 23),
            "android_cache": put(os.path.join(home, ".android", "cache", "a.bin"), b"A" * 24),
            "android_sdk": put(os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"), b"E" * 40),
            "avd": put(os.path.join(home, ".android", "avd", "pixel", "disk.img"), b"M" * 80),
            "flutter_bin": put(os.path.join(home, "flutter", "bin", "cache", "engine.bin"), b"L" * 25),
            "fvm": put(os.path.join(home, "fvm", "versions", "3.24.0", "bin", "cache", "dart.bin"), b"L" * 7),
            "go": put(os.path.join(local, "go-build", "b.bin"), b"G" * 26),
            "gradle": put(os.path.join(home, ".gradle", "caches", "modules.bin"), b"H" * 27),
            "flutter_pf": put(os.path.join(program_files, "flutter", "bin", "cache", "nope.bin"), b"N" * 44),
        }
        env = {
            "USERPROFILE": home,
            "LOCALAPPDATA": local,
            "APPDATA": roaming,
            "TEMP": os.path.join(local, "Temp"),
            "SystemRoot": windows,
        }
        os.makedirs(env["TEMP"], exist_ok=True)
        paths = build_target_paths(env)
        flat = [path for group in paths.values() for path in group]
        for path in flat:
            parts = _path_parts(path)
            assert "winsxs" not in parts
            assert "indexeddb" not in parts
            assert "localstate" not in parts
            assert "sql" not in parts
            assert "attachments.noindex" not in parts
            assert not path_is_forbidden(path)
        assert any(path.endswith(os.path.join("WhatsApp", "Cache")) for path in paths["whatsapp_cache"])
        assert any(path.endswith(os.path.join("WhatsApp", "GPUCache")) for path in paths["whatsapp_cache"])
        assert any("5319275a.whatsappdesktop_" in path.lower() and path.endswith("TempState") for path in paths["whatsapp_cache"])
        assert not any("localstate" in _path_parts(path) for path in paths["whatsapp_cache"])
        assert any(path.endswith(os.path.join("Signal", "Cache")) for path in paths["signal_cache"])
        assert not any("sql" in _path_parts(path) or "attachments.noindex" in _path_parts(path) for path in flat)
        assert any(path.endswith(os.path.join("Skype for Desktop", "Code Cache")) for path in paths["skype_cache"])
        assert any("microsoft.skypeapp_" in path.lower() and path.endswith("TempState") for path in paths["skype_cache"])
        assert not any(path.endswith("main.db") for path in flat)
        assert any(path.endswith(os.path.join("Zoom", "logs")) for path in paths["app_caches"])
        assert not any(path.endswith(os.path.join("Zoom", "logs")) for path in paths["zoom_cache"])
        assert any(path.endswith("WebviewCache") for path in paths["zoom_cache"])
        assert any(path.endswith("WaitingRoom") for path in paths["zoom_cache"])
        assert any(path.endswith("VirtualBkgnd_Default") for path in paths["zoom_cache"])
        assert not any("virtualbkgnd_custom" in _path_parts(path) for path in flat)
        assert any(path.endswith(os.path.join("obs-studio", "logs")) for path in paths["obs_cache"])
        assert any(path.endswith(os.path.join("obs-browser", "Cache")) for path in paths["obs_cache"])
        assert not any("scenes" in _path_parts(path) for path in flat)
        assert not any(path.endswith("config.json") for path in paths["obs_cache"])
        assert any(path.endswith(os.path.join("Cursor", "Cache")) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("Figma", "Cache")) for path in paths["app_caches"])
        assert any(path.endswith(os.path.join("DaVinci Resolve", "Cache")) for path in paths["davinci_caches"])
        assert any(path.endswith(os.path.join("Support", "logs")) for path in paths["davinci_caches"])
        assert not any("resolve disk database" in _path_parts(path) for path in flat)
        assert not any("program files" in _path_parts(path) for path in paths["davinci_caches"])
        assert any(path.endswith(os.path.join("Pub", "Cache")) for path in paths["flutter_android_caches"])
        assert any(path.endswith(os.path.join(".android", "cache")) for path in paths["flutter_android_caches"])
        assert any(path.endswith(os.path.join("flutter", "bin", "cache")) for path in paths["flutter_android_caches"])
        assert any("3.24.0" in _path_parts(path) and path.endswith("cache") for path in paths["flutter_android_caches"])
        assert any(path.endswith("go-build") for path in paths["flutter_android_caches"])
        assert not any("sdk" in _path_parts(path) and "android" in _path_parts(path) for path in paths["flutter_android_caches"])
        assert not any("avd" in _path_parts(path) for path in flat)
        assert not any("program files" in _path_parts(path) for path in paths["flutter_android_caches"])
        assert any(path.endswith(os.path.join(".gradle", "caches")) for path in paths["gradle_caches"])
        assert not any(".gradle" in _path_parts(path) for path in paths["flutter_android_caches"])

        flags = default_target_flags()
        plan = resolve_clean_plan(flags, is_admin=False, deep_user_safe=True)
        assert "whatsapp_cache" in plan["to_run"]
        assert "signal_cache" in plan["to_run"]
        assert "skype_cache" in plan["to_run"]
        assert "zoom_cache" in plan["to_run"]
        assert "obs_cache" in plan["to_run"]
        assert "davinci_caches" not in plan["to_run"]
        assert "flutter_android_caches" not in plan["to_run"]
        assert "recycle_bin" not in plan["to_run"]
        assert "system_temp" not in plan["to_run"]
        scan = estimate_reclaimable(
            flags, is_admin=False, deep_user_safe=True, environ=env, now_ts=now,
        )
        ready = {row["key"]: row for row in scan["targets"] if row["status"] == "ready"}
        assert ready["whatsapp_cache"]["group_vi"] == "Chat"
        assert ready["whatsapp_cache"]["reclaimable_bytes"] == 11 + 12 + 13
        assert ready["signal_cache"]["reclaimable_bytes"] == 14
        assert ready["skype_cache"]["reclaimable_bytes"] == 15 + 16
        assert ready["zoom_cache"]["reclaimable_bytes"] == 21 + 4 + 6
        assert ready["obs_cache"]["reclaimable_bytes"] == 17 + 19
        assert ready["obs_cache"]["log_min_age_days"] == 7
        assert "log chỉ tính khi cũ hơn 7 ngày" in scan["preview_vi"]
        assert "[Chat]" in scan["preview_vi"] or "Cache WhatsApp" in scan["preview_vi"]
        assert ready["app_caches"]["reclaimable_bytes"] == 3 + 8 + 9
        assert "davinci_caches" not in ready
        assert "flutter_android_caches" not in ready
        assert os.path.exists(files["obs_new"])
        assert os.path.exists(files["sig_sql"])

        exclude = [os.path.join(roaming, "WhatsApp", "Cache")]
        excluded = estimate_reclaimable(
            flags,
            is_admin=False,
            deep_user_safe=True,
            environ=env,
            now_ts=now,
            exclude_paths=exclude,
        )
        excluded_ready = {row["key"]: row for row in excluded["targets"] if row["status"] == "ready"}
        assert excluded_ready["whatsapp_cache"]["reclaimable_bytes"] == 12 + 13

        opted = dict(flags)
        opted["davinci_caches"] = True
        opted["flutter_android_caches"] = True
        opted_scan = estimate_reclaimable(
            opted, is_admin=False, deep_user_safe=True, environ=env, now_ts=now,
        )
        opted_ready = {row["key"]: row for row in opted_scan["targets"] if row["status"] == "ready"}
        assert opted_ready["davinci_caches"]["reclaimable_bytes"] == 31 + 5
        assert opted_ready["flutter_android_caches"]["reclaimable_bytes"] == 23 + 24 + 25 + 7 + 26
        assert opted_ready["davinci_caches"]["group_vi"] == "Đồ họa"

        obs_only = JunkCleaner.clean(
            opted,
            is_admin=False,
            deep_user_safe=True,
            environ=env,
            now_ts=now,
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 0},
            only_keys=["obs_cache"],
        )
        assert obs_only["total_freed_bytes"] == 17 + 19
        assert not os.path.exists(files["obs_old"])
        assert not os.path.exists(files["obs_cache"])
        assert os.path.exists(files["obs_new"])
        assert os.path.exists(files["obs_scene"])
        assert os.path.exists(files["obs_plug"])
        assert os.path.exists(files["wa_cache"])

        chat = JunkCleaner.clean(
            opted,
            is_admin=False,
            environ=env,
            now_ts=now,
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 0},
            only_keys=["whatsapp_cache", "signal_cache", "skype_cache", "zoom_cache"],
        )
        assert chat["total_freed_bytes"] == (11 + 12 + 13) + 14 + (15 + 16) + (21 + 4 + 6)
        for key in ("wa_idb", "wa_state", "sig_sql", "sig_att", "sky_db", "sky_idb", "zoom_custom", "zoom_log"):
            assert os.path.exists(files[key]), key
        for key in ("wa_cache", "wa_gpu", "wa_temp", "sig_cache", "sky_cache", "sky_pkg", "zoom_web", "zoom_wait", "zoom_default"):
            assert not os.path.exists(files[key]), key

        heavy = JunkCleaner.clean(
            opted,
            is_admin=False,
            environ=env,
            now_ts=now,
            disk_free_bytes=lambda: None,
            recycle_empty=lambda: {"success": False, "freed_bytes": 1, "items": 0},
            only_keys=["davinci_caches", "flutter_android_caches", "app_caches"],
        )
        assert heavy["total_freed_bytes"] == (31 + 5) + (23 + 24 + 25 + 7 + 26) + (3 + 8 + 9)
        assert os.path.exists(files["dv_log_new"])
        assert os.path.exists(files["dv_db"])
        assert os.path.exists(files["dv_pf"])
        assert os.path.exists(files["android_sdk"])
        assert os.path.exists(files["avd"])
        assert os.path.exists(files["gradle"])
        assert os.path.exists(files["flutter_pf"])
        assert not os.path.exists(files["dv_cache"])
        assert not os.path.exists(files["dv_log_old"])
        assert not os.path.exists(files["pub"])
        assert not os.path.exists(files["go"])
        assert not os.path.exists(files["cursor"])

        info = _tree(basic_root)
        missing = build_target_paths(info["env"])
        for key in (
            "whatsapp_cache", "signal_cache", "skype_cache", "zoom_cache",
            "obs_cache", "davinci_caches", "flutter_android_caches",
        ):
            assert missing[key] == [], key

        ui = open(os.path.join(os.path.dirname(__file__), "ui", "main_window.py"), encoding="utf-8").read()
        module = open(os.path.join(os.path.dirname(__file__), "core", "c_drive_clean.py"), encoding="utf-8").read()
        assert "Ưu tiên hiệu năng" in ui
        assert "_apply_performance_preset" in ui
        assert "WhatsApp, Signal, Skype" in ui
        assert "runas" not in module.lower()
        assert "shellexecute" not in module.lower()
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(basic_root, ignore_errors=True)


def _run():
    tests = [
        test_version_stays_387,
        test_catalog_defaults_match_config,
        test_paths_stay_inside_current_user_and_skip_protected,
        test_non_admin_skips_system_targets_and_counts_only_deleted_bytes,
        test_admin_cleans_system_temp_and_counts_it,
        test_deep_user_safe_maximizes_caches_but_not_downloads_or_admin,
        test_downloads_old_only_when_enabled_and_only_old_files,
        test_locked_file_is_not_counted,
        test_partial_directory_delete_counts_only_removed_bytes,
        test_symlink_is_unlinked_without_deleting_the_target,
        test_failed_recycle_bin_does_not_invent_freed_bytes,
        test_low_disk_threshold_and_toast_cooldown,
        test_expanded_user_safe_paths_scan_without_deleting,
        test_forbidden_and_sync_root_stay_blocked,
        test_deep_report_shows_free_space_delta_and_claimed_bytes,
        test_toolchain_caches_use_safe_defaults_and_skip_package_stores,
        test_large_file_scan_does_not_delete_until_confirmed_paths,
        test_clean_history_round_trip,
        test_admin_deep_plan_respects_elevation_and_forbidden_paths,
        test_chat_gpu_launcher_and_empty_folders_do_not_double_count,
        test_v5_caches_groups_sort_and_min_size_filter,
        test_v7_profile_caches_and_performance_preset,
        test_exclude_paths_downloads_age_and_recycle_bin,
        test_ui_exposes_deep_clean_and_admin_label,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f" [PASS] {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f" [FAIL] {test.__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} test(s) failed")
    print(f"All {len(tests)} c-drive cleanup tests passed.")


if __name__ == "__main__":
    _run()
