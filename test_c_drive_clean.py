"""
Dọn ổ C không cần Admin: chọn mục, bỏ qua mục Admin, cộng byte thật.
Chạy được trên Linux CI — không cần quyền Administrator.
"""
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
    ADMIN_SKIP_REASON_VI,
    SYNC_ROOT_REASON_VI,
    LowDiskToastGate,
    TARGET_CATALOG,
    TARGET_ORDER,
    append_clean_history,
    build_low_disk_notice,
    build_target_paths,
    clean_one_path,
    default_target_flags,
    delete_large_files,
    estimate_reclaimable,
    format_clean_history_vi,
    is_disk_space_low,
    is_process_elevated,
    load_clean_history,
    path_is_forbidden,
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


def test_version_stays_386():
    assert APP_VERSION == "3.8.6"


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


def _run():
    tests = [
        test_version_stays_386,
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
