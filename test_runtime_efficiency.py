"""
Runtime efficiency: RAM readout, HKCU/Startup toggles, safe lighten preset.
Stubs Windows-only bits so this file can run on Linux CI.
"""
import os
import sys
import tempfile
import types

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "winreg" not in sys.modules:
        winreg = types.ModuleType("winreg")
        winreg.HKEY_CURRENT_USER = 1
        winreg.HKEY_LOCAL_MACHINE = 2
        winreg.KEY_READ = 0
        winreg.KEY_WRITE = 0
        winreg.KEY_SET_VALUE = 0
        winreg.KEY_ALL_ACCESS = 0
        winreg.REG_DWORD = 4
        winreg.REG_SZ = 1
        winreg.REG_EXPAND_SZ = 2
        winreg.KEY_WOW64_64KEY = 0x0100

        def _missing(*_a, **_k):
            raise FileNotFoundError("winreg stub")

        winreg.OpenKey = _missing
        winreg.CreateKey = _missing
        winreg.CreateKeyEx = _missing
        winreg.CloseKey = lambda *_a, **_k: None
        winreg.QueryValueEx = _missing
        winreg.SetValueEx = _missing
        winreg.DeleteValue = _missing
        winreg.EnumKey = _missing
        winreg.EnumValue = _missing
        winreg.error = OSError
        sys.modules["winreg"] = winreg
    import ctypes
    if not hasattr(ctypes, "windll"):
        class _P:
            def __getattr__(self, _n):
                return _P()
            def __call__(self, *_a, **_k):
                return 0
        ctypes.windll = _P()  # type: ignore


from app_meta import APP_VERSION
from core.memory_optimizer import (
    BUSY_CPU_SKIP_PERCENT,
    MemoryOptimizer,
    format_ram_report_vi,
)
from core.runtime_lighten import USER_SAFE_QUICK_CLEAN, confirm_text_vi, run_lighten
from startup_manager import (
    HKCU_DISABLED_RUN_PATH,
    HKCU_RUN_PATH,
    IMPACT_UNKNOWN_VI,
    list_user_startup_entries,
    set_user_startup_enabled,
)


class _Mem:
    def __init__(self, available, total, percent):
        self.available = available
        self.total = total
        self.percent = percent


class _Proc:
    def __init__(self, pid, name, rss, cpu=0.0):
        self.pid = pid
        self.info = {
            "pid": pid,
            "name": name,
            "cpu_percent": cpu,
            "memory_info": types.SimpleNamespace(rss=rss),
        }


class _FakeReg:
    def __init__(self, store=None):
        self.store = store if store is not None else {
            HKCU_RUN_PATH: {},
            HKCU_DISABLED_RUN_PATH: {},
        }
        self.paths = []
        self.fail_set_path = None

    def list_values(self, path):
        self.paths.append(path)
        data = self.store.get(path, {})
        return [(name, value, 1) for name, value in data.items()]

    def set_value(self, path, name, value, typ=None):
        if self.fail_set_path and path == self.fail_set_path:
            raise OSError("write denied")
        self.store.setdefault(path, {})[name] = value

    def delete_value(self, path, name):
        self.store.get(path, {}).pop(name, None)


def _samples(before_mb, after_mb):
    seq = [
        _Mem(before_mb * 1024 ** 2, 8 * 1024 ** 3, 70.0),
        _Mem(after_mb * 1024 ** 2, 8 * 1024 ** 3, 60.0),
    ]

    def read():
        return seq.pop(0)

    return read


def test_version_stays_386():
    assert APP_VERSION == "3.8.6"


def test_no_undocumented_standby_purge():
    path = os.path.join(os.path.dirname(__file__), "core", "memory_optimizer.py")
    text = open(path, encoding="utf-8").read()
    assert "ntdll" not in text
    assert "MemoryPurgeStandbyList" not in text
    assert "EmptyWorkingSet" in text
    startup = open(os.path.join(os.path.dirname(__file__), "startup_manager.py"), encoding="utf-8").read()
    assert "HKEY_LOCAL_MACHINE" not in startup


def test_ram_report_shows_before_after_and_skips():
    MemoryOptimizer.reset_for_tests()
    opened = []

    def open_process(pid):
        opened.append(pid)
        return pid

    def empty(_handle):
        return True

    procs = [
        _Proc(10, "chrome.exe", 30 * 1024 ** 2, cpu=1.0),
        _Proc(11, "obs64.exe", 40 * 1024 ** 2, cpu=1.0),
        _Proc(12, "explorer.exe", 80 * 1024 ** 2, cpu=1.0),
        _Proc(13, "tiny.exe", 1024, cpu=0.0),
        _Proc(14, "busy.exe", 50 * 1024 ** 2, cpu=BUSY_CPU_SKIP_PERCENT),
        _Proc(99, "self.exe", 50 * 1024 ** 2, cpu=0.0),
        _Proc(15, "notepad.exe", 20 * 1024 ** 2, cpu=0.0),
    ]
    res = MemoryOptimizer.optimize_ram(
        whitelist={"OBS64.EXE"},
        process_iter=lambda _attrs: procs,
        virtual_memory=_samples(1000, 1500),
        open_process=open_process,
        empty_working_set=empty,
        close_handle=lambda _h: None,
        current_pid=99,
    )
    assert res["success"] is True
    assert res["debounced"] is False
    assert res["available_before_mb"] == 1000.0
    assert res["available_after_mb"] == 1500.0
    assert res["freed_mb"] == 500.0
    assert opened == [10, 15]
    assert res["processes_flushed"] == 2
    assert res["skipped_whitelist"] == 1
    assert "obs64.exe" in res["skipped_whitelist_names"]
    assert res["skipped_protected"] == 1
    assert res["skipped_small"] == 1
    assert res["skipped_busy"] == 1
    report = format_ram_report_vi(res)
    assert "RAM trống (khả dụng) trước:" in report
    assert "RAM trống (khả dụng) sau:" in report
    assert "EmptyWorkingSet" in report
    assert "obs64.exe" in report
    assert "NtSetSystemInformation" in report
    assert "FPS" not in report


def test_ram_report_when_available_drops():
    text = format_ram_report_vi({
        "available_before_mb": 2000,
        "available_after_mb": 1500,
        "processes_flushed": 1,
        "debounced": True,
    })
    assert "Chưa đo lại" in text
    assert "dùng lại" in text


def test_ram_debounce_reuses_previous_readout():
    MemoryOptimizer.reset_for_tests()
    calls = {"n": 0}

    def vm():
        calls["n"] += 1
        return _Mem(2 * 1024 ** 3, 8 * 1024 ** 3, 50.0)

    kwargs = dict(
        process_iter=lambda _a: [],
        virtual_memory=vm,
        open_process=lambda _pid: None,
        empty_working_set=lambda _h: False,
        close_handle=lambda _h: None,
        current_pid=-1,
    )
    first = MemoryOptimizer.optimize_ram(**kwargs)
    second = MemoryOptimizer.optimize_ram(**kwargs)
    assert first["debounced"] is False
    assert second["debounced"] is True
    assert second["available_before_mb"] == first["available_before_mb"]
    assert calls["n"] == 2


def test_live_optimize_ram_returns_readout_without_crashing():
    MemoryOptimizer.reset_for_tests()
    res = MemoryOptimizer.optimize_ram(whitelist={"definitely-not-a-process.exe"})
    assert res["success"] is True
    assert "available_before_mb" in res and "available_after_mb" in res
    assert "không gọi NtSetSystemInformation" in res["note_vi"] or "NtSetSystemInformation" in res["note_vi"]


def test_startup_lists_hkcu_and_folder_with_unknown_impact():
    reg = _FakeReg({
        HKCU_RUN_PATH: {
            "OneDrive": r'"C:\Users\a\OneDrive.exe" /background',
            "PCAutoCleaner": r'"C:\App\PCAutoCleaner.exe" --minimized',
            "Gone": r"C:\missing\tool.exe",
        },
        HKCU_DISABLED_RUN_PATH: {
            "OldUpdater": r"C:\missing\old.exe",
            "OneDrive": r"should-not-duplicate",
        },
    })
    folder = tempfile.mkdtemp(prefix="startup-list-")
    open(os.path.join(folder, "Widget.lnk"), "w", encoding="utf-8").close()
    open(os.path.join(folder, "desktop.ini"), "w", encoding="utf-8").close()
    data = list_user_startup_entries(registry=reg, startup_dir=folder)
    assert reg.paths == [HKCU_RUN_PATH, HKCU_DISABLED_RUN_PATH]
    assert data["omitted_own_app"] is True
    by_name = {item["name"]: item for item in data["entries"]}
    assert "PCAutoCleaner" not in by_name
    assert by_name["OneDrive"]["enabled"] is True
    assert by_name["OneDrive"]["impact"] == IMPACT_UNKNOWN_VI
    assert by_name["OneDrive"]["source"] == "hkcu_run"
    assert by_name["Gone"]["target_exists"] is False
    assert "Không thấy file" in by_name["Gone"]["note_vi"]
    assert by_name["OldUpdater"]["enabled"] is False
    assert by_name["Widget.lnk"]["source"] == "startup_folder"
    assert by_name["Widget.lnk"]["impact"] == "không rõ"
    assert by_name["Widget.lnk"]["target_exists"] is None
    assert "desktop.ini" not in by_name
    assert all(item["impact"] == "không rõ" for item in data["entries"])
    assert "HKLM" in data["scope_vi"]
    assert "không rõ" in data["scope_vi"]


def test_startup_toggle_run_roundtrip_and_failed_write_keeps_original():
    reg = _FakeReg({
        HKCU_RUN_PATH: {"Notes": r"C:\Tools\notes.exe"},
        HKCU_DISABLED_RUN_PATH: {},
    })
    off = set_user_startup_enabled("hkcu:Notes", False, registry=reg, startup_dir=tempfile.gettempdir())
    assert off["success"] is True
    assert "Notes" not in reg.store[HKCU_RUN_PATH]
    assert reg.store[HKCU_DISABLED_RUN_PATH]["Notes"] == r"C:\Tools\notes.exe"
    on = set_user_startup_enabled("hkcu:Notes", True, registry=reg, startup_dir=tempfile.gettempdir())
    assert on["success"] is True
    assert reg.store[HKCU_RUN_PATH]["Notes"] == r"C:\Tools\notes.exe"
    assert "Notes" not in reg.store[HKCU_DISABLED_RUN_PATH]

    reg.store[HKCU_RUN_PATH]["Notes"] = r"C:\Tools\notes.exe"
    reg.fail_set_path = HKCU_DISABLED_RUN_PATH
    failed = set_user_startup_enabled("hkcu:Notes", False, registry=reg, startup_dir=tempfile.gettempdir())
    assert failed["success"] is False
    assert reg.store[HKCU_RUN_PATH]["Notes"] == r"C:\Tools\notes.exe"

    own = set_user_startup_enabled("hkcu:PCAutoCleaner", False, registry=reg, startup_dir=tempfile.gettempdir())
    assert own["success"] is False
    assert "Tự động" in own["message_vi"]


def test_startup_folder_toggle_roundtrip_and_rejects_escape():
    folder = tempfile.mkdtemp(prefix="startup-toggle-")
    outside = os.path.join(tempfile.gettempdir(), "pcac-outside-marker.txt")
    open(os.path.join(folder, "Helper.cmd"), "w", encoding="utf-8").close()
    reg = _FakeReg()
    off = set_user_startup_enabled("folder:Helper.cmd", False, registry=reg, startup_dir=folder)
    assert off["success"] is True
    assert os.path.isfile(os.path.join(folder, "Helper.cmd.pcac-off"))
    listed = list_user_startup_entries(registry=reg, startup_dir=folder)
    helper = next(item for item in listed["entries"] if item["name"] == "Helper.cmd")
    assert helper["enabled"] is False
    assert helper["impact"] == "không rõ"
    on = set_user_startup_enabled("folder:Helper.cmd.pcac-off", True, registry=reg, startup_dir=folder)
    assert on["success"] is True
    assert os.path.isfile(os.path.join(folder, "Helper.cmd"))
    escaped = set_user_startup_enabled("folder:../outside.txt", False, registry=reg, startup_dir=folder)
    assert escaped["success"] is False
    assert not os.path.exists(outside)


def test_lighten_preset_is_user_temp_and_ram_only():
    from core.c_drive_clean import resolve_clean_plan

    assert USER_SAFE_QUICK_CLEAN["user_temp"] is True
    assert USER_SAFE_QUICK_CLEAN["crash_dumps"] is True
    assert USER_SAFE_QUICK_CLEAN["recycle_bin"] is False
    assert USER_SAFE_QUICK_CLEAN["system_temp"] is False
    assert USER_SAFE_QUICK_CLEAN["browser_cache"] is False
    plan = resolve_clean_plan(
        USER_SAFE_QUICK_CLEAN,
        is_admin=False,
        only_keys=("user_temp", "crash_dumps"),
    )
    assert set(plan["to_run"]) == {"user_temp", "crash_dumps"}
    plan_admin = resolve_clean_plan(USER_SAFE_QUICK_CLEAN, is_admin=True)
    assert "recycle_bin" not in plan_admin["to_run"]
    assert "system_temp" not in plan_admin["to_run"]
    assert "browser_cache" not in plan_admin["to_run"]
    assert plan_admin["to_run"].get("user_temp") is True

    seen = {}

    class _Cleaner:
        def clean(self, targets, exclude_paths=None, only_keys=None):
            seen["targets"] = dict(targets)
            seen["only_keys"] = tuple(only_keys or ())
            seen["exclude"] = list(exclude_paths or [])
            return {"total_freed_mb": 3.25, "total_deleted_files": 6}

    class _Ram:
        def optimize_ram(self, whitelist=None):
            seen["whitelist"] = set(whitelist or set())
            return {
                "success": True,
                "available_before_mb": 800,
                "available_after_mb": 900,
                "freed_mb": 100,
                "processes_flushed": 4,
                "skipped_whitelist": 1,
                "skipped_whitelist_names": ["obs64.exe"],
                "note_vi": "note",
            }

    res = run_lighten(
        whitelist={"obs64.exe"},
        cleaner=_Cleaner(),
        ram_optimizer=_Ram(),
        exclude_paths=[r"C:\keep"],
    )
    assert res["success"] is True
    assert res["recycle_emptied"] is False
    assert res["startup_changed"] is False
    assert res["needs_admin"] is False
    assert seen["only_keys"] == ("user_temp", "crash_dumps")
    assert seen["targets"]["recycle_bin"] is False
    assert seen["exclude"] == [r"C:\keep"]
    assert "obs64.exe" in seen["whitelist"]
    message = res["message_vi"]
    assert "Không làm trống thùng rác." in message
    assert "Không tắt mục khởi động." in message
    assert "Administrator" in message
    assert "RAM trống (khả dụng) trước:" in message
    confirm = confirm_text_vi()
    assert "thùng rác" in confirm
    assert "Administrator" in confirm
    assert "khởi động" in confirm
    assert "FPS" in confirm


def test_lighten_reports_partial_failure():
    class _Cleaner:
        def clean(self, targets, exclude_paths=None, only_keys=None):
            raise RuntimeError("temp locked")

    class _Ram:
        def optimize_ram(self, whitelist=None):
            return {"success": True, "freed_mb": 1.0, "available_before_mb": 10, "available_after_mb": 11, "processes_flushed": 1}

    res = run_lighten(cleaner=_Cleaner(), ram_optimizer=_Ram())
    assert res["success"] is False
    assert "user_temp" in res["failed_steps"]
    assert "Không xóa được temp" in res["message_vi"]
    assert res["recycle_emptied"] is False


def test_single_process_trim_refuses_protected():
    import core.process_manager as pm

    original = pm.psutil.Process

    class _FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def name(self):
            return "lsass.exe"

    pm.psutil.Process = _FakeProcess
    try:
        res = pm.ProcessManager.optimize_process_ram(444)
    finally:
        pm.psutil.Process = original
    assert res["success"] is False
    assert "hệ thống" in res["error"]


def test_dashboard_has_lighten_and_startup_controls():
    from PyQt5.QtWidgets import QApplication
    from config_manager import ConfigManager
    from ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    cfg_path = os.path.join(tempfile.mkdtemp(prefix="pcac-cfg-"), "config.json")
    win = MainWindow(ConfigManager(cfg_path))
    try:
        assert hasattr(win, "btn_lighten")
        assert "Làm máy nhẹ hơn" in win.btn_lighten.text()
        sub = win.lbl_lighten_sub.text()
        assert "thùng rác" in sub
        assert "Admin" in sub
        assert "khởi động" in sub
        assert "FPS" in sub
        assert hasattr(win, "btn_startup_entries")
        assert "Khởi động" in win.btn_startup_entries.text()
        tip = win.btn_ram_only.toolTip()
        assert "EmptyWorkingSet" in tip
        assert "ghim" in tip.lower()
    finally:
        win.close()


if __name__ == "__main__":
    tests = [
        test_version_stays_386,
        test_no_undocumented_standby_purge,
        test_ram_report_shows_before_after_and_skips,
        test_ram_report_when_available_drops,
        test_ram_debounce_reuses_previous_readout,
        test_live_optimize_ram_returns_readout_without_crashing,
        test_startup_lists_hkcu_and_folder_with_unknown_impact,
        test_startup_toggle_run_roundtrip_and_failed_write_keeps_original,
        test_startup_folder_toggle_roundtrip_and_rejects_escape,
        test_lighten_preset_is_user_temp_and_ram_only,
        test_lighten_reports_partial_failure,
        test_single_process_trim_refuses_protected,
        test_dashboard_has_lighten_and_startup_controls,
    ]
    failed = 0
    for fn in tests:
        try:
            MemoryOptimizer.reset_for_tests()
            fn()
            print(f" [PASS] {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f" [FAIL] {fn.__name__}: {e}")
            raise
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)
