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
    LowDiskToastGate,
    TARGET_CATALOG,
    build_low_disk_notice,
    build_target_paths,
    default_target_flags,
    is_disk_space_low,
    is_process_elevated,
    path_is_forbidden,
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


def test_version_stays_385():
    assert APP_VERSION == "3.8.5"


def test_catalog_defaults_match_config():
    flags = default_target_flags()
    assert DEFAULT_CONFIG["targets"] == flags
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


def test_ui_exposes_deep_clean_and_admin_label():
    text = open(os.path.join(os.path.dirname(__file__), "ui", "main_window.py"), encoding="utf-8").read()
    assert "Dọn ổ C (không cần Admin)" in text
    assert "Cần Admin" in text
    assert "start_deep_c_clean" in text
    scheduler = open(os.path.join(os.path.dirname(__file__), "core", "scheduler.py"), encoding="utf-8").read()
    assert "low_disk_warning" in scheduler
    assert "LowDiskToastGate" in scheduler


def _run():
    tests = [
        test_version_stays_385,
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
