"""
Compact local profile of this user and machine.

Built from diary episodes, accept/reject, and chat feedback. No model training:
a small JSON file the companion can show, clear, and inject into Copilot context.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

from config_manager import companion_dir
from core.companion_diary import event_weight, recent_events, sanitize_summary, time_band
from core.companion_skills import fold_vi

PROFILE_FILENAME = "profile.json"
MAX_HABITS = 6
MAX_GOAL_LEN = 80
MAX_DISMISSED = 24
PROFILE_VERSION = 1
MUTE_DAYS = 7
SOFT_MUTE_DAYS = 2

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
    _atomic_write_json(profile_path(base_dir), payload)
    return payload


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
    """Clear learned habits. The goal the user typed stays.

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
    muted_line = format_muted_browse(data, base_dir=base_dir)
    if muted_line and not muted_line.startswith("Không có"):
        lines.append(muted_line)
    goal_line = format_goal_status(data, base_dir=base_dir)
    if goal_line:
        lines.append(goal_line)
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
    visible = [
        item for item in candidates
        if item.get("id") not in dismissed and str(item.get("topic") or "") not in muted
    ]
    if not visible:
        return None
    index = stamp.toordinal() % len(visible)
    return visible[index]


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
