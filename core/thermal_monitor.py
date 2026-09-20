"""
Giám sát nhiệt laptop (CPU package / CPU / GPU) mà không bịa số.

Windows thường để trống MSAcpi_ThermalZoneTemperature và Win32_TemperatureProbe
(nhiều laptop ASUS + MediaTek Wi-Fi cũng vậy). Module này lần lượt thử nguồn
thực tế, bỏ qua giá trị vô lý, và trả empty-state tiếng Việt khi không đọc được.

Nguồn (không bắt buộc cài thêm, không bundle HWiNFO):
  1. LibreHardwareMonitor WMI  (root\\LibreHardwareMonitor) nếu user đang chạy LHM
  2. OpenHardwareMonitor WMI   (root\\OpenHardwareMonitor)
  3. nvidia-smi                (GPU NVIDIA nếu có trên PATH)
  4. ACPI thermal zone / Win32_TemperatureProbe / Windows Thermal Zone counter
  5. psutil.sensors_temperatures()  (Linux / một số máy; trên Windows thường rỗng)

Ngưỡng cảnh báo mặc định 90°C — quanh mốc laptop Intel/AMD bắt đầu throttle
(~95–100°C TJmax). Toast có cooldown (cùng tinh thần tip Ổn định Wi-Fi).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

DEFAULT_WARN_CELSIUS = 90
DEFAULT_TOAST_COOLDOWN_SEC = 1800.0  # 30 phút — giống wifi stability tip
MIN_PLAUSIBLE_C = 10.0
MAX_PLAUSIBLE_C = 120.0
CACHE_TTL_SEC = 8.0
EMPTY_CACHE_TTL_SEC = 45.0
SOURCE_MISS_SKIP_SEC = 600.0
THERMAL_TOAST_KIND = "thermal_hot"

LHM_PROJECT_URL = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor"

EMPTY_STATE_VI = (
    "Máy này không có cảm biến nhiệt Windows đọc được. "
    "Nhiều laptop (kể cả ASUS + card MediaTek Wi-Fi) để trống "
    "MSAcpi_ThermalZoneTemperature / Win32_TemperatureProbe. "
    "Ứng dụng không bịa số nhiệt độ."
)

EMPTY_HINT_VI = (
    "Tùy chọn: cài LibreHardwareMonitor (miễn phí, mã nguồn mở), chạy nền "
    "và bật WMI — app sẽ đọc CPU/GPU nếu cảm biến xuất hiện. "
    "Không cần HWiNFO."
)

SOURCE_LABELS_VI = {
    "libre_hardware_monitor": "LibreHardwareMonitor (WMI)",
    "open_hardware_monitor": "OpenHardwareMonitor (WMI)",
    "nvidia_smi": "nvidia-smi",
    "acpi_thermal_zone": "ACPI Thermal Zone",
    "win32_temperature_probe": "Win32_TemperatureProbe",
    "perf_thermal_zone": "Windows Thermal Zone",
    "psutil": "psutil",
    "none": "Không có cảm biến",
    "pending": "Đang kiểm tra",
}

STATUS_LABELS_VI = {
    "unavailable": "Không đọc được cảm biến",
    "pending": "Đang kiểm tra cảm biến…",
    "ok": "Ổn định",
    "warm": "Ấm",
    "hot": "Nóng — trên ngưỡng cảnh báo",
}

_cache_lock = threading.Lock()
_cached_snapshot: Optional[Dict[str, Any]] = None
_cached_at = 0.0
_collecting = False
_skip_until: Dict[str, float] = {}


def kelvin_tenths_to_celsius(raw: Any) -> Optional[float]:
    """ACPI MSAcpi_ThermalZoneTemperature.CurrentTemperature = tenths of Kelvin."""
    try:
        return sanitize_celsius((float(raw) / 10.0) - 273.15)
    except (TypeError, ValueError):
        return None


def kelvin_to_celsius(raw: Any) -> Optional[float]:
    try:
        return sanitize_celsius(float(raw) - 273.15)
    except (TypeError, ValueError):
        return None


def sanitize_celsius(raw: Any) -> Optional[float]:
    """Reject missing / dummy ACPI values. Never invent a number."""
    if raw is None or raw is False:
        return None
    if isinstance(raw, str):
        text = raw.strip().replace(",", ".")
        if not text or text.lower() in {"n/a", "nan", "none", "null"}:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if value != value:  # NaN
        return None
    if value < MIN_PLAUSIBLE_C or value > MAX_PLAUSIBLE_C:
        return None
    return round(value, 1)


def coerce_to_celsius(raw: Any, unit_hint: Optional[str] = None) -> Optional[float]:
    """
    Convert a vendor-specific reading to °C.

    Heuristic when unit is unknown:
      10–120   → already Celsius
      250–400  → Kelvin (Windows Thermal Zone counter)
      2800–4000 → tenths of Kelvin (ACPI CurrentTemperature)
    """
    if raw is None:
        return None
    hint = (unit_hint or "").strip().lower()
    if hint in {"kelvin_tenths", "tenths_kelvin", "acpi"}:
        return kelvin_tenths_to_celsius(raw)
    if hint in {"kelvin", "k"}:
        return kelvin_to_celsius(raw)
    if hint in {"celsius", "c", "°c"}:
        return sanitize_celsius(raw)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return sanitize_celsius(raw)
    if MIN_PLAUSIBLE_C <= value <= MAX_PLAUSIBLE_C:
        return sanitize_celsius(value)
    if 250.0 <= value <= 400.0:
        return kelvin_to_celsius(value)
    if 2800.0 <= value <= 4000.0:
        return kelvin_tenths_to_celsius(value)
    tenths = kelvin_tenths_to_celsius(value)
    if tenths is not None:
        return tenths
    return kelvin_to_celsius(value)


def classify_sensor_kind(name: str, identifier: str = "") -> str:
    blob = f"{name} {identifier}".lower()
    gpu_tokens = (
        "gpu", "nvidia", "radeon", "geforce", "graphics", "intel iris",
        "/nvidiagpu", "/amdgpu", "videocard",
    )
    if any(tok in blob for tok in gpu_tokens):
        return "gpu"
    package_tokens = (
        "package", "tdie", "tctl", "cpu die", "cpu package", "ia cores",
    )
    if any(tok in blob for tok in package_tokens):
        return "package"
    cpu_tokens = (
        "cpu", "core", "processor", "k10temp", "coretemp", "zenpower",
        "/intelcpu", "/amdcpu", "ccd",
    )
    if any(tok in blob for tok in cpu_tokens):
        return "cpu"
    # ACPI TZ is often the only Windows reading; treat as CPU-class, never invent a value.
    if "thermalzone" in blob or "thermal zone" in blob or "tz00" in blob or "tz01" in blob:
        return "cpu"
    return "other"


def parse_ohm_like_sensors(
    payload: Any,
    source: str,
    *,
    sensor_type: str = "Temperature",
) -> List[Dict[str, Any]]:
    """Parse LibreHardwareMonitor / OpenHardwareMonitor WMI JSON (object or list)."""
    if payload is None:
        return []
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        rows: Sequence[Any] = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        return []

    sensors: List[Dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        kind_raw = str(item.get("SensorType") or item.get("sensorType") or "Temperature")
        if sensor_type and kind_raw.lower() != sensor_type.lower():
            continue
        name = str(item.get("Name") or item.get("name") or "").strip() or "Cảm biến"
        ident = str(item.get("Identifier") or item.get("identifier") or "")
        celsius = coerce_to_celsius(item.get("Value") if "Value" in item else item.get("value"), "celsius")
        if celsius is None:
            continue
        sensors.append({
            "name": name,
            "celsius": celsius,
            "kind": classify_sensor_kind(name, ident),
            "source": source,
            "identifier": ident,
        })
    return sensors


def parse_acpi_thermal_zone_payload(payload: Any) -> List[Dict[str, Any]]:
    """Parse MSAcpi_ThermalZoneTemperature CIM JSON (CurrentTemperature = tenths K)."""
    rows = _as_rows(payload)
    sensors: List[Dict[str, Any]] = []
    for item in rows:
        name = str(item.get("InstanceName") or item.get("Name") or "ACPI Thermal Zone").strip()
        celsius = coerce_to_celsius(
            item.get("CurrentTemperature"),
            "kelvin_tenths",
        )
        if celsius is None:
            continue
        sensors.append({
            "name": name,
            "celsius": celsius,
            "kind": classify_sensor_kind(name),
            "source": "acpi_thermal_zone",
            "identifier": name,
        })
    return sensors


def parse_win32_temperature_probe_payload(payload: Any) -> List[Dict[str, Any]]:
    rows = _as_rows(payload)
    sensors: List[Dict[str, Any]] = []
    for item in rows:
        name = str(item.get("Name") or item.get("Description") or "Temperature Probe").strip()
        raw = item.get("CurrentReading")
        if raw is None:
            continue
        celsius = coerce_to_celsius(raw)  # heuristic: tenths-K vs C
        if celsius is None:
            continue
        sensors.append({
            "name": name,
            "celsius": celsius,
            "kind": classify_sensor_kind(name),
            "source": "win32_temperature_probe",
            "identifier": name,
        })
    return sensors


def parse_perf_thermal_zone_payload(payload: Any) -> List[Dict[str, Any]]:
    """Windows \\Thermal Zone Information(*)\\Temperature — CookedValue in Kelvin."""
    rows = _as_rows(payload)
    sensors: List[Dict[str, Any]] = []
    for item in rows:
        name = str(item.get("InstanceName") or item.get("Path") or "Thermal Zone").strip()
        raw = item.get("CookedValue")
        if raw is None:
            raw = item.get("Value")
        celsius = coerce_to_celsius(raw, "kelvin") if raw is not None else None
        if celsius is None:
            celsius = coerce_to_celsius(raw)
        if celsius is None:
            continue
        sensors.append({
            "name": name,
            "celsius": celsius,
            "kind": classify_sensor_kind(name),
            "source": "perf_thermal_zone",
            "identifier": name,
        })
    return sensors


def parse_nvidia_smi_csv(text: str) -> List[Dict[str, Any]]:
    """Parse `nvidia-smi --query-gpu=name,temperature.gpu --format=csv,noheader,nounits`."""
    sensors: List[Dict[str, Any]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("nvidia-smi"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0] or "NVIDIA GPU"
        celsius = sanitize_celsius(parts[-1])
        if celsius is None:
            continue
        sensors.append({
            "name": name,
            "celsius": celsius,
            "kind": "gpu",
            "source": "nvidia_smi",
            "identifier": name,
        })
    return sensors


def parse_psutil_temperatures(raw: Any) -> List[Dict[str, Any]]:
    """psutil.sensors_temperatures() → {chip: [shwtemp|dict|tuple, ...]}."""
    if not isinstance(raw, dict) or not raw:
        return []
    sensors: List[Dict[str, Any]] = []
    for chip, entries in raw.items():
        chip_name = str(chip or "temp")
        if not entries:
            continue
        for entry in entries:
            label = ""
            current = None
            if isinstance(entry, dict):
                label = str(entry.get("label") or "")
                current = entry.get("current")
            elif hasattr(entry, "current"):
                label = str(getattr(entry, "label", "") or "")
                current = getattr(entry, "current", None)
            elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
                label = str(entry[0] or "")
                current = entry[1]
            celsius = sanitize_celsius(current)
            if celsius is None:
                continue
            name = label.strip() or chip_name
            ident = f"{chip_name}/{label}".strip("/")
            sensors.append({
                "name": name,
                "celsius": celsius,
                "kind": classify_sensor_kind(name, ident),
                "source": "psutil",
                "identifier": ident,
            })
    return sensors


def build_thermal_snapshot(
    sensors: Sequence[Dict[str, Any]],
    *,
    warn_celsius: float = DEFAULT_WARN_CELSIUS,
    source: str = "none",
    tried: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Pure snapshot builder — no hardware I/O. Empty sensors ⇒ no fake temps."""
    clean = [s for s in sensors if isinstance(s, dict) and sanitize_celsius(s.get("celsius")) is not None]
    package = _max_of(clean, "package")
    cpu_core = _max_of(clean, "cpu")
    gpu = _max_of(clean, "gpu")
    other = _max_of(clean, "other")
    cpu = package if package is not None else cpu_core
    hottest, hottest_label = _hottest(clean)
    available = bool(clean) and hottest is not None
    status = classify_status(hottest, warn_celsius, available=available)
    primary_source = source
    if available and clean:
        # Prefer the source of the primary (package/cpu/gpu) reading.
        for kind in ("package", "cpu", "gpu"):
            match = next((s for s in clean if s.get("kind") == kind), None)
            if match:
                primary_source = str(match.get("source") or source)
                break
        else:
            primary_source = str(clean[0].get("source") or source)
    return {
        "available": available,
        "pending": False,
        "sensors": [dict(s) for s in clean],
        "package_celsius": package,
        "cpu_celsius": cpu,
        "cpu_core_celsius": cpu_core,
        "gpu_celsius": gpu,
        "other_celsius": other,
        "hottest_celsius": hottest,
        "hottest_label": hottest_label,
        "source": primary_source if available else "none",
        "source_label": SOURCE_LABELS_VI.get(
            primary_source if available else "none",
            primary_source,
        ),
        "status": status,
        "status_label": STATUS_LABELS_VI.get(status, status),
        "warn_celsius": float(warn_celsius),
        "hot": available and hottest is not None and hottest >= float(warn_celsius),
        "empty_message": "" if available else EMPTY_STATE_VI,
        "hint": "" if available else EMPTY_HINT_VI,
        "tried": list(tried or []),
        "lhm_url": LHM_PROJECT_URL,
    }


def pending_snapshot(warn_celsius: float = DEFAULT_WARN_CELSIUS) -> Dict[str, Any]:
    snap = build_thermal_snapshot([], warn_celsius=warn_celsius, source="pending")
    snap["pending"] = True
    snap["status"] = "pending"
    snap["status_label"] = STATUS_LABELS_VI["pending"]
    snap["empty_message"] = "Đang kiểm tra cảm biến nhiệt trên máy này…"
    snap["hint"] = ""
    snap["source"] = "pending"
    snap["source_label"] = SOURCE_LABELS_VI["pending"]
    return snap


def classify_status(
    hottest_celsius: Optional[float],
    warn_celsius: float = DEFAULT_WARN_CELSIUS,
    *,
    available: bool = True,
) -> str:
    if not available or hottest_celsius is None:
        return "unavailable"
    warn = float(warn_celsius)
    if hottest_celsius >= warn:
        return "hot"
    if hottest_celsius >= max(60.0, warn - 10.0):
        return "warm"
    return "ok"


def is_hot_snapshot(
    snapshot: Optional[Dict[str, Any]],
    warn_celsius: float = DEFAULT_WARN_CELSIUS,
) -> bool:
    snap = snapshot if isinstance(snapshot, dict) else {}
    if not snap.get("available"):
        return False
    hottest = snap.get("hottest_celsius")
    if hottest is None:
        return False
    try:
        return float(hottest) >= float(warn_celsius)
    except (TypeError, ValueError):
        return False


def format_celsius(value: Optional[float]) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.0f}°C"
    except (TypeError, ValueError):
        return "—"


def build_thermal_toast_payload(
    snapshot: Optional[Dict[str, Any]],
    *,
    warn_celsius: float = DEFAULT_WARN_CELSIUS,
) -> Optional[Dict[str, Any]]:
    if not is_hot_snapshot(snapshot, warn_celsius):
        return None
    snap = snapshot if isinstance(snapshot, dict) else {}
    hottest = snap.get("hottest_celsius")
    label = str(snap.get("hottest_label") or "CPU/GPU")
    src = str(snap.get("source_label") or "")
    bits = [
        f"{label} đang {format_celsius(hottest)} (ngưỡng {int(warn_celsius)}°C).",
        "Đặt máy trên bề mặt cứng, kiểm tra quạt / khe gió, giảm tải nặng.",
    ]
    cpu = snap.get("cpu_celsius")
    gpu = snap.get("gpu_celsius")
    extra = []
    if cpu is not None:
        extra.append(f"CPU {format_celsius(cpu)}")
    if gpu is not None:
        extra.append(f"GPU {format_celsius(gpu)}")
    if extra:
        bits.append(" · ".join(extra) + ".")
    if src:
        bits.append(f"Nguồn: {src}.")
    return {
        "type": THERMAL_TOAST_KIND,
        "title": "Laptop đang nóng",
        "message": " ".join(bits),
        "hottest_celsius": hottest,
        "warn_celsius": float(warn_celsius),
        "status": "hot",
        "snapshot": snap,
    }


class ThermalToastGate:
    """Throttle hot-temp toasts so a 15s scheduler tick cannot spam."""

    def __init__(self) -> None:
        self.last_toast_ts = 0.0

    def reset(self) -> None:
        self.last_toast_ts = 0.0

    def allow(self, now_ts: float, *, cooldown_sec: float = DEFAULT_TOAST_COOLDOWN_SEC) -> bool:
        now_ts = float(now_ts)
        last = float(self.last_toast_ts or 0.0)
        if last <= 0 or (now_ts - last) >= float(cooldown_sec):
            self.last_toast_ts = now_ts
            return True
        return False

    def allow_from_config(
        self,
        now_ts: float,
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        cfg = config if isinstance(config, dict) else {}
        return self.allow(
            now_ts,
            cooldown_sec=float(
                cfg.get(
                    "thermal_warn_toast_cooldown_seconds",
                    DEFAULT_TOAST_COOLDOWN_SEC,
                )
            ),
        )


def peek_cached_snapshot() -> Optional[Dict[str, Any]]:
    with _cache_lock:
        if _cached_snapshot is None:
            return None
        return dict(_cached_snapshot)


def _fresh_cached_snapshot(force_refresh: bool = False) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        if _cached_snapshot is None or force_refresh:
            return None
        ttl = CACHE_TTL_SEC if _cached_snapshot.get("available") else EMPTY_CACHE_TTL_SEC
        if time.time() - _cached_at < ttl:
            return dict(_cached_snapshot)
        return None


def collect_thermal_snapshot(
    force_refresh: bool = False,
    *,
    warn_celsius: float = DEFAULT_WARN_CELSIUS,
    probes: Optional[Sequence[Tuple[str, Callable[[], List[Dict[str, Any]]]]]] = None,
) -> Dict[str, Any]:
    """
    Probe practical sources (or injected `probes` in tests). Cached.
    Never fills temps when every source is empty.
    """
    global _cached_snapshot, _cached_at
    fresh = _fresh_cached_snapshot(force_refresh)
    if fresh is not None:
        snap = dict(fresh)
        snap["warn_celsius"] = float(warn_celsius)
        snap["hot"] = is_hot_snapshot(snap, warn_celsius)
        snap["status"] = classify_status(
            snap.get("hottest_celsius"), warn_celsius, available=bool(snap.get("available"))
        )
        snap["status_label"] = STATUS_LABELS_VI.get(snap["status"], snap["status"])
        return snap

    tried: List[str] = []
    sensors: List[Dict[str, Any]] = []
    chosen_source = "none"
    probe_list = list(probes) if probes is not None else _default_probes()

    for source_id, fn in probe_list:
        if probes is None and _is_skipped(source_id) and not force_refresh:
            continue
        tried.append(source_id)
        try:
            found = list(fn() or [])
        except Exception:
            found = []
        found = [s for s in found if isinstance(s, dict) and sanitize_celsius(s.get("celsius")) is not None]
        if not found:
            if probes is None:
                _mark_missing(source_id)
            continue
        if probes is None:
            _clear_missing(source_id)
        if source_id in ("libre_hardware_monitor", "open_hardware_monitor"):
            sensors = found
            chosen_source = source_id
            break
        have_cpu = any(s.get("kind") in ("package", "cpu") for s in sensors)
        have_gpu = any(s.get("kind") == "gpu" for s in sensors)
        if not sensors:
            sensors = found
            chosen_source = source_id
            continue
        extra = []
        for item in found:
            kind = item.get("kind")
            if kind == "gpu" and not have_gpu:
                extra.append(item)
            elif kind in ("package", "cpu") and not have_cpu:
                extra.append(item)
                if chosen_source == "nvidia_smi":
                    chosen_source = source_id
        sensors.extend(extra)

    snap = build_thermal_snapshot(
        sensors,
        warn_celsius=warn_celsius,
        source=chosen_source,
        tried=tried,
    )
    with _cache_lock:
        _cached_snapshot = dict(snap)
        _cached_at = time.time()
    return snap


def ensure_snapshot_async(
    on_done: Optional[Callable[[Dict[str, Any]], None]] = None,
    *,
    force_refresh: bool = False,
    warn_celsius: float = DEFAULT_WARN_CELSIUS,
) -> Optional[Dict[str, Any]]:
    """
    Return a fresh cache immediately if present.
    Otherwise start a daemon collect and invoke on_done(snapshot) when finished.
    """
    global _collecting
    cached = peek_cached_snapshot()
    fresh = _fresh_cached_snapshot(force_refresh)
    if fresh is not None:
        if on_done:
            on_done(fresh)
        return fresh

    def _worker() -> None:
        global _collecting
        try:
            snap = collect_thermal_snapshot(
                force_refresh=force_refresh, warn_celsius=warn_celsius
            )
            if on_done:
                on_done(snap)
        finally:
            _collecting = False

    with _cache_lock:
        if _collecting and not force_refresh:
            return cached
        _collecting = True
    threading.Thread(target=_worker, daemon=True, name="ThermalProbe").start()
    return cached


def reset_thermal_cache() -> None:
    global _cached_snapshot, _cached_at, _collecting
    with _cache_lock:
        _cached_snapshot = None
        _cached_at = 0.0
        _collecting = False
        _skip_until.clear()


# ---------------------------------------------------------------------------
# Internal helpers / live Windows probes
# ---------------------------------------------------------------------------

def _as_rows(payload: Any) -> List[Dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


def _max_of(sensors: Sequence[Dict[str, Any]], kind: str) -> Optional[float]:
    vals = [float(s["celsius"]) for s in sensors if s.get("kind") == kind]
    return round(max(vals), 1) if vals else None


def _hottest(sensors: Sequence[Dict[str, Any]]) -> Tuple[Optional[float], str]:
    if not sensors:
        return None, ""
    best = max(sensors, key=lambda s: float(s.get("celsius") or 0.0))
    return float(best["celsius"]), str(best.get("name") or "Cảm biến")


def _is_skipped(source_id: str) -> bool:
    until = _skip_until.get(source_id, 0.0)
    return bool(until and time.time() < until)


def _mark_missing(source_id: str, seconds: float = SOURCE_MISS_SKIP_SEC) -> None:
    _skip_until[source_id] = time.time() + float(seconds)


def _clear_missing(source_id: str) -> None:
    _skip_until.pop(source_id, None)


def _creation_flags() -> int:
    if sys.platform == "win32":
        return int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)
    return 0


def _run_cmd(args: Sequence[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=_creation_flags(),
            env=os.environ.copy(),
        )
    except Exception:
        return ""
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and not out:
        return ""
    return out


def _ps_json(command: str, timeout: float = 5.0) -> Any:
    if sys.platform != "win32":
        return None
    wrapped = (
        "$ErrorActionPreference='Stop'; "
        + command
        + " | ConvertTo-Json -Compress"
    )
    raw = _run_cmd(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", wrapped],
        timeout=timeout,
    )
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _probe_lhm() -> List[Dict[str, Any]]:
    data = _ps_json(
        "Get-CimInstance -Namespace root/LibreHardwareMonitor -ClassName Sensor "
        "| Where-Object { $_.SensorType -eq 'Temperature' } "
        "| Select-Object Name, Value, Identifier, SensorType"
    )
    return parse_ohm_like_sensors(data, "libre_hardware_monitor")


def _probe_ohm() -> List[Dict[str, Any]]:
    data = _ps_json(
        "Get-CimInstance -Namespace root/OpenHardwareMonitor -ClassName Sensor "
        "| Where-Object { $_.SensorType -eq 'Temperature' } "
        "| Select-Object Name, Value, Identifier, SensorType"
    )
    return parse_ohm_like_sensors(data, "open_hardware_monitor")


def _probe_nvidia_smi() -> List[Dict[str, Any]]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    raw = _run_cmd(
        [exe, "--query-gpu=name,temperature.gpu", "--format=csv,noheader,nounits"],
        timeout=4.0,
    )
    return parse_nvidia_smi_csv(raw)


def _probe_acpi() -> List[Dict[str, Any]]:
    data = _ps_json(
        "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature "
        "| Select-Object InstanceName, CurrentTemperature"
    )
    return parse_acpi_thermal_zone_payload(data)


def _probe_win32_probe() -> List[Dict[str, Any]]:
    data = _ps_json(
        "Get-CimInstance Win32_TemperatureProbe "
        "| Select-Object Name, Description, CurrentReading"
    )
    return parse_win32_temperature_probe_payload(data)


def _probe_perf_zone() -> List[Dict[str, Any]]:
    data = _ps_json(
        "(Get-Counter -Counter '\\Thermal Zone Information(*)\\Temperature').CounterSamples "
        "| Select-Object InstanceName, CookedValue"
    )
    return parse_perf_thermal_zone_payload(data)


def _probe_psutil() -> List[Dict[str, Any]]:
    try:
        import psutil
        fn = getattr(psutil, "sensors_temperatures", None)
        if not callable(fn):
            return []
        return parse_psutil_temperatures(fn())
    except Exception:
        return []


def _default_probes() -> List[Tuple[str, Callable[[], List[Dict[str, Any]]]]]:
    probes: List[Tuple[str, Callable[[], List[Dict[str, Any]]]]] = [
        ("libre_hardware_monitor", _probe_lhm),
        ("open_hardware_monitor", _probe_ohm),
        ("nvidia_smi", _probe_nvidia_smi),
        ("acpi_thermal_zone", _probe_acpi),
        ("win32_temperature_probe", _probe_win32_probe),
        ("perf_thermal_zone", _probe_perf_zone),
        ("psutil", _probe_psutil),
    ]
    if sys.platform != "win32":
        # Off Windows, skip PowerShell/WMI probes entirely.
        return [("nvidia_smi", _probe_nvidia_smi), ("psutil", _probe_psutil)]
    return probes
