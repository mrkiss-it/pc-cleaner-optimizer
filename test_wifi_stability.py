"""
Pure tests for the Ổn định Wi-Fi monitor (not a VPN, not a live network).

Gates, cooldowns, and the gentle step plan. No ping, no netsh, no UAC.
"""
import inspect
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

from config_manager import DEFAULT_CONFIG
from core.wifi_recovery import WifiRecovery
from core.wifi_stability import (
    GENTLE_COOLDOWN_SEC,
    GENTLE_FORBIDDEN_ACTIONS,
    GENTLE_MIN_OUTAGE_SEC,
    GENTLE_RECOVERED_COOLDOWN_SEC,
    NOTE_ADMIN,
    NOTE_DNS,
    NOTE_EXTERNAL,
    NOTE_LOCATION,
    WifiStabilityMonitor,
    execute_gentle_recovery,
    format_stability_status_text,
    guess_public_cause,
    mark_stability_triggered,
    reduce_stability_state,
    select_gentle_steps,
    should_trigger_gentle_wifi_stability,
)


def _loss(**kwargs):
    base = dict(
        enabled=True,
        public_cause="adapter_down",
        ping_ok=False,
        now_ts=1_000.0,
        raw_cause="adapter_down",
        adapter_up=False,
        associated=False,
        adapter_name="Wi-Fi",
        ssid="NhaMinh",
    )
    base.update(kwargs)
    return reduce_stability_state({}, **base)


def test_defaults_are_off_and_conservative():
    assert DEFAULT_CONFIG.get("wifi_stability_enabled") is False
    assert int(DEFAULT_CONFIG.get("wifi_stability_min_outage_seconds", 0)) >= 60
    assert int(DEFAULT_CONFIG.get("wifi_stability_cooldown_seconds", 0)) >= 300
    assert int(DEFAULT_CONFIG.get("wifi_stability_recovered_cooldown_seconds", 0)) >= 900
    assert int(DEFAULT_CONFIG.get("wifi_stability_max_unrecovered", 0)) >= 2


def test_healthy_ping_is_ok_even_if_radio_looks_down():
    down = {
        "is_wifi": True,
        "is_up": False,
        "cause": "adapter_down",
        "false_adapter_down": True,
        "ssid": "",
    }
    assert guess_public_cause(down, ping_ok=True) == "ok"
    flap = {"is_wifi": True, "is_up": True, "cause": "reconnect_loop", "ssid": "NhaMinh"}
    assert guess_public_cause(flap, ping_ok=True) == "ok"
    weak = {"is_wifi": True, "is_up": True, "cause": "weak_link", "ssid": "NhaMinh"}
    assert guess_public_cause(weak, ping_ok=True) == "ok"
    state = reduce_stability_state(
        {},
        enabled=True,
        public_cause="ok",
        ping_ok=True,
        now_ts=5000,
        raw_cause="reconnect_loop",
        adapter_up=True,
        associated=True,
    )
    assert should_trigger_gentle_wifi_stability(state, now_ts=5000 + 600) is False
    assert select_gentle_steps("ok", adapter_up=True, associated=True) == []


def test_public_cause_buckets():
    radio = {"is_wifi": True, "is_up": False, "cause": "adapter_down", "ssid": ""}
    assert guess_public_cause(radio, ping_ok=False) == "adapter_down"
    assert guess_public_cause(radio, ping_ok=None) == "adapter_down"
    up = {"is_wifi": True, "is_up": True, "cause": "no_gateway", "ssid": "NhaMinh"}
    assert guess_public_cause(up, ping_ok=False) == "no_ping"
    dns = {"is_wifi": True, "is_up": True, "cause": "dns_fail", "ssid": "NhaMinh"}
    assert guess_public_cause(dns, ping_ok=False, dns_failed=True) == "dns"
    assert guess_public_cause(dns, ping_ok=None, dns_failed=True) == "dns"


def test_gentle_plan_never_flushes_or_kicks_a_live_link():
    assert select_gentle_steps("dns", adapter_up=True, associated=True, raw_cause="dns_fail") == []
    assert select_gentle_steps("ok") == []
    assert select_gentle_steps("adapter_down", adapter_up=False, associated=False) == ["reconnect_ssid"]
    assert select_gentle_steps(
        "no_ping", adapter_up=True, associated=True, raw_cause="weak_link",
    ) == ["renew_dhcp"]
    assert select_gentle_steps(
        "no_ping", adapter_up=True, associated=True, raw_cause="reconnect_loop",
    ) == ["reconnect_ssid"]
    assert select_gentle_steps(
        "no_ping", adapter_up=True, associated=False, raw_cause="link_loss",
    ) == ["reconnect_ssid"]
    for forbidden in GENTLE_FORBIDDEN_ACTIONS:
        assert forbidden not in select_gentle_steps("adapter_down")
        assert forbidden not in select_gentle_steps("no_ping", adapter_up=True, associated=True)


def test_outage_cooldown_and_flag_independence():
    state = _loss()
    assert state["last_drop_ts"] == 1_000.0
    again = reduce_stability_state(
        state,
        enabled=True,
        public_cause="adapter_down",
        ping_ok=False,
        now_ts=1_020.0,
        raw_cause="adapter_down",
        adapter_up=False,
        associated=False,
    )
    assert again["last_drop_ts"] == 1_000.0, "drop time sticks for one outage"
    blank = reduce_stability_state(
        again, enabled=True, public_cause="adapter_down", ping_ok=False,
        now_ts=1_030.0, raw_cause="adapter_down", adapter_up=False,
        associated=False, ssid="",
    )
    assert blank["ssid"] == "NhaMinh", "blank sample keeps the last SSID for reconnect"
    assert should_trigger_gentle_wifi_stability(again, now_ts=1_000.0 + 59) is False
    ready = 1_000.0 + GENTLE_MIN_OUTAGE_SEC
    assert should_trigger_gentle_wifi_stability(again, now_ts=ready) is True
    assert should_trigger_gentle_wifi_stability(
        again, now_ts=ready, aggressive_repair_owns_tick=True,
    ) is False

    held = mark_stability_triggered(again, ready)
    assert should_trigger_gentle_wifi_stability(held, now_ts=ready + GENTLE_COOLDOWN_SEC - 1) is False
    assert should_trigger_gentle_wifi_stability(held, now_ts=ready + GENTLE_COOLDOWN_SEC) is True

    stopped = dict(again)
    stopped["unrecovered"] = 2
    assert should_trigger_gentle_wifi_stability(stopped, now_ts=ready + 10_000) is False

    cooled = dict(again)
    cooled["last_recovered_ts"] = ready
    cooled["last_trigger_ts"] = 0
    cooled["unrecovered"] = 0
    assert should_trigger_gentle_wifi_stability(
        cooled, now_ts=ready + GENTLE_MIN_OUTAGE_SEC,
    ) is False
    assert should_trigger_gentle_wifi_stability(
        cooled, now_ts=ready + GENTLE_RECOVERED_COOLDOWN_SEC,
    ) is True

    off = reduce_stability_state(
        again, enabled=False, public_cause="adapter_down", ping_ok=False, now_ts=ready,
    )
    assert should_trigger_gentle_wifi_stability(off, now_ts=ready + 10_000) is False
    # Dedicated toggle does not consult auto_network_optimize. That flag still
    # blocks the aggressive WifiRecovery loop on its own.
    body = inspect.getsource(should_trigger_gentle_wifi_stability).replace(
        should_trigger_gentle_wifi_stability.__doc__ or "", ""
    )
    assert "auto_network_optimize_enabled" not in body
    assert WifiRecovery.should_trigger_wifi_drop_fix(
        True, True, 5_000, 0, 300, 0,
        first_cooldown_sec=12,
        auto_network_optimize_enabled=False,
        ping_ok=False,
        cause="adapter_down",
        outage_sec=120,
        min_outage_sec=45,
    ) is False


def test_drop_time_resets_only_when_a_new_outage_starts():
    state = _loss(now_ts=10)
    healthy = reduce_stability_state(
        state, enabled=True, public_cause="ok", ping_ok=True, now_ts=30,
        raw_cause="ok", adapter_up=True, associated=True, ssid="NhaMinh",
    )
    assert healthy["last_drop_ts"] == 10
    assert healthy["outage_start"] == 0
    nxt = reduce_stability_state(
        healthy, enabled=True, public_cause="no_ping", ping_ok=False, now_ts=40,
        raw_cause="no_gateway", adapter_up=True, associated=True, ssid="NhaMinh",
    )
    assert nxt["last_drop_ts"] == 40
    assert nxt["cause"] == "no_ping"


def test_execute_reconnects_without_flush_and_labels_admin():
    calls = []

    def reconnect(ssid, adapter, now):
        calls.append(("reconnect", ssid, adapter, now))
        return {"action": "reconnect_ssid", "success": True, "message": "Đã kết nối lại."}

    def renew(_adapter):
        calls.append(("renew",))
        raise AssertionError("adapter_down must not renew DHCP")

    state = _loss(now_ts=2_000)
    result = execute_gentle_recovery(
        state, now_ts=2_060, reconnect_fn=reconnect, renew_fn=renew,
    )
    assert result["attempted"] is True
    assert result["success"] is True
    assert calls == [("reconnect", "NhaMinh", "Wi-Fi", 2_060)]
    assert result["steps"][0]["action"] == "reconnect_ssid"
    assert "flush" not in result["message"].lower()
    text = format_stability_status_text(result["state"])
    assert "adapter_down" in text
    assert "Lần rớt gần nhất" in text
    assert "reconnect" in text.lower() or "Reconnect" in text

    def denied(_adapter):
        return {
            "action": "renew_dhcp",
            "success": False,
            "message": "The requested operation requires elevation.",
        }

    ping_loss = reduce_stability_state(
        {},
        enabled=True,
        public_cause="no_ping",
        ping_ok=False,
        now_ts=3_000,
        raw_cause="no_gateway",
        adapter_up=True,
        associated=True,
        adapter_name="Wi-Fi",
        ssid="NhaMinh",
    )
    admin = execute_gentle_recovery(
        ping_loss,
        now_ts=3_100,
        reconnect_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("no reconnect")),
        renew_fn=denied,
    )
    assert admin["needs_admin"] is True
    assert admin["state"]["note"] == NOTE_ADMIN
    assert admin["state"]["unrecovered"] == 1
    assert "UAC" in admin["message"] or "UAC" in admin["state"]["last_action_text"]

    def blocked(ssid, adapter, now):
        return {
            "action": "reconnect_ssid",
            "success": False,
            "location_blocked": True,
            "message": "Không đọc được SSID vì thiếu quyền Location.",
        }

    loc = execute_gentle_recovery(
        _loss(), now_ts=4_000, reconnect_fn=blocked, renew_fn=denied,
    )
    assert loc["state"]["note"] == NOTE_LOCATION
    assert "UAC" in loc["state"]["note"]


def test_dns_is_reported_and_not_repaired():
    state = reduce_stability_state(
        {},
        enabled=True,
        public_cause="dns",
        ping_ok=False,
        now_ts=100,
        raw_cause="dns_fail",
        adapter_up=True,
        associated=True,
        ssid="NhaMinh",
    )
    assert state["note"] == NOTE_DNS
    assert should_trigger_gentle_wifi_stability(state, now_ts=100 + 600) is False
    result = execute_gentle_recovery(
        state,
        now_ts=200,
        reconnect_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("dns must not reconnect")),
        renew_fn=lambda *_a: (_ for _ in ()).throw(AssertionError("dns must not renew")),
    )
    assert result["attempted"] is False


def test_external_repair_note_and_sources_have_no_vpn_or_flush():
    state = reduce_stability_state(
        {},
        enabled=True,
        public_cause="adapter_down",
        ping_ok=False,
        now_ts=10,
        raw_cause="adapter_down",
        external_repair=True,
    )
    assert state["note"] == NOTE_EXTERNAL
    src = inspect.getsource(execute_gentle_recovery)
    from core.scheduler import BackgroundScheduler
    sched = inspect.getsource(BackgroundScheduler.run_gentle_wifi_stability)
    monitor = inspect.getsource(BackgroundScheduler._maybe_run_wifi_stability)
    for blob in (src, sched, monitor):
        low = blob.lower()
        assert "flush_dns" not in low
        assert "emptyworkingset" not in low
        assert "runas" not in low
        assert "shellexecute" not in low
        assert "vpn" not in low
    assert "wifi_stability_enabled" in monitor
    assert "aggressive_repair_owns_tick" in monitor


def test_monitor_hydrate_and_due_roundtrip():
    WifiStabilityMonitor.reset_state()
    try:
        WifiStabilityMonitor.hydrate({
            "enabled": True,
            "cause": "adapter_down",
            "ping_ok": False,
            "outage_start": 100.0,
            "last_drop_ts": 100.0,
            "unrecovered": 0,
            "last_trigger_ts": 0,
            "last_recovered_ts": 0,
            "adapter_up": False,
            "associated": False,
            "raw_cause": "adapter_down",
            "adapter_name": "Wi-Fi",
            "ssid": "NhaMinh",
        })
        WifiStabilityMonitor.hydrate({"cause": "ok"})  # second hydrate is a no-op
        assert WifiStabilityMonitor.snapshot()["cause"] == "adapter_down"
        assert WifiStabilityMonitor.recovery_due(now_ts=100 + 60, config={}) is True
        WifiStabilityMonitor.mark_triggered(160)
        assert WifiStabilityMonitor.recovery_due(now_ts=200, config={}) is False
    finally:
        WifiStabilityMonitor.reset_state()


if __name__ == "__main__":
    tests = [
        test_defaults_are_off_and_conservative,
        test_healthy_ping_is_ok_even_if_radio_looks_down,
        test_public_cause_buckets,
        test_gentle_plan_never_flushes_or_kicks_a_live_link,
        test_outage_cooldown_and_flag_independence,
        test_drop_time_resets_only_when_a_new_outage_starts,
        test_execute_reconnects_without_flush_and_labels_admin,
        test_dns_is_reported_and_not_repaired,
        test_external_repair_note_and_sources_have_no_vpn_or_flush,
        test_monitor_hydrate_and_due_roundtrip,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] wifi stability monitor")
