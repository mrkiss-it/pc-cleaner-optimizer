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

from core.wifi_recovery import (
    WifiRecovery,
    WIFI_WEAK_LINK_MBPS,
    STABILITY_WINDOW_SEC,
    SUCCESS_TOAST_COOLDOWN_SEC,
    MIN_OUTAGE_RETOAST_SEC,
    parse_link_mbps,
    parse_wlan_event_ids,
    count_wlan_auth_flaps,
    count_status_flaps,
    classify_wifi_cause,
    is_filtering_or_custom_dns,
    parse_wlan_interfaces,
    parse_wifi_signal,
    resolve_overlay_wifi_status,
    overlay_word_for_cause,
    is_genuine_link_loss,
    should_show_recovery_toast,
    RecoveryToastGate,
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
    assert wlan.get("location_blocked") is False


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
    # Have a ping reading → always keep the number (never replace with only yếu/rớt).
    assert format_ping_overlay_text(28, True, "ok", wifi_status="reconnect_loop") == "28 ms"
    assert format_ping_overlay_text(40, True, "ok", wifi_status="weak_link") == "40 ms · yếu"
    assert format_ping_overlay_text(28, True, "ok") == "28 ms"
    assert format_ping_overlay_text(300, True, "ok", wifi_status="adapter_down") == "300 ms"
    assert "rớt" not in format_ping_overlay_text(300, True, "ok", wifi_status="weak_link")
    # No ping + genuine drop → rớt. No ping + only weak → timeout, not rớt.
    assert format_ping_overlay_text(-1, True, "ok", wifi_status="reconnect_loop") == "rớt"
    assert format_ping_overlay_text(-1, True, "link_loss") == "rớt"
    assert format_ping_overlay_text(-1, True, "timeout", wifi_status="weak_link") == "timeout"
    assert overlay_word_for_cause("link_loss") == "rớt"
    assert overlay_word_for_cause("weak_link") == "yếu"
    assert overlay_word_for_cause("ok") == ""


def test_classify_connected_low_rate_is_weak_not_link_loss():
    """User PC: MT7921 Up, ~13–26 Mbps, no WLAN flap → yếu, never rớt."""
    weak_snap = _wifi_snap(
        status_flaps=0, wlan_flaps=0, link_mbps=26.0, link_loss=False,
        state="connected", ssid="Ba Duong L2", is_up=True, signal="45%",
    )
    cause, label = classify_wifi_cause(weak_snap)
    assert cause == "weak_link"
    assert "yếu" in label or "thấp" in label
    assert is_genuine_link_loss(weak_snap) is False
    assert overlay_word_for_cause(cause) == "yếu"
    assert format_ping_overlay_text(300, True, "ok", wifi_status=cause) == "300 ms · yếu"
    assert "rớt" not in format_ping_overlay_text(300, True, "ok", wifi_status=cause)

    # Empty SSID + adapter Status "up" + usable PHY (netsh gap) is NOT link_loss.
    gap = _wifi_snap(
        status_flaps=0, wlan_flaps=0, link_mbps=19.0, link_loss=True,
        state="up", ssid="", is_up=True, signal="",
    )
    gap_cause, _ = classify_wifi_cause(gap)
    assert gap_cause == "weak_link", f"netsh gap was {gap_cause}, expected weak_link"
    assert is_genuine_link_loss(gap) is False

    rssi_snap = _wifi_snap(
        status_flaps=0, wlan_flaps=0, link_mbps=200.0, link_loss=False,
        state="connected", ssid="Ba Duong L2", is_up=True, signal="-71 dBm",
    )
    rssi_cause, _ = classify_wifi_cause(rssi_snap)
    assert rssi_cause == "weak_link"
    pct, rssi = parse_wifi_signal("-71 dBm")
    assert rssi == -71.0
    assert pct is None


def test_overlay_priority_flap_beats_weak_and_stale_report():
    WifiRecovery.reset_state()
    weak = WifiRecovery.detect_wifi_instability(
        snapshot=_wifi_snap(
            status_flaps=0, wlan_flaps=0, link_mbps=13.0, link_loss=False,
            unstable=False, cause="ok",
        ),
        include_events=False,
        health={"checks": {"ping": {"ok": True, "ping_ms": 300}}, "issues": []},
    )
    assert weak["cause"] == "weak_link"
    assert weak["overlay"] == "yếu"
    # Stale repair report of link_loss must not keep the badge on rớt.
    stale = {"cause": "link_loss", "cause_label": "mất liên kết Wi-Fi (không còn SSID / link)"}
    assert resolve_overlay_wifi_status(weak, last_report=stale) == "weak_link"
    WifiRecovery.last_detect = weak
    WifiRecovery.last_wifi_drop_report = stale
    assert WifiRecovery.overlay_wifi_status(last_report=stale) == "weak_link"
    assert format_ping_overlay_text(
        300, True, "ok", wifi_status=WifiRecovery.overlay_wifi_status(last_report=stale)
    ) == "300 ms · yếu"

    flap = WifiRecovery.detect_wifi_instability(
        snapshot=_wifi_snap(status_flaps=4, wlan_flaps=5, link_mbps=13.0),
        include_events=False,
    )
    assert flap["cause"] == "reconnect_loop"
    assert flap["overlay"] == "rớt"
    assert resolve_overlay_wifi_status(flap) == "reconnect_loop"
    assert format_ping_overlay_text(28, True, "ok", wifi_status="reconnect_loop") == "28 ms"
    assert format_ping_overlay_text(-1, True, "ok", wifi_status="reconnect_loop") == "rớt"

    down = WifiRecovery.detect_wifi_instability(
        snapshot=_wifi_snap(
            is_up=False, state="disconnected", ssid="", link_mbps=-1,
            status_flaps=0, wlan_flaps=0, link_loss=True,
        ),
        include_events=False,
    )
    assert down["cause"] == "adapter_down"
    assert overlay_word_for_cause(down["cause"]) == "rớt"

    lost = classify_wifi_cause(_wifi_snap(
        is_up=True, state="authenticating", ssid="", link_mbps=-1,
        status_flaps=0, wlan_flaps=0, link_loss=True,
    ))[0]
    assert lost == "link_loss"
    assert overlay_word_for_cause(lost) == "rớt"

    # Timeout-only with healthy Wi-Fi → no Wi-Fi overlay (keep timeout).
    healthy = WifiRecovery.detect_wifi_instability(
        snapshot=_wifi_snap(
            status_flaps=0, wlan_flaps=0, link_mbps=400, link_loss=False,
            state="connected", ssid="NhaMinh", is_up=True, signal="90%",
        ),
        include_events=False,
        health={"checks": {"ping": {"ok": False, "ping_ms": -1, "status": "timeout"}},
                "issues": ["ping_missing"]},
    )
    assert healthy["cause"] == "ok"
    token = resolve_overlay_wifi_status(healthy)
    assert token == ""
    assert format_ping_overlay_text(-1, True, "timeout", wifi_status=token) == "timeout"
    WifiRecovery.reset_state()


def test_snapshot_empty_netsh_keeps_up_adapter_as_weak():
    WifiRecovery.reset_state()
    snap = WifiRecovery.get_wifi_snapshot(
        adapters=[{
            "Name": "Wi-Fi",
            "Status": "Up",
            "LinkSpeed": "26 Mbps",
            "InterfaceDescription": "MediaTek Wi-Fi 6 MT7921 Wireless LAN Card",
        }],
        wlan_text="",
        event_text="",
        include_events=False,
        now=5000.0,
        dns_text="",
    )
    assert snap["is_up"] is True
    assert snap["link_mbps"] == 26.0
    det = WifiRecovery.detect_wifi_instability(snapshot=snap, include_events=False)
    assert det["cause"] == "weak_link"
    assert det["overlay"] == "yếu"
    assert det["cause"] != "link_loss"
    WifiRecovery.reset_state()


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


def test_connected_weak_skips_ssid_reconnect():
    """Sustained weak link while still associated must not self-disconnect."""
    orig, counts = _patch_wifi_repair()
    clock = FakeClock(0)
    try:
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: 280.0)
        SystemMonitor.reset_ping_state()
        WifiRecovery.reset_state()
        snap = _wifi_snap(
            status_flaps=0, wlan_flaps=0, link_mbps=13.0, link_loss=False,
            state="connected", ssid="Ba Duong L2", is_up=True,
            filtering_dns=False, dns_servers=["8.8.8.8"],
        )
        result = WifiRecovery.diagnose_and_repair_wifi_drop(
            apply_dns=False,
            snapshot=snap,
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
            stability_sec=2,
        )
        assert result["cause"] == "weak_link"
        assert result.get("overlay") == "yếu"
        assert counts["recon"] == 0, "Must not reconnect SSID on connected weak link"
        assert counts["pwr"] >= 1, "Power-save off is still the weak-link fix"
        assert any("chỉ yếu" in s or "reconnect" in s.lower() for s in result.get("skipped", []))
    finally:
        _restore_wifi_repair(orig)


def test_config_wifi_defaults():
    assert int(DEFAULT_CONFIG.get("auto_network_wifi_fix_first_cooldown_seconds", 99)) <= 15
    assert int(DEFAULT_CONFIG.get("auto_network_wifi_fix_cooldown_seconds", 0)) >= 60
    assert DEFAULT_CONFIG.get("auto_network_ping_fix_enabled") is True
    assert STABILITY_WINDOW_SEC >= 8
    assert int(DEFAULT_CONFIG.get("auto_network_recovery_success_toast_cooldown_seconds", 0)) >= 60
    assert int(DEFAULT_CONFIG.get("auto_network_recovery_min_outage_retoast_seconds", 0)) >= 30
    assert SUCCESS_TOAST_COOLDOWN_SEC >= 60
    assert MIN_OUTAGE_RETOAST_SEC >= 30


def _success_info(cause="adapter_down", kind="wifi_drop", outage=12.0):
    return {
        "type": kind,
        "recovered": True,
        "cause": cause,
        "outage_seconds": outage,
        "message": (
            f"Nguyên nhân: card Wi-Fi tắt / không Up. "
            f"Đã sửa: flush DNS, làm mới ARP/NetBIOS. Ping đo được lại: 88 ms."
        ),
    }


def test_should_show_recovery_toast_rules():
    kw = dict(
        recovered=True,
        kind="wifi_drop",
        cause="adapter_down",
        last_success_kind="wifi_drop",
        last_success_cause="adapter_down",
        success_cooldown_sec=180,
        min_outage_retoast_sec=60,
    )
    assert should_show_recovery_toast(
        recovered=True, kind="wifi_drop", cause="adapter_down", now_ts=10,
    ) is True, "First success toast must show"
    assert should_show_recovery_toast(now_ts=40, last_success_ts=10, **kw) is False, (
        "Repeat success within cooldown must be suppressed"
    )
    assert should_show_recovery_toast(now_ts=200, last_success_ts=10, **kw) is True, (
        "Success toast after cooldown must show again"
    )
    assert should_show_recovery_toast(
        now_ts=40, last_success_ts=10, last_success_kind="wifi_drop",
        last_success_cause="adapter_down", recovered=True, kind="wifi_drop",
        cause="reconnect_loop", success_cooldown_sec=180, min_outage_retoast_sec=60,
    ) is True, "Different cause must toast even during cooldown"
    assert should_show_recovery_toast(
        now_ts=40, last_success_ts=10, **kw,
        saw_stable_since_success=True, outage_sec=90,
    ) is True, "Sustained new outage after a stable window must toast"
    assert should_show_recovery_toast(
        now_ts=40, last_success_ts=10, **kw,
        saw_stable_since_success=False, outage_sec=90,
    ) is False, "Continuous flap (never stable) must not bypass cooldown"
    assert should_show_recovery_toast(
        recovered=False, kind="wifi_drop", cause="adapter_down", now_ts=20,
        last_success_ts=10, needs_user_cta=True, cta_cooldown_sec=0,
    ) is True, "Location / DNS CTA must not be throttled by default"
    assert should_show_recovery_toast(
        recovered=False, kind="wifi_drop", cause="adapter_down", now_ts=20,
        last_failure_ts=10, failure_cooldown_sec=45,
    ) is False, "Generic failure toast is lightly throttled"
    assert should_show_recovery_toast(
        recovered=False, kind="wifi_drop", cause="adapter_down", now_ts=60,
        last_failure_ts=10, failure_cooldown_sec=45,
    ) is True
    assert should_show_recovery_toast(
        recovered=True, kind="ping_threshold", cause="", now_ts=20, last_success_ts=10,
    ) is True, "Non-recovery network toasts are unchanged"


def test_recovery_toast_gate_mt7921_flap_spam():
    """Simulate MediaTek flap: recovered=True every 15s → one success toast per window."""
    gate = RecoveryToastGate()
    shown = []
    t = 0.0
    for i in range(12):
        t += 15.0
        gate.observe_wifi(True, t)
        info = _success_info(outage=15.0)
        shown.append(gate.allow(info, now_ts=t, success_cooldown_sec=180, min_outage_retoast_sec=60))
    assert shown[0] is True
    assert shown[1:] == [False] * 11, f"Only the first flap success should toast, got {shown}"

    t += 180.0
    gate.observe_wifi(True, t)
    assert gate.allow(_success_info(), now_ts=t, success_cooldown_sec=180) is True

    # Stable, then a long distinct outage → toast even inside a fresh cooldown
    t += 5.0
    gate.observe_wifi(False, t)
    t += 5.0
    gate.observe_wifi(True, t)
    t += 70.0
    info = _success_info(outage=70.0)
    assert gate.allow(info, now_ts=t, success_cooldown_sec=180, min_outage_retoast_sec=60) is True

    ping_gate = RecoveryToastGate()
    ping_ok = {
        "type": "ping_missing",
        "recovered": True,
        "cause": "dns_fail",
        "outage_seconds": 8,
    }
    assert ping_gate.allow(ping_ok, now_ts=1.0) is True
    assert ping_gate.allow(ping_ok, now_ts=20.0) is False
    cta = {
        "type": "wifi_drop",
        "recovered": False,
        "cause": "adapter_down",
        "needs_location_unlock": True,
    }
    assert ping_gate.allow(cta, now_ts=21.0) is True
    assert ping_gate.allow(cta, now_ts=22.0) is True  # CTA unthrottled
    fail = {
        "type": "wifi_drop",
        "recovered": False,
        "cause": "adapter_down",
    }
    assert ping_gate.allow(fail, now_ts=23.0) is True
    assert ping_gate.allow(fail, now_ts=24.0) is False


def test_scheduler_has_toast_gate():
    assert "outage_seconds" in BackgroundScheduler.run_auto_wifi_drop_fix.__code__.co_varnames
    assert "outage_seconds" in BackgroundScheduler.run_auto_missing_ping_fix.__code__.co_varnames


def _install_fake_location_registry(values):
    """values: dict[name] -> DWORD/str. Missing names raise FileNotFoundError."""
    import core.windows_location as loc

    loc.invalidate_cache()

    def query(hive, path, name):
        path_n = str(path or "")
        if "LocationAndSensors" in path_n:
            if name in values:
                return values[name]
            raise FileNotFoundError(name)
        if "ConsentStore" in path_n and name == "Value":
            if "consent" in values:
                return values["consent"]
            raise FileNotFoundError(name)
        raise FileNotFoundError(name)

    loc._query_value_fn = query
    return loc


def test_location_gpo_detection_mocked_registry():
    import core.windows_location as loc
    from core.windows_location import (
        get_location_lock_status,
        is_location_gpo_locked,
        looks_like_location_permission_error,
        build_unlock_powershell,
        unlock_location_via_uac,
    )
    try:
        _install_fake_location_registry({"DisableLocation": 1})
        status = get_location_lock_status(force=True)
        assert status["locked"] is True
        assert is_location_gpo_locked(force=True) is True
        assert "DisableLocation" in status["locked_values"]
        assert "Group Policy" in status["message"]

        _install_fake_location_registry({})
        loc.invalidate_cache()
        assert is_location_gpo_locked(force=True) is False

        _install_fake_location_registry({
            "DisableLocationScripting": 1,
            "DisableSensors": 1,
        })
        loc.invalidate_cache()
        related = get_location_lock_status(force=True)
        assert related["locked"] is True
        assert "DisableLocationScripting" in related["locked_values"]

        netsh_err = (
            "Unable to get the wireless interface information because "
            "Location permission is disabled. Please enable Location permission."
        )
        assert looks_like_location_permission_error(netsh_err) is True
        assert looks_like_location_permission_error("SSID : NhaMinh") is False
        vi_err = "Cần có quyền vị trí để sử dụng lệnh này."
        assert looks_like_location_permission_error(vi_err) is True

        script = build_unlock_powershell()
        assert "DisableLocation" in script
        assert "DisableLocationScripting" in script
        assert "DisableSensors" in script
        assert "DisableWindowsLocationProvider" in script
        assert "ConsentStore" in script
        assert "Allow" in script
        assert "lfsvc" in script
        assert "LOCATION_UNLOCK_OK" in script

        cancelled = {"n": 0}

        def fake_cancel(script_text, timeout_sec=30):
            cancelled["n"] += 1
            return {"success": False, "cancelled": True, "stderr": "UAC cancelled"}

        loc._elevate_runner = fake_cancel
        _install_fake_location_registry({"DisableLocation": 1})
        loc.invalidate_cache()
        res = unlock_location_via_uac()
        assert res["cancelled"] is True
        assert res["success"] is False
        assert "UAC" in res["message"] or "hủy" in res["message"].lower()
        assert cancelled["n"] == 1

        store = {"DisableLocation": 1}

        def query_mutating(hive, path, name):
            if "LocationAndSensors" in str(path) and name in store:
                return store[name]
            raise FileNotFoundError(name)

        def fake_ok(script_text, timeout_sec=30):
            store.clear()
            return {"success": True, "cancelled": False}

        loc._query_value_fn = query_mutating
        loc._elevate_runner = fake_ok
        loc.invalidate_cache()
        ok = unlock_location_via_uac()
        assert ok["success"] is True
        assert ok["cancelled"] is False
        assert ok["locked_after"] is False
        assert "gỡ khóa" in ok["message"].lower() or "Location" in ok["message"]
    finally:
        loc.reset_state()


def test_repair_does_not_auto_unlock_location_gpo():
    """Automatic wifi_recovery must never launch UAC / edit GPO."""
    import core.windows_location as loc
    orig, counts = _patch_wifi_repair()
    clock = FakeClock(50)
    elevate_calls = []

    def boom(script_text, timeout_sec=30):
        elevate_calls.append(script_text)
        raise AssertionError("wifi_recovery must not auto-unlock Location GPO")

    try:
        _install_fake_location_registry({"DisableLocation": 1})
        loc._elevate_runner = boom
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: 33.0)
        SystemMonitor.reset_ping_state()
        WifiRecovery.reset_state()
        result = WifiRecovery.diagnose_and_repair_wifi_drop(
            apply_dns=False,
            snapshot=_wifi_snap(location_gpo_locked=True),
            sleep_fn=clock.sleep,
            clock_fn=clock.time,
            stability_sec=8,
        )
        assert elevate_calls == []
        skipped = " ".join(result.get("skipped") or [])
        assert "Location" in skipped or "Group Policy" in skipped
        assert result.get("needs_location_unlock") is True
        assert result.get("location_gpo_locked") is True
        assert "Disable-NetAdapter" not in str(result.get("steps"))
    finally:
        loc.reset_state()
        _restore_wifi_repair(orig)


def test_reconnect_reports_location_blocked_without_unlock():
    import core.windows_location as loc
    WifiRecovery.reset_state()
    cmds = []

    def runner(cmd, timeout=8):
        cmds.append(cmd)
        return {
            "success": False,
            "stdout": "Location permission is disabled. Please enable Location permission.",
            "stderr": "",
            "returncode": 1,
        }

    try:
        _install_fake_location_registry({"DisableLocation": 1})
        loc._elevate_runner = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no UAC"))
        WifiRecovery._cmd_runner = runner
        res = WifiRecovery.reconnect_wifi_profile("", "Wi-Fi", now=5000, min_interval=0)
        assert res["success"] is False
        assert res.get("location_blocked") is True
        assert "Gỡ khóa Location" in res["message"]
        assert loc._elevate_runner  # still hooked, never called
        wlan = parse_wlan_interfaces(
            "Unable to retrieve wireless interface because location services are turned off."
        )
        assert wlan["location_blocked"] is True
    finally:
        loc.reset_state()
        WifiRecovery.reset_state()


def test_advisor_surfaces_location_unlock_cta():
    import core.windows_location as loc
    from core.ai_advisor import AIAdvisor, CATEGORY_NETWORK
    WifiRecovery.reset_state()
    try:
        _install_fake_location_registry({"DisableLocation": 1})
        loc.invalidate_cache()
        adv = AIAdvisor()
        adv._cache_ttl = 0.0
        for _ in range(4):
            adv.feed_snapshot({
                "ram": {"percent": 40.0},
                "cpu": {"percent": 10.0},
                "disk": {"free_gb": 80.0},
                "net": {"ping_ms": 28.0, "ping_measured": True, "ping_status": "ok"},
            })
        sug = [s for s in adv.get_suggestions() if s.category == CATEGORY_NETWORK]
        loc_sugs = [s for s in sug if s.action_key == "unlock_location"]
        assert loc_sugs, "Advisor must offer Gỡ khóa Location when GPO is locked"
        assert "Group Policy" in loc_sugs[0].detail or "DisableLocation" in loc_sugs[0].detail
        assert loc_sugs[0].action_label
    finally:
        loc.reset_state()
        WifiRecovery.reset_state()


if __name__ == "__main__":
    tests = [
        test_parse_helpers,
        test_classify_and_filtering_dns,
        test_overlay_wifi_words,
        test_classify_connected_low_rate_is_weak_not_link_loss,
        test_overlay_priority_flap_beats_weak_and_stale_report,
        test_snapshot_empty_netsh_keeps_up_adapter_as_weak,
        test_stability_window_fake_clock,
        test_reconnect_throttle_and_dhcp_cmds,
        test_power_save_no_nic_toggle,
        test_repair_does_not_stop_on_lucky_ping_during_flap,
        test_dns_only_when_filtering,
        test_should_trigger_wifi_and_wins_over_ping,
        test_detect_reconnect_loop_from_events,
        test_missing_ping_routes_to_wifi,
        test_connected_weak_skips_ssid_reconnect,
        test_config_wifi_defaults,
        test_should_show_recovery_toast_rules,
        test_recovery_toast_gate_mt7921_flap_spam,
        test_scheduler_has_toast_gate,
        test_location_gpo_detection_mocked_registry,
        test_repair_does_not_auto_unlock_location_gpo,
        test_reconnect_reports_location_blocked_without_unlock,
        test_advisor_surfaces_location_unlock_cta,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] wifi drop / flap recovery suite")
