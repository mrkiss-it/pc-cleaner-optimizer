"""Local daily learning model — a JSON snapshot, not an LLM weight file.

Schema v2 is still one file on this PC (`learning_model.json`). It is rebuilt
once per calendar day from the diary, profile, and feedback already here.
A second full rebuild the same day returns the stored snapshot and does not
add those counts again. The next morning stores deltas against yesterday.

Same-day Có ích / Chưa, mute, snooze, pin, focus end, and a rough-day flag
only touch the `micro` overlay (and a mute log). They do not rewrite
`topic_scores`, windows, or deltas. The next full rebuild is the source of
truth and does not add `micro` on top of the diary, so nothing is counted twice.

No download, no Ollama, no Gemini, no neural-net training.

How fields affect behavior (they never raise action caps or enable Trước thi/họp):

- `windows` 7d/30d: recent Có ích/Chưa, rough-day rate, focus starts, mute/snooze.
  A weak 7-day topic is quieter in insight ranking. The rate does not schedule work.
- `time_weights` / `time_preference`: diary hours plus habit bands. A favorite
  band is a small tie-break among non-window insights and feeds lesson text.
- `skill_affinity`: which allowlisted actions worked (Có ích, pins, repairs).
  Together with a live pin and the last Có ích action, it picks the propose key.
  Blocked keys are dropped. The button still has to pass stage, consent, mute,
  quiet hours, focus, and a rough day.
- `confidence` / `maturity_signal`: stage + active days + feedback volume, 0–1.
  They only soften or slightly warm `stage_voice` tone. Quiet hours, mute,
  a rough day, and focus soft mode still win. This is not an AGI score.
- `lessons`: up to five short Vietnamese lines. The next morning cites one
  concrete lesson from yesterday when it is not muted.
- `micro`: same-day counters and at most a few lesson candidates. Ranking adds
  them on top of the snapshot until the next full rebuild clears them.
- `trust_deltas` / `stat_deltas`: change versus yesterday's snapshot, not a
  second copy of the lifetime totals.
- `history`: up to seven dated lesson lines for the panel. Display only.
  It is not a second score, and an empty day ("chưa có gì mới", no lessons)
  does not take a slot. A same-day rebuild replaces that day's row.
- `last_rebuild_at`: when the last full rebuild ran. «Học lại hôm nay» ignores
  clicks inside a short cooldown. The next calendar day is not blocked.
- Sparse warning: one quiet Vietnamese line on the model panel when Có ích/Chưa
  volume is still low. It is not added to the morning line, the weekly line,
  or insight text, and it does not change caps.

Phase 2 uses the same file to choose quieter, explainable behavior. Still no
training, and still no raise of action caps.

- Promote: an allowlisted action with at least 3 Có ích and a margin of 2,
  plus a skill candidate or a lesson that names the topic, becomes an offer.
  Muted and declined topics are skipped. `skills.json` changes only after Lưu.
  Blocked keys are never offered and nothing is saved in silence.
- Rank: the morning lead, weekly bullets, and insight order prefer a high
  decayed score. A Chưa-heavy topic drops out when another line remains.
- Explain: one «Vì sao nhắc?» line from today's lesson, yesterday's lesson,
  or that topic's Có ích / Chưa counts.
- Decay: after 7 days without a diary or feedback signal, ranking loses one
  point every 4 days, toward zero. Stored counts and the history ring stay.
  A same-day micro update counts as a fresh signal.
- One tap: a trusted disk topic may suggest «Quét ổ C (xem trước)»; a trusted
  focus topic may suggest Trước thi/họp. The button is the confirmation.
  Preview does not delete and does not ask for UAC.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from config_manager import companion_dir

MODEL_FILENAME = "learning_model.json"
MODEL_VERSION = 2
_WINDOW_DAYS = 21
_RECENT_DAYS = 14
_WINDOW_SHORT = 7
_WINDOW_LONG = 30
_MAX_LESSONS = 5
_MAX_MICRO_LESSONS = 3
_MAX_SIGNAL = 80
_HISTORY_DAYS = 7
_HISTORY_LESSONS = 3
SPARSE_FEEDBACK_MIN = 3
REBUILD_COOLDOWN_SEC = 60
# Ranking only. Stored helpful/unhelpful counts are not reduced.
DECAY_GRACE_DAYS = 7
DECAY_STEP_DAYS = 4
# Offer a playbook after this many Có ích, with a clear margin over Chưa.
PROMOTE_HELPFUL_MIN = 3
PROMOTE_MARGIN = 2
# Suggest one existing safe button. Lower than promote: the tap still confirms.
ONE_TAP_HELPFUL_MIN = 2
_ONE_TAP_BY_TOPIC = {
    "disk": "preview_c_drive",
    "focus": "enable_exam_focus",
}
_NOTE_VI = "Trí nhớ thích nghi trên máy này, không phải AGI và không phải file trọng số."
_HONEST_PANEL_VI = (
    "Trí nhớ thích nghi local trên máy này, không phải AGI, không train lại mạng nơ-ron."
)
_SPARSE_VI = "Cần thêm phản hồi Có ích/Chưa để học chắc hơn."
_REBUILD_DONE_VI = "Đã học lại từ máy này."
_REBUILD_SOON_VI = "Mình vừa học lại hôm nay."
_SIGNALS = ("new", "growing", "steady", "familiar")
_SIGNAL_VI = {
    "new": "mới gặp",
    "growing": "đang lớn",
    "steady": "đã quen dần",
    "familiar": "quen máy này",
}

_SKIP_KINDS = frozenset({
    "session_day",
    "reflection",
    "stage_up",
    "user_feedback",
    "skill_saved",
    "tip_snooze",
    "topic_trust",
    "update_ok",
})
_STRESS_KINDS = frozenset({"wifi_weak", "ping_high", "thermal_warn", "high_ram"})
_STRESS_FAMILY = {
    "wifi_weak": "network",
    "ping_high": "network",
    "thermal_warn": "thermal",
    "high_ram": "ram",
}
_BAND_VI = {
    "morning": "sáng",
    "afternoon": "chiều",
    "evening": "tối",
    "night": "đêm",
}
_IN_REBUILD = False


def model_path(base_dir: Optional[str] = None) -> str:
    folder = base_dir if base_dir else companion_dir()
    return os.path.join(folder, MODEL_FILENAME)


def _empty_window(span: int) -> Dict[str, Any]:
    return {
        "topic_helpfulness": {},
        "rough_days": 0,
        "rough_day_rate": 0.0,
        "focus_sessions": 0,
        "mute": 0,
        "snooze": 0,
        "span_days": int(span),
    }


def _empty_micro() -> Dict[str, Any]:
    return {
        "helpful": 0,
        "unhelpful": 0,
        "mute": 0,
        "snooze": 0,
        "pin": 0,
        "focus_end": 0,
        "rough_day": 0,
        "topics": {},
        "skills": {},
        "lesson_candidates": [],
        "seen_mute": [],
        "seen_snooze": [],
        "seen_pin": [],
    }


def _empty_preference() -> Dict[str, Any]:
    return {"global": {}, "topics": {}}


def _empty_model() -> Dict[str, Any]:
    return {
        "version": MODEL_VERSION,
        "date": "",
        "updated_at": "",
        "source": "local",
        "topic_scores": {},
        "time_weights": {},
        "time_preference": _empty_preference(),
        "habit_weights": [],
        "skill_candidates": [],
        "skill_affinity": {},
        "trust_deltas": {},
        "trust": {"level": "steady", "helpful": 0, "unhelpful": 0},
        "baseline_scores": {},
        "baseline_trust": {"level": "steady", "helpful": 0, "unhelpful": 0},
        "baseline_stats": _empty_stats(),
        "stat_deltas": _empty_stat_deltas(),
        "windows": {"7d": _empty_window(_WINDOW_SHORT), "30d": _empty_window(_WINDOW_LONG)},
        "rough_days": 0,
        "focus_sessions": 0,
        "confidence": 0.0,
        "maturity_signal": "new",
        "lessons": [],
        "micro": _empty_micro(),
        "signal_log": [],
        "summary_vi": "",
        "yesterday_vi": "",
        "yesterday_topic": "",
        "yesterday_lesson": "",
        "history": [],
        "last_rebuild_at": "",
        "note_vi": _NOTE_VI,
    }


def _empty_stats() -> Dict[str, Any]:
    return {
        "rough_days": 0,
        "focus_sessions": 0,
        "confidence": 0.0,
        "mute_7d": 0,
        "snooze_7d": 0,
    }


def _empty_stat_deltas() -> Dict[str, Any]:
    return {
        "rough_days": 0,
        "focus_sessions": 0,
        "confidence": 0.0,
        "mute_7d": 0,
        "snooze_7d": 0,
    }


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _topic_name(topic: str) -> str:
    try:
        from core.companion_profile import TOPIC_META
        return str((TOPIC_META.get(topic) or {}).get("name") or "")
    except Exception:
        return ""


def _band(hour: int) -> str:
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _parse_ts(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if len(raw) < 10:
        return None
    try:
        return datetime.fromisoformat(raw[:19])
    except ValueError:
        return None


def _blocked_keys() -> Set[str]:
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
        return set(BLOCKED_ACTION_KEYS)
    except Exception:
        return set()


def _topic_trust_level(helpful: int, unhelpful: int) -> str:
    try:
        from core.companion_profile import _topic_trust_level_from_counts
        level = _topic_trust_level_from_counts(helpful, unhelpful)
    except Exception:
        level = "steady"
    return level if level in ("low", "steady", "high") else "steady"


def _clean_scores(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Dict[str, Any]] = {}
    for topic, row in raw.items():
        key = str(topic or "").strip()[:24]
        if not key or not isinstance(row, dict):
            continue
        helpful = _as_int(row.get("helpful"))
        unhelpful = _as_int(row.get("unhelpful"))
        diary = _as_int(row.get("diary"))
        last = str(row.get("last_signal") or "")[:10]
        if not _valid_day(last):
            last = ""
        cleaned[key] = {
            "helpful": helpful,
            "unhelpful": unhelpful,
            "diary": diary,
            "score": helpful - unhelpful,
            "level": _topic_trust_level(helpful, unhelpful),
            "last_signal": last,
        }
    return cleaned


def _clean_helpfulness(raw: Any) -> Dict[str, Dict[str, int]]:
    """Rolling Có ích / Chưa only. Not the lifetime topic_scores."""
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Dict[str, int]] = {}
    for topic, row in list(raw.items())[:12]:
        key = str(topic or "").strip()[:24]
        if not key or not isinstance(row, dict):
            continue
        helpful = _as_int(row.get("helpful"))
        unhelpful = _as_int(row.get("unhelpful"))
        if not helpful and not unhelpful:
            continue
        cleaned[key] = {
            "helpful": helpful,
            "unhelpful": unhelpful,
            "score": helpful - unhelpful,
        }
    return cleaned


def _clean_window(raw: Any, span: int) -> Dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    rate = _as_float(row.get("rough_day_rate"), 0.0)
    if rate < 0:
        rate = 0.0
    if rate > 1:
        rate = 1.0
    return {
        "topic_helpfulness": _clean_helpfulness(row.get("topic_helpfulness")),
        "rough_days": _as_int(row.get("rough_days")),
        "rough_day_rate": round(rate, 2),
        "focus_sessions": _as_int(row.get("focus_sessions")),
        "mute": _as_int(row.get("mute")),
        "snooze": _as_int(row.get("snooze")),
        "span_days": span,
    }


def _clean_windows(raw: Any) -> Dict[str, Dict[str, Any]]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "7d": _clean_window(row.get("7d"), _WINDOW_SHORT),
        "30d": _clean_window(row.get("30d"), _WINDOW_LONG),
    }


def _clean_weights(raw: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Dict[str, int]] = {}
    for topic, bands in raw.items():
        key = str(topic or "").strip()[:24]
        if not key or not isinstance(bands, dict):
            continue
        kept = {}
        for band, count in bands.items():
            name = str(band or "").strip()
            if name not in _BAND_VI:
                continue
            n = _as_int(count)
            if n:
                kept[name] = n
        if kept:
            cleaned[key] = kept
    return cleaned


def _clean_band_map(raw: Any) -> Dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    kept: Dict[str, int] = {}
    for band, count in raw.items():
        name = str(band or "").strip()
        if name not in _BAND_VI:
            continue
        try:
            n = int(round(float(count)))
        except (TypeError, ValueError):
            continue
        if n > 0:
            kept[name] = min(100, n)
    return kept


def _clean_preference(raw: Any) -> Dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    topics_raw = row.get("topics") if isinstance(row.get("topics"), dict) else {}
    topics: Dict[str, Dict[str, int]] = {}
    for topic, bands in list(topics_raw.items())[:12]:
        key = str(topic or "").strip()[:24]
        cleaned = _clean_band_map(bands)
        if key and cleaned:
            topics[key] = cleaned
    return {"global": _clean_band_map(row.get("global")), "topics": topics}


def _clean_habits(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        topic = str(item.get("topic") or "").strip()[:24]
        label = " ".join(str(item.get("label_vi") or "").split())[:80]
        if not topic and not label:
            continue
        band = str(item.get("band") or "").strip()
        rows.append({
            "id": str(item.get("id") or "")[:40],
            "topic": topic,
            "weight": _as_int(item.get("weight")),
            "label_vi": label,
            "band": band if band in _BAND_VI else "",
        })
        if len(rows) >= 5:
            break
    return rows


def _clean_candidates(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    blocked = _blocked_keys()
    rows: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action_key") or "").strip().lower()
        issue = str(item.get("issue_class") or "").strip().lower()[:32]
        if action in blocked or issue in blocked:
            continue
        if "winsxs" in issue or "winsxs" in action:
            continue
        title = " ".join(str(item.get("title_vi") or "").split())[:80]
        if not issue and not title:
            continue
        rows.append({
            "issue_class": issue,
            "weight": _as_int(item.get("weight")),
            "title_vi": title,
        })
        if len(rows) >= 5:
            break
    return rows


def _clean_affinity(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    blocked = _blocked_keys()
    cleaned: Dict[str, Dict[str, Any]] = {}
    for key, row in list(raw.items())[:12]:
        action = str(key or "").strip().lower()
        if not action or action in blocked or "winsxs" in action or not isinstance(row, dict):
            continue
        issue = str(row.get("issue_class") or "").strip().lower()[:32]
        if issue in blocked or "winsxs" in issue:
            continue
        helpful = _as_int(row.get("helpful"))
        unhelpful = _as_int(row.get("unhelpful"))
        try:
            score = int(row.get("score"))
        except (TypeError, ValueError):
            score = helpful - unhelpful
        title = " ".join(str(row.get("title_vi") or "").split())[:80]
        cleaned[action] = {
            "score": score,
            "helpful": helpful,
            "unhelpful": unhelpful,
            # Có ích / Chưa only. Repairs and pins raise helpful without this,
            # so propose ranking does not treat a repair as a saved preference.
            "confirmed": _as_int(row.get("confirmed")),
            "title_vi": title,
            "issue_class": issue,
        }
    return cleaned


def _clean_trust(raw: Any) -> Dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    level = str(row.get("level") or "steady")
    if level not in ("low", "steady", "high"):
        level = "steady"
    return {
        "level": level,
        "helpful": _as_int(row.get("helpful")),
        "unhelpful": _as_int(row.get("unhelpful")),
    }


def _clean_deltas(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Dict[str, Any]] = {}
    for topic, row in list(raw.items())[:12]:
        key = str(topic or "").strip()[:24]
        if not key or not isinstance(row, dict):
            continue
        level = str(row.get("level") or "steady")
        if level not in ("low", "steady", "high"):
            level = "steady"
        try:
            delta = int(row.get("delta") or 0)
        except (TypeError, ValueError):
            delta = 0
        try:
            score = int(row.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        cleaned[key] = {"score": score, "delta": delta, "level": level}
    return cleaned


def _clean_stats(raw: Any) -> Dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    confidence = _as_float(row.get("confidence"), 0.0)
    confidence = max(0.0, min(1.0, confidence))
    return {
        "rough_days": _as_int(row.get("rough_days")),
        "focus_sessions": _as_int(row.get("focus_sessions")),
        "confidence": round(confidence, 2),
        "mute_7d": _as_int(row.get("mute_7d")),
        "snooze_7d": _as_int(row.get("snooze_7d")),
    }


def _clean_stat_deltas(raw: Any) -> Dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    confidence = _as_float(row.get("confidence"), 0.0)
    return {
        "rough_days": int(_as_float(row.get("rough_days"), 0.0)),
        "focus_sessions": int(_as_float(row.get("focus_sessions"), 0.0)),
        "confidence": round(confidence, 2),
        "mute_7d": int(_as_float(row.get("mute_7d"), 0.0)),
        "snooze_7d": int(_as_float(row.get("snooze_7d"), 0.0)),
    }


def _valid_day(date: str) -> bool:
    text = str(date or "")
    return len(text) == 10 and text[4] == "-" and text[7] == "-"


def _parse_stamp(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:32])
    except ValueError:
        return None


def _history_row(raw: Any) -> Optional[Dict[str, Any]]:
    """One dated lesson. Empty days stay out of the ring."""
    if not isinstance(raw, dict):
        return None
    date = str(raw.get("date") or "")[:10]
    if not _valid_day(date):
        return None
    summary = " ".join(str(raw.get("summary_vi") or "").split())[:180]
    lessons = _clean_lessons(raw.get("lessons"), limit=_HISTORY_LESSONS)
    quiet = "chưa có gì mới" in summary and not lessons
    if quiet or (not summary and not lessons):
        return None
    return {"date": date, "summary_vi": summary, "lessons": lessons}


def _clean_history(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    by_date: Dict[str, Dict[str, Any]] = {}
    for item in raw:
        row = _history_row(item)
        if row:
            by_date[row["date"]] = row
    ordered = [by_date[key] for key in sorted(by_date)]
    return ordered[-_HISTORY_DAYS:]


def _merge_history(history: List[Dict[str, Any]], model: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Keep one row per date. A quiet snapshot removes that day instead of filling the ring."""
    date = str(model.get("date") or "")[:10]
    kept = [row for row in _clean_history(history) if row.get("date") != date]
    row = _history_row(model)
    if row:
        kept.append(row)
    kept.sort(key=lambda item: str(item.get("date") or ""))
    return kept[-_HISTORY_DAYS:]


def _clean_lessons(raw: Any, limit: int = _MAX_LESSONS) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen = set()
    for item in raw:
        text = " ".join(str(item or "").split())[:90]
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean_string_list(raw: Any, limit: int = 12) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        text = str(item or "").strip()[:40]
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _clean_micro_topics(raw: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(raw, dict):
        return {}
    cleaned: Dict[str, Dict[str, int]] = {}
    for topic, row in list(raw.items())[:12]:
        key = str(topic or "").strip()[:24]
        if not key or not isinstance(row, dict):
            continue
        helpful = _as_int(row.get("helpful"))
        unhelpful = _as_int(row.get("unhelpful"))
        if helpful or unhelpful:
            cleaned[key] = {"helpful": helpful, "unhelpful": unhelpful}
    return cleaned


def _clean_micro_skills(raw: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(raw, dict):
        return {}
    blocked = _blocked_keys()
    cleaned: Dict[str, Dict[str, int]] = {}
    for key, row in list(raw.items())[:12]:
        action = str(key or "").strip().lower()
        if not action or action in blocked or "winsxs" in action or not isinstance(row, dict):
            continue
        helpful = _as_int(row.get("helpful"))
        unhelpful = _as_int(row.get("unhelpful"))
        if helpful or unhelpful:
            cleaned[action] = {"helpful": helpful, "unhelpful": unhelpful}
    return cleaned


def _clean_micro(raw: Any) -> Dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "helpful": _as_int(row.get("helpful")),
        "unhelpful": _as_int(row.get("unhelpful")),
        "mute": _as_int(row.get("mute")),
        "snooze": _as_int(row.get("snooze")),
        "pin": _as_int(row.get("pin")),
        "focus_end": _as_int(row.get("focus_end")),
        "rough_day": 1 if _as_int(row.get("rough_day")) else 0,
        "topics": _clean_micro_topics(row.get("topics")),
        "skills": _clean_micro_skills(row.get("skills")),
        "lesson_candidates": _clean_lessons(row.get("lesson_candidates"), _MAX_MICRO_LESSONS),
        "seen_mute": _clean_string_list(row.get("seen_mute")),
        "seen_snooze": _clean_string_list(row.get("seen_snooze")),
        "seen_pin": _clean_string_list(row.get("seen_pin")),
    }


def _clean_signal_log(raw: Any) -> List[Dict[str, str]]:
    """Mute rows the diary does not store. One topic per day, so a rebuild cannot stack them."""
    if not isinstance(raw, list):
        return []
    try:
        from core.companion_profile import TOPIC_META
    except Exception:
        TOPIC_META = {}
    out: List[Dict[str, str]] = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "") != "mute":
            continue
        topic = str(item.get("topic") or "").strip()[:24]
        date = str(item.get("date") or "")[:10]
        if topic not in TOPIC_META or len(date) != 10:
            continue
        token = (topic, date)
        if token in seen:
            continue
        seen.add(token)
        out.append({"kind": "mute", "topic": topic, "date": date})
        if len(out) >= _MAX_SIGNAL:
            break
    return out


def _clean_confidence(value: Any) -> float:
    number = _as_float(value, 0.0)
    if number < 0:
        number = 0.0
    if number > 1:
        number = 1.0
    return round(number, 2)


def _clean_signal(value: Any, confidence: float) -> str:
    signal = str(value or "").strip()
    if signal in _SIGNALS:
        return signal
    if confidence < 0.2:
        return "new"
    if confidence < 0.45:
        return "growing"
    if confidence < 0.7:
        return "steady"
    return "familiar"


def _clean_model(raw: Any) -> Dict[str, Any]:
    base = _empty_model()
    if not isinstance(raw, dict):
        return base
    date = str(raw.get("date") or "")[:10]
    if len(date) == 10 and date[4] == "-" and date[7] == "-":
        base["date"] = date
    base["updated_at"] = str(raw.get("updated_at") or "")[:32]
    base["source"] = "local"
    base["topic_scores"] = _clean_scores(raw.get("topic_scores"))
    base["time_weights"] = _clean_weights(raw.get("time_weights"))
    base["time_preference"] = _clean_preference(raw.get("time_preference"))
    base["habit_weights"] = _clean_habits(raw.get("habit_weights"))
    base["skill_candidates"] = _clean_candidates(raw.get("skill_candidates"))
    base["skill_affinity"] = _clean_affinity(raw.get("skill_affinity"))
    base["trust_deltas"] = _clean_deltas(raw.get("trust_deltas"))
    base["trust"] = _clean_trust(raw.get("trust"))
    base["baseline_scores"] = _clean_scores(raw.get("baseline_scores"))
    base["baseline_trust"] = _clean_trust(raw.get("baseline_trust"))
    base["baseline_stats"] = _clean_stats(raw.get("baseline_stats"))
    base["stat_deltas"] = _clean_stat_deltas(raw.get("stat_deltas"))
    base["windows"] = _clean_windows(raw.get("windows"))
    base["rough_days"] = _as_int(raw.get("rough_days"))
    base["focus_sessions"] = _as_int(raw.get("focus_sessions"))
    confidence = _clean_confidence(raw.get("confidence"))
    base["confidence"] = confidence
    base["maturity_signal"] = _clean_signal(raw.get("maturity_signal"), confidence)
    base["lessons"] = _clean_lessons(raw.get("lessons"))
    base["micro"] = _clean_micro(raw.get("micro"))
    base["signal_log"] = _clean_signal_log(raw.get("signal_log"))
    base["summary_vi"] = " ".join(str(raw.get("summary_vi") or "").split())[:180]
    base["yesterday_vi"] = " ".join(str(raw.get("yesterday_vi") or "").split())[:160]
    base["yesterday_topic"] = str(raw.get("yesterday_topic") or "")[:24]
    base["yesterday_lesson"] = " ".join(str(raw.get("yesterday_lesson") or "").split())[:90]
    base["history"] = _clean_history(raw.get("history"))
    rebuilt = _parse_stamp(raw.get("last_rebuild_at"))
    base["last_rebuild_at"] = rebuilt.replace(microsecond=0).isoformat(timespec="seconds") if rebuilt else ""
    base["note_vi"] = _NOTE_VI
    base["version"] = MODEL_VERSION
    return base


def load_daily_model(base_dir: Optional[str] = None) -> Dict[str, Any]:
    path = model_path(base_dir)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return _empty_model()
    return _clean_model(payload)


def _atomic_write(path: str, payload: Dict[str, Any]) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temporary, path)


def save_daily_model(model: Dict[str, Any], base_dir: Optional[str] = None) -> Dict[str, Any]:
    cleaned = _clean_model(model)
    _atomic_write(model_path(base_dir), cleaned)
    return cleaned


def _mentions_muted(text: str, muted: Set[str]) -> bool:
    lowered = str(text or "").lower()
    if not lowered or not muted:
        return False
    for topic in muted:
        key = str(topic or "").strip().lower()
        if key and key in lowered:
            return True
        name = _topic_name(key).lower()
        if name and name in lowered:
            return True
    return False


def _trust_snapshot(base_dir: Optional[str], now: datetime) -> Dict[str, Any]:
    try:
        from core.companion_profile import score_trust
        scored = score_trust(base_dir=base_dir, now=now)
    except Exception:
        scored = {}
    return _clean_trust({
        "level": (scored or {}).get("level"),
        "helpful": (scored or {}).get("accepted"),
        "unhelpful": (scored or {}).get("rejected"),
    })


def _deltas(scores: Dict[str, Dict[str, Any]], baseline: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    topics = set(scores) | set(baseline)
    out: Dict[str, Dict[str, Any]] = {}
    for topic in sorted(topics):
        new = scores.get(topic) or {}
        old = baseline.get(topic) or {}
        new_score = int(new.get("score") or 0)
        old_score = int(old.get("score") or 0)
        level = str(new.get("level") or old.get("level") or "steady")
        out[topic] = {"score": new_score, "delta": new_score - old_score, "level": level}
    return out


def _top_band(weights: Dict[str, int]) -> str:
    if not weights:
        return ""
    return max(weights, key=lambda band: (weights[band], band))


def _normalize_bands(weights: Dict[str, int]) -> Dict[str, int]:
    total = sum(int(value or 0) for value in weights.values())
    if total <= 0:
        return {}
    out: Dict[str, int] = {}
    for band, value in weights.items():
        if band not in _BAND_VI or int(value or 0) <= 0:
            continue
        out[band] = max(1, int(round(100 * int(value) / total)))
    return out


def _topic_band_lesson(topic: str, band: str, count: int) -> str:
    when = _BAND_VI.get(band, "")
    name = _topic_name(topic) or topic
    if not when:
        return name
    hay = "hay " if count >= 2 else ""
    templates = {
        "wifi": f"Wi-Fi {hay}yếu buổi {when}",
        "thermal": f"Nhiệt {hay}lên buổi {when}",
        "ram": f"RAM {hay}cao buổi {when}",
        "disk": f"Dọn máy {hay}vào buổi {when}",
        "focus": f"Trước thi/họp {hay}bật buổi {when}",
    }
    return templates.get(topic) or f"{name} buổi {when}"


def _build_summary(
    scores: Dict[str, Dict[str, Any]],
    weights: Dict[str, Dict[str, int]],
    yesterday_topic: str,
    yesterday_count: int,
    rough_days: int,
    focus_sessions: int,
    deltas: Dict[str, Dict[str, Any]],
) -> str:
    bits: List[str] = []
    if yesterday_topic and yesterday_count:
        name = _topic_name(yesterday_topic) or yesterday_topic
        band = _top_band(weights.get(yesterday_topic) or {})
        if band:
            bits.append(f"{name} hay gặp buổi {_BAND_VI.get(band, band)}")
        else:
            bits.append(name)
    for topic, row in deltas.items():
        if topic == yesterday_topic:
            continue
        try:
            delta = int(row.get("delta") or 0)
        except (TypeError, ValueError):
            delta = 0
        name = _topic_name(topic)
        if not name or abs(delta) < 2:
            continue
        if delta >= 2:
            bits.append(f"{name} bạn thấy có ích hơn")
        else:
            bits.append(f"{name} mình nói nhẹ hơn")
        if len(bits) >= 2:
            break
    if focus_sessions >= 2 and len(bits) < 3:
        bits.append(f"{focus_sessions} lần Trước thi/họp")
    if rough_days and len(bits) < 3:
        bits.append(f"{rough_days} ngày hơi nặng")
    if not bits and scores:
        topic = max(scores, key=lambda key: (int(scores[key].get("score") or 0), int(scores[key].get("diary") or 0), key))
        name = _topic_name(topic)
        if name and (int(scores[topic].get("diary") or 0) or int(scores[topic].get("helpful") or 0)):
            bits.append(name)
    if not bits:
        return "Hôm nay chưa có gì mới để học từ máy này."
    return ("Hôm nay học được: " + "; ".join(bits[:3]) + ".")[:180]


def _feedback_topic(event: Dict[str, Any]) -> str:
    try:
        from core.companion_profile import TOPIC_META
    except Exception:
        return ""
    tags = event.get("tags") if isinstance(event.get("tags"), list) else []
    for tag in tags:
        if str(tag) in TOPIC_META:
            return str(tag)
    return ""


def _event_weight(event: Dict[str, Any]) -> int:
    metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
    return max(1, _as_int(metrics.get("count") or 1))


def _event_in_window(when: datetime, stamp: datetime, days: int) -> bool:
    start = stamp - timedelta(days=days)
    return start <= when <= stamp + timedelta(minutes=1)


def _rolling_window(
    events: List[Dict[str, Any]],
    stamp: datetime,
    days: int,
    signal_log: List[Dict[str, str]],
) -> Dict[str, Any]:
    """One rolling window. Rough days need two stress families, matching the companion flag.

    Focus counts `focus_mode` starts only. Mute comes from `signal_log` (the diary
    does not store im-chủ-đề). Snooze counts `tip_snooze` rows.
    """
    helpful: Dict[str, Dict[str, int]] = {}
    families: Dict[str, Set[str]] = {}
    focus_sessions = 0
    snooze = 0
    for event in events:
        when = _parse_ts(event.get("ts"))
        if when is None or not _event_in_window(when, stamp, days):
            continue
        kind = str(event.get("kind") or "")
        if kind == "focus_mode":
            focus_sessions += 1
        family = _STRESS_FAMILY.get(kind)
        if family:
            families.setdefault(when.strftime("%Y-%m-%d"), set()).add(family)
        if kind == "tip_snooze":
            snooze += 1
        if kind != "user_feedback":
            continue
        topic = _feedback_topic(event)
        if not topic:
            continue
        bucket = helpful.setdefault(topic, {"helpful": 0, "unhelpful": 0})
        outcome = str(event.get("outcome") or "")
        metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
        weight = _event_weight(event)
        if outcome == "accepted" or _as_int(metrics.get("helpful")) > 0:
            bucket["helpful"] += weight
        elif outcome == "rejected":
            bucket["unhelpful"] += weight
    start_day = (stamp - timedelta(days=days)).strftime("%Y-%m-%d")
    end_day = stamp.strftime("%Y-%m-%d")
    mute = 0
    for row in signal_log:
        date = str(row.get("date") or "")
        if start_day < date <= end_day or date == end_day:
            if date >= start_day:
                mute += 1
    rough_days = sum(1 for names in families.values() if len(names) >= 2)
    rate = round(rough_days / float(days), 2) if days else 0.0
    return _clean_window({
        "topic_helpfulness": helpful,
        "rough_days": rough_days,
        "rough_day_rate": rate,
        "focus_sessions": focus_sessions,
        "mute": mute,
        "snooze": snooze,
        "span_days": days,
    }, days)


def _preference_from(weights: Dict[str, Dict[str, int]], habits: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize diary counts, then add habit evidence on that habit's band.

    The result is a 0–100 share, not a second copy of `time_weights`.
    """
    topics: Dict[str, Dict[str, int]] = {}
    global_counts: Dict[str, int] = {}
    for topic, bands in weights.items():
        topics[topic] = dict(bands)
        for band, count in bands.items():
            global_counts[band] = global_counts.get(band, 0) + int(count or 0)
    for habit in habits:
        topic = str(habit.get("topic") or "")
        band = str(habit.get("band") or "")
        if not topic or band not in _BAND_VI:
            continue
        extra = max(1, _as_int(habit.get("weight")))
        bucket = topics.setdefault(topic, {})
        bucket[band] = bucket.get(band, 0) + extra
        global_counts[band] = global_counts.get(band, 0) + extra
    return _clean_preference({
        "global": _normalize_bands(global_counts),
        "topics": {topic: _normalize_bands(bands) for topic, bands in topics.items()},
    })


def _playbook_action(topic: str) -> str:
    try:
        from core.companion_profile import TOPIC_META
        from core.companion_skills import PLAYBOOKS
    except Exception:
        return ""
    issue = str((TOPIC_META.get(topic) or {}).get("issue") or "")
    action = str((PLAYBOOKS.get(issue) or {}).get("action_key") or "")
    if not action or action in _blocked_keys() or "winsxs" in action:
        return ""
    return action


def _affinity_title(action: str, issue: str) -> str:
    try:
        from core.companion_skills import PLAYBOOKS
    except Exception:
        return ""
    book = PLAYBOOKS.get(issue) or {}
    return str(book.get("title") or action)


def _bump_affinity(
    rows: Dict[str, Dict[str, int]],
    action: str,
    *,
    helpful: int = 0,
    unhelpful: int = 0,
    confirmed: int = 0,
    issue: str = "",
) -> None:
    if not action or action in _blocked_keys() or "winsxs" in action:
        return
    bucket = rows.setdefault(action, {"helpful": 0, "unhelpful": 0, "confirmed": 0, "issue_class": issue})
    bucket["helpful"] += helpful
    bucket["unhelpful"] += unhelpful
    bucket["confirmed"] += confirmed
    if issue and not bucket.get("issue_class"):
        bucket["issue_class"] = issue


def _skill_affinity(
    events: List[Dict[str, Any]],
    stamp: datetime,
    base_dir: Optional[str],
) -> Dict[str, Dict[str, Any]]:
    """Actions that worked. Repeated warnings stay in skill_candidates, not here.

    Có ích / Chưa map through the topic playbook. A pin and the last Có ích
    action add a small score. Two repairs add one point each. Blocked keys never enter.
    """
    try:
        from core.companion_profile import TOPIC_META
        from core.companion_skills import PLAYBOOKS
    except Exception:
        TOPIC_META = {}
        PLAYBOOKS = {}
    ok_action = {
        "wifi_repaired": "repair_network_now",
        "ping_repaired": "repair_network_now",
        "ram_optimized": "optimize_ram",
        "clean_light": "clean_light",
        "clean_freed": "clean_light",
    }
    tallies: Dict[str, Dict[str, int]] = {}
    start = stamp - timedelta(days=_WINDOW_LONG)
    for event in events:
        when = _parse_ts(event.get("ts"))
        if when is None or when < start or when > stamp + timedelta(minutes=1):
            continue
        kind = str(event.get("kind") or "")
        if kind == "user_feedback":
            topic = _feedback_topic(event)
            action = _playbook_action(topic)
            issue = str((TOPIC_META.get(topic) or {}).get("issue") or "")
            outcome = str(event.get("outcome") or "")
            metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
            weight = _event_weight(event)
            if outcome == "accepted" or _as_int(metrics.get("helpful")) > 0:
                _bump_affinity(tallies, action, helpful=weight, confirmed=weight, issue=issue)
            elif outcome == "rejected":
                _bump_affinity(tallies, action, unhelpful=weight, confirmed=weight, issue=issue)
            continue
        action = ok_action.get(kind, "")
        if action:
            issue = ""
            for name, book in PLAYBOOKS.items():
                if str(book.get("action_key") or "") == action:
                    issue = name
                    break
            _bump_affinity(tallies, action, helpful=1, issue=issue)
    try:
        from core.companion_maturity import load_state
        state = load_state(base_dir)
    except Exception:
        state = {}
    for pin in state.get("pinned_actions") or []:
        if not isinstance(pin, dict):
            continue
        _bump_affinity(tallies, str(pin.get("action_key") or ""), helpful=2)
    replay = state.get("helpful_replay") if isinstance(state.get("helpful_replay"), dict) else {}
    if replay and not replay.get("surfaced"):
        _bump_affinity(tallies, str(replay.get("action_key") or ""), helpful=2)
    cleaned: Dict[str, Dict[str, Any]] = {}
    for action, row in tallies.items():
        helpful = _as_int(row.get("helpful"))
        unhelpful = _as_int(row.get("unhelpful"))
        issue = str(row.get("issue_class") or "")
        cleaned[action] = {
            "score": helpful - unhelpful,
            "helpful": helpful,
            "unhelpful": unhelpful,
            "confirmed": _as_int(row.get("confirmed")),
            "title_vi": _affinity_title(action, issue),
            "issue_class": issue,
        }
    return _clean_affinity(cleaned)


def _confidence_from(stage_n: int, active_days: int, feedback_n: int) -> tuple:
    """0–1 familiarity from stage, days, and feedback volume. Not a claim of intelligence."""
    stage_part = {0: 0.05, 1: 0.18, 2: 0.38, 3: 0.55}.get(max(0, min(3, stage_n)), 0.05)
    day_part = min(max(0, active_days), 30) / 30.0 * 0.25
    fb_part = min(max(0, feedback_n), 20) / 20.0 * 0.20
    confidence = round(min(1.0, stage_part + day_part + fb_part), 2)
    signal = _clean_signal("", confidence)
    return confidence, signal


def _push_lesson(rows: List[str], text: str) -> None:
    clean = " ".join(str(text or "").split())[:90]
    if clean and clean not in rows and len(rows) < _MAX_LESSONS:
        rows.append(clean)


def _build_lessons(
    weights: Dict[str, Dict[str, int]],
    scores: Dict[str, Dict[str, Any]],
    affinity: Dict[str, Dict[str, Any]],
    windows: Dict[str, Any],
    focus_sessions: int,
    signal_log: Optional[List[Dict[str, str]]] = None,
) -> List[str]:
    lessons: List[str] = []
    ranked = sorted(
        weights.items(),
        key=lambda item: (-sum(item[1].values()), item[0]),
    )
    for topic, bands in ranked:
        band = _top_band(bands)
        count = int(bands.get(band) or 0) if band else 0
        if count <= 0:
            continue
        _push_lesson(lessons, _topic_band_lesson(topic, band, count))
        if len(lessons) >= 2:
            break
    for topic, row in sorted(scores.items(), key=lambda item: (-int(item[1].get("helpful") or 0), item[0])):
        name = _topic_name(topic)
        if not name:
            continue
        helpful = int(row.get("helpful") or 0)
        unhelpful = int(row.get("unhelpful") or 0)
        if helpful >= 3 and helpful > unhelpful:
            _push_lesson(lessons, f"{name} — người dùng thấy có ích")
        elif unhelpful >= 2 and unhelpful > helpful:
            _push_lesson(lessons, f"Nói nhẹ hơn về {name}")
    week = windows.get("7d") if isinstance(windows.get("7d"), dict) else {}
    if _as_int(week.get("mute")) + _as_int(week.get("snooze")) >= 2:
        _push_lesson(lessons, "Người dùng thích gợi ý ngắn")
    elif _as_int(week.get("mute")) >= 1:
        muted_name = ""
        for row in reversed(list(signal_log or [])):
            muted_name = _topic_name(str(row.get("topic") or ""))
            if muted_name:
                break
        if muted_name:
            _push_lesson(lessons, f"Người dùng muốn im {muted_name}")
    if _as_int(week.get("rough_days")) >= 1:
        _push_lesson(lessons, "Có ngày máy hơi nặng — mình nói nhẹ")
    if focus_sessions >= 2:
        _push_lesson(lessons, "Bạn hay tự bật Trước thi/họp")
    best_action = ""
    best_score = 0
    for action, row in affinity.items():
        score = int(row.get("score") or 0)
        if score > best_score and int(row.get("helpful") or 0) > int(row.get("unhelpful") or 0):
            best_score = score
            best_action = action
    if best_action and best_score >= 2:
        title = str((affinity.get(best_action) or {}).get("title_vi") or "").strip()
        if title:
            _push_lesson(lessons, f"Việc «{title}» hay được chọn")
    return _clean_lessons(lessons)


def _stats_snapshot(model: Dict[str, Any]) -> Dict[str, Any]:
    windows = model.get("windows") if isinstance(model.get("windows"), dict) else {}
    week = windows.get("7d") if isinstance(windows.get("7d"), dict) else {}
    return _clean_stats({
        "rough_days": model.get("rough_days"),
        "focus_sessions": model.get("focus_sessions"),
        "confidence": model.get("confidence"),
        "mute_7d": week.get("mute"),
        "snooze_7d": week.get("snooze"),
    })


def _compute(
    stamp: datetime,
    base_dir: Optional[str],
    baseline_scores: Dict[str, Any],
    baseline_trust: Dict[str, Any],
    baseline_stats: Dict[str, Any],
    prior_lessons: List[str],
    prior_yesterday_lesson: str,
    signal_log: List[Dict[str, str]],
) -> Dict[str, Any]:
    from core.companion_diary import read_events
    from core.companion_profile import TOPIC_META, event_topic, load_profile
    from core.companion_skills import BLOCKED_ACTION_KEYS, PLAYBOOKS, count_issue_classes

    profile = load_profile(base_dir)
    events = read_events(base_dir=base_dir, limit=0)
    kept_log = _clean_signal_log(signal_log)
    start = stamp - timedelta(days=_WINDOW_DAYS)
    recent_start = stamp - timedelta(days=_RECENT_DAYS)
    yesterday = (stamp - timedelta(days=1)).strftime("%Y-%m-%d")
    scores: Dict[str, Dict[str, int]] = {}
    weights: Dict[str, Dict[str, int]] = {}
    kind_counts: Dict[str, int] = {}
    yesterday_counts: Dict[str, int] = {}
    rough_by_day: Dict[str, int] = {}
    focus_sessions = 0

    trust_rows = profile.get("topic_trust") if isinstance(profile.get("topic_trust"), dict) else {}
    for topic, row in trust_rows.items():
        key = str(topic or "").strip()
        if key not in TOPIC_META or not isinstance(row, dict):
            continue
        bucket = scores.setdefault(key, {"helpful": 0, "unhelpful": 0, "diary": 0})
        bucket["helpful"] += _as_int(row.get("helpful"))
        bucket["unhelpful"] += _as_int(row.get("unhelpful"))

    for event in events:
        when = _parse_ts(event.get("ts"))
        if when is None or when < start or when > stamp + timedelta(minutes=1):
            continue
        kind = str(event.get("kind") or "")
        topic = event_topic(event)
        if kind == "focus_mode" and when >= recent_start:
            focus_sessions += 1
        if kind in _STRESS_KINDS and when >= recent_start:
            day = when.strftime("%Y-%m-%d")
            rough_by_day[day] = rough_by_day.get(day, 0) + 1
        if kind not in _SKIP_KINDS:
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if not topic or topic not in TOPIC_META:
            continue
        if kind not in _SKIP_KINDS:
            bucket = scores.setdefault(topic, {"helpful": 0, "unhelpful": 0, "diary": 0})
            bucket["diary"] += 1
            band = _band(when.hour)
            topic_bands = weights.setdefault(topic, {})
            topic_bands[band] = topic_bands.get(band, 0) + 1
            if when.strftime("%Y-%m-%d") == yesterday:
                yesterday_counts[topic] = yesterday_counts.get(topic, 0) + 1

    # Older diaries may only have Có ích / Chưa on the event, not in topic_trust.
    for event in events:
        if str(event.get("kind") or "") != "user_feedback":
            continue
        when = _parse_ts(event.get("ts"))
        if when is None or when < start or when > stamp + timedelta(minutes=1):
            continue
        topic = ""
        tags = event.get("tags") if isinstance(event.get("tags"), list) else []
        for tag in tags:
            if str(tag) in TOPIC_META:
                topic = str(tag)
                break
        if not topic or topic in trust_rows:
            continue
        bucket = scores.setdefault(topic, {"helpful": 0, "unhelpful": 0, "diary": 0})
        outcome = str(event.get("outcome") or "")
        metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
        if outcome == "accepted" or _as_int(metrics.get("helpful")) > 0:
            bucket["helpful"] += 1
        elif outcome == "rejected":
            bucket["unhelpful"] += 1

    last_seen: Dict[str, str] = {}
    today_key = stamp.strftime("%Y-%m-%d")
    for event in events:
        when = _parse_ts(event.get("ts"))
        if when is None or when > stamp + timedelta(minutes=1):
            continue
        seen_topic = event_topic(event) or _feedback_topic(event)
        if seen_topic not in TOPIC_META:
            continue
        day = when.strftime("%Y-%m-%d")
        if day > last_seen.get(seen_topic, ""):
            last_seen[seen_topic] = day
    for row in kept_log:
        seen_topic = str(row.get("topic") or "")
        day = str(row.get("date") or "")
        if seen_topic not in TOPIC_META or not _valid_day(day) or day > today_key:
            continue
        if day > last_seen.get(seen_topic, ""):
            last_seen[seen_topic] = day
    for seen_topic, day in last_seen.items():
        if seen_topic in scores:
            scores[seen_topic]["last_signal"] = day

    cleaned_scores = _clean_scores(scores)
    cleaned_weights = _clean_weights(weights)
    trust = _trust_snapshot(base_dir, stamp)
    prior_scores = _clean_scores(baseline_scores)
    prior_trust = _clean_trust(baseline_trust)
    deltas = _deltas(cleaned_scores, prior_scores)
    deltas["global"] = {
        "score": int(trust["helpful"]) - int(trust["unhelpful"]),
        "delta": (int(trust["helpful"]) - int(trust["unhelpful"]))
        - (int(prior_trust["helpful"]) - int(prior_trust["unhelpful"])),
        "level": trust["level"],
    }
    classes = count_issue_classes(kind_counts)
    candidates: List[Dict[str, Any]] = []
    for issue, weight in sorted(classes.items(), key=lambda item: (-item[1], item[0])):
        book = PLAYBOOKS.get(issue) or {}
        action = str(book.get("action_key") or "")
        if action in BLOCKED_ACTION_KEYS:
            continue
        candidates.append({
            "issue_class": issue,
            "weight": int(weight),
            "title_vi": str(book.get("title") or issue),
        })
        if len(candidates) >= 3:
            break
    habits: List[Dict[str, Any]] = []
    for habit in profile.get("habits") or []:
        if not isinstance(habit, dict):
            continue
        habits.append({
            "id": habit.get("id"),
            "topic": habit.get("topic"),
            "weight": habit.get("evidence"),
            "label_vi": habit.get("label_vi"),
            "band": habit.get("band"),
        })
    habits = _clean_habits(sorted(habits, key=lambda item: (-int(item.get("weight") or 0), str(item.get("id") or ""))))
    preference = _preference_from(cleaned_weights, habits)
    windows = {
        "7d": _rolling_window(events, stamp, _WINDOW_SHORT, kept_log),
        "30d": _rolling_window(events, stamp, _WINDOW_LONG, kept_log),
    }
    affinity = _skill_affinity(events, stamp, base_dir)
    stage_n = 0
    active_days = 0
    feedback_n = int(trust["helpful"]) + int(trust["unhelpful"])
    try:
        from core.companion import current_stage
        stage = current_stage(base_dir=base_dir)
        stage_n = int(stage.stage)
        active_days = int(stage.active_days)
        feedback_n = int(stage.positive_feedback) + int(stage.negative_feedback)
    except Exception:
        pass
    confidence, signal = _confidence_from(stage_n, active_days, feedback_n)
    lessons = _build_lessons(
        cleaned_weights,
        cleaned_scores,
        affinity,
        windows,
        focus_sessions,
        kept_log,
    )
    yesterday_topic = ""
    yesterday_count = 0
    if yesterday_counts:
        yesterday_topic = max(yesterday_counts, key=lambda key: (yesterday_counts[key], key))
        yesterday_count = yesterday_counts[yesterday_topic]
    yesterday_lesson = ""
    for text in _clean_lessons(prior_lessons):
        yesterday_lesson = text
        break
    if not yesterday_lesson:
        yesterday_lesson = " ".join(str(prior_yesterday_lesson or "").split())[:90]
    if not yesterday_lesson and yesterday_topic and yesterday_count:
        band = _top_band(cleaned_weights.get(yesterday_topic) or {})
        yesterday_lesson = _topic_band_lesson(yesterday_topic, band, yesterday_count)
    rough_days = sum(1 for count in rough_by_day.values() if count >= 2)
    summary = _build_summary(
        cleaned_scores,
        cleaned_weights,
        yesterday_topic,
        yesterday_count,
        rough_days,
        focus_sessions,
        deltas,
    )
    yesterday_vi = ""
    if yesterday_lesson:
        yesterday_vi = f"Hôm qua mình học từ máy này: {yesterday_lesson.rstrip('.')}."
    elif yesterday_topic and yesterday_count:
        name = _topic_name(yesterday_topic) or yesterday_topic
        yesterday_vi = f"Hôm qua mình học từ máy này: {name}."
    prior = _clean_stats(baseline_stats)
    week = windows["7d"]
    stat_deltas = _clean_stat_deltas({
        "rough_days": rough_days - int(prior["rough_days"]),
        "focus_sessions": focus_sessions - int(prior["focus_sessions"]),
        "confidence": round(confidence - float(prior["confidence"]), 2),
        "mute_7d": int(week["mute"]) - int(prior["mute_7d"]),
        "snooze_7d": int(week["snooze"]) - int(prior["snooze_7d"]),
    })
    return _clean_model({
        "version": MODEL_VERSION,
        "date": stamp.strftime("%Y-%m-%d"),
        "updated_at": stamp.replace(microsecond=0).isoformat(timespec="seconds"),
        "source": "local",
        "topic_scores": cleaned_scores,
        "time_weights": cleaned_weights,
        "time_preference": preference,
        "habit_weights": habits,
        "skill_candidates": candidates,
        "skill_affinity": affinity,
        "trust_deltas": deltas,
        "trust": trust,
        "baseline_scores": prior_scores,
        "baseline_trust": prior_trust,
        "baseline_stats": prior,
        "stat_deltas": stat_deltas,
        "windows": windows,
        "rough_days": rough_days,
        "focus_sessions": focus_sessions,
        "confidence": confidence,
        "maturity_signal": signal,
        "lessons": lessons,
        "micro": _empty_micro(),
        "signal_log": kept_log,
        "summary_vi": summary,
        "yesterday_vi": yesterday_vi,
        "yesterday_topic": yesterday_topic,
        "yesterday_lesson": yesterday_lesson,
        "note_vi": _NOTE_VI,
    })


def update_daily_model(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Recompute today's snapshot. The same calendar day is not counted twice.

    A forced rebuild the same day still uses yesterday's baselines, keeps the
    mute log, and clears `micro` because the diary is now the source of truth.
    """
    global _IN_REBUILD
    stamp = now or datetime.now()
    today = stamp.strftime("%Y-%m-%d")
    current = load_daily_model(base_dir)
    if current.get("date") == today and not force:
        return current
    history = _clean_history(current.get("history"))
    if current.get("date") and current.get("date") != today:
        history = _merge_history(history, current)
        baseline_scores = current.get("topic_scores") or {}
        baseline_trust = current.get("trust") or {}
        baseline_stats = _stats_snapshot(current)
        prior_lessons = list(current.get("lessons") or [])
        prior_yesterday_lesson = ""
    elif current.get("date") == today:
        baseline_scores = current.get("baseline_scores") or {}
        baseline_trust = current.get("baseline_trust") or {}
        baseline_stats = current.get("baseline_stats") or {}
        prior_lessons = []
        prior_yesterday_lesson = str(current.get("yesterday_lesson") or "")
    else:
        baseline_scores = {}
        baseline_trust = {}
        baseline_stats = {}
        prior_lessons = []
        prior_yesterday_lesson = ""
    _IN_REBUILD = True
    try:
        built = _compute(
            stamp,
            base_dir,
            baseline_scores,
            baseline_trust,
            baseline_stats,
            prior_lessons,
            prior_yesterday_lesson,
            list(current.get("signal_log") or []),
        )
    finally:
        _IN_REBUILD = False
    built["history"] = _merge_history(history, built)
    built["last_rebuild_at"] = stamp.replace(microsecond=0).isoformat(timespec="seconds")
    saved = save_daily_model(built, base_dir=base_dir)
    try:
        refresh_learned_skill_offer(now=stamp, base_dir=base_dir)
    except Exception:
        pass
    return saved


def ensure_daily_model(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """First open of the local day. Later calls reuse the file."""
    if config_manager is not None:
        try:
            from core.companion import is_enabled
            if not is_enabled(config_manager):
                return load_daily_model(base_dir)
        except Exception:
            pass
    return update_daily_model(now=now, base_dir=base_dir, force=False)


def rebuild_on_cooldown(model: Optional[Dict[str, Any]] = None, *, now: Optional[datetime] = None) -> bool:
    """True only when today's snapshot was fully rebuilt moments ago."""
    payload = _clean_model(model) if isinstance(model, dict) else {}
    stamp = now or datetime.now()
    if str(payload.get("date") or "") != stamp.strftime("%Y-%m-%d"):
        return False
    previous = _parse_stamp(payload.get("last_rebuild_at"))
    if previous is None:
        return False
    elapsed = (stamp - previous).total_seconds()
    return 0 <= elapsed < REBUILD_COOLDOWN_SEC


def request_rebuild_today(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Dict[str, Any]:
    """Force today's full rebuild from diary, profile, and feedback.

    The same calendar day still uses yesterday's baselines, so a rebuild
    replaces today's snapshot and does not invent a second day's counts.
    A click inside the cooldown is a no-op. The next day is not blocked.
    This does not run an action and does not turn Trước thi/họp on.
    """
    del config_manager
    stamp = now or datetime.now()
    current = load_daily_model(base_dir)
    if rebuild_on_cooldown(current, now=stamp):
        return {"rebuilt": False, "model": current, "message_vi": _REBUILD_SOON_VI}
    model = update_daily_model(now=stamp, base_dir=base_dir, force=True)
    return {"rebuilt": True, "model": model, "message_vi": _REBUILD_DONE_VI}


def _append_lesson(micro: Dict[str, Any], text: str) -> None:
    rows = list(micro.get("lesson_candidates") or [])
    clean = " ".join(str(text or "").split())[:90]
    if not clean or clean in rows or len(rows) >= _MAX_MICRO_LESSONS:
        return
    rows.append(clean)
    micro["lesson_candidates"] = rows


def apply_micro_update(
    kind: str,
    *,
    helpful: Optional[bool] = None,
    topic: str = "",
    action_key: str = "",
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    lesson_vi: str = "",
) -> Dict[str, Any]:
    """Same-day overlay. Does not rewrite snapshot scores, windows, or deltas.

    If today's snapshot does not exist yet, the full rebuild runs instead and
    this event is left to the diary (or the mute log). That avoids counting it
    once in the snapshot and again in `micro`.
    """
    if _IN_REBUILD:
        return load_daily_model(base_dir)
    stamp = now or datetime.now()
    today = stamp.strftime("%Y-%m-%d")
    kind_key = str(kind or "").strip().lower()
    if kind_key not in ("feedback", "mute", "snooze", "pin", "focus_end", "rough_day"):
        return load_daily_model(base_dir)
    current = load_daily_model(base_dir)
    topic_key = str(topic or "").strip()[:24]
    action = str(action_key or "").strip().lower()
    if action in _blocked_keys() or "winsxs" in action:
        action = ""
    if kind_key == "mute" and topic_key:
        log = list(current.get("signal_log") or [])
        log.append({"kind": "mute", "topic": topic_key, "date": today})
        current["signal_log"] = _clean_signal_log(log)
        current = save_daily_model(current, base_dir=base_dir)
    if str(current.get("date") or "") != today:
        return update_daily_model(now=stamp, base_dir=base_dir, force=False)
    micro = _clean_micro(current.get("micro"))
    if kind_key == "rough_day" and micro.get("rough_day"):
        return current
    name = _topic_name(topic_key) or topic_key
    if kind_key == "feedback":
        topics = dict(micro.get("topics") or {})
        bucket = dict(topics.get(topic_key) or {"helpful": 0, "unhelpful": 0}) if topic_key else {"helpful": 0, "unhelpful": 0}
        if helpful:
            micro["helpful"] = int(micro.get("helpful") or 0) + 1
            if topic_key:
                bucket["helpful"] = int(bucket.get("helpful") or 0) + 1
            if action:
                skills = dict(micro.get("skills") or {})
                row = dict(skills.get(action) or {"helpful": 0, "unhelpful": 0})
                row["helpful"] = int(row.get("helpful") or 0) + 1
                skills[action] = row
                micro["skills"] = skills
            if name:
                _append_lesson(micro, lesson_vi or f"{name} — người dùng thấy có ích")
        else:
            micro["unhelpful"] = int(micro.get("unhelpful") or 0) + 1
            if topic_key:
                bucket["unhelpful"] = int(bucket.get("unhelpful") or 0) + 1
            if action:
                skills = dict(micro.get("skills") or {})
                row = dict(skills.get(action) or {"helpful": 0, "unhelpful": 0})
                row["unhelpful"] = int(row.get("unhelpful") or 0) + 1
                skills[action] = row
                micro["skills"] = skills
            if name:
                _append_lesson(micro, lesson_vi or f"Nói nhẹ hơn về {name}")
        if topic_key:
            topics[topic_key] = bucket
            micro["topics"] = topics
    elif kind_key == "mute" and topic_key:
        seen = list(micro.get("seen_mute") or [])
        if topic_key not in seen:
            seen.append(topic_key)
            micro["seen_mute"] = seen
            micro["mute"] = int(micro.get("mute") or 0) + 1
            if name:
                _append_lesson(micro, lesson_vi or f"Người dùng muốn im {name}")
    elif kind_key == "snooze" and topic_key:
        seen = list(micro.get("seen_snooze") or [])
        if topic_key not in seen:
            seen.append(topic_key)
            micro["seen_snooze"] = seen
            micro["snooze"] = int(micro.get("snooze") or 0) + 1
            if name:
                _append_lesson(micro, lesson_vi or f"Người dùng muốn nhắc {name} thưa hơn")
    elif kind_key == "pin" and action:
        seen = list(micro.get("seen_pin") or [])
        if action not in seen:
            seen.append(action)
            micro["seen_pin"] = seen
            micro["pin"] = int(micro.get("pin") or 0) + 1
            skills = dict(micro.get("skills") or {})
            row = dict(skills.get(action) or {"helpful": 0, "unhelpful": 0})
            row["helpful"] = int(row.get("helpful") or 0) + 1
            skills[action] = row
            micro["skills"] = skills
            _append_lesson(micro, lesson_vi or "Người dùng ghim một việc hay dùng")
    elif kind_key == "focus_end":
        micro["focus_end"] = int(micro.get("focus_end") or 0) + 1
        _append_lesson(micro, lesson_vi or "Vừa kết thúc Trước thi/họp — mình không tự bật lại")
    elif kind_key == "rough_day":
        micro["rough_day"] = 1
        _append_lesson(micro, lesson_vi or "Hôm nay máy hơi nặng — mình nói nhẹ")
    current["micro"] = micro
    current["updated_at"] = stamp.replace(microsecond=0).isoformat(timespec="seconds")
    saved = save_daily_model(current, base_dir=base_dir)
    if kind_key in ("feedback", "mute"):
        try:
            refresh_learned_skill_offer(now=stamp, base_dir=base_dir)
        except Exception:
            pass
    return saved


def learn_status_vi(model: Optional[Dict[str, Any]] = None, *, now: Optional[datetime] = None, base_dir: Optional[str] = None) -> str:
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    date = str(payload.get("date") or "")
    if len(date) != 10:
        return ""
    shown = date[8:10] + "/" + date[5:7]
    summary = str(payload.get("summary_vi") or "")
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    if "chưa có gì mới" in summary:
        lead = f"Hôm nay đã mở sổ trên máy này ({shown}) — chưa có gì mới để học."
    elif date == today:
        lead = f"Hôm nay đã học từ máy này ({shown})."
    else:
        lead = f"Lần học gần nhất: {shown}."
    return lead + " Trí nhớ local, không phải AGI."


def current_lessons(model: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None, limit: int = 3) -> List[str]:
    """Snapshot lessons plus today's micro candidates. Micro is listed first so a new Có ích shows up."""
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    micro = payload.get("micro") if isinstance(payload.get("micro"), dict) else {}
    merged: List[str] = []
    for text in list(micro.get("lesson_candidates") or []) + list(payload.get("lessons") or []):
        clean = " ".join(str(text or "").split())
        if clean and clean not in merged:
            merged.append(clean)
        if len(merged) >= max(1, int(limit)):
            break
    return merged


def _trust_bar_line(model: Dict[str, Any]) -> str:
    scores = model.get("topic_scores") if isinstance(model.get("topic_scores"), dict) else {}
    micro = model.get("micro") if isinstance(model.get("micro"), dict) else {}
    topics = micro.get("topics") if isinstance(micro.get("topics"), dict) else {}
    ranked = []
    for topic, row in scores.items():
        extra = topics.get(topic) if isinstance(topics.get(topic), dict) else {}
        score = int(row.get("score") or 0) + int(extra.get("helpful") or 0) - int(extra.get("unhelpful") or 0)
        ranked.append((score, str(topic), row))
    for topic, extra in topics.items():
        if topic in scores or not isinstance(extra, dict):
            continue
        score = int(extra.get("helpful") or 0) - int(extra.get("unhelpful") or 0)
        ranked.append((score, str(topic), {}))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    bits = []
    for score, topic, _row in ranked[:3]:
        name = _topic_name(topic) or topic
        cells = max(0, min(6, 3 + int(score)))
        bits.append(f"{name} {'█' * cells}{'░' * (6 - cells)}")
    return " · ".join(bits)


def _feedback_volume(model: Dict[str, Any]) -> int:
    trust = model.get("trust") if isinstance(model.get("trust"), dict) else {}
    return _as_int(trust.get("helpful")) + _as_int(trust.get("unhelpful"))


def sparse_warning_vi(model: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None) -> str:
    """One quiet line when Có ích/Chưa is still thin. Not a morning or insight sentence."""
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    if not _valid_day(str(payload.get("date") or "")):
        return ""
    if _feedback_volume(payload) >= SPARSE_FEEDBACK_MIN:
        return ""
    return _SPARSE_VI


def format_history_vi(model: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None) -> str:
    """Newest-first lesson ring. Uses a middle dot so it is not a lesson bullet."""
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    rows = _clean_history(payload.get("history"))
    if not rows:
        return ""
    lines = ["Bảy ngày gần đây:"]
    for row in reversed(rows):
        date = str(row.get("date") or "")
        shown = date[8:10] + "/" + date[5:7]
        summary = str(row.get("summary_vi") or "").replace("•", "·")
        if not summary:
            summary = "; ".join(row.get("lessons") or []).replace("•", "·")
        lines.append(f"{shown} · {summary}")
    return "\n".join(lines)


def format_model_panel_vi(model: Optional[Dict[str, Any]] = None, *, base_dir: Optional[str] = None) -> str:
    """Short honest panel: date, lessons, 7-day history, topic bars. Not an AGI readout.

    The sparse-data line is shown here at most once. It is not copied into
    the morning line, the weekly line, or insight text.
    """
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    date = str(payload.get("date") or "")
    if len(date) != 10:
        return "Chưa có mô hình học cho hôm nay.\n" + _HONEST_PANEL_VI
    shown = date[8:10] + "/" + date[5:7]
    version = int(payload.get("version") or MODEL_VERSION)
    lines = [f"Mô hình học v{version} · lần học {shown}"]
    lessons = current_lessons(payload, limit=3)
    if lessons:
        lines.extend(f"• {item}" for item in lessons)
    else:
        lines.append("• Chưa có bài học ngắn mới.")
    bars = _trust_bar_line(payload)
    if bars:
        lines.append(bars)
    signal = _SIGNAL_VI.get(str(payload.get("maturity_signal") or ""), "")
    if signal:
        lines.append(f"Độ chín của trí nhớ: {signal}.")
    history = format_history_vi(payload)
    if history:
        lines.append(history)
    warning = sparse_warning_vi(payload)
    if warning:
        lines.append(warning)
    lines.append(_HONEST_PANEL_VI)
    return "\n".join(lines)


def morning_learn_clause(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    hidden: Optional[Set[str]] = None,
) -> str:
    """One calm sentence for the morning line. Cites yesterday's concrete lesson when it has one."""
    model = load_daily_model(base_dir)
    stamp = now or datetime.now()
    if str(model.get("date") or "") != stamp.strftime("%Y-%m-%d"):
        return ""
    lesson = str(model.get("yesterday_lesson") or "").strip()
    text = str(model.get("yesterday_vi") or "").strip()
    if lesson:
        body = lesson if lesson.endswith(".") else lesson + "."
        if "Hôm qua" not in body:
            body = f"Hôm qua mình học từ máy này: {body}"
        text = body
    topic = str(model.get("yesterday_topic") or "")
    blocked = set(hidden or [])
    if not text or topic in blocked or _mentions_muted(text, blocked):
        return ""
    # History and the sparse-data line stay on the model panel. An empty or
    # thin snapshot must not grow a second morning sentence.
    if "chưa có gì mới" in text or "Cần thêm phản hồi" in text:
        return ""
    return text


def weekly_learn_line(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    muted: Optional[Set[str]] = None,
) -> str:
    model = load_daily_model(base_dir)
    text = str(model.get("summary_vi") or "").strip()
    if not text or "chưa có gì mới" in text or "Cần thêm phản hồi" in text:
        return ""
    date = str(model.get("date") or "")
    stamp = now or datetime.now()
    if len(date) == 10:
        try:
            learned = datetime.fromisoformat(date)
        except ValueError:
            learned = None
        if learned is not None and (stamp.date() - learned.date()).days > 7:
            return ""
    if _mentions_muted(text, set(muted or [])):
        return ""
    if not text.endswith("."):
        text += "."
    return text


def prompt_learn_line(*, now: Optional[datetime] = None, base_dir: Optional[str] = None) -> str:
    text = weekly_learn_line(now=now, base_dir=base_dir, muted=set())
    if not text:
        return ""
    return "Đã học từ máy này: " + text


def voice_tone_kwargs(base_dir: Optional[str] = None) -> Dict[str, Any]:
    """Pass into stage_voice. Empty until this PC has a snapshot.

    confidence colors tone only. It does not change boldness, action caps,
    or may_propose. Callers still apply quiet hours, mute, focus, and rough day.
    """
    model = load_daily_model(base_dir)
    if not model.get("date"):
        return {}
    return {
        "confidence": model.get("confidence"),
        "maturity_signal": str(model.get("maturity_signal") or ""),
    }


def _decay_steps(idle_days: int) -> int:
    """One ranking point per quiet stretch after the grace window. History is untouched."""
    if idle_days <= DECAY_GRACE_DAYS:
        return 0
    return (idle_days - DECAY_GRACE_DAYS) // DECAY_STEP_DAYS


def _apply_decay(score: int, idle_days: int) -> int:
    steps = _decay_steps(idle_days)
    if steps <= 0 or score == 0:
        return score
    if score > 0:
        return max(0, score - steps)
    return min(0, score + steps)


def _micro_topic(topic: str, model: Dict[str, Any]) -> Dict[str, int]:
    micro = model.get("micro") if isinstance(model.get("micro"), dict) else {}
    topics = micro.get("topics") if isinstance(micro.get("topics"), dict) else {}
    extra = topics.get(topic) if isinstance(topics.get(topic), dict) else {}
    return extra if isinstance(extra, dict) else {}


def _last_signal_day(topic: str, model: Dict[str, Any]) -> str:
    """Newest diary/feedback day. Today's micro counts as the snapshot date."""
    extra = _micro_topic(topic, model)
    if int(extra.get("helpful") or 0) or int(extra.get("unhelpful") or 0):
        date = str(model.get("date") or "")
        if _valid_day(date):
            return date
    scores = model.get("topic_scores") if isinstance(model.get("topic_scores"), dict) else {}
    row = scores.get(topic) if isinstance(scores.get(topic), dict) else {}
    last = str(row.get("last_signal") or "") if isinstance(row, dict) else ""
    return last if _valid_day(last) else ""


def _idle_days(last_day: str, now: datetime) -> int:
    if not _valid_day(last_day):
        return 0
    try:
        then = datetime.fromisoformat(last_day)
    except ValueError:
        return 0
    return max(0, (now.date() - then.date()).days)


def _raw_topic_score(topic: str, model: Dict[str, Any]) -> int:
    """Lifetime snapshot plus today's micro, before decay."""
    scores = model.get("topic_scores") if isinstance(model.get("topic_scores"), dict) else {}
    row = scores.get(topic) if isinstance(scores.get(topic), dict) else {}
    score = int(row.get("score") or 0) if isinstance(row, dict) else 0
    extra = _micro_topic(topic, model)
    score += int(extra.get("helpful") or 0) - int(extra.get("unhelpful") or 0)
    return score


def _effective_topic_score(topic: str, model: Dict[str, Any], now: Optional[datetime] = None) -> int:
    """Ranking weight. Decay fades stale weight and does not rewrite the file."""
    score = _raw_topic_score(topic, model)
    stamp = now or datetime.now()
    return _apply_decay(score, _idle_days(_last_signal_day(topic, model), stamp))


def effective_topic_score(
    topic: str,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    model: Optional[Dict[str, Any]] = None,
) -> int:
    """Decayed ranking weight for one topic. Stored counts stay as they are."""
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    return _effective_topic_score(str(topic or ""), payload, now=now or datetime.now())


def _topic_is_weak(topic: str, model: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Quiet a topic the user keeps marking Chưa. Windows are not dropped here."""
    if not topic:
        return False
    score = _effective_topic_score(topic, model, now=now)
    scores = model.get("topic_scores") if isinstance(model.get("topic_scores"), dict) else {}
    row = scores.get(topic) if isinstance(scores.get(topic), dict) else {}
    level = str(row.get("level") or "") if isinstance(row, dict) else ""
    windows = model.get("windows") if isinstance(model.get("windows"), dict) else {}
    week = windows.get("7d") if isinstance(windows.get("7d"), dict) else {}
    recent = (week.get("topic_helpfulness") or {}).get(topic) if isinstance(week.get("topic_helpfulness"), dict) else {}
    recent = recent if isinstance(recent, dict) else {}
    recent_bad = int(recent.get("unhelpful") or 0) >= 2 and int(recent.get("unhelpful") or 0) > int(recent.get("helpful") or 0)
    if score <= -2:
        return True
    if level == "low" and score < 0:
        return True
    if recent_bad and score <= 0:
        return True
    return False


def _band_bonus(topic: str, model: Dict[str, Any], band: str) -> int:
    """One point when this hour is the topic's favorite band. A tie-break, not a mute override."""
    pref = model.get("time_preference") if isinstance(model.get("time_preference"), dict) else {}
    topics = pref.get("topics") if isinstance(pref.get("topics"), dict) else {}
    bands = topics.get(topic) if isinstance(topics.get(topic), dict) else {}
    if not isinstance(bands, dict) or not bands:
        return 0
    best = _top_band({key: int(value or 0) for key, value in bands.items()})
    if best == band and int(bands.get(best) or 0) >= 50:
        return 1
    return 0


def prefer_learned_topics(
    items: List[Dict[str, Any]],
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Keep window insights in place. Prefer a topic this PC already found useful.

    Weak topics (Chưa-heavy snapshot or a bad 7-day window) drop out when another
    line remains. A stale topic loses ranking weight without losing its counts.
    Today's micro Có ích/Chưa counts here and is not part of the stored lifetime
    score, so the next rebuild does not add it twice.
    """
    model = load_daily_model(base_dir)
    scores = model.get("topic_scores") if isinstance(model.get("topic_scores"), dict) else {}
    if not model.get("date") or not scores:
        return list(items)
    stamp = now or datetime.now()
    band = _band(stamp.hour)
    weak_ids = set()
    for item in items:
        if str((item or {}).get("id") or "").startswith("window:"):
            continue
        if _topic_is_weak(str((item or {}).get("topic") or ""), model, now=stamp):
            weak_ids.add(id(item))
    strong = [item for item in items if id(item) not in weak_ids]
    pool = strong if strong else list(items)

    def sort_key(pair):
        index, item = pair
        topic = str((item or {}).get("topic") or "")
        is_window = str((item or {}).get("id") or "").startswith("window:")
        score = _effective_topic_score(topic, model, now=stamp) + _band_bonus(topic, model, band)
        if is_window:
            return (0, index)
        return (1, -score, index)

    return [item for _, item in sorted(enumerate(pool), key=sort_key)]


def _safe_allowlisted(action_key: str) -> str:
    key = str(action_key or "").strip()
    if not key or key in _blocked_keys() or "winsxs" in key.lower():
        return ""
    try:
        from core.companion_moment import INSIGHT_ACTION_ALLOWLIST, SKILL_ACTION_TO_INSIGHT
    except Exception:
        return ""
    mapped = SKILL_ACTION_TO_INSIGHT.get(key, key if key in INSIGHT_ACTION_ALLOWLIST else "")
    if not mapped or mapped in _blocked_keys() or mapped not in INSIGHT_ACTION_ALLOWLIST:
        return ""
    return mapped


def _action_matches_topic(action_key: str, topic: str) -> bool:
    if not topic:
        return True
    try:
        from core.companion_moment import INSIGHT_ACTION_ALLOWLIST
    except Exception:
        return False
    spec = INSIGHT_ACTION_ALLOWLIST.get(action_key) or {}
    topics = spec.get("topics") or frozenset()
    if not topics:
        return True
    return topic in topics


def rank_propose_key(
    topic: str,
    *,
    base_dir: Optional[str] = None,
    fallback: str = "",
    now: Optional[datetime] = None,
) -> str:
    """One allowlisted key: last Có ích, then a pin, then skill affinity, then fallback.

    Affinity only wins when the user marked that action Có ích (helpful > unhelpful).
    Repeated warnings do not replace the topic's existing button. Nothing here runs
    the action or turns Trước thi / họp on. Stage and consent are still checked later.
    """
    del now  # ranking uses stored stamps, not the clock, except via the caller's gates
    topic_key = str(topic or "").strip()
    safe_fallback = _safe_allowlisted(fallback)
    if safe_fallback and topic_key and not _action_matches_topic(safe_fallback, topic_key):
        safe_fallback = ""
    best = ""
    best_rank = 0
    try:
        from core.companion_maturity import load_state
        state = load_state(base_dir)
    except Exception:
        state = {}
    replay = state.get("helpful_replay") if isinstance(state.get("helpful_replay"), dict) else {}
    replay_key = _safe_allowlisted(str((replay or {}).get("action_key") or ""))
    replay_topic = str((replay or {}).get("topic") or "")
    if replay_key and (not topic_key or replay_topic == topic_key or _action_matches_topic(replay_key, topic_key)):
        if not topic_key or _action_matches_topic(replay_key, topic_key):
            best, best_rank = replay_key, 3
    if best_rank < 2:
        try:
            from core.companion_moment import list_pinned_actions
            pins = list_pinned_actions(base_dir)
        except Exception:
            pins = []
        for pin in pins:
            key = _safe_allowlisted(str((pin or {}).get("action_key") or ""))
            if not key or (topic_key and not _action_matches_topic(key, topic_key)):
                continue
            best, best_rank = key, 2
            break
    model = load_daily_model(base_dir)
    if best_rank < 1 and model.get("date"):
        combined: Dict[str, Dict[str, int]] = {}
        affinity = model.get("skill_affinity") if isinstance(model.get("skill_affinity"), dict) else {}
        for key, row in affinity.items():
            if not isinstance(row, dict):
                continue
            combined[str(key)] = {
                "helpful": _as_int(row.get("helpful")),
                "unhelpful": _as_int(row.get("unhelpful")),
                "confirmed": _as_int(row.get("confirmed")),
            }
        micro = model.get("micro") if isinstance(model.get("micro"), dict) else {}
        skills = micro.get("skills") if isinstance(micro.get("skills"), dict) else {}
        # Feedback micro is a Có ích/Chưa. Pin micro also lands here, but a pin
        # already won above when it matches the topic.
        for key, row in skills.items():
            if not isinstance(row, dict):
                continue
            bucket = combined.setdefault(str(key), {"helpful": 0, "unhelpful": 0, "confirmed": 0})
            added_help = _as_int(row.get("helpful"))
            added_no = _as_int(row.get("unhelpful"))
            bucket["helpful"] += added_help
            bucket["unhelpful"] += added_no
            if added_help or added_no:
                bucket["confirmed"] += added_help + added_no
        winner = ""
        winner_score = 0
        for key, row in combined.items():
            safe = _safe_allowlisted(key)
            if not safe or (topic_key and not _action_matches_topic(safe, topic_key)):
                continue
            helpful = int(row.get("helpful") or 0)
            unhelpful = int(row.get("unhelpful") or 0)
            confirmed = int(row.get("confirmed") or 0)
            if confirmed < 1 or helpful <= unhelpful:
                continue
            score = helpful - unhelpful
            if score > winner_score:
                winner, winner_score = safe, score
        if winner:
            best, best_rank = winner, 1
    if best:
        return best
    return safe_fallback


def topic_is_quiet(
    topic: str,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    model: Optional[Dict[str, Any]] = None,
) -> bool:
    """True when repeated Chưa should keep this topic out of the next suggestion."""
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    if not payload.get("date"):
        return False
    return _topic_is_weak(str(topic or ""), payload, now=now or datetime.now())


def rank_topic_keys(
    topics: List[str],
    *,
    counts: Optional[Dict[str, int]] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[str]:
    """Order topics for the next sentence. Higher decayed trust first.

    Without a snapshot this matches the old tie-break: more diary hits, then
    the later name. A Chưa-heavy topic drops only when another topic remains.
    """
    keys: List[str] = []
    seen = set()
    for topic in topics or []:
        key = str(topic or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    if not keys:
        return []
    stamp = now or datetime.now()
    tally = counts if isinstance(counts, dict) else {}
    model = load_daily_model(base_dir)
    micro = model.get("micro") if isinstance(model.get("micro"), dict) else {}
    micro_topics = micro.get("topics") if isinstance(micro.get("topics"), dict) else {}
    if not model.get("date") or not (model.get("topic_scores") or micro_topics):
        return sorted(keys, key=lambda key: (int(tally.get(key) or 0), key), reverse=True)
    strong = [key for key in keys if not _topic_is_weak(key, model, now=stamp)]
    pool = strong or list(keys)

    def sort_key(key: str):
        return (
            _effective_topic_score(key, model, now=stamp),
            int(tally.get(key) or 0),
            key,
        )

    return sorted(pool, key=sort_key, reverse=True)


def _lesson_mentions(topic: str, lessons: List[str]) -> bool:
    name = _topic_name(topic).lower()
    key = str(topic or "").strip().lower()
    for text in lessons:
        lowered = str(text or "").lower()
        if name and name in lowered:
            return True
        if key and key in lowered:
            return True
    return False


def explain_suggestion_vi(
    topic: str,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    model: Optional[Dict[str, Any]] = None,
) -> str:
    """One calm reason. Empty when this PC has nothing local to cite.

    Order: today's lesson, yesterday's lesson for this topic, then Có ích / Chưa
    counts. The sparse-data warning is not a reason to speak.
    """
    del now
    key = str(topic or "").strip()
    if not key:
        return ""
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    if not _valid_day(str(payload.get("date") or "")):
        return ""
    name = _topic_name(key) or key
    for text in current_lessons(payload, limit=5):
        if "Cần thêm phản hồi" in text:
            continue
        if _lesson_mentions(key, [text]):
            body = text.rstrip(".")
            return f"Vì sao nhắc? {body}."
    if str(payload.get("yesterday_topic") or "") == key:
        lesson = str(payload.get("yesterday_lesson") or "").strip().rstrip(".")
        if lesson:
            return f"Vì sao nhắc? {lesson}."
    scores = payload.get("topic_scores") if isinstance(payload.get("topic_scores"), dict) else {}
    row = scores.get(key) if isinstance(scores.get(key), dict) else {}
    extra = _micro_topic(key, payload)
    helpful = int(row.get("helpful") or 0) + int(extra.get("helpful") or 0)
    unhelpful = int(row.get("unhelpful") or 0) + int(extra.get("unhelpful") or 0)
    diary = int(row.get("diary") or 0)
    if helpful >= 1 and helpful > unhelpful:
        return f"Vì sao nhắc? {name}: bạn đánh Có ích {helpful} lần trên máy này."
    if unhelpful >= 2 and unhelpful > helpful:
        return f"Vì sao nhắc? {name}: vài lần Chưa — mình nói nhẹ."
    if diary >= 1:
        return f"Vì sao nhắc? {name} có trong nhật ký máy này."
    return ""


def _topic_feedback_counts(topic: str, model: Dict[str, Any]) -> Dict[str, int]:
    scores = model.get("topic_scores") if isinstance(model.get("topic_scores"), dict) else {}
    row = scores.get(topic) if isinstance(scores.get(topic), dict) else {}
    extra = _micro_topic(topic, model)
    return {
        "helpful": int(row.get("helpful") or 0) + int(extra.get("helpful") or 0),
        "unhelpful": int(row.get("unhelpful") or 0) + int(extra.get("unhelpful") or 0),
    }


def _combined_action_feedback(model: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Có ích / Chưa per action. Pins and repairs are not counted as Có ích."""
    affinity = model.get("skill_affinity") if isinstance(model.get("skill_affinity"), dict) else {}
    micro = model.get("micro") if isinstance(model.get("micro"), dict) else {}
    skills = micro.get("skills") if isinstance(micro.get("skills"), dict) else {}
    seen_pin = set(str(item) for item in (micro.get("seen_pin") or []))
    combined: Dict[str, Dict[str, Any]] = {}
    for key in set(affinity) | set(skills):
        row = affinity.get(key) if isinstance(affinity.get(key), dict) else {}
        micro_row = skills.get(key) if isinstance(skills.get(key), dict) else {}
        confirmed = _as_int(row.get("confirmed"))
        feedback_helpful = min(_as_int(row.get("helpful")), confirmed)
        feedback_unhelpful = min(_as_int(row.get("unhelpful")), max(0, confirmed - feedback_helpful))
        micro_helpful = _as_int(micro_row.get("helpful"))
        if str(key) in seen_pin:
            micro_helpful = max(0, micro_helpful - 1)
        combined[str(key)] = {
            "helpful": feedback_helpful + micro_helpful,
            "unhelpful": feedback_unhelpful + _as_int(micro_row.get("unhelpful")),
            "issue_class": str(row.get("issue_class") or ""),
        }
    return combined


def learned_one_tap_key(
    topic: str,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    model: Optional[Dict[str, Any]] = None,
) -> str:
    """One allowlisted button for a trusted topic. Empty when trust is thin or low.

    Disk maps to a C: preview. Focus maps to Trước thi/họp. The caller still
    has to pass stage, consent, mute, and the button. This does not run it.
    """
    topic_key = str(topic or "").strip()
    action = _ONE_TAP_BY_TOPIC.get(topic_key, "")
    if not action:
        return ""
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    if not payload.get("date"):
        return ""
    stamp = now or datetime.now()
    if _topic_is_weak(topic_key, payload, now=stamp):
        return ""
    try:
        from core.companion_profile import active_muted_topics
        if topic_key in set(active_muted_topics(base_dir=base_dir, now=stamp)):
            return ""
    except Exception:
        pass
    micro = payload.get("micro") if isinstance(payload.get("micro"), dict) else {}
    if topic_key in set(micro.get("seen_mute") or []):
        return ""
    counts = _topic_feedback_counts(topic_key, payload)
    helpful = counts["helpful"]
    unhelpful = counts["unhelpful"]
    if helpful < ONE_TAP_HELPFUL_MIN or helpful <= unhelpful:
        return ""
    if _effective_topic_score(topic_key, payload, now=stamp) < 1:
        return ""
    return _safe_allowlisted(action)


def learned_skill_offer(
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    model: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """One playbook offer from Có ích. Does not write skills.json.

    Needs PROMOTE_HELPFUL_MIN Có ích, a margin of PROMOTE_MARGIN, and either a
    skill candidate or a lesson that names the topic. Muted, declined, blocked,
    and already saved issues are skipped.
    """
    payload = _clean_model(model) if isinstance(model, dict) else load_daily_model(base_dir)
    if not payload.get("date"):
        return None
    stamp = now or datetime.now()
    try:
        from core.companion_profile import active_muted_topics, topic_for_issue, topic_issue
        from core.companion_skills import (
            BLOCKED_ACTION_KEYS,
            PLAYBOOKS,
            has_skill,
            issue_is_declined,
        )
    except Exception:
        return None
    muted = set(active_muted_topics(base_dir=base_dir, now=stamp))
    micro = payload.get("micro") if isinstance(payload.get("micro"), dict) else {}
    muted.update(str(item) for item in (micro.get("seen_mute") or []))
    lessons = current_lessons(payload, limit=5)
    candidate_weight: Dict[str, int] = {}
    for item in payload.get("skill_candidates") or []:
        if not isinstance(item, dict):
            continue
        issue = str(item.get("issue_class") or "").strip().lower()
        if issue:
            candidate_weight[issue] = max(candidate_weight.get(issue, 0), _as_int(item.get("weight")))
    best: Optional[Dict[str, Any]] = None
    best_rank = (-1, -1)
    for action, row in _combined_action_feedback(payload).items():
        safe = _safe_allowlisted(action)
        if not safe or safe in BLOCKED_ACTION_KEYS or "winsxs" in safe:
            continue
        issue = str(row.get("issue_class") or "").strip().lower()
        if issue not in PLAYBOOKS:
            try:
                from core.companion_skills import action_to_issue
                issue = action_to_issue().get(safe, "")
            except Exception:
                issue = ""
        if issue not in PLAYBOOKS:
            continue
        template = PLAYBOOKS[issue]
        template_action = str(template.get("action_key") or "")
        if template_action in BLOCKED_ACTION_KEYS or not _safe_allowlisted(template_action):
            continue
        helpful = int(row.get("helpful") or 0)
        unhelpful = int(row.get("unhelpful") or 0)
        if helpful < PROMOTE_HELPFUL_MIN or helpful - unhelpful < PROMOTE_MARGIN or helpful <= unhelpful:
            continue
        topic = topic_for_issue(issue)
        if not topic or topic in muted or _topic_is_weak(topic, payload, now=stamp):
            continue
        if _effective_topic_score(topic, payload, now=stamp) < 1:
            continue
        if has_skill(issue, base_dir=base_dir) or issue_is_declined(issue, base_dir=base_dir, now=stamp):
            continue
        if candidate_weight.get(issue, 0) < 1 and not _lesson_mentions(topic, lessons):
            continue
        rank = (helpful - unhelpful, helpful)
        if rank <= best_rank:
            continue
        best_rank = rank
        best = _learning_offer(issue, template, helpful)
    scores = payload.get("topic_scores") if isinstance(payload.get("topic_scores"), dict) else {}
    micro_topics = micro.get("topics") if isinstance(micro.get("topics"), dict) else {}
    for topic in set(scores) | set(micro_topics):
        topic_key = str(topic or "")
        counts = _topic_feedback_counts(topic_key, payload)
        helpful = counts["helpful"]
        unhelpful = counts["unhelpful"]
        if helpful < PROMOTE_HELPFUL_MIN or helpful - unhelpful < PROMOTE_MARGIN or helpful <= unhelpful:
            continue
        if topic_key in muted or _topic_is_weak(topic_key, payload, now=stamp):
            continue
        if _effective_topic_score(topic_key, payload, now=stamp) < 1:
            continue
        issue = topic_issue(topic_key)
        if issue not in PLAYBOOKS:
            continue
        if has_skill(issue, base_dir=base_dir) or issue_is_declined(issue, base_dir=base_dir, now=stamp):
            continue
        if candidate_weight.get(issue, 0) < 1 and not _lesson_mentions(topic_key, lessons):
            continue
        template = PLAYBOOKS[issue]
        template_action = str(template.get("action_key") or "")
        if template_action in BLOCKED_ACTION_KEYS or not _safe_allowlisted(template_action):
            continue
        rank = (helpful - unhelpful, helpful)
        if rank <= best_rank:
            continue
        best_rank = rank
        best = _learning_offer(issue, template, helpful)
    return best


def _learning_offer(issue: str, template: Dict[str, Any], helpful: int) -> Dict[str, Any]:
    title = str(template.get("title") or issue)
    return {
        "issue_class": issue,
        "hit_count": helpful,
        "title": title,
        "if_condition": str(template.get("if_condition") or ""),
        "suggest": str(template.get("suggest") or ""),
        "action_key": str(template.get("action_key") or ""),
        "source": "learning",
        "message_vi": (
            f"Bạn đánh Có ích {helpful} lần cho «{title}». "
            "Lưu thành kỹ năng trên máy này? Mình không tự chạy."
        ),
    }


def refresh_learned_skill_offer(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Store the learning offer when no diary-repeat offer is waiting.

    A repeat-count offer is left alone. A learning offer is replaced or cleared
    when Có ích no longer clears the bar. This never calls save_skill.
    """
    try:
        from core.companion_maturity import load_state, save_state
    except Exception:
        return None
    stamp = now or datetime.now()
    state = load_state(base_dir)
    current = state.get("pending_skill_offer")
    if isinstance(current, dict) and current.get("issue_class") and current.get("source") != "learning":
        return current
    offer = learned_skill_offer(base_dir=base_dir, now=stamp)
    if offer:
        state["pending_skill_offer"] = offer
        save_state(state, base_dir=base_dir)
        return offer
    if isinstance(current, dict) and current.get("source") == "learning":
        state["pending_skill_offer"] = None
        save_state(state, base_dir=base_dir)
    return None


def merge_learning_models(local: Any, incoming: Any) -> Dict[str, Any]:
    """Keep the newer snapshot. The same day does not add the two files together."""
    current = _clean_model(local)
    other = _clean_model(incoming)
    if not other.get("date"):
        return current
    if not current.get("date") or str(other.get("date")) > str(current.get("date")):
        return other
    return current
