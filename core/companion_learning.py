"""Local daily learning model — a JSON snapshot, not an LLM weight file.

Recomputed once per calendar day from the diary, profile, and feedback
already on this PC. A second run the same day returns the stored snapshot
and does not add the counts again. No download, no Ollama, no Gemini.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from config_manager import companion_dir

MODEL_FILENAME = "learning_model.json"
MODEL_VERSION = 1
_WINDOW_DAYS = 21
_RECENT_DAYS = 14
_NOTE_VI = "Trí nhớ thích nghi trên máy này, không phải AGI và không phải file trọng số."

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
_BAND_VI = {
    "morning": "sáng",
    "afternoon": "chiều",
    "evening": "tối",
    "night": "đêm",
}


def model_path(base_dir: Optional[str] = None) -> str:
    folder = base_dir if base_dir else companion_dir()
    return os.path.join(folder, MODEL_FILENAME)


def _empty_model() -> Dict[str, Any]:
    return {
        "version": MODEL_VERSION,
        "date": "",
        "updated_at": "",
        "source": "local",
        "topic_scores": {},
        "time_weights": {},
        "habit_weights": [],
        "skill_candidates": [],
        "trust_deltas": {},
        "trust": {"level": "steady", "helpful": 0, "unhelpful": 0},
        "baseline_scores": {},
        "baseline_trust": {"level": "steady", "helpful": 0, "unhelpful": 0},
        "rough_days": 0,
        "focus_sessions": 0,
        "summary_vi": "",
        "yesterday_vi": "",
        "yesterday_topic": "",
        "note_vi": _NOTE_VI,
    }


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


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


def _clean_scores(raw: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    try:
        from core.companion_profile import _topic_trust_level_from_counts
    except Exception:
        _topic_trust_level_from_counts = None  # type: ignore
    cleaned: Dict[str, Dict[str, Any]] = {}
    for topic, row in raw.items():
        key = str(topic or "").strip()[:24]
        if not key or not isinstance(row, dict):
            continue
        helpful = _as_int(row.get("helpful"))
        unhelpful = _as_int(row.get("unhelpful"))
        diary = _as_int(row.get("diary"))
        if _topic_trust_level_from_counts is not None:
            level = _topic_trust_level_from_counts(helpful, unhelpful)
        else:
            level = "steady"
        cleaned[key] = {
            "helpful": helpful,
            "unhelpful": unhelpful,
            "diary": diary,
            "score": helpful - unhelpful,
            "level": level if level in ("low", "steady", "high") else "steady",
        }
    return cleaned


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
        rows.append({
            "id": str(item.get("id") or "")[:40],
            "topic": topic,
            "weight": _as_int(item.get("weight")),
            "label_vi": label,
        })
        if len(rows) >= 5:
            break
    return rows


def _clean_candidates(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
    except Exception:
        BLOCKED_ACTION_KEYS = frozenset()
    rows: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action_key") or "").strip().lower()
        issue = str(item.get("issue_class") or "").strip().lower()[:32]
        if action in BLOCKED_ACTION_KEYS or issue in BLOCKED_ACTION_KEYS:
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
    base["habit_weights"] = _clean_habits(raw.get("habit_weights"))
    base["skill_candidates"] = _clean_candidates(raw.get("skill_candidates"))
    base["trust_deltas"] = _clean_deltas(raw.get("trust_deltas"))
    base["trust"] = _clean_trust(raw.get("trust"))
    base["baseline_scores"] = _clean_scores(raw.get("baseline_scores"))
    base["baseline_trust"] = _clean_trust(raw.get("baseline_trust"))
    base["rough_days"] = _as_int(raw.get("rough_days"))
    base["focus_sessions"] = _as_int(raw.get("focus_sessions"))
    base["summary_vi"] = " ".join(str(raw.get("summary_vi") or "").split())[:180]
    base["yesterday_vi"] = " ".join(str(raw.get("yesterday_vi") or "").split())[:140]
    base["yesterday_topic"] = str(raw.get("yesterday_topic") or "")[:24]
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


def _compute(stamp: datetime, base_dir: Optional[str], baseline_scores: Dict[str, Any], baseline_trust: Dict[str, Any]) -> Dict[str, Any]:
    from core.companion_diary import read_events
    from core.companion_profile import TOPIC_META, event_topic, load_profile
    from core.companion_skills import BLOCKED_ACTION_KEYS, PLAYBOOKS, count_issue_classes

    profile = load_profile(base_dir)
    events = read_events(base_dir=base_dir, limit=0)
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
        })
    habits = _clean_habits(sorted(habits, key=lambda item: (-int(item.get("weight") or 0), str(item.get("id") or ""))))
    yesterday_topic = ""
    yesterday_count = 0
    if yesterday_counts:
        yesterday_topic = max(yesterday_counts, key=lambda key: (yesterday_counts[key], key))
        yesterday_count = yesterday_counts[yesterday_topic]
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
    if yesterday_topic and yesterday_count:
        name = _topic_name(yesterday_topic) or yesterday_topic
        yesterday_vi = f"Hôm qua mình học từ máy này: {name}."
    return _clean_model({
        "version": MODEL_VERSION,
        "date": stamp.strftime("%Y-%m-%d"),
        "updated_at": stamp.replace(microsecond=0).isoformat(timespec="seconds"),
        "source": "local",
        "topic_scores": cleaned_scores,
        "time_weights": cleaned_weights,
        "habit_weights": habits,
        "skill_candidates": candidates,
        "trust_deltas": deltas,
        "trust": trust,
        "baseline_scores": prior_scores,
        "baseline_trust": prior_trust,
        "rough_days": rough_days,
        "focus_sessions": focus_sessions,
        "summary_vi": summary,
        "yesterday_vi": yesterday_vi,
        "yesterday_topic": yesterday_topic,
        "note_vi": _NOTE_VI,
    })


def update_daily_model(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Recompute today's snapshot. The same calendar day is not counted twice."""
    stamp = now or datetime.now()
    today = stamp.strftime("%Y-%m-%d")
    current = load_daily_model(base_dir)
    if current.get("date") == today and not force:
        return current
    if current.get("date") and current.get("date") != today:
        baseline_scores = current.get("topic_scores") or {}
        baseline_trust = current.get("trust") or {}
    elif current.get("date") == today:
        baseline_scores = current.get("baseline_scores") or {}
        baseline_trust = current.get("baseline_trust") or {}
    else:
        baseline_scores = {}
        baseline_trust = {}
    built = _compute(stamp, base_dir, baseline_scores, baseline_trust)
    return save_daily_model(built, base_dir=base_dir)


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


def morning_learn_clause(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    hidden: Optional[Set[str]] = None,
) -> str:
    """One calm sentence for the morning line. Empty when nothing was learned yesterday."""
    model = load_daily_model(base_dir)
    stamp = now or datetime.now()
    if str(model.get("date") or "") != stamp.strftime("%Y-%m-%d"):
        return ""
    text = str(model.get("yesterday_vi") or "").strip()
    topic = str(model.get("yesterday_topic") or "")
    blocked = set(hidden or [])
    if not text or topic in blocked or _mentions_muted(text, blocked):
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
    if not text or "chưa có gì mới" in text:
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


def prefer_learned_topics(items: List[Dict[str, Any]], base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Keep window insights in place. Prefer a topic this PC already found useful."""
    model = load_daily_model(base_dir)
    scores = model.get("topic_scores") if isinstance(model.get("topic_scores"), dict) else {}
    if not model.get("date") or not scores:
        return list(items)

    def sort_key(pair):
        index, item = pair
        topic = str((item or {}).get("topic") or "")
        is_window = str((item or {}).get("id") or "").startswith("window:")
        row = scores.get(topic) if isinstance(scores.get(topic), dict) else {}
        score = int(row.get("score") or 0) if isinstance(row, dict) else 0
        if is_window:
            return (0, index)
        return (1, -score, index)

    return [item for _, item in sorted(enumerate(items), key=sort_key)]


def merge_learning_models(local: Any, incoming: Any) -> Dict[str, Any]:
    """Keep the newer snapshot. The same day does not add the two files together."""
    current = _clean_model(local)
    other = _clean_model(incoming)
    if not other.get("date"):
        return current
    if not current.get("date") or str(other.get("date")) > str(current.get("date")):
        return other
    return current
