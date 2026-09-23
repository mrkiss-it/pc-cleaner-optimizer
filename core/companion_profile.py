"""
Compact local profile of this user and machine.

Built from diary episodes, accept/reject, and chat feedback. No model training:
a small JSON file the companion can show, clear, and inject into Copilot context.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from config_manager import companion_dir
from core.companion_diary import event_weight, read_events, recent_events, sanitize_summary, time_band
from core.companion_skills import fold_vi

PROFILE_FILENAME = "profile.json"
MAX_HABITS = 6
MAX_GOAL_LEN = 80
MAX_DISMISSED = 24
MAX_NOTES = 20
MAX_NOTE_LEN = 120
PROFILE_VERSION = 1
MUTE_DAYS = 7
SOFT_MUTE_DAYS = 2
# Đừng nhắc hides one tip family for this many days from the tap.
# Not "until tomorrow morning": a snooze at 22:00 still lasts three full days
# (`until` is compared with `until > now`). Critical thermal / Wi-Fi emergency
# alerts are never stored here — see tip_snooze_allowed.
SNOOZE_DAYS = 3
CRITICAL_ALERT_LEVELS = frozenset({"warning", "danger", "critical", "emergency"})
QUIET_HOURS_START = "23:00"
QUIET_HOURS_END = "07:00"
# Trust is computed, not trained. Fewer than this many accept/reject rows stays "steady".
TRUST_MIN_SAMPLE = 3
WINDOW_PHRASE = "Thường vào khung giờ này trên máy này"
GROWTH_EMPTY_VI = "Chưa có mốc lớn — mình mới gặp máy này. Dùng thêm rồi xem lại."
GROWTH_LIMIT = 12

TOPIC_META: Dict[str, Dict[str, Any]] = {
    "wifi": {
        "kinds": {"wifi_weak", "ping_high", "wifi_repaired", "ping_repaired"},
        "warn": {"wifi_weak", "ping_high"},
        "ok": {"wifi_repaired", "ping_repaired"},
        "issue": "wifi_weak",
        "name": "Wi-Fi",
        "concern": "Quan tâm Wi-Fi",
        "next": "Việc tiếp: tắt tiết kiệm điện Wi-Fi trước khi cần mạng — không tự đổi DNS.",
    },
    "thermal": {
        "kinds": {"thermal_warn"},
        "warn": {"thermal_warn"},
        "ok": set(),
        "issue": "thermal",
        "name": "nhiệt",
        "concern": "Nhạy với nhiệt",
        "next": "Việc tiếp: xem giám sát nhiệt; có thể bật tiết kiệm pin — không bịa °C.",
    },
    "ram": {
        "kinds": {"high_ram", "ram_optimized"},
        "warn": {"high_ram"},
        "ok": {"ram_optimized"},
        "issue": "high_ram",
        "name": "RAM",
        "concern": "Quan tâm RAM",
        "next": "Việc tiếp: thu hồi RAM standby, không tắt app đang dùng.",
    },
    "disk": {
        "kinds": {"clean_freed", "clean_light"},
        "warn": set(),
        "ok": {"clean_freed", "clean_light"},
        "issue": "disk_low",
        "name": "dọn máy",
        "concern": "Hay dọn máy",
        "next": "Việc tiếp: Dọn nhẹ temp — không WinSxS, không thùng rác.",
    },
    "focus": {
        "kinds": {"focus_mode"},
        "warn": set(),
        "ok": {"focus_mode"},
        "issue": "focus",
        "name": "Trước thi / họp",
        "concern": "Hay tập trung",
        "next": "Việc tiếp: có thể bật Trước thi / họp — không tự bật.",
    },
    "update": {
        "kinds": {"update_ok", "update_fail"},
        "warn": {"update_fail"},
        "ok": {"update_ok"},
        "issue": "",
        "name": "cập nhật",
        "concern": "Quan tâm cập nhật",
        "next": "Việc tiếp: kiểm tra mạng trước khi tải cập nhật lại.",
    },
}

# Longer phrases first. Matched with word boundaries so "don" does not hit "dong".
_TOPIC_TERMS: tuple = (
    ("wifi", ("wi-fi", "wifi", "ping", "mang")),
    ("thermal", ("may mat", "may nong", "nhiet", "nong", "quat")),
    ("ram", ("bo nho", "ram", "do may", "lag")),
    ("disk", ("o c", "dung luong", "don rac", "don nhe", "don", "rac", "disk", "temp")),
    ("focus", ("truoc thi", "tap trung", "focus", "thi", "hop", "hoc")),
    ("update", ("cap nhat", "ban moi", "update")),
)

_BAND_VI = {
    "morning": "buổi sáng",
    "afternoon": "buổi chiều",
    "evening": "buổi tối",
    "night": "đêm",
}
_WEEKDAY_VI = (
    "thứ Hai",
    "thứ Ba",
    "thứ Tư",
    "thứ Năm",
    "thứ Sáu",
    "thứ Bảy",
    "Chủ nhật",
)

_ACTION_TOPIC = {
    "optimize_ram": "ram",
    "optimize_ram_only": "ram",
    "clean_light": "disk",
    "clean_junk": "disk",
    "repair_network_now": "wifi",
    "optimize_network": "wifi",
    "open_wifi_stability": "wifi",
    "disable_wifi_power_save": "wifi",
    "open_thermal_card": "thermal",
    "view_hardware": "thermal",
    "open_hardware_dialog": "thermal",
    "battery_saver": "thermal",
    "enable_exam_focus": "focus",
    "toggle_exam_focus": "focus",
}

_EMPTY_PROFILE_VI = (
    "Chưa có hồ sơ thói quen — dùng máy vài ngày, AI sẽ ghi điều máy này hay gặp. "
    "Mục tiêu là tuỳ chọn."
)


def profile_path(base_dir: Optional[str] = None) -> str:
    return os.path.join(base_dir or companion_dir(), PROFILE_FILENAME)


def _default_quiet_hours() -> Dict[str, Any]:
    return {
        "enabled": False,
        "start": QUIET_HOURS_START,
        "end": QUIET_HOURS_END,
        "allow_actions": False,
    }


def _clean_hhmm(value: Any, fallback: str) -> str:
    raw = str(value or "").strip()
    parts = raw.split(":")
    if len(parts) != 2:
        return fallback
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        return fallback
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return fallback
    return f"{hour:02d}:{minute:02d}"


def _hhmm_minutes(value: str) -> Optional[int]:
    cleaned = _clean_hhmm(value, "")
    if not cleaned:
        return None
    hour, minute = cleaned.split(":")
    return int(hour) * 60 + int(minute)


def _clean_quiet_hours(raw: Any) -> Dict[str, Any]:
    base = _default_quiet_hours()
    if not isinstance(raw, dict):
        return base
    base["enabled"] = bool(raw.get("enabled"))
    base["start"] = _clean_hhmm(raw.get("start"), QUIET_HOURS_START)
    base["end"] = _clean_hhmm(raw.get("end"), QUIET_HOURS_END)
    base["allow_actions"] = bool(raw.get("allow_actions"))
    return base


def default_profile() -> Dict[str, Any]:
    return {
        "version": PROFILE_VERSION,
        "updated_at": "",
        "habits": [],
        "coaching": "steady",
        "feedback": {"helpful": 0, "unhelpful": 0},
        "goal": None,
        "dismissed_insights": [],
        "insight_snooze_date": "",
        "habits_after": "",
        "last_chat": None,
        "muted_topics": {},
        "topic_coaching": {},
        "corrections": [],
        "preferences": [],
        "quiet_hours": _default_quiet_hours(),
        "snoozed_tips": {},
    }


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_profile(base_dir: Optional[str] = None) -> Dict[str, Any]:
    merged = default_profile()
    path = profile_path(base_dir)
    if not path or not os.path.exists(path):
        return merged
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return merged
    if isinstance(data, dict):
        merged.update(data)
    habits = merged.get("habits") if isinstance(merged.get("habits"), list) else []
    merged["habits"] = [item for item in habits if isinstance(item, dict)][:MAX_HABITS]
    feedback = merged.get("feedback") if isinstance(merged.get("feedback"), dict) else {}
    merged["feedback"] = {
        "helpful": max(0, int(feedback.get("helpful") or 0)),
        "unhelpful": max(0, int(feedback.get("unhelpful") or 0)),
    }
    goal = merged.get("goal")
    merged["goal"] = goal if isinstance(goal, dict) and str(goal.get("text") or "").strip() else None
    dismissed = merged.get("dismissed_insights") if isinstance(merged.get("dismissed_insights"), list) else []
    merged["dismissed_insights"] = [str(item) for item in dismissed if str(item).strip()][-MAX_DISMISSED:]
    if merged.get("coaching") not in ("steady", "ask_more"):
        merged["coaching"] = "steady"
    merged["insight_snooze_date"] = str(merged.get("insight_snooze_date") or "")[:10]
    merged["habits_after"] = str(merged.get("habits_after") or "")
    last_chat = merged.get("last_chat")
    if isinstance(last_chat, dict) and str(last_chat.get("topic") or "").strip():
        merged["last_chat"] = {
            "topic": str(last_chat.get("topic") or "")[:24],
            "at": str(last_chat.get("at") or "")[:32],
        }
    else:
        merged["last_chat"] = None
    merged["muted_topics"] = _clean_muted(merged.get("muted_topics"))
    merged["topic_coaching"] = _clean_topic_coaching(merged.get("topic_coaching"))
    corrections, preferences = _split_notes(merged.get("corrections"), merged.get("preferences"))
    merged["corrections"] = corrections
    merged["preferences"] = preferences
    merged["quiet_hours"] = _clean_quiet_hours(merged.get("quiet_hours"))
    merged["snoozed_tips"] = _clean_snoozed(merged.get("snoozed_tips"))
    return merged


def save_profile(profile: Dict[str, Any], base_dir: Optional[str] = None) -> Dict[str, Any]:
    payload = default_profile()
    if isinstance(profile, dict):
        payload.update(profile)
    payload["habits"] = [item for item in (payload.get("habits") or []) if isinstance(item, dict)][:MAX_HABITS]
    payload["dismissed_insights"] = [
        str(item) for item in (payload.get("dismissed_insights") or []) if str(item).strip()
    ][-MAX_DISMISSED:]
    payload["muted_topics"] = _clean_muted(payload.get("muted_topics"))
    payload["topic_coaching"] = _clean_topic_coaching(payload.get("topic_coaching"))
    corrections, preferences = _split_notes(payload.get("corrections"), payload.get("preferences"))
    payload["corrections"] = corrections
    payload["preferences"] = preferences
    payload["quiet_hours"] = _clean_quiet_hours(payload.get("quiet_hours"))
    payload["snoozed_tips"] = _clean_snoozed(payload.get("snoozed_tips"))
    _atomic_write_json(profile_path(base_dir), payload)
    return payload


def quiet_hours_settings(
    profile: Optional[Dict[str, Any]] = None,
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Saved quiet-hours window. Off until the user enables the suggested 23:00–07:00."""
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    return _clean_quiet_hours(data.get("quiet_hours"))


def set_quiet_hours(
    enabled: bool,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    allow_actions: Optional[bool] = None,
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist the optional quiet window on the companion profile."""
    profile = load_profile(base_dir)
    current = _clean_quiet_hours(profile.get("quiet_hours"))
    current["enabled"] = bool(enabled)
    if start is not None:
        current["start"] = _clean_hhmm(start, current["start"])
    if end is not None:
        current["end"] = _clean_hhmm(end, current["end"])
    if allow_actions is not None:
        current["allow_actions"] = bool(allow_actions)
    profile["quiet_hours"] = current
    save_profile(profile, base_dir=base_dir)
    return current


def in_quiet_hours(
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when quiet hours are on and ``now`` falls inside the window.

    A window that crosses midnight (23:00–07:00) counts the late evening and
    the early morning. The end minute is exclusive, so 07:00 is morning again.
    """
    settings = quiet_hours_settings(profile, base_dir)
    if not settings.get("enabled"):
        return False
    start = _hhmm_minutes(str(settings.get("start") or ""))
    end = _hhmm_minutes(str(settings.get("end") or ""))
    if start is None or end is None or start == end:
        return False
    stamp = now or datetime.now()
    current = stamp.hour * 60 + stamp.minute
    if start < end:
        return start <= current < end
    return current >= start or current < end


def quiet_hours_allow_actions(
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> bool:
    """Propose buttons during quiet hours only when the user opted in."""
    if not in_quiet_hours(now, base_dir=base_dir, profile=profile):
        return True
    return bool(quiet_hours_settings(profile, base_dir).get("allow_actions"))


def _parse_ts(value: str) -> Optional[float]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).timestamp()
    except Exception:
        return None


def _event_dt(event: Dict[str, Any]) -> Optional[datetime]:
    ts = _parse_ts(str(event.get("ts") or ""))
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts)
    except Exception:
        return None


def _contains_term(folded: str, term: str) -> bool:
    token = str(term or "").strip().lower()
    if not token or not folded:
        return False
    if " " in token or "-" in token:
        return token in folded
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", folded) is not None


def infer_topics(text: str) -> List[str]:
    """Topics mentioned in a question or goal, strongest first."""
    folded = fold_vi(text)
    if not folded.strip():
        return []
    scores: Dict[str, int] = {}
    for topic, terms in _TOPIC_TERMS:
        score = 0
        for term in terms:
            if _contains_term(folded, term):
                score += 2 if (" " in term or "-" in term) else 1
        if score:
            scores[topic] = score
    order = {name: index for index, (name, _terms) in enumerate(_TOPIC_TERMS)}
    ranked = sorted(scores.items(), key=lambda item: (-item[1], order.get(item[0], 99)))
    return [topic for topic, _score in ranked]


def topic_issue(topic: str) -> str:
    return str((TOPIC_META.get(topic) or {}).get("issue") or "")


def topic_for_issue(issue_class: str) -> str:
    wanted = str(issue_class or "").strip().lower()
    if not wanted:
        return ""
    for topic, meta in TOPIC_META.items():
        if str(meta.get("issue") or "") == wanted:
            return topic
    return ""


def _clean_topic_coaching(raw: Any) -> Dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for topic, mode in raw.items():
        key = str(topic or "").strip()
        if key in TOPIC_META and str(mode or "") == "ask_more":
            out[key] = "ask_more"
    return out


def _parse_mute(value: Any) -> Optional[Dict[str, str]]:
    if isinstance(value, str):
        until, reason = value, "user"
    elif isinstance(value, dict):
        until = str(value.get("until") or "")
        reason = str(value.get("reason") or "user")
    else:
        return None
    try:
        when = datetime.fromisoformat(str(until).replace("Z", ""))
    except Exception:
        return None
    if reason not in ("user", "feedback"):
        reason = "user"
    return {
        "until": when.replace(microsecond=0).isoformat(timespec="seconds"),
        "reason": reason,
    }


def _clean_muted(raw: Any) -> Dict[str, Dict[str, str]]:
    """Keep well-formed mutes, including ones a simulated clock would call expired."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for topic, value in raw.items():
        key = str(topic or "").strip()
        if key not in TOPIC_META:
            continue
        parsed = _parse_mute(value)
        if parsed:
            out[key] = parsed
    return out


def active_muted_topics(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, str]]:
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    stamp = now or datetime.now()
    active: Dict[str, Dict[str, str]] = {}
    for topic, meta in _clean_muted(data.get("muted_topics")).items():
        try:
            until = datetime.fromisoformat(meta["until"])
        except Exception:
            continue
        if until > stamp:
            active[topic] = meta
    return active


def topic_is_muted(
    topic: str,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> bool:
    key = str(topic or "").strip()
    return bool(key) and key in active_muted_topics(base_dir=base_dir, now=now, profile=profile)


def topic_asks_more(
    topic: str,
    base_dir: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> bool:
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    coaching = data.get("topic_coaching") if isinstance(data.get("topic_coaching"), dict) else {}
    return str(coaching.get(str(topic or "").strip()) or "") == "ask_more"


def mute_topic(
    topic: str,
    days: int = MUTE_DAYS,
    reason: str = "user",
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Hide a topic from insight and nudges until the cooldown ends. Copilot may still answer."""
    key = str(topic or "").strip()
    if key not in TOPIC_META:
        return None
    try:
        span = max(1, int(days))
    except (TypeError, ValueError):
        span = MUTE_DAYS
    stamp = now or datetime.now()
    until_dt = (stamp + timedelta(days=span)).replace(microsecond=0)
    reason_key = "feedback" if str(reason or "") == "feedback" else "user"
    profile = load_profile(base_dir)
    muted = _clean_muted(profile.get("muted_topics"))
    existing = muted.get(key)
    if existing and reason_key == "feedback":
        try:
            old_until = datetime.fromisoformat(existing["until"])
        except Exception:
            old_until = None
        if old_until is not None and old_until > until_dt:
            return existing["until"]
    until = until_dt.isoformat(timespec="seconds")
    muted[key] = {"until": until, "reason": reason_key}
    profile["muted_topics"] = muted
    save_profile(profile, base_dir=base_dir)
    return until


def unmute_topic(topic: str, base_dir: Optional[str] = None) -> bool:
    """Clear one mute and that topic's ask-more coaching. A hard mute is the user's call."""
    key = str(topic or "").strip()
    if not key:
        return False
    profile = load_profile(base_dir)
    muted = _clean_muted(profile.get("muted_topics"))
    coaching = _clean_topic_coaching(profile.get("topic_coaching"))
    had = key in muted or key in coaching
    muted.pop(key, None)
    coaching.pop(key, None)
    profile["muted_topics"] = muted
    profile["topic_coaching"] = coaching
    save_profile(profile, base_dir=base_dir)
    return had


def clear_feedback_mute(topic: str, base_dir: Optional[str] = None) -> bool:
    """Helpful feedback lifts a soft mute. An explicit «đừng nhắc» mute stays."""
    key = str(topic or "").strip()
    if key not in TOPIC_META:
        return False
    profile = load_profile(base_dir)
    muted = _clean_muted(profile.get("muted_topics"))
    current = muted.get(key)
    if not current or current.get("reason") != "feedback":
        return False
    muted.pop(key, None)
    profile["muted_topics"] = muted
    save_profile(profile, base_dir=base_dir)
    return True


def _parse_snooze(value: Any) -> Optional[Dict[str, str]]:
    if isinstance(value, str):
        until = value
    elif isinstance(value, dict):
        until = str(value.get("until") or "")
    else:
        return None
    try:
        when = datetime.fromisoformat(str(until).replace("Z", ""))
    except Exception:
        return None
    return {"until": when.replace(microsecond=0).isoformat(timespec="seconds")}


def _clean_snoozed(raw: Any) -> Dict[str, Dict[str, str]]:
    """Keep well-formed snoozes, including ones a simulated clock would call expired."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, str]] = {}
    for topic, value in raw.items():
        key = str(topic or "").strip()
        if key not in TOPIC_META:
            continue
        parsed = _parse_snooze(value)
        if parsed:
            out[key] = parsed
    return out


def tip_snooze_allowed(*, level: str = "info", critical: bool = False) -> bool:
    """Soft companion tips only.

    Thermal warnings and Wi-Fi/ping emergency toasts use a warning or danger
    level (or critical=True). Those are never snoozable. Habit nudges and
    insight lines stay level=info and may be snoozed.
    """
    if critical:
        return False
    return str(level or "info").strip().lower() not in CRITICAL_ALERT_LEVELS


def active_snoozed_topics(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, str]]:
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    stamp = now or datetime.now()
    active: Dict[str, Dict[str, str]] = {}
    for topic, meta in _clean_snoozed(data.get("snoozed_tips")).items():
        try:
            until = datetime.fromisoformat(meta["until"])
        except Exception:
            continue
        if until > stamp:
            active[topic] = meta
    return active


def topic_is_snoozed(
    topic: str,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> bool:
    key = str(topic or "").strip()
    return bool(key) and key in active_snoozed_topics(base_dir=base_dir, now=now, profile=profile)


def snooze_tip_family(
    topic: str,
    days: int = SNOOZE_DAYS,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    *,
    level: str = "info",
    critical: bool = False,
    write_diary: bool = True,
) -> Optional[Dict[str, str]]:
    """Hide one tip family for SNOOZE_DAYS (default 3) from this moment.

    The window is three days, not until tomorrow morning. A tap at 22:00 still
    covers the next three days. Expired rows stay on disk but are inactive.

    Critical thermal / Wi-Fi emergency alerts are refused: nothing is stored
    and no diary line is written. Soft insight tips and info nudges may.
    """
    if not tip_snooze_allowed(level=level, critical=critical):
        return None
    key = str(topic or "").strip()
    if key not in TOPIC_META:
        return None
    try:
        span = max(1, int(days))
    except (TypeError, ValueError):
        span = SNOOZE_DAYS
    stamp = now or datetime.now()
    until_dt = (stamp + timedelta(days=span)).replace(microsecond=0)
    until = until_dt.isoformat(timespec="seconds")
    profile = load_profile(base_dir)
    snoozed = _clean_snoozed(profile.get("snoozed_tips"))
    snoozed[key] = {"until": until}
    profile["snoozed_tips"] = snoozed
    save_profile(profile, base_dir=base_dir)
    if write_diary:
        name = str((TOPIC_META.get(key) or {}).get("name") or key)
        summary = f"Bạn chọn Đừng nhắc {name} trong {span} ngày."
        try:
            from core.companion import record_app_event
            record_app_event(
                "tip_snooze",
                summary,
                source="user",
                now=stamp,
                base_dir=base_dir,
                outcome="neutral",
                tags=["snooze", key],
                coalesce=False,
            )
        except Exception:
            pass
    return {"topic": key, "until": until}


def merge_snoozed_tips(local: Any, incoming: Any) -> Dict[str, Dict[str, str]]:
    """Union of snoozes. The later `until` wins for the same family."""
    merged = _clean_snoozed(local)
    for topic, meta in _clean_snoozed(incoming).items():
        current = merged.get(topic)
        if current is None or str(meta.get("until") or "") > str(current.get("until") or ""):
            merged[topic] = meta
    return merged


def clear_muted_topics(base_dir: Optional[str] = None) -> int:
    profile = load_profile(base_dir)
    muted = _clean_muted(profile.get("muted_topics"))
    count = len(muted)
    profile["muted_topics"] = {}
    profile["topic_coaching"] = {}
    save_profile(profile, base_dir=base_dir)
    return count


def set_topic_coaching(topic: str, ask_more: bool, base_dir: Optional[str] = None) -> None:
    key = str(topic or "").strip()
    if key not in TOPIC_META:
        return
    profile = load_profile(base_dir)
    coaching = _clean_topic_coaching(profile.get("topic_coaching"))
    if ask_more:
        coaching[key] = "ask_more"
    else:
        coaching.pop(key, None)
    profile["topic_coaching"] = coaching
    save_profile(profile, base_dir=base_dir)


def format_muted_policy(
    profile: Optional[Dict[str, Any]] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Tell Copilot not to volunteer muted topics. It may still answer a direct question."""
    active = active_muted_topics(base_dir=base_dir, now=now, profile=profile)
    if not active:
        return ""
    bits = []
    for topic, meta in active.items():
        name = str((TOPIC_META.get(topic) or {}).get("name") or topic)
        until = str(meta.get("until") or "")
        day = ""
        if len(until) >= 10:
            day = f"{until[8:10]}/{until[5:7]}"
        bits.append(f"{name} đến {day}" if day else name)
    return "Đừng chủ động nhắc: " + ", ".join(bits) + ". Vẫn trả lời nếu người dùng hỏi."


def format_muted_browse(
    profile: Optional[Dict[str, Any]] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    active = active_muted_topics(base_dir=base_dir, now=now, profile=profile)
    if not active:
        return "Không có chủ đề đang im."
    bits = []
    for topic, meta in active.items():
        name = str((TOPIC_META.get(topic) or {}).get("name") or topic)
        until = str(meta.get("until") or "")
        day = f"{until[8:10]}/{until[5:7]}" if len(until) >= 10 else ""
        why = "bạn bảo đừng nhắc" if meta.get("reason") == "user" else "phản hồi chưa khớp"
        bits.append(f"{name} đến {day} ({why})" if day else f"{name} ({why})")
    return "Đang im: " + "; ".join(bits) + "."


# Clear correction cues. Matched on the raw line so "đừng" is not confused with "đúng"
# after accent folding ("đ" and "d" both become "d").
_CORRECTION_CUES_RAW = (
    "không phải",
    "khong phai",
    "sai rồi",
    "sai roi",
    "đừng",
    "nhầm rồi",
    "nham roi",
    "không đúng",
)
_PREFERENCE_CUES_RAW = (
    "đừng",
    "ngắn gọn",
    "ngan gon",
    "gọi ngắn",
    "goi ngan",
    "phong cách",
    "phong cach",
    "đừng đề xuất",
    "dung de xuat",
)


def _note_fold(text: str) -> str:
    return fold_vi(sanitize_summary(text))


def is_clear_correction(text: str) -> bool:
    """True when the user is correcting the companion, not asking a normal question."""
    raw = str(text or "").lower()
    if not raw.strip():
        return False
    return any(cue in raw for cue in _CORRECTION_CUES_RAW)


def classify_note_kind(text: str) -> str:
    raw = str(text or "").lower()
    folded = fold_vi(text)
    for cue in _PREFERENCE_CUES_RAW:
        if cue in raw or cue in folded:
            return "preference"
    return "correction"


def _clean_one_note(item: Any, default_kind: str) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    text = sanitize_summary(item.get("text") or "")
    if len(text) > MAX_NOTE_LEN:
        text = text[: MAX_NOTE_LEN - 1].rstrip() + "…"
    if len(text) < 4 or text == "[redacted]":
        return None
    topic = str(item.get("topic") or "").strip()
    if topic not in TOPIC_META:
        topic = ""
    kind = str(item.get("kind") or default_kind)
    if kind not in ("correction", "preference"):
        kind = default_kind
    source = str(item.get("source") or "user")
    if source not in ("user", "chat"):
        source = "user"
    note_id = str(item.get("id") or "").strip()[:16]
    if not note_id:
        return None
    return {
        "id": note_id,
        "text": text,
        "topic": topic,
        "kind": kind,
        "at": str(item.get("at") or "")[:32],
        "source": source,
    }


def _split_notes(corrections: Any, preferences: Any) -> tuple:
    """Keep the newest MAX_NOTES facts and style notes. Drop secrets and dupes."""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for default_kind, raw in (("correction", corrections), ("preference", preferences)):
        if not isinstance(raw, list):
            continue
        for item in raw:
            note = _clean_one_note(item, default_kind)
            if note is None:
                continue
            key = _note_fold(note["text"])
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(note)
    rows.sort(key=lambda item: str(item.get("at") or ""))
    rows = rows[-MAX_NOTES:]
    facts = [item for item in rows if item.get("kind") != "preference"]
    prefs = [item for item in rows if item.get("kind") == "preference"]
    return facts, prefs


def list_user_notes(
    profile: Optional[Dict[str, Any]] = None,
    base_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    rows = list(data.get("corrections") or []) + list(data.get("preferences") or [])
    rows = [item for item in rows if isinstance(item, dict)]
    rows.sort(key=lambda item: str(item.get("at") or ""))
    return rows


def add_user_note(
    text: str,
    *,
    kind: str = "",
    topic: str = "",
    source: str = "user",
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Remember one short fact or preference. Never stores a chat transcript."""
    clean = sanitize_summary(text)
    if len(clean) > MAX_NOTE_LEN:
        clean = clean[: MAX_NOTE_LEN - 1].rstrip() + "…"
    if len(clean) < 4 or clean == "[redacted]":
        return None
    note_kind = kind if kind in ("correction", "preference") else classify_note_kind(clean)
    topics = infer_topics(clean)
    primary = str(topic or "").strip()
    if primary not in TOPIC_META:
        primary = topics[0] if topics else ""
    stamp = (now or datetime.now()).replace(microsecond=0).isoformat(timespec="seconds")
    src = "chat" if str(source or "") == "chat" else "user"
    profile = load_profile(base_dir)
    rows = list_user_notes(profile)
    folded = _note_fold(clean)
    kept = [item for item in rows if _note_fold(str(item.get("text") or "")) != folded]
    note_id = hashlib.sha1(folded.encode("utf-8")).hexdigest()[:12]
    note = {
        "id": note_id,
        "text": clean,
        "topic": primary,
        "kind": note_kind,
        "at": stamp,
        "source": src,
    }
    kept.append(note)
    facts = [item for item in kept if item.get("kind") != "preference"]
    prefs = [item for item in kept if item.get("kind") == "preference"]
    profile["corrections"] = facts
    profile["preferences"] = prefs
    save_profile(profile, base_dir=base_dir)
    return note


def delete_user_note(note_id: str, base_dir: Optional[str] = None) -> bool:
    wanted = str(note_id or "").strip()
    if not wanted:
        return False
    profile = load_profile(base_dir)
    before = list_user_notes(profile)
    facts = [item for item in (profile.get("corrections") or []) if str(item.get("id") or "") != wanted]
    prefs = [item for item in (profile.get("preferences") or []) if str(item.get("id") or "") != wanted]
    if len(facts) + len(prefs) == len(before):
        return False
    profile["corrections"] = facts
    profile["preferences"] = prefs
    save_profile(profile, base_dir=base_dir)
    return True


def matching_user_notes(
    profile: Optional[Dict[str, Any]],
    topics: Optional[Iterable[str]] = None,
    *,
    limit: int = 2,
    include_style: bool = True,
) -> List[Dict[str, Any]]:
    """Topic matches first, then one untagged style preference. Nothing is invented."""
    rows = list(reversed(list_user_notes(profile)))
    cap = max(1, int(limit))
    wanted = [str(topic) for topic in (topics or []) if str(topic)]
    picked: List[Dict[str, Any]] = []
    if wanted:
        for note in rows:
            if str(note.get("topic") or "") in wanted:
                picked.append(note)
            if len(picked) >= cap:
                break
        if include_style and len(picked) < cap:
            for note in rows:
                if note in picked:
                    continue
                if note.get("kind") == "preference" and not str(note.get("topic") or ""):
                    picked.append(note)
                    break
    else:
        picked = rows[:cap]
    return picked


def format_user_note_line(note: Dict[str, Any]) -> str:
    text = str(note.get("text") or "").strip()
    if not text:
        return ""
    if note.get("kind") == "preference":
        return f"Bạn muốn: {text}"
    topic = str(note.get("topic") or "")
    name = str((TOPIC_META.get(topic) or {}).get("name") or "")
    if name:
        return f"Bạn đã sửa ({name}): {text}"
    return f"Bạn đã sửa: {text}"


def format_user_note_lines(
    profile: Optional[Dict[str, Any]],
    topics: Optional[Iterable[str]] = None,
    *,
    limit: int = 2,
    include_style: bool = True,
) -> List[str]:
    lines = [
        format_user_note_line(item)
        for item in matching_user_notes(profile, topics, limit=limit, include_style=include_style)
    ]
    return [line for line in lines if line]


def annotate_learned_line(text: str, topic: str, profile: Optional[Dict[str, Any]]) -> str:
    """Append one stored note when the topic matches. Does not add hardware facts."""
    body = str(text or "").strip()
    if not body or not topic:
        return body
    notes = matching_user_notes(profile, [topic], limit=1, include_style=False)
    if not notes:
        return body
    extra = str(notes[0].get("text") or "").strip()
    if not extra or extra in body:
        return body
    suffix = f" Bạn đã nói: {extra}."
    if len(body) + len(suffix) > 320:
        return body
    return body.rstrip() + suffix


def score_trust(
    events: Optional[Sequence[Dict[str, Any]]] = None,
    profile: Optional[Dict[str, Any]] = None,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Accept vs reject on this PC. Not a model, and not the global coaching flag.

    Count one point per diary row (coalesced bursts are not extra trust):
      accept — suggestion_accepted, or user_feedback / chat rating marked accepted
               (insight and check-in taps already write suggestion_accepted)
      reject — suggestion_rejected, or user_feedback marked rejected
               plus one point per explicit «đừng nhắc» mute still active
    A soft mute from «Chưa khớp» is already the user_feedback row, so it is not
    counted again. Topic mute and topic ask-more still win for that topic even
    when trust is high — see effective_coaching.

    low    — at least 2 rejects and rejects outnumber accepts
    high   — at least TRUST_MIN_SAMPLE rows, at least 2 accepts, accept rate
             ≥ 2/3, and accepts outnumber rejects
    steady — too little evidence, or a mixed record

    High trust does not by itself set may_propose_actions. Stage ≥ 2 and the
    consent flag still gate proposals, and BLOCKED_ACTION_KEYS stay blocked.
    Low trust only forces the ask-more voice (fewer buttons, softer check-ins).
    """
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    if events is None:
        rows = recent_events(days=30, limit=0, base_dir=base_dir, now=now)
    else:
        rows = list(events)
    accepted = 0
    rejected = 0
    for event in rows:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "")
        outcome = str(event.get("outcome") or "")
        if kind == "suggestion_accepted" or (kind == "user_feedback" and outcome == "accepted"):
            accepted += 1
        elif kind == "suggestion_rejected" or (kind == "user_feedback" and outcome == "rejected"):
            rejected += 1
    for _topic, meta in active_muted_topics(now=now, profile=data).items():
        if str(meta.get("reason") or "") == "user":
            rejected += 1
    sample = accepted + rejected
    if rejected >= 2 and rejected > accepted:
        level = "low"
    elif (
        sample >= TRUST_MIN_SAMPLE
        and accepted >= 2
        and rejected < accepted
        and accepted / float(sample) >= (2.0 / 3.0)
    ):
        level = "high"
    else:
        level = "steady"
    return {"level": level, "accepted": accepted, "rejected": rejected, "sample": sample}


def effective_coaching(
    profile: Optional[Dict[str, Any]] = None,
    *,
    topic: str = "",
    events: Optional[Sequence[Dict[str, Any]]] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Global coaching, else low trust. A muted topic or topic ask-more always wins.

    High trust returns "steady" and does not clear a mute or an ask-more flag.
    Callers still honor may_propose_actions and the insight allowlist.
    """
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    key = str(topic or "").strip()
    if key and (topic_is_muted(key, now=now, profile=data) or topic_asks_more(key, profile=data)):
        return "ask_more"
    if str(data.get("coaching") or "") == "ask_more":
        return "ask_more"
    trust = score_trust(events, data, base_dir=base_dir, now=now)
    if trust.get("level") == "low":
        return "ask_more"
    return "steady"


def issues_for_topics(topics: Sequence[str]) -> List[str]:
    out: List[str] = []
    for topic in topics:
        issue = topic_issue(topic)
        if issue and issue not in out:
            out.append(issue)
    return out


def _topic_of_kind(kind: str) -> str:
    key = str(kind or "")
    for topic, meta in TOPIC_META.items():
        if key in meta["kinds"]:
            return topic
    return ""


def event_topic(event: Optional[Dict[str, Any]]) -> str:
    """Topic of a diary row. Chat notes carry the topic in tags, not the kind."""
    if not isinstance(event, dict):
        return ""
    kind = str(event.get("kind") or "")
    topic = _topic_of_kind(kind)
    if topic:
        return topic
    if kind == "chat_note":
        for tag in event.get("tags") or []:
            if str(tag) in TOPIC_META:
                return str(tag)
    return ""


def _dominant(counts: Dict[str, int], minimum: int = 2, ratio: float = 0.6) -> str:
    if not counts:
        return ""
    key, hits = max(counts.items(), key=lambda item: (item[1], item[0]))
    total = sum(counts.values())
    if hits >= minimum and total > 0 and hits >= total * ratio:
        return key
    return ""


def _habit(
    habit_id: str,
    topic: str,
    label: str,
    detail: str,
    evidence: int,
    polarity: str,
    *,
    band: str = "",
    weekday: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "id": habit_id,
        "topic": topic,
        "label_vi": label[:80],
        "detail_vi": detail[:160],
        "evidence": max(0, int(evidence)),
        "polarity": polarity,
        "band": band,
        "weekday": weekday,
    }


def _suggestion_topic(event: Dict[str, Any]) -> str:
    for tag in event.get("tags") or []:
        topic = _ACTION_TOPIC.get(str(tag))
        if topic:
            return topic
        if str(tag) in TOPIC_META:
            return str(tag)
    return ""


def derive_habits(events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn episodes + feedback into a handful of factual habits."""
    rows = [item for item in events if isinstance(item, dict)]
    by_topic: Dict[str, List[Dict[str, Any]]] = {topic: [] for topic in TOPIC_META}
    accepted: Dict[str, int] = {}
    rejected: Dict[str, int] = {}
    helpful = 0
    unhelpful = 0
    chat_hits: Dict[str, int] = {}
    for event in rows:
        kind = str(event.get("kind") or "")
        weight = event_weight(event)
        if kind == "chat_note":
            tags = {str(tag) for tag in (event.get("tags") or [])}
            if "feedback" not in tags:
                asked = event_topic(event)
                if asked:
                    chat_hits[asked] = chat_hits.get(asked, 0) + weight
            continue
        topic = _topic_of_kind(kind)
        if topic:
            by_topic[topic].append(event)
        if kind == "suggestion_accepted":
            topic = _suggestion_topic(event)
            if topic:
                accepted[topic] = accepted.get(topic, 0) + weight
        elif kind == "suggestion_rejected":
            topic = _suggestion_topic(event)
            if topic:
                rejected[topic] = rejected.get(topic, 0) + weight
        elif kind == "user_feedback":
            outcome = str(event.get("outcome") or "")
            metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
            if outcome == "accepted" or metrics.get("helpful") in (1, 1.0, True):
                helpful += weight
            elif outcome == "rejected" or metrics.get("helpful") in (0, 0.0, False):
                unhelpful += weight
    habits: List[Dict[str, Any]] = []
    for topic, meta in TOPIC_META.items():
        topic_rows = by_topic.get(topic) or []
        if not topic_rows and accepted.get(topic, 0) < 2 and rejected.get(topic, 0) < 2:
            continue
        band_counts: Dict[str, int] = {}
        weekday_counts: Dict[int, int] = {}
        warn_n = 0
        ok_n = 0
        activity = 0
        for event in topic_rows:
            weight = event_weight(event)
            activity += weight
            kind = str(event.get("kind") or "")
            if kind in meta["warn"]:
                warn_n += weight
            if kind in meta["ok"] and str(event.get("outcome") or "") in ("ok", "neutral", "accepted", ""):
                ok_n += weight
            stamp = _event_dt(event)
            if stamp is None:
                continue
            band = time_band(stamp)
            band_counts[band] = band_counts.get(band, 0) + weight
            weekday_counts[stamp.weekday()] = weekday_counts.get(stamp.weekday(), 0) + weight
        band = _dominant(band_counts)
        weekday_key = ""
        if weekday_counts:
            wd, wd_hits = max(weekday_counts.items(), key=lambda item: (item[1], -item[0]))
            wd_total = sum(weekday_counts.values())
            if wd_hits >= 2 and wd_total > 0 and wd_hits >= wd_total * 0.6:
                weekday_key = str(wd)
                weekday_hits = wd_hits
            else:
                weekday_hits = 0
        else:
            weekday_hits = 0
        name = str(meta["name"])
        if topic == "focus" and weekday_key != "" and weekday_hits >= 2:
            wd = int(weekday_key)
            label = f"Hay tập trung {_WEEKDAY_VI[wd]}"
            detail = f"Bạn bật Trước thi / họp vào {_WEEKDAY_VI[wd]} ({weekday_hits} lần)."
            habits.append(_habit(
                f"focus_wd{wd}",
                topic,
                label,
                detail,
                weekday_hits,
                "preference",
                weekday=wd,
            ))
        elif topic == "thermal" and warn_n >= 2:
            habits.append(_habit(
                "thermal_sensitive",
                topic,
                "Nhạy với nhiệt",
                f"Nhiệt vượt ngưỡng {warn_n} lần trên máy này.",
                warn_n,
                "concern",
            ))
        elif band and (warn_n >= 2 or (topic in ("focus", "disk") and activity >= 2)):
            band_n = band_counts.get(band, 0)
            when = _BAND_VI.get(band, band)
            if topic == "wifi":
                label = f"Quan tâm Wi-Fi {when}"
                detail = f"Wi-Fi yếu {when} đã ghi {band_n} lần trên máy này."
            elif topic == "focus":
                label = f"Hay tập trung {when}"
                detail = f"Bạn bật Trước thi / họp {when} ({band_n} lần)."
            elif topic == "disk":
                label = f"Hay dọn máy {when}"
                detail = f"Máy được dọn {when} ({band_n} lần)."
            else:
                label = f"{meta['concern']} {when}"
                detail = f"{name} {when} đã ghi {band_n} lần trên máy này."
            habits.append(_habit(
                f"{topic}_{band}",
                topic,
                label,
                detail,
                band_n,
                "concern" if topic != "focus" else "preference",
                band=band,
            ))
        elif warn_n >= 2:
            habits.append(_habit(
                f"{topic}_concern",
                topic,
                str(meta["concern"]),
                f"{name} gặp vấn đề {warn_n} lần trên máy này.",
                warn_n,
                "concern",
            ))
        elif topic == "disk" and activity >= 3:
            habits.append(_habit(
                "disk_clean",
                topic,
                "Hay dọn máy",
                f"Máy đã được dọn {activity} lần.",
                activity,
                "preference",
            ))
        elif topic == "update" and warn_n >= 1 and ok_n == 0:
            habits.append(_habit(
                "update_fail",
                topic,
                "Cập nhật hay lỗi",
                f"Cập nhật không xong {warn_n} lần — kiểm tra mạng trước khi tải lại.",
                warn_n,
                "concern",
            ))
        if accepted.get(topic, 0) >= 2:
            habits.append(_habit(
                f"{topic}_prefer",
                topic,
                f"Thường làm theo gợi ý {name}",
                f"Bạn làm theo gợi ý {name} {accepted[topic]} lần.",
                accepted[topic],
                "preference",
            ))
        if rejected.get(topic, 0) >= 2 and rejected.get(topic, 0) > accepted.get(topic, 0):
            habits.append(_habit(
                f"{topic}_avoid",
                topic,
                f"Hay bỏ qua gợi ý {name}",
                f"Bạn bỏ qua gợi ý {name} {rejected[topic]} lần.",
                rejected[topic],
                "avoid",
            ))
    for topic, hits in chat_hits.items():
        if hits < 2 or topic not in TOPIC_META:
            continue
        name = str(TOPIC_META[topic]["name"])
        habits.append(_habit(
            f"{topic}_asks",
            topic,
            f"Bạn hay hỏi về {name}",
            f"Bạn đã hỏi Copilot về {name} {hits} lần trên máy này.",
            hits,
            "interest",
        ))
    habits.sort(key=lambda item: (-int(item.get("evidence") or 0), str(item.get("id") or "")))
    # One concern/preference story per topic, plus a separate avoid line.
    kept: List[Dict[str, Any]] = []
    seen_topic_polarity = set()
    for habit in habits:
        key = (habit.get("topic"), habit.get("polarity"))
        if key in seen_topic_polarity:
            continue
        seen_topic_polarity.add(key)
        kept.append(habit)
        if len(kept) >= MAX_HABITS:
            break
    coaching = "ask_more" if unhelpful >= 2 and unhelpful > helpful else "steady"
    return {
        "habits": kept,
        "coaching": coaching,
        "feedback": {"helpful": helpful, "unhelpful": unhelpful},
    }


def refresh_profile(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    events: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Rebuild habits from the diary. Keeps the goal and dismissed insights."""
    prior = load_profile(base_dir)
    rows = list(events) if events is not None else recent_events(days=30, limit=0, base_dir=base_dir, now=now)
    rows = _events_after(rows, str(prior.get("habits_after") or ""))
    derived = derive_habits(rows)
    stamp = (now or datetime.now()).replace(microsecond=0).isoformat(timespec="seconds")
    prior["version"] = PROFILE_VERSION
    prior["updated_at"] = stamp
    prior["habits"] = derived["habits"]
    prior["coaching"] = derived["coaching"]
    prior["feedback"] = derived["feedback"]
    return save_profile(prior, base_dir=base_dir)


def clear_profile(base_dir: Optional[str] = None) -> int:
    """Remove the whole profile file, including the optional goal."""
    path = profile_path(base_dir)
    if not path or not os.path.exists(path):
        return 0
    try:
        os.remove(path)
    except Exception:
        return 0
    return 1


def clear_habits(base_dir: Optional[str] = None, now: Optional[datetime] = None) -> int:
    """Clear learned habits. The goal and the notes the user typed stay.

    Episodes from before this moment do not rebuild the same habits on the next refresh.
    """
    prior = load_profile(base_dir)
    had = len(prior.get("habits") or [])
    stamp = now or datetime.now()
    prior["habits"] = []
    prior["coaching"] = "steady"
    prior["feedback"] = {"helpful": 0, "unhelpful": 0}
    prior["habits_after"] = stamp.replace(microsecond=0).isoformat(timespec="seconds")
    prior["updated_at"] = prior["habits_after"]
    save_profile(prior, base_dir=base_dir)
    return had


def _events_after(events: Sequence[Dict[str, Any]], after_iso: str) -> List[Dict[str, Any]]:
    after = _parse_ts(after_iso)
    if after is None:
        return list(events)
    kept: List[Dict[str, Any]] = []
    for event in events:
        ts = _parse_ts(str(event.get("ts") or ""))
        if ts is None or ts > after:
            kept.append(event)
    return kept


def matching_habits(
    profile: Optional[Dict[str, Any]],
    topics: Optional[Iterable[str]] = None,
    limit: int = 2,
) -> List[Dict[str, Any]]:
    habits = list((profile or {}).get("habits") or [])
    wanted = [str(topic) for topic in (topics or []) if str(topic)]
    if wanted:
        habits = [item for item in habits if item.get("topic") in wanted]
    return habits[: max(1, int(limit))]


def format_habit_line(habit: Dict[str, Any]) -> str:
    label = str(habit.get("label_vi") or "").strip()
    detail = str(habit.get("detail_vi") or "").strip()
    if label and detail:
        return f"{label} — {detail}"
    return label or detail


def format_profile_lines(
    profile: Optional[Dict[str, Any]],
    topics: Optional[Iterable[str]] = None,
    limit: int = 2,
) -> List[str]:
    lines = [format_habit_line(item) for item in matching_habits(profile, topics, limit=limit)]
    lines = [line for line in lines if line]
    coaching = str((profile or {}).get("coaching") or "")
    if coaching == "ask_more" and (not topics or lines):
        lines.append("Phản hồi gần đây: gợi ý chưa khớp — hỏi thêm trước khi đề xuất.")
    return lines[: max(1, int(limit) + 1)]


def _goal_dict(profile: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    goal = (profile or {}).get("goal")
    if isinstance(goal, dict) and str(goal.get("text") or "").strip():
        return goal
    return None


def format_profile_browse(profile: Optional[Dict[str, Any]] = None, base_dir: Optional[str] = None) -> str:
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    habits = data.get("habits") or []
    lines: List[str] = []
    if habits:
        lines.append("Về máy này:")
        for habit in habits:
            text = format_habit_line(habit)
            if text:
                lines.append(f"• {text}")
    else:
        lines.append(_EMPTY_PROFILE_VI)
    if str(data.get("coaching") or "") == "ask_more":
        lines.append("Phản hồi: gợi ý gần đây chưa khớp — hỏi thêm trước khi đề xuất.")
    taught = format_user_note_lines(data, limit=4, include_style=True)
    if taught:
        lines.append("Lời bạn đã dạy:")
        lines.extend(f"• {line}" for line in taught)
    muted_line = format_muted_browse(data, base_dir=base_dir)
    if muted_line and not muted_line.startswith("Không có"):
        lines.append(muted_line)
    goal_line = format_goal_status(data, base_dir=base_dir)
    if goal_line:
        lines.append(goal_line)
    quiet = quiet_hours_settings(data)
    if quiet.get("enabled"):
        lines.append(f"Giờ yên lặng: {quiet.get('start')}–{quiet.get('end')}.")
    snoozed = active_snoozed_topics(profile=data)
    if snoozed:
        names = [
            str((TOPIC_META.get(topic) or {}).get("name") or topic)
            for topic in sorted(snoozed)
        ]
        lines.append("Đừng nhắc: " + ", ".join(names) + ".")
    return "\n".join(lines)


def set_goal(
    text: str,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Store one short goal. Blank text clears it and stops goal coaching."""
    profile = load_profile(base_dir)
    raw = sanitize_summary(text)
    if len(raw) > MAX_GOAL_LEN:
        raw = raw[: MAX_GOAL_LEN - 1].rstrip() + "…"
    if not raw:
        profile["goal"] = None
        save_profile(profile, base_dir=base_dir)
        return None
    topics = infer_topics(raw)
    primary = topics[0] if topics else ""
    stamp = (now or datetime.now()).replace(microsecond=0).isoformat(timespec="seconds")
    goal = {
        "text": raw,
        "topic": primary,
        "topics": topics,
        "issue_classes": issues_for_topics(topics),
        "set_at": stamp,
    }
    profile["goal"] = goal
    save_profile(profile, base_dir=base_dir)
    return goal


def clear_goal(base_dir: Optional[str] = None) -> None:
    set_goal("", base_dir=base_dir)


def goal_issue_classes(profile: Optional[Dict[str, Any]] = None, base_dir: Optional[str] = None) -> List[str]:
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    goal = _goal_dict(data)
    if not goal:
        return []
    stored = goal.get("issue_classes")
    if isinstance(stored, list) and stored:
        return [str(item) for item in stored if str(item).strip()]
    return issues_for_topics(goal.get("topics") or [])


def goal_status(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    events: Optional[Sequence[Dict[str, Any]]] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Progress since the goal was set. None when the user has no goal."""
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    goal = _goal_dict(data)
    if not goal:
        return None
    topics = [str(item) for item in (goal.get("topics") or []) if str(item)]
    primary = str(goal.get("topic") or (topics[0] if topics else ""))
    if primary and primary not in topics:
        topics.insert(0, primary)
    set_ts = _parse_ts(str(goal.get("set_at") or ""))
    rows = list(events) if events is not None else recent_events(days=30, limit=0, base_dir=base_dir, now=now)
    open_count = 0
    improved_count = 0
    for event in rows:
        if set_ts is not None:
            ts = _parse_ts(str(event.get("ts") or ""))
            if ts is None or ts < set_ts:
                continue
        topic = _topic_of_kind(str(event.get("kind") or ""))
        if topics and topic not in topics:
            continue
        if not topics and not topic:
            continue
        meta = TOPIC_META.get(topic) or {}
        weight = event_weight(event)
        kind = str(event.get("kind") or "")
        if kind in (meta.get("warn") or set()):
            open_count += weight
        elif kind in (meta.get("ok") or set()) and str(event.get("outcome") or "") in ("ok", "neutral", "accepted", ""):
            improved_count += weight
    related = open_count + improved_count
    text = str(goal.get("text") or "").strip()
    if related <= 0:
        summary = f"Mục tiêu «{text}»: chưa có diễn biến mới."
        next_action = ""
    else:
        bits = []
        if open_count:
            bits.append(f"{open_count} lần chưa ổn")
        if improved_count:
            bits.append(f"{improved_count} lần đã khá hơn")
        summary = f"Mục tiêu «{text}»: " + ", ".join(bits) + "."
        next_action = str((TOPIC_META.get(primary) or {}).get("next") or "")
    return {
        "text": text,
        "topic": primary,
        "topics": topics,
        "set_at": str(goal.get("set_at") or ""),
        "open_count": open_count,
        "improved_count": improved_count,
        "related_count": related,
        "next_action_vi": next_action,
        "summary_vi": summary,
        "issue_classes": goal_issue_classes(data),
    }


def format_goal_status(
    profile: Optional[Dict[str, Any]] = None,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    events: Optional[Sequence[Dict[str, Any]]] = None,
) -> str:
    status = goal_status(base_dir=base_dir, now=now, events=events, profile=profile)
    if not status:
        return ""
    lines = [status["summary_vi"]]
    if status.get("next_action_vi"):
        lines.append(str(status["next_action_vi"]))
    return "\n".join(lines)


def rank_events(
    user_text: str,
    events: Sequence[Dict[str, Any]],
    *,
    limit: int = 4,
    topics: Optional[Sequence[str]] = None,
    goal_topics: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Pick diary rows for a question: topic match, then goal, then recency."""
    rows = [item for item in events if isinstance(item, dict)]
    if not rows:
        return []
    cap = max(1, int(limit))
    wanted = list(topics) if topics is not None else infer_topics(user_text)
    goal = [str(item) for item in (goal_topics or []) if str(item)]
    stamp = now or datetime.now()
    now_ts = stamp.timestamp()

    def _score(event: Dict[str, Any]) -> float:
        kind = str(event.get("kind") or "")
        topic = event_topic(event)
        score = 0.0
        if kind == "session_day":
            score -= 40
        if wanted:
            if topic in wanted:
                score += 50
            else:
                score -= 25
        elif topic and goal and topic in goal:
            score += 18
        elif not wanted:
            score += 1
        if goal and topic in goal:
            score += 12
        ts = _parse_ts(str(event.get("ts") or ""))
        if ts is not None:
            age = max(0.0, now_ts - ts)
            if age <= 3 * 86400:
                score += 8
            elif age <= 7 * 86400:
                score += 4
        score += min(4, event_weight(event))
        if wanted and topic in wanted and str(event.get("outcome") or "") in ("ok", "fail"):
            score += 3
        return score

    scored = [( _score(item), _parse_ts(str(item.get("ts") or "")) or 0.0, item) for item in rows]
    if wanted:
        matched = [item for item in scored if item[0] >= 40]
        pool = matched or [item for item in scored if event_topic(item[2]) in wanted]
    else:
        pool = [item for item in scored if str(item[2].get("kind") or "") != "session_day"] or scored
    pool.sort(key=lambda item: (item[0], item[1]))
    picked = [item[2] for item in pool[-cap:]]
    picked.sort(key=lambda item: _parse_ts(str(item.get("ts") or "")) or 0.0)
    return picked


def active_time_windows(
    events: Optional[Sequence[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Recurring topic windows from diary timestamps. No LLM and no invented causes.

    A window counts when the same topic falls in one time band on at least two
    different days, and that band is the majority of the topic's dated rows.
    Only the band that contains ``now`` is returned, and muted topics are left out.
    """
    stamp = now or datetime.now()
    band_now = time_band(stamp)
    muted = set(active_muted_topics(now=stamp, profile=profile)) if profile is not None else set()
    days_by_topic: Dict[str, Dict[str, set]] = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        topic = event_topic(event)
        if not topic or topic in muted:
            continue
        meta = TOPIC_META.get(topic) or {}
        if str(event.get("kind") or "") not in (meta.get("kinds") or set()):
            continue
        moment = _event_dt(event)
        if moment is None:
            continue
        band = time_band(moment)
        days_by_topic.setdefault(topic, {}).setdefault(band, set()).add(moment.strftime("%Y-%m-%d"))
    found: List[Dict[str, Any]] = []
    for topic, bands in days_by_topic.items():
        counts = {band: len(days) for band, days in bands.items()}
        if not counts:
            continue
        best = max(counts, key=lambda band: (counts[band], band))
        best_days = counts[best]
        total_days = sum(counts.values())
        if best_days < 2 or best != band_now:
            continue
        # Majority of the topic's dated rows, so one odd evening is not a habit.
        if total_days and best_days * 5 < total_days * 3:
            continue
        name = str((TOPIC_META.get(topic) or {}).get("name") or topic)
        when = _BAND_VI.get(best, best)
        found.append({
            "topic": topic,
            "band": best,
            "evidence": best_days,
            "text": f"{WINDOW_PHRASE}: {name} {when} ({best_days} ngày).",
        })
    found.sort(key=lambda item: (-int(item.get("evidence") or 0), str(item.get("topic") or "")))
    return found


def build_growth_timeline(
    base_dir: Optional[str] = None,
    *,
    limit: int = GROWTH_LIMIT,
    now: Optional[datetime] = None,
) -> List[Dict[str, str]]:
    """Read-only moments already on disk: stage-ups, skills, notes, weekly markers."""
    items: List[Dict[str, str]] = []
    try:
        rows = read_events(base_dir=base_dir, limit=0)
    except Exception:
        rows = []
    for event in rows:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "")
        ts = str(event.get("ts") or "")
        summary = str(event.get("summary") or "").strip()
        if kind == "stage_up" and summary:
            items.append({"ts": ts, "kind": "stage_up", "text": summary})
        elif kind == "skill_saved" and summary:
            items.append({"ts": ts, "kind": "skill", "text": summary})
        elif kind == "reflection" and "tuần" in summary.lower():
            items.append({"ts": ts, "kind": "weekly", "text": "Đã ghi tóm tắt tuần."})
    try:
        from core.companion_skills import load_skills
        skills = load_skills(base_dir)
    except Exception:
        skills = []
    skill_blob = " ".join(item.get("text") or "" for item in items if item.get("kind") == "skill")
    for skill in skills:
        title = str(getattr(skill, "title", "") or "").strip()
        if not title or title in skill_blob:
            continue
        items.append({
            "ts": str(getattr(skill, "created_at", "") or ""),
            "kind": "skill",
            "text": f"Đã lưu kỹ năng: {title}",
        })
    if not any(item.get("kind") == "weekly" for item in items):
        try:
            from core.companion_reflection import WEEKLY_MARKER, load_reflection, load_reflection_meta
            note = load_reflection(base_dir)
            if WEEKLY_MARKER in note:
                meta = load_reflection_meta(base_dir)
                items.append({
                    "ts": str(meta.get("updated_at") or ""),
                    "kind": "weekly",
                    "text": "Đã ghi tóm tắt tuần.",
                })
        except Exception:
            pass
    for note in list_user_notes(base_dir=base_dir):
        line = format_user_note_line(note)
        if not line:
            continue
        items.append({
            "ts": str(note.get("at") or ""),
            "kind": str(note.get("kind") or "correction"),
            "text": line,
        })
    items.sort(key=lambda item: (str(item.get("ts") or "9999"), str(item.get("kind") or "")))
    cap = max(1, int(limit or GROWTH_LIMIT))
    return items[-cap:]


def format_growth_row(item: Optional[Dict[str, Any]]) -> str:
    if not isinstance(item, dict):
        return ""
    text = str(item.get("text") or "").strip()
    if not text:
        return ""
    ts = str(item.get("ts") or "")
    if len(ts) >= 10:
        return f"{ts[8:10]}/{ts[5:7]} · {text}"
    return text


def _insight(insight_id: str, text: str, topic: str = "") -> Dict[str, str]:
    body = str(text or "").strip()
    if body and not body.startswith("Hôm nay:"):
        body = "Hôm nay: " + body
    return {"id": insight_id, "text": body, "topic": topic}


def build_insight_candidates(
    profile: Optional[Dict[str, Any]],
    events: Optional[Sequence[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, str]]:
    data = profile or {}
    stamp = now or datetime.now()
    items: List[Dict[str, str]] = []
    for window in active_time_windows(events, now=stamp, profile=data):
        items.append(_insight(
            f"window:{window.get('topic')}:{window.get('band')}",
            str(window.get("text") or ""),
            str(window.get("topic") or ""),
        ))
    status = goal_status(profile=data, events=events, now=stamp)
    if status and int(status.get("related_count") or 0) > 0:
        items.append(_insight(
            f"goal:{status.get('topic') or 'goal'}",
            status.get("summary_vi") or "",
            str(status.get("topic") or ""),
        ))
    for habit in data.get("habits") or []:
        if int(habit.get("evidence") or 0) < 2:
            continue
        detail = str(habit.get("detail_vi") or habit.get("label_vi") or "").strip()
        if not detail:
            continue
        items.append(_insight(f"habit:{habit.get('id')}", detail, str(habit.get("topic") or "")))
        if len(items) >= 4:
            break
    cutoff = stamp.timestamp() - 2 * 86400
    for event in reversed(list(events or [])):
        kind = str(event.get("kind") or "")
        if str(event.get("outcome") or "") != "ok":
            continue
        if kind not in ("wifi_repaired", "ping_repaired", "ram_optimized", "clean_light", "update_ok"):
            continue
        ts = _parse_ts(str(event.get("ts") or ""))
        if ts is None or ts < cutoff:
            continue
        topic = _topic_of_kind(kind)
        summary = str(event.get("summary") or "").strip()
        if not summary:
            continue
        day = str(event.get("ts") or "")[:10]
        items.append(_insight(f"ok:{kind}:{day}", summary, topic))
        break
    # Drop empty texts
    return [item for item in items if item.get("text")]


def current_insight(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    enabled: bool = True,
    profile: Optional[Dict[str, Any]] = None,
    events: Optional[Sequence[Dict[str, Any]]] = None,
) -> Optional[Dict[str, str]]:
    """One calm factual line for today. None when disabled, empty, or dismissed."""
    if not enabled:
        return None
    stamp = now or datetime.now()
    data = profile if isinstance(profile, dict) else load_profile(base_dir)
    if str(data.get("insight_snooze_date") or "") == stamp.strftime("%Y-%m-%d"):
        return None
    rows = list(events) if events is not None else recent_events(days=21, limit=0, base_dir=base_dir, now=stamp)
    candidates = build_insight_candidates(data, rows, now=stamp)
    dismissed = set(data.get("dismissed_insights") or [])
    muted = set(active_muted_topics(now=stamp, profile=data))
    snoozed = set(active_snoozed_topics(now=stamp, profile=data))
    visible = [
        item for item in candidates
        if item.get("id") not in dismissed
        and str(item.get("topic") or "") not in muted
        and str(item.get("topic") or "") not in snoozed
    ]
    if not visible:
        return None
    windows = [item for item in visible if str(item.get("id") or "").startswith("window:")]
    if windows:
        chosen = dict(windows[0])
    else:
        chosen = dict(visible[stamp.toordinal() % len(visible)])
    chosen["text"] = annotate_learned_line(str(chosen.get("text") or ""), str(chosen.get("topic") or ""), data)
    return chosen


def dismiss_insight(
    insight_id: str,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Hide this insight, and don't rotate in a replacement until tomorrow."""
    wanted = str(insight_id or "").strip()
    if not wanted:
        return
    profile = load_profile(base_dir)
    dismissed = [str(item) for item in (profile.get("dismissed_insights") or [])]
    if wanted not in dismissed:
        dismissed.append(wanted)
    profile["dismissed_insights"] = dismissed[-MAX_DISMISSED:]
    profile["insight_snooze_date"] = (now or datetime.now()).strftime("%Y-%m-%d")
    save_profile(profile, base_dir=base_dir)
