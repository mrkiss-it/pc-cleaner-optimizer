"""
Tests for Wi-Fi drop / reconnect-loop recovery.
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

from core.wifi_recovery import (
    WifiRecovery,
    WIFI_WEAK_LINK_MBPS,
    STABILITY_WINDOW_SEC,
    parse_link_mbps,
    parse_wlan_event_ids,
    count_wlan_auth_flaps,
    count_status_flaps,
    classify_wifi_cause,
    is_filtering_or_custom_dns,
    parse_wlan_interfaces,
)
from core.system_monitor import SystemMonitor, format_ping_overlay_text
from core.network_optimizer import NetworkOptimizer
from core.scheduler import BackgroundScheduler
from config_manager import DEFAULT_CONFIG


WLAN_SAMPLE = """
Event[0]
  Event ID: 8003
  Description: Wireless security stopped.
Event[1]
  Event ID: 11010
Event[2]
  Event ID: 11000
Event[3]
  Event ID: 11001
Event[4]
  Event ID: 8002
  Description: Wireless security started.
"""

WLAN_IFACE_SAMPLE = """
    Name                   : Wi-Fi
    Description            : MediaTek Wi-Fi 6 MT7921 Wireless LAN Card
    State                  : connected
    SSID                   : NhaMinh
    Receive rate (Mbps)    : 26
    Transmit rate (Mbps)   : 26
    Signal                 : 45%
"""


def _wifi_snap(**overrides):
    base = {
        "is_wifi": True,
        "name": "Wi-Fi",
        "description": "MediaTek Wi-Fi 6 MT7921 Wireless LAN Card",
        "is_up": True,
        "status": "up",
        "state": "connected",
        "ssid": "NhaMinh",
        "link_mbps": 26.0,
        "dns_servers": ["94.140.14.14", "94.140.15.15"],
        "filtering_dns": True,
        "status_flaps": 4,
        "wlan_flaps": 5,
        "link_loss": False,
        "event_text": WLAN_SAMPLE,
        "unstable": True,
        "cause": "reconnect_loop",
        "cause_label": "Wi-Fi rớt liên tục / vòng reconnect (WLAN flap)",
    }
    base.update(overrides)
    return base


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = float(t)

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += float(s)


def test_parse_helpers():
    assert parse_link_mbps("26 Mbps") == 26.0
    assert parse_link_mbps("1.2 Gbps") == 1200.0
    assert parse_link_mbps(26) == 26.0
    ids = parse_wlan_event_ids(WLAN_SAMPLE)
    assert 8003 in ids and 11000 in ids and 8002 in ids
    assert count_wlan_auth_flaps(WLAN_SAMPLE) >= 4
    flaps = count_status_flaps(
        [(0, True), (10, False), (20, True), (30, False), (40, True)],
        now=40, window_sec=120,
    )
    assert flaps >= 4
    wlan = parse_wlan_interfaces(WLAN_IFACE_SAMPLE)
    assert wlan["ssid"] == "NhaMinh"
    assert wlan["rx_mbps"] == 26.0
    assert "MT7921" in wlan["description"]


def test_classify_and_filtering_dns():
    cause, label = classify_wifi_cause(_wifi_snap())
    assert cause == "reconnect_loop"
    assert "reconnect" in label.lower() or "rớt" in label

    weak, wlabel = classify_wifi_cause(_wifi_snap(
        status_flaps=0, wlan_flaps=0, link_mbps=26.0,
    ))
    assert weak == "weak_link"
    assert "yếu" in wlabel or "thấp" in wlabel
    assert WIFI_WEAK_LINK_MBPS == 50.0

    down, dlabel = classify_wifi_cause(_wifi_snap(is_up=False, status_flaps=0, wlan_flaps=0))
    assert down == "adapter_down"

    assert is_filtering_or_custom_dns(["94.140.14.14"]) is True
    assert is_filtering_or_custom_dns(["45.90.28.0"]) is True
    assert is_filtering_or_custom_dns(["8.8.8.8", "8.8.4.4"]) is False
    assert is_filtering_or_custom_dns(["192.168.1.1"]) is False


def test_overlay_wifi_words():
    assert format_ping_overlay_text(28, True, "ok", wifi_status="reconnect_loop") == "rớt"
    assert format_ping_overlay_text(-1, True, "link_loss") == "rớt"
    assert format_ping_overlay_text(40, True, "ok", wifi_status="weak_link") == "yếu"
    assert format_ping_overlay_text(28, True, "ok") == "28 ms"


def test_stability_window_fake_clock():
    clock = FakeClock(0)
    samples = {"n": 0}

    def get_snap():
        samples["n"] += 1
        return {"is_up": True, "name": "Wi-Fi"}

    result = WifiRecovery.wait_for_stable_link(
        get_snapshot=get_snap,
        duration_sec=8,
        interval_sec=2,
        sleep_fn=clock.sleep,
        clock_fn=clock.time,
        probe_fn=lambda: True,
    )
    assert result["stable"] is True
    assert result["success"] is True
    assert samples["n"] >= 4
    assert clock.t >= 8

    clock2 = FakeClock(0)
    toggling = {"n": 0}

    def flap_snap():
        toggling["n"] += 1
        return {"is_up": toggling["n"] % 2 == 0}

    bad = WifiRecovery.wait_for_stable_link(
        get_snapshot=flap_snap,
        duration_sec=8,
        interval_sec=2,
        sleep_fn=clock2.sleep,
        clock_fn=clock2.time,
        probe_fn=lambda: False,
    )
    assert bad["stable"] is False


def test_reconnect_throttle_and_dhcp_cmds():
    WifiRecovery.reset_state()
    cmds = []

    def runner(cmd, timeout=8):
        cmds.append(cmd)
        return {"success": True, "stdout": "Ok.", "stderr": "", "returncode": 0}

    WifiRecovery._cmd_runner = runner
    first = WifiRecovery.reconnect_wifi_profile("NhaMinh", "Wi-Fi", now=1000)
    assert first["success"] is True
    assert first.get("throttled") is False
    assert any("wlan disconnect" in c for c in cmds)
    assert any('wlan connect name="NhaMinh"' in c for c in cmds)

    second = WifiRecovery.reconnect_wifi_profile("NhaMinh", "Wi-Fi", now=1030)
    assert second.get("throttled") is True
    assert "90" in second["message"] or "throttle" in second["message"].lower()

    cmds.clear()
    dhcp = WifiRecovery.renew_dhcp("Wi-Fi")
    assert dhcp["action"] == "renew_dhcp"
    joined = " ".join(cmds)
    assert 'ipconfig /release "Wi-Fi"' in joined
    assert 'ipconfig /renew "Wi-Fi"' in joined
    WifiRecovery.reset_state()


def test_power_save_no_nic_toggle():
    WifiRecovery.reset_state()
    cmds = []
    ps = []

    def runner(cmd, timeout=8):
        cmds.append(cmd)
        return {"success": True, "stdout": "Ok.", "stderr": "", "returncode": 0}

    def ps_runner(command, timeout=12):
        ps.append(command)
        return {"success": True, "stdout": "", "stderr": "", "returncode": 0}

    WifiRecovery._cmd_runner = runner
    WifiRecovery._ps_runner = ps_runner
    res = WifiRecovery.disable_wifi_power_saving("Wi-Fi")
    assert res["success"] is True
    assert res["reversible"] is True
    blob = "\n".join(cmds + ps)
    assert "19cbb8fa-5279-450e-9fac-8a3d5fedd0c1" in blob
    assert "12bbebe6-58d6-4636-95bb-3217ef867c1a" in blob
    assert "Disable-NetAdapterPowerManagement" in blob
    assert "-NoRestart" in blob
    assert WifiRecovery.skipped_nic_toggle()
    import re
    assert not re.search(r"Disable-NetAdapter\s", blob)
    WifiRecovery.reset_state()


def _patch_wifi_repair():
    orig = {
        "flush": NetworkOptimizer.__dict__["flush_dns"],
        "arp": NetworkOptimizer.__dict__["purge_arp_netbios"],
        "best": NetworkOptimizer.__dict__["apply_best_dns"],
        "health": NetworkOptimizer.__dict__["run_health_check"],
        "measure": SystemMonitor.__dict__["_measure_quick_ping"],
        "renew": WifiRecovery.__dict__["renew_dhcp"],
        "recon": WifiRecovery.__dict__["reconnect_wifi_profile"],
        "pwr": WifiRecovery.__dict__["disable_wifi_power_saving"],
        "snap": WifiRecovery.__dict__["get_wifi_snapshot"],
    }
    counts = {"flush": 0, "arp": 0, "best": 0, "dhcp": 0, "recon": 0, "pwr": 0}

    def fake_flush(cls=None):
        counts["flush"] += 1
        return {"action": "flush_dns", "success": True, "message": "flush-ok"}

    def fake_arp(cls=None):
        counts["arp"] += 1
        return {"action": "purge_arp_netbios", "success": True, "message": "arp-ok"}

    def fake_best(cls=None, allow_elevation=True):
        counts["best"] += 1
        return {"success": True, "message": "dns-applied", "needs_admin": False}

    def fake_health(cls, measure_ping=True):
        ping = SystemMonitor.measure_ping_now() if measure_ping else 25.0
        return {
            "ok": ping > 0,
            "issues": [] if ping > 0 else ["ping_missing"],
            "checks": {
                "adapter": {"ok": True},
                "gateway": {"ok": True},
                "dns": {"ok": True},
                "connectivity": {"ok": True},
                "ping": {"ok": ping > 0, "ping_ms": ping, "status": "ok" if ping > 0 else "timeout"},
                "wifi": _wifi_snap(),
            },
        }

    def fake_renew(cls, adapter_name):
        counts["dhcp"] += 1
        return {"action": "renew_dhcp", "success": True, "message": f"dhcp-{adapter_name}"}

    def fake_recon(cls, ssid, adapter_name="", now=None, min_interval=90):
        counts["recon"] += 1
        return {"action": "reconnect_ssid", "success": True, "throttled": False, "message": f"recon-{ssid}"}

    def fake_pwr(cls, adapter_name=""):
        counts["pwr"] += 1
        return {"action": "disable_wifi_power_saving", "success": True, "reversible": True, "message": "psm-off"}

    def fake_snap(cls, **kwargs):
        return _wifi_snap(status_flaps=0, wlan_flaps=0, is_up=True, link_mbps=400)

    NetworkOptimizer.flush_dns = classmethod(fake_flush)
    NetworkOptimizer.purge_arp_netbios = classmethod(fake_arp)
    NetworkOptimizer.apply_best_dns = classmethod(fake_best)
    NetworkOptimizer.run_health_check = classmethod(fake_health)
    WifiRecovery.renew_dhcp = classmethod(fake_renew)
    WifiRecovery.reconnect_wifi_profile = classmethod(fake_recon)
    WifiRecovery.disable_wifi_power_saving = classmethod(fake_pwr)
    WifiRecovery.get_wifi_snapshot = classmethod(fake_snap)
    return orig, counts


def _restore_wifi_repair(orig):
    NetworkOptimizer.flush_dns = orig["flush"]
    NetworkOptimizer.purge_arp_netbios = orig["arp"]
    NetworkOptimizer.apply_best_dns = orig["best"]
    NetworkOptimizer.run_health_check = orig["health"]
    SystemMonitor._measure_quick_ping = orig["measure"]
    WifiRecovery.renew_dhcp = orig["renew"]
    WifiRecovery.reconnect_wifi_profile = orig["recon"]
    WifiRecovery.disable_wifi_power_saving = orig["pwr"]
    WifiRecovery.get_wifi_snapshot = orig["snap"]
    SystemMonitor.reset_ping_state()
    WifiRecovery.reset_state()
    NetworkOptimizer.last_wifi_drop_report = {}
    NetworkOptimizer.last_missing_ping_report = {}


def test_repair_does_not_stop_on_lucky_ping_during_flap():
    """ICMP may succeed while WLAN is flapping — still DHCP + SSID + power-save + stability."""
    orig, counts = _patch_wifi_repair()
    clock = FakeClock(50)
    try:
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: 33.0)
        SystemMonitor.reset_ping_state()
        WifiRecovery.reset_state()
        result = WifiRecovery.diagnose_and_repair_wifi_drop(
            apply_dns=False,
            snapshot=_wifi_snap(),
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
            stability_sec=8,
        )
        actions = [s.get("action") for s in result.get("steps", [])]
        assert counts["flush"] >= 1
        assert counts["dhcp"] >= 1, "Must renew DHCP even if ping luckily OK"
        assert counts["recon"] >= 1, "Must reconnect SSID"
        assert counts["pwr"] >= 1, "Must disable Wi-Fi power saving"
        assert "wait_stable_link" in actions
        assert counts["best"] >= 1, "AdGuard DNS must be swapped"
        assert any("Disable-NetAdapter" in s or "tắt/bật" in s or "card mạng" in s for s in result.get("skipped", []))
        assert result["cause"] == "reconnect_loop"
        assert "Nguyên nhân" in result["message"]
        assert clock.t >= 8, "Post-fix stability window must elapse"
    finally:
        _restore_wifi_repair(orig)


def test_dns_only_when_filtering():
    orig, counts = _patch_wifi_repair()
    clock = FakeClock(0)
    try:
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: -1.0)
        SystemMonitor.reset_ping_state()
        snap = _wifi_snap(
            dns_servers=["8.8.8.8"],
            filtering_dns=False,
            status_flaps=5,
            wlan_flaps=5,
        )
        WifiRecovery.diagnose_and_repair_wifi_drop(
            apply_dns=False,
            snapshot=snap,
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
            stability_sec=2,
        )
        assert counts["best"] == 0, "Must NOT auto-switch DNS when not AdGuard/custom"
    finally:
        _restore_wifi_repair(orig)


def test_should_trigger_wifi_and_wins_over_ping():
    T = WifiRecovery.should_trigger_wifi_drop_fix
    assert T(False, True, 1000, 0, 300, 0) is False
    assert T(True, False, 1000, 0, 300, 0) is False
    assert T(True, True, 1000, 990, 300, 0, first_cooldown_sec=12) is False
    assert T(True, True, 1000, 980, 300, 0, first_cooldown_sec=12) is True
    assert T(True, True, 9999, 0, 300, 2) is False  # anti-loop

    # Wi-Fi due even when ping is healthy
    ping_due = BackgroundScheduler.should_trigger_missing_ping_fix(
        True, 28.0, True, 0, 1, 1000, 0, 300, 0, first_cooldown_sec=8,
    )
    wifi_due = T(True, True, 1000, 0, 300, 0, first_cooldown_sec=12)
    assert ping_due is False
    assert wifi_due is True


def test_detect_reconnect_loop_from_events():
    WifiRecovery.reset_state()
    snap = WifiRecovery.detect_wifi_instability(
        snapshot=_wifi_snap(status_flaps=0, wlan_flaps=5, link_mbps=200),
        include_events=False,
    )
    assert snap["unstable"] is True
    assert snap["cause"] == "reconnect_loop"
    WifiRecovery.reset_state()


def test_missing_ping_routes_to_wifi():
    orig, counts = _patch_wifi_repair()
    clock = FakeClock(0)
    try:
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: -1.0)
        SystemMonitor.reset_ping_state()
        WifiRecovery.reset_state()
        # Inject detect path via health wifi + diagnose_and_repair_missing_ping
        orig_diag = WifiRecovery.__dict__["diagnose_and_repair_wifi_drop"]

        def wrapped(cls, apply_dns=False, snapshot=None, health=None, **kw):
            kw.setdefault("sleep_fn", clock.sleep)
            kw.setdefault("clock_fn", clock.time)
            kw.setdefault("stability_sec", 2)
            return orig_diag.__func__(
                cls, apply_dns=apply_dns, snapshot=snapshot or _wifi_snap(),
                health=health, **kw,
            )

        WifiRecovery.diagnose_and_repair_wifi_drop = classmethod(wrapped)
        result = NetworkOptimizer.diagnose_and_repair_missing_ping(apply_dns=False)
        assert result.get("type") == "wifi_drop" or result.get("reason") == "wifi_drop"
        assert counts["dhcp"] >= 1
    finally:
        WifiRecovery.diagnose_and_repair_wifi_drop = orig_diag
        _restore_wifi_repair(orig)


def test_config_wifi_defaults():
    assert int(DEFAULT_CONFIG.get("auto_network_wifi_fix_first_cooldown_seconds", 99)) <= 15
    assert int(DEFAULT_CONFIG.get("auto_network_wifi_fix_cooldown_seconds", 0)) >= 60
    assert DEFAULT_CONFIG.get("auto_network_ping_fix_enabled") is True
    assert STABILITY_WINDOW_SEC >= 8


if __name__ == "__main__":
    tests = [
        test_parse_helpers,
        test_classify_and_filtering_dns,
        test_overlay_wifi_words,
        test_stability_window_fake_clock,
        test_reconnect_throttle_and_dhcp_cmds,
        test_power_save_no_nic_toggle,
        test_repair_does_not_stop_on_lucky_ping_during_flap,
        test_dns_only_when_filtering,
        test_should_trigger_wifi_and_wins_over_ping,
        test_detect_reconnect_loop_from_events,
        test_missing_ping_routes_to_wifi,
        test_config_wifi_defaults,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] wifi drop / flap recovery suite")
