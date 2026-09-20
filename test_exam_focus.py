"""
Unit tests for Chế độ Trước thi / họp (ExamMeetingFocus).
Stubs Windows-only bits so this file can run on Linux CI.
"""
import os
import sys
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


from core.exam_focus import (
    ExamMeetingFocus,
    LIGHT_CLEAN_TARGETS,
    MEETING_PROTECT,
    NETWORK_TIP,
    format_enable_message,
    format_disable_message,
)
from core.game_booster import BACKGROUND_HOGS, GameBooster


class _FakeCleaner:
    last_targets = None
    raise_error = False
    result = {"total_freed_mb": 12.5, "total_deleted_files": 7}

    @classmethod
    def clean(cls, targets):
        cls.last_targets = dict(targets)
        if cls.raise_error:
            raise RuntimeError("disk locked")
        return dict(cls.result)


class _FakeRam:
    last_whitelist = None
    raise_error = False
    result = {"success": True, "freed_mb": 64.0, "processes_flushed": 11}

    @classmethod
    def optimize_ram(cls, whitelist=None):
        cls.last_whitelist = set(whitelist or set())
        if cls.raise_error:
            raise RuntimeError("EmptyWorkingSet denied")
        return dict(cls.result)


class _FakeProc:
    def __init__(self, pid, name, prio=32):
        self.info = {"pid": pid, "name": name}
        self.pid = pid
        self._prio = prio
        self.nice_calls = []

    def nice(self, value=None):
        if value is None:
            return self._prio
        self.nice_calls.append(value)
        self._prio = value
        return value


class _FakeTweaker:
    def __init__(self, already_applied=False, apply_ok=True, revert_ok=True):
        self.already_applied = already_applied
        self.apply_ok = apply_ok
        self.revert_ok = revert_ok
        self.apply_calls = []
        self.revert_calls = []

    def is_applied(self, tweak_id):
        return self.already_applied

    def apply_tweak(self, tweak_id):
        self.apply_calls.append(tweak_id)
        if self.apply_ok:
            return True, "ok"
        return False, "access denied"

    def revert_tweak(self, tweak_id):
        self.revert_calls.append(tweak_id)
        if self.revert_ok:
            return True, "reverted"
        return False, "revert failed"


class _FakeBooster:
    active = False

    @classmethod
    def is_active(cls):
        return cls.active


def _enable(**kw):
    defaults = dict(
        cleaner=_FakeCleaner,
        ram_optimizer=_FakeRam,
        process_iter=lambda attrs: [],
        tweaker=_FakeTweaker(already_applied=True),
        game_booster=_FakeBooster,
    )
    defaults.update(kw)
    return ExamMeetingFocus.enable(**defaults)


def test_light_clean_targets_are_safe():
    assert LIGHT_CLEAN_TARGETS["user_temp"] is True
    assert LIGHT_CLEAN_TARGETS["system_temp"] is True
    assert LIGHT_CLEAN_TARGETS["crash_dumps"] is True
    for banned in ("recycle_bin", "browser_cache", "windows_update", "app_caches"):
        assert LIGHT_CLEAN_TARGETS.get(banned) is False, f"{banned} must stay off"
    assert "zoom.exe" in MEETING_PROTECT
    assert "teams.exe" in MEETING_PROTECT
    assert "searchindexer.exe" in BACKGROUND_HOGS


def test_enable_disable_roundtrip_restores_priorities():
    ExamMeetingFocus.reset_for_tests()
    hog = _FakeProc(111, "searchindexer.exe", prio=32)
    other = _FakeProc(222, "notepad.exe", prio=32)
    zoom = _FakeProc(333, "zoom.exe", prio=32)

    def iterate(_attrs):
        return [hog, other, zoom]

    tweaker = _FakeTweaker(already_applied=False, apply_ok=True)
    res = _enable(process_iter=iterate, tweaker=tweaker)
    assert res["success"] is True
    assert ExamMeetingFocus.is_active() is True
    assert ExamMeetingFocus.should_suppress_app_toasts() is True
    assert res["network_changed"] is False
    assert NETWORK_TIP in res["message"]
    assert res["demoted_count"] == 1
    assert hog.nice_calls, "searchindexer must be demoted"
    assert not zoom.nice_calls, "Zoom must not be demoted"
    assert not other.nice_calls, "unrelated procs must not be touched"
    assert 111 in ExamMeetingFocus._saved_priorities
    assert ExamMeetingFocus._saved_priorities[111] == 32
    assert tweaker.apply_calls == ["disable_feedback_prompts"]

    restored = []

    class _Ctor:
        def __init__(self, pid):
            self.pid = pid
            self.proc = hog if pid == 111 else _FakeProc(pid, "gone")

        def nice(self, value=None):
            restored.append((self.pid, value))
            return self.proc.nice(value)

    off = ExamMeetingFocus.disable(process_ctor=_Ctor, tweaker=tweaker)
    assert off["success"] is True
    assert ExamMeetingFocus.is_active() is False
    assert ExamMeetingFocus.should_suppress_app_toasts() is False
    assert off["restored_count"] == 1
    assert restored == [(111, 32)]
    assert tweaker.revert_calls == ["disable_feedback_prompts"]
    assert ExamMeetingFocus._saved_priorities == {}


def test_already_active_and_inactive_are_idempotent():
    ExamMeetingFocus.reset_for_tests()
    first = _enable()
    assert first.get("already_active") is not True
    second = _enable()
    assert second["already_active"] is True
    assert second["is_active"] is True
    off = ExamMeetingFocus.disable(tweaker=_FakeTweaker(already_applied=True))
    assert off["already_inactive"] is not True
    off2 = ExamMeetingFocus.disable()
    assert off2["already_inactive"] is True
    assert off2["is_active"] is False


def test_light_clean_failure_is_reported_honestly():
    ExamMeetingFocus.reset_for_tests()
    _FakeCleaner.raise_error = True
    try:
        res = _enable()
    finally:
        _FakeCleaner.raise_error = False
    assert res["success"] is False
    assert "light_clean" in res["failed_steps"]
    assert ExamMeetingFocus.is_active() is True  # still on so user can restore
    assert "Không dọn được rác nhẹ" in res["message"] or "lỗi" in res["message"].lower()
    ExamMeetingFocus.disable(tweaker=_FakeTweaker(already_applied=True))


def test_ram_protects_meeting_apps_and_uses_light_clean_only():
    ExamMeetingFocus.reset_for_tests()
    _FakeCleaner.last_targets = None
    _FakeRam.last_whitelist = None
    _enable(whitelist={"obs64.exe"})
    targets = _FakeCleaner.last_targets
    assert targets["user_temp"] is True
    assert targets["recycle_bin"] is False
    assert targets["windows_update"] is False
    assert targets["browser_cache"] is False
    assert "zoom.exe" in _FakeRam.last_whitelist
    assert "obs64.exe" in _FakeRam.last_whitelist
    ExamMeetingFocus.disable(tweaker=_FakeTweaker(already_applied=True))


def test_skip_priority_when_game_boost_already_on():
    ExamMeetingFocus.reset_for_tests()
    _FakeBooster.active = True
    hog = _FakeProc(50, "onedrive.exe", prio=8)

    def iterate(_a):
        return [hog]

    try:
        res = _enable(process_iter=iterate)
        assert res["skipped_game_boost"] is True
        assert res["demoted_count"] == 0
        assert not hog.nice_calls
    finally:
        _FakeBooster.active = False
        ExamMeetingFocus.reset_for_tests()


def test_does_not_touch_network_optimizer():
    ExamMeetingFocus.reset_for_tests()
    import core.network_optimizer as net

    calls = []
    orig_flush = getattr(net.NetworkOptimizer, "flush_dns", None)
    orig_tcp = getattr(net.NetworkOptimizer, "optimize_tcp_stack", None)
    orig_dns = getattr(net.NetworkOptimizer, "apply_best_dns", None)

    def _boom(*_a, **_k):
        calls.append("network")
        raise AssertionError("Exam focus must not change DNS/Wi-Fi")

    net.NetworkOptimizer.flush_dns = _boom
    net.NetworkOptimizer.optimize_tcp_stack = _boom
    net.NetworkOptimizer.apply_best_dns = _boom
    try:
        res = _enable()
        assert res["network_changed"] is False
        assert calls == []
        off = ExamMeetingFocus.disable(tweaker=_FakeTweaker(already_applied=True))
        assert off["network_changed"] is False
        assert calls == []
    finally:
        if orig_flush is not None:
            net.NetworkOptimizer.flush_dns = orig_flush
        if orig_tcp is not None:
            net.NetworkOptimizer.optimize_tcp_stack = orig_tcp
        if orig_dns is not None:
            net.NetworkOptimizer.apply_best_dns = orig_dns
        ExamMeetingFocus.reset_for_tests()


def test_feedback_tweak_not_reverted_if_already_applied():
    ExamMeetingFocus.reset_for_tests()
    tweaker = _FakeTweaker(already_applied=True)
    _enable(tweaker=tweaker)
    assert tweaker.apply_calls == []
    ExamMeetingFocus.disable(tweaker=tweaker)
    assert tweaker.revert_calls == []


def test_format_messages_mention_failures():
    steps = [
        {"id": "light_clean", "label": "Dọn rác nhẹ", "detail": "ok junk", "success": False},
        {"id": "ram_trim", "label": "RAM", "detail": "ok ram", "success": True},
    ]
    failed = [steps[0]]
    msg = format_enable_message(steps, failed)
    assert "Dọn rác nhẹ" in msg
    assert NETWORK_TIP in msg
    off = format_disable_message(steps, failed, restored_count=2)
    assert "2 tiến trình" in off
    assert "Dọn rác nhẹ" in off


def test_ui_has_focus_card_and_toggle():
    from PyQt5.QtWidgets import QApplication
    from config_manager import ConfigManager
    from ui.main_window import MainWindow
    from app_meta import APP_NAME

    app = QApplication.instance() or QApplication(sys.argv)
    cfg = ConfigManager()
    win = MainWindow(cfg)
    assert hasattr(win, "btn_exam_focus")
    assert "Trước thi" in win.btn_exam_focus.text()
    assert hasattr(win, "lbl_exam_focus_sub")
    sub = win.lbl_exam_focus_sub.text()
    assert "thi" in sub.lower() or "họp" in sub.lower()
    assert "Pro" not in win.btn_exam_focus.text()
    assert APP_NAME in win.lbl_exam_focus_sub.text()
    assert "Pro" not in win.lbl_exam_focus_title.text()
    assert "Pro" not in win.lbl_exam_focus_sub.text()
    # Active state updates from engine
    ExamMeetingFocus.reset_for_tests()
    ExamMeetingFocus._is_active = True
    win._sync_exam_focus_ui()
    assert "khôi phục" in win.btn_exam_focus.text()
    assert "ĐANG TẬP TRUNG" in win.badge_exam_focus.text()
    ExamMeetingFocus.reset_for_tests()
    win._sync_exam_focus_ui()
    assert "Bật Trước thi" in win.btn_exam_focus.text()
    assert "Đang Tắt" in win.badge_exam_focus.text()
    win.close()


def test_tray_suppresses_toasts_during_focus_unless_forced():
    from PyQt5.QtWidgets import QApplication
    from ui.tray_icon import SystemTrayManager

    app = QApplication.instance() or QApplication(sys.argv)
    tray = SystemTrayManager()

    class _Cfg:
        def get(self, key, default=None):
            if key == "instant_screen_notifications_enabled":
                return False
            if key == "show_notifications":
                return True
            return default

    tray.config_manager = _Cfg()
    shown = []
    tray.showMessage = lambda *a, **k: shown.append(a[0] if a else "msg")
    ExamMeetingFocus.reset_for_tests()
    ExamMeetingFocus._is_active = True
    ExamMeetingFocus._suppress_app_toasts = True
    tray.notify("hidden", "should skip")
    assert shown == [], "Focus mode must mute app toasts"
    tray.notify("visible", "confirm", force=True)
    assert shown == ["visible"], "force=True must still show the toggle toast"
    ExamMeetingFocus.reset_for_tests()


if __name__ == "__main__":
    tests = [
        test_light_clean_targets_are_safe,
        test_enable_disable_roundtrip_restores_priorities,
        test_already_active_and_inactive_are_idempotent,
        test_light_clean_failure_is_reported_honestly,
        test_ram_protects_meeting_apps_and_uses_light_clean_only,
        test_skip_priority_when_game_boost_already_on,
        test_does_not_touch_network_optimizer,
        test_feedback_tweak_not_reverted_if_already_applied,
        test_format_messages_mention_failures,
        test_ui_has_focus_card_and_toggle,
        test_tray_suppresses_toasts_during_focus_unless_forced,
    ]
    failed = 0
    for fn in tests:
        try:
            ExamMeetingFocus.reset_for_tests()
            GameBooster._is_active = False
            _FakeCleaner.raise_error = False
            _FakeRam.raise_error = False
            fn()
            print(f" [PASS] {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f" [FAIL] {fn.__name__}: {e}")
            raise
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if failed:
        sys.exit(1)
