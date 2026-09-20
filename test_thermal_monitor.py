"""
Unit tests for laptop thermal monitoring.

No live hardware asserts — parsers, threshold, cooldown, and the honest
no-sensor path are exercised with fixtures.
"""
from __future__ import annotations

import json
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

from core.thermal_monitor import (
    DEFAULT_TOAST_COOLDOWN_SEC,
    DEFAULT_WARN_CELSIUS,
    EMPTY_HINT_VI,
    EMPTY_STATE_VI,
    THERMAL_TOAST_KIND,
    ThermalToastGate,
    build_thermal_snapshot,
    build_thermal_toast_payload,
    classify_sensor_kind,
    classify_status,
    coerce_to_celsius,
    collect_thermal_snapshot,
    format_celsius,
    is_hot_snapshot,
    kelvin_tenths_to_celsius,
    parse_acpi_thermal_zone_payload,
    parse_nvidia_smi_csv,
    parse_ohm_like_sensors,
    parse_psutil_temperatures,
    parse_win32_temperature_probe_payload,
    reset_thermal_cache,
    sanitize_celsius,
)
from config_manager import DEFAULT_CONFIG

LHM_SAMPLE = [
    {
        "Name": "CPU Package",
        "Value": 67.0,
        "Identifier": "/intelcpu/0/temperature/0",
        "SensorType": "Temperature",
    },
    {
        "Name": "CPU Core #0",
        "Value": 64.5,
        "Identifier": "/intelcpu/0/temperature/1",
        "SensorType": "Temperature",
    },
    {
        "Name": "GPU Core",
        "Value": 54.0,
        "Identifier": "/nvidiagpu/0/temperature/0",
        "SensorType": "Temperature",
    },
    {
        "Name": "Fan",
        "Value": 2100,
        "Identifier": "/lpc/nct/fan/0",
        "SensorType": "Fan",
    },
]

ACPI_SAMPLE = {
    "InstanceName": "ACPI\\ThermalZone\\TZ00_0",
    "CurrentTemperature": 3382,  # tenths Kelvin → ~65°C
}

NVIDIA_CSV = "NVIDIA GeForce RTX 3050 Laptop GPU, 62\n"


def setup_function():
    reset_thermal_cache()


def test_sanitize_rejects_dummy_and_out_of_range():
    assert sanitize_celsius(None) is None
    assert sanitize_celsius("") is None
    assert sanitize_celsius("N/A") is None
    assert sanitize_celsius(0) is None
    assert sanitize_celsius(9.9) is None
    assert sanitize_celsius(121) is None
    assert sanitize_celsius(999) is None
    assert sanitize_celsius(72) == 72.0
    assert sanitize_celsius("68.4") == 68.4


def test_kelvin_tenths_acpi_conversion():
    c = kelvin_tenths_to_celsius(3382)
    assert c is not None
    assert 64.0 <= c <= 66.0
    assert kelvin_tenths_to_celsius(0) is None
    assert kelvin_tenths_to_celsius(None) is None


def test_coerce_heuristic_kelvin_vs_celsius():
    assert coerce_to_celsius(72, "celsius") == 72.0
    k = coerce_to_celsius(310)  # Kelvin
    assert k is not None and 35.0 <= k <= 38.0
    tenths = coerce_to_celsius(3382)  # tenths of Kelvin
    assert tenths is not None and 64.0 <= tenths <= 66.0


def test_classify_sensor_kind():
    assert classify_sensor_kind("CPU Package", "/intelcpu/0/temperature/0") == "package"
    assert classify_sensor_kind("Tctl", "/amdcpu/0") == "package"
    assert classify_sensor_kind("CPU Core #1") == "cpu"
    assert classify_sensor_kind("GPU Core", "/nvidiagpu/0") == "gpu"
    assert classify_sensor_kind("NVIDIA GeForce RTX 3050 Laptop GPU") == "gpu"
    assert classify_sensor_kind("ACPI\\ThermalZone\\TZ00_0") == "cpu"


def test_parse_lhm_json_ignores_non_temperature():
    sensors = parse_ohm_like_sensors(LHM_SAMPLE, "libre_hardware_monitor")
    names = {s["name"] for s in sensors}
    assert "CPU Package" in names
    assert "GPU Core" in names
    assert "Fan" not in names
    kinds = {s["name"]: s["kind"] for s in sensors}
    assert kinds["CPU Package"] == "package"
    assert kinds["GPU Core"] == "gpu"
    # Single-object JSON (PowerShell when one sensor)
    one = parse_ohm_like_sensors(json.dumps(LHM_SAMPLE[0]), "libre_hardware_monitor")
    assert len(one) == 1 and one[0]["celsius"] == 67.0


def test_parse_acpi_and_empty_win32_probe():
    acpi = parse_acpi_thermal_zone_payload(ACPI_SAMPLE)
    assert len(acpi) == 1
    assert 64.0 <= acpi[0]["celsius"] <= 66.0
    empty_probe = parse_win32_temperature_probe_payload(
        {"Name": "CPU Thermal Zone", "CurrentReading": None}
    )
    assert empty_probe == []
    bogus = parse_acpi_thermal_zone_payload({"InstanceName": "TZ00", "CurrentTemperature": 0})
    assert bogus == []


def test_parse_nvidia_smi_and_psutil():
    gpu = parse_nvidia_smi_csv(NVIDIA_CSV)
    assert len(gpu) == 1
    assert gpu[0]["kind"] == "gpu"
    assert gpu[0]["celsius"] == 62.0
    assert parse_nvidia_smi_csv("") == []
    ps = parse_psutil_temperatures({
        "coretemp": [
            {"label": "Package id 0", "current": 45.0},
            {"label": "Core 0", "current": 43.0},
        ]
    })
    assert any(s["kind"] == "package" for s in ps)
    assert parse_psutil_temperatures({}) == []
    assert parse_psutil_temperatures(None) == []


def test_no_sensor_path_does_not_fake_numbers():
    snap = build_thermal_snapshot([], warn_celsius=90)
    assert snap["available"] is False
    assert snap["cpu_celsius"] is None
    assert snap["gpu_celsius"] is None
    assert snap["package_celsius"] is None
    assert snap["hottest_celsius"] is None
    assert snap["hot"] is False
    assert snap["status"] == "unavailable"
    assert "không bịa" in snap["empty_message"].lower() or "khong bia" in snap["empty_message"].lower() or "không có cảm biến" in snap["empty_message"]
    assert EMPTY_STATE_VI in snap["empty_message"] or snap["empty_message"] == EMPTY_STATE_VI
    assert "LibreHardwareMonitor" in snap["hint"]
    assert EMPTY_HINT_VI == snap["hint"]
    assert format_celsius(None) == "—"
    assert is_hot_snapshot(snap, 90) is False
    assert build_thermal_toast_payload(snap) is None


def test_collect_with_empty_injected_probes():
    reset_thermal_cache()
    snap = collect_thermal_snapshot(force_refresh=True, probes=[])
    assert snap["available"] is False
    assert snap["hottest_celsius"] is None
    assert "cảm biến" in snap["empty_message"].lower() or "cam bien" in snap["empty_message"].lower()


def test_collect_prefers_lhm_then_fills_nothing_fake():
    reset_thermal_cache()

    def lhm():
        return parse_ohm_like_sensors(LHM_SAMPLE, "libre_hardware_monitor")

    def acpi_should_not_run():
        raise AssertionError("ACPI must not run after LHM hit")

    snap = collect_thermal_snapshot(
        force_refresh=True,
        probes=[
            ("libre_hardware_monitor", lhm),
            ("acpi_thermal_zone", acpi_should_not_run),
        ],
        warn_celsius=90,
    )
    assert snap["available"] is True
    assert snap["package_celsius"] == 67.0
    assert snap["gpu_celsius"] == 54.0
    assert snap["source"] == "libre_hardware_monitor"
    assert snap["hot"] is False
    assert snap["status"] == "ok"


def test_threshold_and_toast_payload():
    sensors = parse_ohm_like_sensors(
        [{"Name": "CPU Package", "Value": 94, "SensorType": "Temperature", "Identifier": "/intelcpu/0"}],
        "libre_hardware_monitor",
    )
    snap = build_thermal_snapshot(sensors, warn_celsius=90)
    assert snap["hot"] is True
    assert snap["status"] == "hot"
    assert is_hot_snapshot(snap, 90) is True
    assert is_hot_snapshot(snap, 95) is False
    payload = build_thermal_toast_payload(snap, warn_celsius=90)
    assert payload is not None
    assert payload["type"] == THERMAL_TOAST_KIND
    assert "94" in payload["message"]
    assert "90" in payload["message"]
    assert payload["title"] == "Laptop đang nóng"

    cool = build_thermal_snapshot(
        parse_ohm_like_sensors(
            [{"Name": "CPU Package", "Value": 72, "SensorType": "Temperature"}],
            "libre_hardware_monitor",
        ),
        warn_celsius=90,
    )
    assert cool["status"] == "ok"
    assert classify_status(82, 90) == "warm"


def test_toast_gate_cooldown_matches_wifi_spirit():
    gate = ThermalToastGate()
    assert gate.allow(1000.0, cooldown_sec=1800) is True
    assert gate.allow(1001.0, cooldown_sec=1800) is False
    assert gate.allow(1000.0 + 1799, cooldown_sec=1800) is False
    assert gate.allow(1000.0 + 1800, cooldown_sec=1800) is True
    gate.reset()
    cfg = {"thermal_warn_toast_cooldown_seconds": 60}
    assert gate.allow_from_config(50.0, cfg) is True
    assert gate.allow_from_config(80.0, cfg) is False
    assert gate.allow_from_config(110.0, cfg) is True


def test_default_config_thermal_keys():
    assert DEFAULT_CONFIG.get("thermal_monitor_enabled") is True
    assert DEFAULT_CONFIG.get("thermal_warn_toast_enabled") is True
    assert int(DEFAULT_CONFIG.get("thermal_warn_celsius", 0)) == DEFAULT_WARN_CELSIUS
    assert int(DEFAULT_CONFIG.get("thermal_warn_toast_cooldown_seconds", 0)) >= 300
    assert int(DEFAULT_CONFIG["thermal_warn_toast_cooldown_seconds"]) == int(DEFAULT_TOAST_COOLDOWN_SEC)


def test_merge_nvidia_gpu_onto_acpi_cpu():
    reset_thermal_cache()

    def acpi():
        return parse_acpi_thermal_zone_payload(ACPI_SAMPLE)

    def nv():
        return parse_nvidia_smi_csv(NVIDIA_CSV)

    snap = collect_thermal_snapshot(
        force_refresh=True,
        probes=[
            ("acpi_thermal_zone", acpi),
            ("nvidia_smi", nv),
        ],
    )
    assert snap["available"] is True
    assert snap["gpu_celsius"] == 62.0
    assert snap["hottest_celsius"] is not None
    assert snap["cpu_celsius"] is not None or snap["other_celsius"] is not None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            setup_function()
            fn()
            print(f"ok {name}")
    print("thermal tests passed")
