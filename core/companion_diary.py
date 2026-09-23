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
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config_manager import companion_dir

ALLOWED_KINDS = frozenset({
    "session_day",
    "high_ram",
    "ram_optimized",
    "wifi_weak",
    "wifi_repaired",
    "ping_high",
    "ping_repaired",
    "focus_mode",
    "clean_freed",
    "clean_light",
    "thermal_warn",
    "security_note",
    "user_feedback",
    "skill_saved",
    "reflection",
    "update_ok",
    "update_fail",
    "suggestion_accepted",
    "suggestion_rejected",
    "chat_note",
    "stage_up",
    "focus_end",
})

ALLOWED_OUTCOMES = frozenset({
    "ok",
    "fail",
    "warn",
    "neutral",
    "accepted",
    "rejected",
})

# Default outcome when the caller does not pass one.
KIND_OUTCOME = {
    "session_day": "neutral",
    "high_ram": "warn",
    "ram_optimized": "ok",
    "wifi_weak": "warn",
    "wifi_repaired": "ok",
    "ping_high": "warn",
    "ping_repaired": "ok",
    "focus_mode": "ok",
    "clean_freed": "ok",
    "clean_light": "ok",
    "thermal_warn": "warn",
    "security_note": "warn",
    "user_feedback": "neutral",
    "skill_saved": "ok",
    "reflection": "ok",
    "update_ok": "ok",
    "update_fail": "fail",
    "suggestion_accepted": "accepted",
    "suggestion_rejected": "rejected",
    "chat_note": "neutral",
    "stage_up": "ok",
    "focus_end": "neutral",
}

KIND_TAGS = {
    "session_day": ["session"],
    "high_ram": ["ram"],
    "ram_optimized": ["ram"],
    "wifi_weak": ["wifi"],
    "wifi_repaired": ["wifi"],
    "ping_high": ["wifi", "ping"],
    "ping_repaired": ["wifi", "ping"],
    "focus_mode": ["focus"],
    "clean_freed": ["disk", "clean"],
    "clean_light": ["disk", "clean"],
    "thermal_warn": ["thermal"],
    "security_note": ["security"],
    "user_feedback": ["feedback"],
    "skill_saved": ["skill"],
    "reflection": ["reflection"],
    "update_ok": ["update"],
    "update_fail": ["update"],
    "suggestion_accepted": ["suggestion"],
    "suggestion_rejected": ["suggestion"],
    "chat_note": ["chat"],
    "stage_up": ["stage"],
    "focus_end": ["focus", "end"],
}

# Same kind+outcome+tags inside this window updates the open episode instead of a new line.
COALESCE_SEC = {
    "high_ram": 3 * 3600,
    "wifi_weak": 3 * 3600,
    "ping_high": 3 * 3600,
    "thermal_warn": 3 * 3600,
    "clean_freed": 20 * 60,
    "clean_light": 20 * 60,
    "ram_optimized": 20 * 60,
    "wifi_repaired": 30 * 60,
    "ping_repaired": 30 * 60,
    "focus_mode": 2 * 3600,
    "update_ok": 6 * 3600,
    "update_fail": 6 * 3600,
    "suggestion_accepted": 15 * 60,
    "suggestion_rejected": 15 * 60,
    "user_feedback": 90,
    "chat_note": 30 * 60,
}

TIME_TAGS = frozenset({"morning", "afternoon", "evening", "night"})
MAX_TAGS = 8

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


def time_band(now: Optional[datetime] = None) -> str:
    hour = (now or datetime.now()).hour
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _clean_tag(value: Any) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_-]+", "", raw)
    return raw[:24]


def clean_tags(tags: Optional[Iterable[str]], *, kind: str = "", now: Optional[datetime] = None) -> List[str]:
    merged: List[str] = []
    for item in list(KIND_TAGS.get(kind, [])) + list(tags or []):
        tag = _clean_tag(item)
        if tag and tag not in merged:
            merged.append(tag)
    band = time_band(now)
    if band not in merged:
        merged.append(band)
    return merged[:MAX_TAGS]


def resolve_outcome(kind: str, outcome: str = "") -> str:
    raw = str(outcome or "").strip().lower()
    if raw in ALLOWED_OUTCOMES:
        return raw
    return KIND_OUTCOME.get(kind, "neutral")


def coalesce_window_sec(kind: str) -> int:
    try:
        return max(0, int(COALESCE_SEC.get(str(kind or "").lower(), 0)))
    except (TypeError, ValueError):
        return 0


def event_weight(event: Optional[Dict[str, Any]]) -> int:
    item = event if isinstance(event, dict) else {}
    metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
    try:
        weight = int(metrics.get("count") or 1)
    except (TypeError, ValueError):
        weight = 1
    return max(1, weight)


def redact_sensitive(text: Any) -> str:
    """Strip secrets and paths. Does not clip length."""
    raw = str(text or "")
    raw = raw.replace("\x00", "")
    raw = _SECRET_RE.sub("[redacted]", raw)
    raw = _WIN_PATH_RE.sub("[path]", raw)
    raw = _POSIX_PATH_RE.sub("[path]", raw)
    raw = _UNC_PATH_RE.sub("[path]", raw)
    return raw


def sanitize_summary(text: Any) -> str:
    raw = redact_sensitive(text).strip()
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
    outcome: str = "",
    tags: Optional[Iterable[str]] = None,
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
    stamp = now or datetime.now()
    return {
        "ts": _now_iso(stamp),
        "kind": kind_key,
        "summary": text,
        "metrics": sanitize_metrics(metrics),
        "source": src,
        "outcome": resolve_outcome(kind_key, outcome),
        "tags": clean_tags(tags, kind=kind_key, now=stamp),
    }


def _coalesce_key(event: Dict[str, Any]) -> Tuple[str, str, Tuple[str, ...]]:
    tags = [
        tag for tag in (event.get("tags") or [])
        if tag not in TIME_TAGS
    ]
    return (
        str(event.get("kind") or ""),
        str(event.get("outcome") or ""),
        tuple(sorted(tags)),
    )


def _normalize_row(item: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(item.get("kind") or "").lower()
    ts = str(item.get("ts") or "")
    stamp = None
    parsed = _parse_ts(ts)
    if parsed is not None:
        try:
            stamp = datetime.fromtimestamp(parsed)
        except Exception:
            stamp = None
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    if not tags:
        tags = clean_tags([], kind=kind, now=stamp)
    else:
        tags = clean_tags(tags, kind=kind, now=stamp)
    return {
        "ts": ts,
        "kind": kind,
        "summary": sanitize_summary(item.get("summary") or ""),
        "metrics": sanitize_metrics(item.get("metrics") if isinstance(item.get("metrics"), dict) else {}),
        "source": sanitize_summary(item.get("source") or "app")[:32],
        "outcome": resolve_outcome(kind, str(item.get("outcome") or "")),
        "tags": tags,
    }


def _try_coalesce(
    event: Dict[str, Any],
    base_dir: Optional[str] = None,
    window_sec: int = 0,
) -> Optional[Dict[str, Any]]:
    if window_sec <= 0:
        return None
    rows = read_events(base_dir=base_dir, limit=0)
    if not rows:
        return None
    new_ts = _parse_ts(event.get("ts") or "")
    if new_ts is None:
        return None
    key = _coalesce_key(event)
    idx = None
    for i in range(len(rows) - 1, -1, -1):
        if _coalesce_key(rows[i]) != key:
            continue
        old_ts = _parse_ts(rows[i].get("ts") or "")
        if old_ts is None or abs(new_ts - old_ts) > window_sec:
            break
        idx = i
        break
    if idx is None:
        return None
    row = dict(rows[idx])
    prev = event_weight(row)
    incoming = (event.get("metrics") or {}).get("count")
    try:
        extra = int(incoming) if incoming else 1
    except (TypeError, ValueError):
        extra = 1
    metrics = dict(row.get("metrics") or {})
    metrics.update(event.get("metrics") or {})
    metrics["count"] = prev + max(1, extra)
    row["metrics"] = sanitize_metrics(metrics)
    row["summary"] = event.get("summary") or row.get("summary")
    parsed = _parse_ts(row.get("ts") or "")
    stamp = datetime.fromtimestamp(parsed) if parsed else None
    row["tags"] = clean_tags(
        list(row.get("tags") or []) + list(event.get("tags") or []),
        kind=str(row.get("kind") or ""),
        now=stamp,
    )
    rows[idx] = row
    write_events(rows, base_dir=base_dir)
    return row


def append_event(
    kind: str,
    summary: str,
    metrics: Optional[Dict[str, Any]] = None,
    source: str = "app",
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    outcome: str = "",
    tags: Optional[Iterable[str]] = None,
    coalesce: bool = False,
) -> Optional[Dict[str, Any]]:
    event = make_event(
        kind,
        summary,
        metrics=metrics,
        source=source,
        now=now,
        outcome=outcome,
        tags=tags,
    )
    if event is None:
        return None
    if coalesce:
        merged = _try_coalesce(event, base_dir=base_dir, window_sec=coalesce_window_sec(event["kind"]))
        if merged is not None:
            return merged
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
                row = _normalize_row(item)
                if not row.get("summary"):
                    continue
                out.append(row)
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
        counts[kind] = counts.get(kind, 0) + event_weight(item)
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
        weight = event_weight(item)
        suffix = f" ×{weight}" if weight > 1 else ""
        lines.append(f"- {ts}: {summary}{suffix}")
    return "\n".join(lines)


def event_identity(event: Optional[Dict[str, Any]]) -> Tuple[str, str, str]:
    item = event if isinstance(event, dict) else {}
    return (
        str(item.get("ts") or ""),
        str(item.get("kind") or "").lower(),
        str(item.get("summary") or ""),
    )


def format_event_row(event: Optional[Dict[str, Any]]) -> str:
    item = event if isinstance(event, dict) else {}
    ts = str(item.get("ts") or "").replace("T", " ")[:16]
    summary = str(item.get("summary") or "").strip()
    weight = event_weight(item)
    suffix = f" ×{weight}" if weight > 1 else ""
    if ts and summary:
        return f"{ts}  {summary}{suffix}"
    return (summary + suffix) if summary else ts or ""


def write_events(events: List[Dict[str, Any]], base_dir: Optional[str] = None) -> None:
    path = diary_path(base_dir)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        for item in events:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").lower()
            if kind not in ALLOWED_KINDS:
                continue
            normalized = _normalize_row(item)
            payload = {
                "ts": normalized["ts"],
                "kind": kind,
                "summary": normalized["summary"],
                "metrics": normalized["metrics"],
                "source": normalized["source"],
                "outcome": normalized["outcome"],
                "tags": normalized["tags"],
            }
            if not payload["summary"]:
                continue
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def delete_event(event: Dict[str, Any], base_dir: Optional[str] = None) -> bool:
    """Remove the first diary row matching ts+kind+summary. Privacy-friendly."""
    if not isinstance(event, dict):
        return False
    rows = read_events(base_dir=base_dir, limit=0)
    target = event_identity(event)
    kept: List[Dict[str, Any]] = []
    removed = False
    for item in rows:
        if not removed and event_identity(item) == target:
            removed = True
            continue
        kept.append(item)
    if not removed:
        return False
    write_events(kept, base_dir=base_dir)
    return True


def clear_events(base_dir: Optional[str] = None) -> int:
    rows = read_events(base_dir=base_dir, limit=0)
    write_events([], base_dir=base_dir)
    return len(rows)
