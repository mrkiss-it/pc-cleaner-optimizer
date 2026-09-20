"""
Offscreen tests for missing-ping detection, health check, and safe auto-repair.
Stubs Windows-only modules so this file can run on Linux CI.
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

from core.scheduler import BackgroundScheduler
from core.system_monitor import (
    SystemMonitor,
    PING_SOCKET_TIMEOUT,
    PING_REPAIR_TIMEOUT,
    PING_TARGETS,
    format_ping_overlay_text,
)
from core.network_optimizer import NetworkOptimizer
from core.ai_advisor import AIAdvisor, CATEGORY_NETWORK
from core.ai_copilot import TelemetryCollector, OfflineExpertBrain
from core.predictive_ai import PredictiveAIEngine
from config_manager import DEFAULT_CONFIG, ConfigManager


def _canned_health(ping_ms: float, extra_issues=None, connectivity_ok=True, conn_error="", dns_ok=True):
    ping_ok = ping_ms > 0
    issues = list(extra_issues or [])
    if not ping_ok:
        issues.append("ping_missing")
    if not connectivity_ok and "no_connectivity" not in issues:
        issues.append("no_connectivity")
    if not dns_ok and "dns_fail" not in issues:
        issues.append("dns_fail")
    probe = {"ok": connectivity_ok, "error": conn_error, "latency_ms": 40.0 if connectivity_ok else -1.0}
    return {
        "ok": ping_ok and connectivity_ok,
        "summary": "canned",
        "issues": issues,
        "checks": {
            "adapter": {"ok": "adapter_down" not in issues},
            "gateway": {"ok": "no_gateway" not in issues},
            "dns": {"ok": dns_ok},
            "connectivity": {
                "ok": connectivity_ok,
                "cloudflare": dict(probe),
                "google_dns": dict(probe),
                "google_https": dict(probe),
            },
            "ping": {
                "ok": ping_ok,
                "ping_ms": ping_ms,
                "status": "ok" if ping_ok else "timeout",
            },
        },
    }


def _install_fast_health():
    """Avoid real TCP/DNS during repair tests; still measures ping via SystemMonitor."""
    orig = NetworkOptimizer.__dict__["run_health_check"]

    def fake(cls, measure_ping=True):
        ping = SystemMonitor.measure_ping_now() if measure_ping else float(
            SystemMonitor.get_network_info().get("ping_ms", -1)
        )
        return _canned_health(ping, connectivity_ok=True)

    NetworkOptimizer.run_health_check = classmethod(fake)
    return orig


def test_telemetry_measures_ping():
    orig = SystemMonitor.__dict__["_measure_quick_ping"]
    SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: 18.5)
    SystemMonitor.reset_ping_state()
    try:
        tel = TelemetryCollector.collect()
        assert tel["net"]["ping_ms"] == 18.5
        assert tel["net"]["ping_measured"] is True
        assert tel["net"]["ping_status"] == "ok"
    finally:
        SystemMonitor._measure_quick_ping = orig
        SystemMonitor.reset_ping_state()


def test_meter_timeout_and_targets():
    assert PING_SOCKET_TIMEOUT >= 1.5
    assert PING_REPAIR_TIMEOUT >= PING_SOCKET_TIMEOUT
    assert ("8.8.8.8", 443) in PING_TARGETS
    assert any(port == 443 and host not in ("8.8.8.8", "1.1.1.1") for host, port in PING_TARGETS)


def test_overlay_shows_timeout_not_dash():
    assert format_ping_overlay_text(28.0, True, "ok") == "28 ms"
    assert format_ping_overlay_text(-1, False, "unknown") == "-- ms"
    assert format_ping_overlay_text(-1, True, "timeout") == "timeout"
    assert format_ping_overlay_text(-1, True, "meter_timeout") == "timeout"
    assert format_ping_overlay_text(-1, True, "unreachable") == "mất"
    assert format_ping_overlay_text(-1, True, "dns_fail") == "DNS"
    assert format_ping_overlay_text(-1, True, "reconnect_loop") == "rớt"
    assert format_ping_overlay_text(26, True, "ok", wifi_status="weak_link") == "26 ms · yếu"
    assert format_ping_overlay_text(-1, True, "timeout", wifi_status="weak_link") == "timeout"


def test_diagnosis_labels():
    C = NetworkOptimizer.classify_missing_ping_cause
    cause, label = C(_canned_health(-1, extra_issues=["adapter_down"]))
    assert cause == "adapter_down"
    assert "card mạng" in label

    cause, label = C(_canned_health(-1, extra_issues=["no_gateway"]))
    assert cause == "no_gateway"
    assert "gateway" in label

    cause, label = C(_canned_health(-1, dns_ok=False, connectivity_ok=True))
    assert cause == "dns_fail"
    assert "DNS" in label

    cause, label = C(_canned_health(-1, connectivity_ok=False, conn_error="timed out"))
    assert cause == "tcp_fail"
    assert "TCP" in label

    cause, label = C(
        _canned_health(-1, connectivity_ok=False, conn_error="No route to host"),
        ping_status="unreachable",
    )
    assert cause == "firewall_or_no_route"
    assert "firewall" in label or "tuyến" in label

    cause, label = C(_canned_health(-1, connectivity_ok=True), ping_status="timeout", down_bps=12000)
    assert cause == "meter_timeout"
    assert "quá thời gian" in label or "timeout" in label.lower()


def test_should_trigger_gates():
    S = BackgroundScheduler.should_trigger_missing_ping_fix
    assert S(True, -1, False, 9, 3, 1000, 0, 300, 0) is False
    assert S(True, 25.0, True, 0, 3, 1000, 0, 300, 0) is False
    assert S(False, -1, True, 5, 3, 1000, 0, 300, 0) is False
    assert S(True, -1, True, 1, 3, 1000, 0, 300, 0) is False
    assert S(True, -1, True, 3, 3, 1000, 900, 300, 0) is False
    assert S(True, -1, True, 4, 3, 1000, 100, 300, 2) is False
    assert S(True, -1, True, 3, 3, 1000, 100, 300, 0) is True


def test_first_repair_immediacy_and_backoff():
    S = BackgroundScheduler.should_trigger_missing_ping_fix
    E = BackgroundScheduler.effective_missing_ping_cooldown
    assert E(0, 8, 300) == 8
    assert E(1, 8, 300) == 300
    assert E(2, 8, 300) == 600
    # First repair: 8s gate, 10s elapsed → fire
    assert S(
        True, -1, True, 1, 1, 1000, 990, 300, 0,
        first_cooldown_sec=8,
    ) is True
    # First repair: 8s gate, only 2s elapsed → wait
    assert S(
        True, -1, True, 1, 1, 1000, 998, 300, 0,
        first_cooldown_sec=8,
    ) is False
    # First repair with 0s gate → immediate
    assert S(
        True, -1, True, 1, 1, 1000, 999, 300, 0,
        first_cooldown_sec=0,
    ) is True
    # After one unrecovered: still in 300s backoff
    assert S(
        True, -1, True, 1, 1, 1000, 900, 300, 1,
        first_cooldown_sec=8,
    ) is False
    # After one unrecovered: backoff elapsed → fire
    assert S(
        True, -1, True, 1, 1, 1400, 1000, 300, 1,
        first_cooldown_sec=8,
    ) is True
    # Two unrecovered → stop (no infinite loop)
    assert S(
        True, -1, True, 9, 1, 9999, 0, 300, 2,
        first_cooldown_sec=8,
    ) is False


def test_health_check_shape():
    health = NetworkOptimizer.run_health_check(measure_ping=False)
    for key in ("adapter", "gateway", "dns", "connectivity", "ping"):
        assert key in health["checks"]
    assert "issues" in health and "summary" in health
    assert "google_https" in health["checks"]["connectivity"]


def _patch_repair_actions():
    orig = {
        "flush": NetworkOptimizer.__dict__["flush_dns"],
        "arp": NetworkOptimizer.__dict__["purge_arp_netbios"],
        "best": NetworkOptimizer.__dict__["apply_best_dns"],
        "tcp": NetworkOptimizer.__dict__["optimize_tcp_stack"],
        "health": NetworkOptimizer.__dict__["run_health_check"],
        "measure": SystemMonitor.__dict__["_measure_quick_ping"],
    }
    counts = {"flush": 0, "arp": 0, "best": 0, "tcp": 0}

    def fake_flush(cls=None):
        counts["flush"] += 1
        return {"action": "flush_dns", "success": True, "message": "flush-ok"}

    def fake_arp(cls=None):
        counts["arp"] += 1
        return {"action": "purge_arp_netbios", "success": True, "message": "arp-ok"}

    def fake_best(cls=None, allow_elevation=True):
        counts["best"] += 1
        return {"success": True, "message": "dns-applied", "needs_admin": False}

    def fake_tcp(cls=None):
        counts["tcp"] += 1
        return {"action": "optimize_tcp_stack", "success": True, "message": "tcp-ok"}

    NetworkOptimizer.flush_dns = classmethod(fake_flush)
    NetworkOptimizer.purge_arp_netbios = classmethod(fake_arp)
    NetworkOptimizer.apply_best_dns = classmethod(fake_best)
    NetworkOptimizer.optimize_tcp_stack = classmethod(fake_tcp)
    _install_fast_health()
    return orig, counts


def _restore_repair_actions(orig):
    NetworkOptimizer.flush_dns = orig["flush"]
    NetworkOptimizer.purge_arp_netbios = orig["arp"]
    NetworkOptimizer.apply_best_dns = orig["best"]
    NetworkOptimizer.optimize_tcp_stack = orig["tcp"]
    NetworkOptimizer.run_health_check = orig["health"]
    SystemMonitor._measure_quick_ping = orig["measure"]
    SystemMonitor.reset_ping_state()
    NetworkOptimizer.last_missing_ping_report = {}


def test_repair_short_circuits_on_good_ping():
    orig, counts = _patch_repair_actions()
    try:
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: 22.0)
        SystemMonitor.reset_ping_state()
        skip = NetworkOptimizer.diagnose_and_repair_missing_ping(apply_dns=False)
        assert skip["repaired"] is False
        assert skip["recovered"] is True
        assert counts["flush"] == 0
        assert counts["best"] == 0
    finally:
        _restore_repair_actions(orig)


def test_timeout_increase_path_recovers_without_flush():
    orig, counts = _patch_repair_actions()
    timeouts = []

    def fake(timeout=0.45):
        timeouts.append(timeout)
        return 85.0 if timeout >= 1.9 else -1.0

    try:
        SystemMonitor._measure_quick_ping = staticmethod(fake)
        SystemMonitor.reset_ping_state()
        result = NetworkOptimizer.diagnose_and_repair_missing_ping()
        assert any(t >= 1.9 for t in timeouts), f"Repair must remeasure with long timeout, got {timeouts}"
        assert result["recovered"] is True
        assert result["repaired"] is True
        assert counts["flush"] == 0, "Must stop after longer timeout recovers"
        assert counts["best"] == 0
        assert result["stopped_at"] == "remeasure_long_timeout"
        assert "Nguyên nhân" in result["message"]
        assert "timeout" in result["message"].lower() or "quá thời gian" in result["message"]
    finally:
        _restore_repair_actions(orig)


def test_repair_stops_after_flush_recovers():
    orig, counts = _patch_repair_actions()
    state = {"n": 0}

    def fake(timeout=0.45):
        state["n"] += 1
        # health + first remasure fail; after flush the next remasure succeeds
        return -1.0 if state["n"] <= 2 else 40.0

    try:
        SystemMonitor._measure_quick_ping = staticmethod(fake)
        SystemMonitor.reset_ping_state()
        result = NetworkOptimizer.diagnose_and_repair_missing_ping()
        assert result["recovered"] is True
        assert counts["flush"] == 1
        assert counts["arp"] == 0
        assert counts["best"] == 0
        assert "flush_dns" in [s.get("action") for s in result["steps"]]
    finally:
        _restore_repair_actions(orig)


def test_escalate_to_dns_when_flush_fails():
    orig, counts = _patch_repair_actions()
    try:
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: -1.0)
        SystemMonitor.reset_ping_state()
        fixed = NetworkOptimizer.diagnose_and_repair_missing_ping(apply_dns=False, escalate_dns=True)
        assert fixed["repaired"] is True
        assert counts["flush"] >= 1
        assert counts["arp"] >= 1
        assert counts["best"] >= 1, "Flush/ARP failed → must apply best DNS"
        actions = [s.get("action") for s in fixed.get("steps", [])]
        assert "flush_dns" in actions
        assert "apply_best_dns" in actions
        assert any("Winsock" in s or "card" in s.lower() for s in fixed.get("skipped", []))
        assert "Nguyên nhân" in fixed["message"]
        assert "Đã sửa" in fixed["message"] or "đã sửa" in fixed["message"].lower()
    finally:
        _restore_repair_actions(orig)


def test_no_infinite_loop_after_unrecovered():
    S = BackgroundScheduler.should_trigger_missing_ping_fix
    # Simulate two failed repairs then ping still missing
    fired = 0
    unrecovered = 0
    last = 0
    now = 1000
    for i in range(20):
        now += 400
        if S(
            True, -1, True, 5, 1, now, last, 300, unrecovered,
            max_unrecovered=2, first_cooldown_sec=8,
        ):
            fired += 1
            last = now
            unrecovered += 1
    assert fired == 2
    assert unrecovered == 2
    assert S(
        True, -1, True, 9, 1, now + 9999, last, 300, unrecovered,
        max_unrecovered=2, first_cooldown_sec=8,
    ) is False


def test_advisor_missing_ping_suggestion():
    adv = AIAdvisor()
    adv._cache_ttl = 0.0
    from core.wifi_recovery import WifiRecovery
    WifiRecovery.reset_state()
    NetworkOptimizer.last_missing_ping_report = {
        "cause_label": "đồng hồ Ping quá thời gian (probe chậm hoặc bị chặn)",
        "applied_summary": "flush DNS, làm mới ARP/NetBIOS",
    }
    try:
        for _ in range(4):
            adv.feed_snapshot({
                "ram": {"percent": 40.0},
                "cpu": {"percent": 10.0},
                "disk": {"free_gb": 80.0},
                "net": {"ping_ms": -1.0, "ping_measured": True, "ping_status": "timeout"},
            })
        sug = [s for s in adv.get_suggestions() if s.category == CATEGORY_NETWORK]
        assert sug
        assert sug[0].action_key == "repair_network_now"
        assert "Nguyên nhân" in sug[0].detail
        assert "Đã sửa" in sug[0].detail
    finally:
        NetworkOptimizer.last_missing_ping_report = {}


def test_copilot_replies():
    ok = OfflineExpertBrain.answer(
        "Kiem tra mang va giam giat ping",
        telemetry={
            "ram": {"percent": 40}, "cpu": {"percent": 10},
            "disk": {"free_gb": 50, "total_gb": 256},
            "battery": {"percent": 100, "power_plugged": True},
            "net": {"ping_ms": 28.0, "ping_measured": True, "ping_status": "ok"},
        },
    )
    assert any(a.key in ("optimize_network", "switch_dns") for a in ok.actions)
    assert "28" in ok.reply

    miss = OfflineExpertBrain.answer(
        "Ping khong co, mat mang",
        telemetry={
            "ram": {"percent": 40}, "cpu": {"percent": 10},
            "disk": {"free_gb": 50, "total_gb": 256},
            "battery": {"percent": 100, "power_plugged": True},
            "net": {"ping_ms": -1.0, "ping_measured": True, "ping_status": "timeout"},
        },
    )
    assert any(a.key == "repair_network_now" for a in miss.actions)
    assert "không đo được" in miss.reply.lower() or "Ping" in miss.reply


def test_health_score_prescription():
    engine = PredictiveAIEngine()
    report = engine.calculate_health_score(
        stats={
            "ram": {"percent": 40}, "cpu": {"percent": 10},
            "disk": {"free_gb": 80, "total_gb": 256},
            "net": {"ping_ms": -1.0, "ping_measured": True},
        },
        force_refresh=True,
    )
    assert any(p.get("action_key") == "repair_network_now" for p in report.prescription)


def test_config_defaults():
    assert DEFAULT_CONFIG.get("auto_network_ping_fix_enabled") is True
    assert int(DEFAULT_CONFIG.get("auto_network_ping_fail_streak", 0)) >= 1
    assert int(DEFAULT_CONFIG.get("auto_network_ping_fix_first_cooldown_seconds", 99)) <= 15
    assert int(DEFAULT_CONFIG.get("auto_network_ping_fix_cooldown_seconds", 0)) >= 60
    cfg = ConfigManager.__new__(ConfigManager)
    cfg.config = dict(DEFAULT_CONFIG)
    assert cfg.config["auto_network_ping_fix_enabled"] is True


def test_toast_action_does_not_crash_deleted_timer():
    """Clicking a missing-ping toast action must stop QTimer before deleteLater."""
    from PyQt5.QtWidgets import QApplication
    from ui.toast_notification import ToastNotification, LEVEL_WARNING
    app = QApplication.instance() or QApplication([])
    fired = []

    def _cb():
        fired.append(True)
        # Pump events the way opening Network dialog would.
        app.processEvents()

    toast = ToastNotification(
        title="Tự kiểm tra & sửa mạng",
        message="Nguyên nhân: đồng hồ Ping quá thời gian. Đã sửa: flush DNS.",
        level=LEVEL_WARNING,
        action_text="📶 Xem Mạng",
        action_callback=_cb,
        duration_ms=2500,
    )
    toast.start(toast.pos())
    app.processEvents()
    toast._on_tick()
    toast._on_action_clicked()
    assert fired == [True]
    assert toast._dismissing is True
    toast._on_tick()  # must not raise RuntimeError
    toast.dismiss()   # idempotent
    toast._on_action_clicked()
    app.processEvents()


if __name__ == "__main__":
    tests = [
        test_telemetry_measures_ping,
        test_meter_timeout_and_targets,
        test_overlay_shows_timeout_not_dash,
        test_diagnosis_labels,
        test_should_trigger_gates,
        test_first_repair_immediacy_and_backoff,
        test_health_check_shape,
        test_repair_short_circuits_on_good_ping,
        test_timeout_increase_path_recovers_without_flush,
        test_repair_stops_after_flush_recovers,
        test_escalate_to_dns_when_flush_fails,
        test_no_infinite_loop_after_unrecovered,
        test_advisor_missing_ping_suggestion,
        test_copilot_replies,
        test_health_score_prescription,
        test_config_defaults,
        test_toast_action_does_not_crash_deleted_timer,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] missing-ping auto-fix suite")
