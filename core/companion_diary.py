"""
Episodic machine diary — local, privacy-safe events for the companion AI.

Stores dated summaries of app activity and light snapshots (high RAM, weak Wi-Fi,
focus mode, clean freed X MB). Never writes secrets, full disk-scan listings, or
raw user file paths.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from config_manager import companion_dir

ALLOWED_KINDS = frozenset({
    "session_day",
    "high_ram",
    "ram_optimized",
    "wifi_weak",
    "wifi_repaired",
    "ping_high",
    "focus_mode",
    "clean_freed",
    "clean_light",
    "thermal_warn",
    "security_note",
    "user_feedback",
    "skill_saved",
    "reflection",
})

ALLOWED_METRIC_KEYS = frozenset({
    "ram_percent",
    "cpu_percent",
    "disk_free_gb",
    "freed_mb",
    "junk_freed_mb",
    "ram_freed_mb",
    "ping_ms",
    "thermal_c",
    "stage",
    "helpful",
    "count",
})

MAX_SUMMARY_LEN = 160
MAX_DIARY_EVENTS = 500
DIARY_FILENAME = "diary.jsonl"

_SECRET_RE = re.compile(
    r"(AIza[0-9A-Za-z_-]{10,}|sk-[A-Za-z0-9]{10,}|api[_-]?key\s*[:=]\s*\S+|password\s*[:=]\s*\S+)",
    re.IGNORECASE,
)
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s,;]{2,}")
_POSIX_PATH_RE = re.compile(r"(?:/home|/Users|/var|/tmp)/[^\s,;]{2,}")
_UNC_PATH_RE = re.compile(r"\\\\[^\s,;]{2,}")


def diary_path(base_dir: Optional[str] = None) -> str:
    root = base_dir or companion_dir()
    return os.path.join(root, DIARY_FILENAME)


def _now_iso(now: Optional[datetime] = None) -> str:
    stamp = now or datetime.now()
    return stamp.replace(microsecond=0).isoformat(timespec="seconds")


def sanitize_summary(text: Any) -> str:
    raw = str(text or "").strip()
    raw = _SECRET_RE.sub("[redacted]", raw)
    raw = _WIN_PATH_RE.sub("[path]", raw)
    raw = _POSIX_PATH_RE.sub("[path]", raw)
    raw = _UNC_PATH_RE.sub("[path]", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    if len(raw) > MAX_SUMMARY_LEN:
        raw = raw[: MAX_SUMMARY_LEN - 1].rstrip() + "…"
    return raw


def sanitize_metrics(metrics: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(metrics, dict):
        return {}
    clean: Dict[str, Any] = {}
    for key, value in metrics.items():
        if key not in ALLOWED_METRIC_KEYS:
            continue
        if isinstance(value, bool):
            clean[key] = bool(value)
        elif isinstance(value, int) and not isinstance(value, bool):
            clean[key] = int(value)
        elif isinstance(value, float):
            clean[key] = round(float(value), 2)
        elif value is None:
            continue
        else:
            try:
                clean[key] = round(float(value), 2)
            except (TypeError, ValueError):
                continue
    return clean


def make_event(
    kind: str,
    summary: str,
    metrics: Optional[Dict[str, Any]] = None,
    source: str = "app",
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    kind_key = str(kind or "").strip().lower()
    if kind_key not in ALLOWED_KINDS:
        return None
    text = sanitize_summary(summary)
    if not text:
        return None
    src = sanitize_summary(source) or "app"
    if len(src) > 32:
        src = src[:32]
    return {
        "ts": _now_iso(now),
        "kind": kind_key,
        "summary": text,
        "metrics": sanitize_metrics(metrics),
        "source": src,
    }


def append_event(
    kind: str,
    summary: str,
    metrics: Optional[Dict[str, Any]] = None,
    source: str = "app",
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    event = make_event(kind, summary, metrics=metrics, source=source, now=now)
    if event is None:
        return None
    path = diary_path(base_dir)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    _trim_diary(path)
    return event


def _trim_diary(path: str, max_events: int = MAX_DIARY_EVENTS) -> None:
    try:
        if not os.path.exists(path) or os.path.getsize(path) < 50_000:
            return
        events = read_events(path=path, limit=0)
        if len(events) <= max_events:
            return
        keep = events[-max_events:]
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            for item in keep:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
    except Exception:
        return


def read_events(
    path: Optional[str] = None,
    base_dir: Optional[str] = None,
    limit: int = 0,
    kinds: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    target = path or diary_path(base_dir)
    if not target or not os.path.exists(target):
        return []
    allow = {str(k).lower() for k in kinds} if kinds else None
    out: List[Dict[str, Any]] = []
    try:
        with open(target, "r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    item = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(item, dict):
                    continue
                kind = str(item.get("kind") or "").lower()
                if kind not in ALLOWED_KINDS:
                    continue
                if allow is not None and kind not in allow:
                    continue
                out.append({
                    "ts": str(item.get("ts") or ""),
                    "kind": kind,
                    "summary": sanitize_summary(item.get("summary") or ""),
                    "metrics": sanitize_metrics(item.get("metrics") if isinstance(item.get("metrics"), dict) else {}),
                    "source": sanitize_summary(item.get("source") or "app")[:32],
                })
    except Exception:
        return []
    if limit and limit > 0:
        return out[-limit:]
    return out


def recent_events(
    days: int = 14,
    limit: int = 40,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    events = read_events(base_dir=base_dir, limit=0)
    if not events:
        return []
    stamp = now or datetime.now()
    cutoff = stamp.timestamp() - max(1, int(days)) * 86400
    kept: List[Dict[str, Any]] = []
    for item in events:
        ts = _parse_ts(item.get("ts") or "")
        if ts is None or ts >= cutoff:
            kept.append(item)
    if limit and limit > 0:
        return kept[-limit:]
    return kept


def _parse_ts(value: str) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).timestamp()
    except Exception:
        return None


def count_by_kind(
    events: Optional[List[Dict[str, Any]]] = None,
    *,
    days: int = 14,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, int]:
    rows = events if events is not None else recent_events(days=days, limit=0, base_dir=base_dir, now=now)
    counts: Dict[str, int] = {}
    for item in rows:
        kind = str(item.get("kind") or "")
        if not kind:
            continue
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def format_digest(
    events: Optional[List[Dict[str, Any]]] = None,
    *,
    days: int = 14,
    limit: int = 8,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    empty_vi: str = "Nhật ký máy còn trống (cài mới). Không bịa kỷ niệm.",
) -> str:
    rows = events if events is not None else recent_events(days=days, limit=limit, base_dir=base_dir, now=now)
    if not rows:
        return empty_vi
    lines = []
    for item in rows[-limit:]:
        ts = str(item.get("ts") or "")[:10]
        summary = item.get("summary") or ""
        lines.append(f"- {ts}: {summary}")
    return "\n".join(lines)
