"""
Maturity stages (0→3) for the in-app companion AI.

Stage advances with *days of use* (distinct calendar days with activity) plus
optional user feedback — not wall-clock since install alone.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from config_manager import companion_dir

STATE_FILENAME = "maturity.json"
MAX_ACTIVE_DATES = 400
# Local celebrations that fire once. Stage-up is intentionally absent:
# that banner already lives on pending_stage_up / last_celebrated_stage.
MILESTONE_IDS = frozenset({"first_week", "useful_answers", "focus_session"})

STAGE_LABELS_VI = {
    0: "Mới gặp",
    1: "Đang học",
    2: "Lớn dần",
    3: "Đồng hành",
}

STAGE_BLURBS_VI = {
    0: "AI vừa gặp máy này. Nhật ký còn trống — hỏi nhiều, chưa đề xuất hành động chủ động.",
    1: "Đã có ngày dùng thật trên máy này. Vẫn hỏi trước khi gợi ý việc cần làm.",
    2: "Bắt đầu nhận ra thói quen máy này. Có thể đề xuất dọn nhẹ / tập trung — không tự chạy.",
    3: "Nhớ nhật ký và kỹ năng máy này. Vẫn không tự thay đổi phá hủy nếu bạn chưa đồng ý.",
}

EMPTY_STAGE_VI = "Giai đoạn 0 · Mới gặp — chưa có ngày dùng trên máy này."


@dataclass
class StageInfo:
    stage: int
    name_vi: str
    blurb_vi: str
    active_days: int
    positive_feedback: int
    negative_feedback: int
    skills_count: int
    ask_more: bool
    may_propose_actions: bool
    first_seen: str = ""
    empty: bool = True

    def badge_vi(self) -> str:
        return f"Giai đoạn {self.stage} · {self.name_vi}"


def compute_stage(
    active_days: int,
    positive_feedback: int = 0,
    skills_count: int = 0,
) -> int:
    """
    Pure stage rules.

    0: no active use days (fresh install / wall-clock only does not count)
    1: ≥1 active day
    2: ≥7 active days, or ≥5 days with helpful feedback or a saved skill
    3: ≥21 active days, or ≥14 days with ≥2 helpful feedback or ≥1 skill
    """
    days = max(0, int(active_days or 0))
    fb = max(0, int(positive_feedback or 0))
    skills = max(0, int(skills_count or 0))
    if days < 1:
        return 0
    if days >= 21 or (days >= 14 and (fb >= 2 or skills >= 1)):
        return 3
    if days >= 7 or (days >= 5 and (fb >= 1 or skills >= 1)):
        return 2
    return 1


def default_state() -> Dict[str, Any]:
    return {
        "first_seen": "",
        "active_dates": [],
        "positive_feedback": 0,
        "negative_feedback": 0,
        "last_high_ram_ts": 0.0,
        "last_wifi_ts": 0.0,
        "last_ping_ts": 0.0,
        "last_thermal_ts": 0.0,
        "last_reflection_date": "",
        "last_session_date": "",
        "pending_skill_offer": None,
        "last_nudge_ts": 0.0,
        "last_nudge_class": "",
        "declined_skill_until": {},
        "last_weekly_digest_week": "",
        # None until the first observation so an upgrade does not fake a stage-up.
        "last_recorded_stage": None,
        "last_celebrated_stage": None,
        "pending_stage_up": None,
        "last_checkin_date": "",
        "pending_checkin": None,
        "pending_followup": None,
        "pending_outcome": None,
        "last_eod_date": "",
        "pending_eod": None,
        "focus_session": None,
        "last_goal_conflict_date": "",
        "pending_goal_conflict": None,
        "shown_milestones": [],
        "last_milestone_date": "",
        "pending_milestone": None,
        "helpful_replay": None,
        "pinned_actions": [],
        "last_weekly_strip_week": "",
        "pending_weekly_strip": None,
        "last_exam_hint_week": "",
        "pending_exam_hint": None,
        # One soft pointer after a useful C: preview. Never a delete key.
        "pending_disk_next": None,
        "disk_next_closed": [],
    }


def state_path(base_dir: Optional[str] = None) -> str:
    return os.path.join(base_dir or companion_dir(), STATE_FILENAME)


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_state(base_dir: Optional[str] = None) -> Dict[str, Any]:
    path = state_path(base_dir)
    merged = default_state()
    if not path or not os.path.exists(path):
        return merged
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            merged.update(data)
    except Exception:
        return default_state()
    dates = merged.get("active_dates") or []
    if not isinstance(dates, list):
        dates = []
    cleaned: List[str] = []
    seen = set()
    for item in dates:
        day = str(item or "")[:10]
        if len(day) == 10 and day not in seen:
            seen.add(day)
            cleaned.append(day)
    merged["active_dates"] = cleaned[-MAX_ACTIVE_DATES:]
    try:
        merged["positive_feedback"] = max(0, int(merged.get("positive_feedback") or 0))
    except (TypeError, ValueError):
        merged["positive_feedback"] = 0
    try:
        merged["negative_feedback"] = max(0, int(merged.get("negative_feedback") or 0))
    except (TypeError, ValueError):
        merged["negative_feedback"] = 0
    merged["last_recorded_stage"] = _optional_stage(merged.get("last_recorded_stage"))
    merged["last_celebrated_stage"] = _optional_stage(merged.get("last_celebrated_stage"))
    pending_stage = merged.get("pending_stage_up")
    merged["pending_stage_up"] = pending_stage if isinstance(pending_stage, dict) and pending_stage.get("text") else None
    pending_checkin = merged.get("pending_checkin")
    merged["pending_checkin"] = pending_checkin if isinstance(pending_checkin, dict) and pending_checkin.get("text") else None
    merged["last_checkin_date"] = str(merged.get("last_checkin_date") or "")[:10]
    merged["focus_session"] = _clean_focus_session(merged.get("focus_session"))
    merged["last_goal_conflict_date"] = str(merged.get("last_goal_conflict_date") or "")[:10]
    pending_conflict = merged.get("pending_goal_conflict")
    merged["pending_goal_conflict"] = (
        pending_conflict if isinstance(pending_conflict, dict) and pending_conflict.get("text") else None
    )
    merged["shown_milestones"] = _clean_shown_milestones(merged.get("shown_milestones"))
    merged["last_milestone_date"] = str(merged.get("last_milestone_date") or "")[:10]
    merged["pending_milestone"] = _clean_pending_milestone(merged.get("pending_milestone"))
    merged["helpful_replay"] = _clean_helpful_replay(merged.get("helpful_replay"))
    merged["pinned_actions"] = _clean_pinned_actions(merged.get("pinned_actions"))
    merged["last_weekly_strip_week"] = str(merged.get("last_weekly_strip_week") or "")[:12]
    merged["pending_weekly_strip"] = _clean_weekly_strip(merged.get("pending_weekly_strip"))
    merged["last_exam_hint_week"] = str(merged.get("last_exam_hint_week") or "")[:12]
    merged["pending_exam_hint"] = _clean_exam_hint(merged.get("pending_exam_hint"))
    merged["pending_disk_next"] = _clean_disk_next(merged.get("pending_disk_next"))
    merged["disk_next_closed"] = _clean_disk_next_closed(merged.get("disk_next_closed"))
    return merged


def _clean_disk_next(raw: Any) -> Optional[Dict[str, Any]]:
    """One line pointing at the existing C: preview. The key cannot be rewritten."""
    if not isinstance(raw, dict):
        return None
    text = " ".join(str(raw.get("text") or "").split())
    if not text or "không tự xóa" not in text:
        return None
    try:
        size = max(0, int(raw.get("bytes") or 0))
    except (TypeError, ValueError):
        size = 0
    return {
        "text": text[:240],
        "action_key": "preview_c_drive",
        "label_vi": "Mở xem trước",
        "since": str(raw.get("since") or "")[:32],
        "bytes": size,
    }


def _clean_disk_next_closed(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        token = str(item or "").strip()[:32]
        if token and token not in out:
            out.append(token)
    return out[-8:]


def _clean_shown_milestones(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        key = str(item or "").strip()
        if key in MILESTONE_IDS and key not in out:
            out.append(key)
    return out


def _clean_pending_milestone(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    milestone_id = str(raw.get("id") or "").strip()
    text = str(raw.get("text") or "").strip()
    if milestone_id not in MILESTONE_IDS or not text:
        return None
    return {
        "id": milestone_id,
        "text": text[:240],
        "date": str(raw.get("date") or "")[:10],
    }


def _clean_helpful_replay(raw: Any) -> Optional[Dict[str, Any]]:
    """One allowlisted Có ích action. Blocked keys are dropped on load."""
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("action_key") or "").strip()
    if not key:
        return None
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
        if key in BLOCKED_ACTION_KEYS:
            return None
    except Exception:
        return None
    try:
        from core.companion_moment import INSIGHT_ACTION_ALLOWLIST
        if key not in INSIGHT_ACTION_ALLOWLIST:
            return None
    except Exception:
        return None
    return {
        "action_key": key,
        "topic": str(raw.get("topic") or "")[:24],
        "at": str(raw.get("at") or "")[:32],
        "surfaced": bool(raw.get("surfaced")),
    }


def _clean_pinned_actions(raw: Any) -> List[Dict[str, Any]]:
    """Up to three allowlisted favorites. Blocked keys are dropped on load."""
    if not isinstance(raw, list):
        return []
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
    except Exception:
        BLOCKED_ACTION_KEYS = frozenset()
    try:
        from core.companion_moment import INSIGHT_ACTION_ALLOWLIST
    except Exception:
        return []
    try:
        from core.companion_profile import TOPIC_META
    except Exception:
        TOPIC_META = {}
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("action_key") or "").strip()
        if not key or key in seen or key in BLOCKED_ACTION_KEYS or key not in INSIGHT_ACTION_ALLOWLIST:
            continue
        spec = INSIGHT_ACTION_ALLOWLIST.get(key) or {}
        topics = [str(topic) for topic in (spec.get("topics") or []) if str(topic)]
        topic = topics[0] if len(topics) == 1 else str(item.get("topic") or "").strip()
        if topic not in TOPIC_META:
            topic = ""
        seen.add(key)
        out.append({
            "action_key": key,
            "topic": topic[:24],
            "label_vi": str(spec.get("label_vi") or "")[:80],
            "pinned_at": str(item.get("pinned_at") or "")[:32],
        })
        if len(out) >= 3:
            break
    return out


def _clean_weekly_strip(raw: Any) -> Optional[Dict[str, Any]]:
    """One local weekly strip. Missing or odd shapes become nothing."""
    if not isinstance(raw, dict):
        return None
    week = str(raw.get("week") or "").strip()[:12]
    items_raw = raw.get("items") if isinstance(raw.get("items"), list) else []
    items: List[Dict[str, str]] = []
    for item in items_raw:
        if isinstance(item, str):
            text = item.strip()
            topic = ""
        elif isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            topic = str(item.get("topic") or "").strip()[:24]
        else:
            continue
        if not text:
            continue
        items.append({"text": text[:160], "topic": topic})
        if len(items) >= 3:
            break
    if not week or not items:
        return None
    text = str(raw.get("text") or "").strip()
    if not text:
        text = "Tóm tắt tuần:\n" + "\n".join("• " + item["text"] for item in items)
    return {"week": week, "text": text[:500], "items": items}


def _clean_exam_hint(raw: Any) -> Optional[Dict[str, Any]]:
    """Soft exam-season line. Never keeps an action key from disk."""
    if not isinstance(raw, dict):
        return None
    week = str(raw.get("week") or "").strip()[:12]
    text = str(raw.get("text") or "").strip()
    if not week or not text:
        return None
    return {
        "id": str(raw.get("id") or f"exam_season:{week}")[:40],
        "week": week,
        "text": text[:320],
        "topic": "focus",
    }


def _clean_focus_session(raw: Any) -> Optional[Dict[str, Any]]:
    """Keep a small session stamp. Never implies the mode should turn itself on."""
    if not isinstance(raw, dict):
        return None
    started = str(raw.get("started_at") or "")[:32]
    ended = str(raw.get("ended_at") or "")[:32]
    follow = str(raw.get("followup_for") or "")[:32]
    active = bool(raw.get("active"))
    if not started and not ended and not active:
        return None
    return {
        "active": active,
        "started_at": started,
        "ended_at": ended,
        "followup_for": follow,
    }


def _optional_stage(value: Any) -> Optional[int]:
    """Missing stage stays unknown. 0 is a real baseline, not 'never seen'."""
    if value is None or value == "":
        return None
    try:
        return max(0, min(3, int(value)))
    except (TypeError, ValueError):
        return None


def save_state(state: Dict[str, Any], base_dir: Optional[str] = None) -> Dict[str, Any]:
    payload = default_state()
    if isinstance(state, dict):
        payload.update(state)
    dates = payload.get("active_dates") or []
    if isinstance(dates, list):
        payload["active_dates"] = [str(d)[:10] for d in dates][-MAX_ACTIVE_DATES:]
    _atomic_write_json(state_path(base_dir), payload)
    return payload


def mark_active_day(
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    state = load_state(base_dir)
    stamp = now or datetime.now()
    day = stamp.strftime("%Y-%m-%d")
    if not state.get("first_seen"):
        state["first_seen"] = stamp.replace(microsecond=0).isoformat(timespec="seconds")
    dates = list(state.get("active_dates") or [])
    if day not in dates:
        dates.append(day)
        state["active_dates"] = dates[-MAX_ACTIVE_DATES:]
        save_state(state, base_dir=base_dir)
    return state


def add_feedback(
    helpful: bool,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    state = mark_active_day(now=now, base_dir=base_dir)
    if helpful:
        state["positive_feedback"] = int(state.get("positive_feedback") or 0) + 1
    else:
        state["negative_feedback"] = int(state.get("negative_feedback") or 0) + 1
    save_state(state, base_dir=base_dir)
    return state


def explain_stage_vi(
    active_days: int,
    positive_feedback: int = 0,
    skills_count: int = 0,
) -> str:
    """Why the companion is at this stage, and what moves it forward."""
    days = max(0, int(active_days or 0))
    fb = max(0, int(positive_feedback or 0))
    skills = max(0, int(skills_count or 0))
    stage = compute_stage(days, fb, skills)
    if stage <= 0:
        return "Chưa có ngày dùng trên máy này — giai đoạn giữ Mới gặp cho đến khi bạn mở app."
    if stage == 1:
        return (
            f"Đang học vì đã có {days} ngày dùng. "
            "Sang Lớn dần khi đủ 7 ngày, hoặc 5 ngày kèm phản hồi hữu ích hoặc 1 kỹ năng."
        )
    if stage == 2:
        if days >= 7:
            why = f"{days} ngày dùng"
        elif fb >= 1:
            why = f"{days} ngày dùng và phản hồi hữu ích"
        elif skills >= 1:
            why = f"{days} ngày dùng và đã có kỹ năng"
        else:
            why = f"{days} ngày dùng"
        return (
            f"Lớn dần vì {why}. "
            "Sang Đồng hành khi đủ 21 ngày, hoặc 14 ngày kèm 2 phản hồi hữu ích hoặc 1 kỹ năng."
        )
    if days >= 21:
        reason = f"{days} ngày dùng"
    elif fb >= 2:
        reason = f"{days} ngày dùng và {fb} phản hồi hữu ích"
    else:
        reason = f"{days} ngày dùng và {skills} kỹ năng"
    return f"Đồng hành vì {reason}. Vẫn không tự chạy việc phá hủy."


def build_stage_info(
    state: Optional[Dict[str, Any]] = None,
    skills_count: int = 0,
    *,
    consent_propose: bool = True,
    base_dir: Optional[str] = None,
) -> StageInfo:
    data = state if isinstance(state, dict) else load_state(base_dir)
    dates = data.get("active_dates") or []
    active_days = len(dates) if isinstance(dates, list) else 0
    positive = int(data.get("positive_feedback") or 0)
    negative = int(data.get("negative_feedback") or 0)
    stage = compute_stage(active_days, positive, skills_count)
    ask_more = stage <= 1
    may_propose = stage >= 2 and bool(consent_propose)
    return StageInfo(
        stage=stage,
        name_vi=STAGE_LABELS_VI[stage],
        blurb_vi=STAGE_BLURBS_VI[stage],
        active_days=active_days,
        positive_feedback=positive,
        negative_feedback=negative,
        skills_count=max(0, int(skills_count or 0)),
        ask_more=ask_more,
        may_propose_actions=may_propose,
        first_seen=str(data.get("first_seen") or ""),
        empty=active_days < 1,
    )
