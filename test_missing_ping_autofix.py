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
from core.system_monitor import SystemMonitor
from core.network_optimizer import NetworkOptimizer
from core.ai_advisor import AIAdvisor, CATEGORY_NETWORK
from core.ai_copilot import TelemetryCollector, OfflineExpertBrain
from core.predictive_ai import PredictiveAIEngine
from config_manager import DEFAULT_CONFIG, ConfigManager


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


def test_should_trigger_gates():
    S = BackgroundScheduler.should_trigger_missing_ping_fix
    assert S(True, -1, False, 9, 3, 1000, 0, 300, 0) is False
    assert S(True, 25.0, True, 0, 3, 1000, 0, 300, 0) is False
    assert S(False, -1, True, 5, 3, 1000, 0, 300, 0) is False
    assert S(True, -1, True, 1, 3, 1000, 0, 300, 0) is False
    assert S(True, -1, True, 3, 3, 1000, 900, 300, 0) is False
    assert S(True, -1, True, 4, 3, 1000, 100, 300, 2) is False
    assert S(True, -1, True, 3, 3, 1000, 100, 300, 0) is True


def test_health_check_shape():
    health = NetworkOptimizer.run_health_check(measure_ping=False)
    for key in ("adapter", "gateway", "dns", "connectivity", "ping"):
        assert key in health["checks"]
    assert "issues" in health and "summary" in health


def test_repair_skips_dns_and_short_circuits_on_good_ping():
    orig_m = SystemMonitor.__dict__["_measure_quick_ping"]
    orig_flush = NetworkOptimizer.__dict__["flush_dns"]
    orig_arp = NetworkOptimizer.__dict__["purge_arp_netbios"]
    orig_best = NetworkOptimizer.__dict__["apply_best_dns"]
    flush_n = {"n": 0}
    best_n = {"n": 0}

    def fake_flush(cls=None):
        flush_n["n"] += 1
        return {"action": "flush_dns", "success": True, "message": "flush-ok"}

    def fake_arp(cls=None):
        return {"action": "purge_arp_netbios", "success": True, "message": "arp-ok"}

    def fake_best(cls=None, allow_elevation=True):
        best_n["n"] += 1
        return {"success": True, "message": "dns-applied"}

    NetworkOptimizer.flush_dns = classmethod(fake_flush)
    NetworkOptimizer.purge_arp_netbios = classmethod(fake_arp)
    NetworkOptimizer.apply_best_dns = classmethod(fake_best)
    try:
        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: 22.0)
        SystemMonitor.reset_ping_state()
        skip = NetworkOptimizer.diagnose_and_repair_missing_ping(apply_dns=False)
        assert skip["repaired"] is False
        assert skip["recovered"] is True
        assert flush_n["n"] == 0

        SystemMonitor._measure_quick_ping = staticmethod(lambda timeout=0.45: -1.0)
        SystemMonitor.reset_ping_state()
        fixed = NetworkOptimizer.diagnose_and_repair_missing_ping(apply_dns=False)
        assert fixed["repaired"] is True
        assert flush_n["n"] >= 1
        assert best_n["n"] == 0
        actions = [s.get("action") for s in fixed.get("steps", [])]
        assert "flush_dns" in actions
        assert "apply_best_dns" not in actions
        assert any("Winsock" in s or "card" in s.lower() for s in fixed.get("skipped", []))
    finally:
        NetworkOptimizer.flush_dns = orig_flush
        NetworkOptimizer.purge_arp_netbios = orig_arp
        NetworkOptimizer.apply_best_dns = orig_best
        SystemMonitor._measure_quick_ping = orig_m
        SystemMonitor.reset_ping_state()


def test_advisor_missing_ping_suggestion():
    adv = AIAdvisor()
    adv._cache_ttl = 0.0
    for _ in range(4):
        adv.feed_snapshot({
            "ram": {"percent": 40.0},
            "cpu": {"percent": 10.0},
            "disk": {"free_gb": 80.0},
            "net": {"ping_ms": -1.0, "ping_measured": True},
        })
    sug = [s for s in adv.get_suggestions() if s.category == CATEGORY_NETWORK]
    assert sug
    assert sug[0].action_key == "repair_network_now"


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
    assert int(DEFAULT_CONFIG.get("auto_network_ping_fail_streak", 0)) >= 3
    assert int(DEFAULT_CONFIG.get("auto_network_ping_fix_cooldown_seconds", 0)) >= 60
    cfg = ConfigManager.__new__(ConfigManager)
    cfg.config = dict(DEFAULT_CONFIG)
    assert cfg.config["auto_network_ping_fix_enabled"] is True


if __name__ == "__main__":
    tests = [
        test_telemetry_measures_ping,
        test_should_trigger_gates,
        test_health_check_shape,
        test_repair_skips_dns_and_short_circuits_on_good_ping,
        test_advisor_missing_ping_suggestion,
        test_copilot_replies,
        test_health_score_prescription,
        test_config_defaults,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] missing-ping auto-fix suite")
