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
    return merged


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
