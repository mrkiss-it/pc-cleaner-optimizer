"""
Growing companion AI facade — diary, maturity, skills, reflection.

Not AGI and not full-model self-training: local memory for Copilot on this PC.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.companion_diary import (
    ALLOWED_KINDS,
    append_event,
    clear_events,
    count_by_kind,
    delete_event,
    event_weight,
    format_digest,
    format_event_row,
    recent_events,
    time_band,
)
from core.companion_maturity import (
    EMPTY_STAGE_VI,
    STAGE_BLURBS_VI,
    STAGE_LABELS_VI,
    StageInfo,
    add_feedback,
    build_stage_info,
    compute_stage,
    explain_stage_vi,
    load_state,
    mark_active_day,
    save_state,
)
from core.companion_reflection import (
    clear_reflection,
    load_reflection,
    load_reflection_meta,
    resolve_llm_provider,
    run_reflection,
)
from core.companion_skills import (
    CompanionSkill,
    clear_skills,
    crystallize_skills,
    delete_skill,
    format_skill_row,
    format_skills_context,
    has_skill,
    issue_class_for_kind,
    load_skills,
    match_skills,
    pending_offer_from_counts,
    save_skill,
)

CONTEXT_CHAR_BUDGET = 1100
NUDGE_COOLDOWN_SEC = 12 * 3600
NUDGE_SAME_CLASS_SEC = 36 * 3600
SKILL_DECLINE_DAYS = 7
_LATE_BANDS = frozenset({"evening", "night"})

SNAPSHOT_COOLDOWN_SEC = 3 * 3600
DEFAULT_REFLECTION_HOUR = 20
POSTSCRIPT_COOLDOWN_SEC = 20 * 60
REFLECT_BUTTON_VI = "Phản tỉnh / Viết sổ tay"
STAGE_LEGEND_VI = (
    "0 Mới gặp → 1 Đang học → 2 Lớn dần → 3 Đồng hành — "
    "lớn theo ngày dùng máy này, không theo ngày cài."
)

_last_postscript_at = 0.0
_last_postscript_sig = ""
_syncing_stage = False

_MEMORY_HINTS = (
    "nhat ky", "nhật ký", "so tay", "sổ tay", "giai doan", "giai đoạn",
    "ky nang", "kỹ năng", "dong hanh", "đồng hành", "nho gi", "nhớ gì",
    "ban nho", "bạn nhớ", "diary", "companion", "skill",
)


def _cfg_get(config_manager: Optional[Any], key: str, default: Any = None) -> Any:
    if config_manager is None:
        return default
    try:
        if hasattr(config_manager, "get"):
            return config_manager.get(key, default)
        if isinstance(config_manager, dict):
            return config_manager.get(key, default)
    except Exception:
        return default
    return default


def is_enabled(config_manager: Optional[Any] = None) -> bool:
    return bool(_cfg_get(config_manager, "companion_enabled", True))


def record_session_day(
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """One diary line per calendar day the app actually ran — not wall-clock since install."""
    if config_manager is not None and not is_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    day = stamp.strftime("%Y-%m-%d")
    try:
        state = load_state(base_dir)
        if str(state.get("last_session_date") or "") == day:
            mark_active_day(now=stamp, base_dir=base_dir)
            return None
        event = record_app_event(
            "session_day",
            "Phiên dùng app trên máy này",
            source="session",
            now=stamp,
            base_dir=base_dir,
            config_manager=config_manager,
        )
        state = load_state(base_dir)
        state["last_session_date"] = day
        save_state(state, base_dir=base_dir)
        return event
    except Exception:
        return None


def record_app_event(
    kind: str,
    summary: str,
    metrics: Optional[Dict[str, Any]] = None,
    source: str = "app",
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
    outcome: str = "",
    tags: Optional[List[str]] = None,
    coalesce: bool = True,
) -> Optional[Dict[str, Any]]:
    if config_manager is not None and not is_enabled(config_manager):
        return None
    if str(kind or "") != "stage_up":
        try:
            maybe_note_stage_up(config_manager=config_manager, base_dir=base_dir, now=now)
        except Exception:
            pass
    try:
        event = append_event(
            kind,
            summary,
            metrics=metrics,
            source=source,
            now=now,
            base_dir=base_dir,
            outcome=outcome,
            tags=tags,
            coalesce=coalesce,
        )
        if event:
            mark_active_day(now=now, base_dir=base_dir)
            _refresh_skill_offer(base_dir=base_dir, now=now)
            try:
                from core.companion_profile import refresh_profile
                refresh_profile(base_dir=base_dir, now=now)
            except Exception:
                pass
            if str(kind or "") != "stage_up":
                try:
                    maybe_note_stage_up(config_manager=config_manager, base_dir=base_dir, now=now)
                except Exception:
                    pass
            if str(kind or "") not in ("user_feedback", "stage_up"):
                try:
                    from core.companion_moment import maybe_credit_action_outcome
                    maybe_credit_action_outcome(
                        event,
                        base_dir=base_dir,
                        now=now,
                        config_manager=config_manager,
                    )
                except Exception:
                    pass
        return event
    except Exception:
        return None


def _pending_stage_payload(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pending = state.get("pending_stage_up")
    if isinstance(pending, dict) and str(pending.get("text") or "").strip():
        return pending
    return None


def pending_stage_celebration(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Undismissed stage-up line for the day it happened.

    A later calendar day drops the banner without writing another diary event,
    so reopening the app does not celebrate the same stage again.
    """
    state = load_state(base_dir)
    pending = _pending_stage_payload(state)
    if not pending:
        return None
    day = str(pending.get("date") or "")[:10]
    today = (now or datetime.now()).strftime("%Y-%m-%d")
    if day and today and day < today:
        state["pending_stage_up"] = None
        save_state(state, base_dir=base_dir)
        return None
    return pending


def dismiss_stage_celebration(base_dir: Optional[str] = None) -> None:
    """Hide the banner. last_celebrated_stage stays so the same stage is not announced again."""
    state = load_state(base_dir)
    state["pending_stage_up"] = None
    save_state(state, base_dir=base_dir)


def maybe_note_stage_up(
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Diary + one banner when compute_stage rises. The first sight of an existing stage is silent.

    Celebration is one-shot per stage via last_celebrated_stage. Dismiss clears the banner only.
    A later drop (for example deleting the skill that earned the stage) can celebrate
    again only if the stage climbs past the last celebrated value.
    """
    global _syncing_stage
    if _syncing_stage:
        return None
    if config_manager is not None and not is_enabled(config_manager):
        return None
    info = current_stage(config_manager=config_manager, base_dir=base_dir)
    state = load_state(base_dir)
    recorded = state.get("last_recorded_stage")
    celebrated = state.get("last_celebrated_stage")
    if recorded is None:
        state["last_recorded_stage"] = info.stage
        if celebrated is None:
            state["last_celebrated_stage"] = info.stage
        save_state(state, base_dir=base_dir)
        return None
    try:
        recorded_n = int(recorded)
    except (TypeError, ValueError):
        recorded_n = info.stage
    try:
        celebrated_n = int(celebrated) if celebrated is not None else -1
    except (TypeError, ValueError):
        celebrated_n = -1
    if info.stage < recorded_n:
        state["last_recorded_stage"] = info.stage
        save_state(state, base_dir=base_dir)
        return _pending_stage_payload(state)
    if info.stage == recorded_n:
        return _pending_stage_payload(state)
    reason = explain_stage_vi(info.active_days, info.positive_feedback, info.skills_count)
    head = reason.split(".", 1)[0].strip()
    banner = f"Mình vừa lên giai đoạn {info.stage} · {info.name_vi} — {head}."
    summary = f"Mình vừa lên giai đoạn {info.stage} · {info.name_vi}. {reason}"
    stamp = now or datetime.now()
    if info.stage > celebrated_n:
        _syncing_stage = True
        try:
            record_app_event(
                "stage_up",
                summary,
                metrics={"stage": info.stage},
                source="companion",
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
                outcome="ok",
                tags=["stage"],
                coalesce=False,
            )
        finally:
            _syncing_stage = False
        state = load_state(base_dir)
        state["pending_stage_up"] = {
            "stage": info.stage,
            "name_vi": info.name_vi,
            "reason_vi": reason,
            "text": banner,
            "date": stamp.strftime("%Y-%m-%d"),
        }
        state["last_celebrated_stage"] = info.stage
    state["last_recorded_stage"] = info.stage
    save_state(state, base_dir=base_dir)
    return _pending_stage_payload(load_state(base_dir))


def _refresh_skill_offer(base_dir: Optional[str] = None, now: Optional[datetime] = None) -> None:
    try:
        counts = count_by_kind(days=21, base_dir=base_dir, now=now)
        offer = pending_offer_from_counts(counts, base_dir=base_dir, now=now)
        state = load_state(base_dir)
        state["pending_skill_offer"] = offer
        save_state(state, base_dir=base_dir)
    except Exception:
        return


def pending_skill_offer(base_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
    state = load_state(base_dir)
    offer = state.get("pending_skill_offer")
    return offer if isinstance(offer, dict) else None


def accept_skill_offer(issue_class: str = "", base_dir: Optional[str] = None) -> Optional[CompanionSkill]:
    offer = pending_skill_offer(base_dir)
    issue = str(issue_class or (offer or {}).get("issue_class") or "").strip()
    if not issue:
        return None
    hit = int((offer or {}).get("hit_count") or 0)
    skill = save_skill(issue, hit_count=hit, base_dir=base_dir)
    if skill:
        record_app_event(
            "skill_saved",
            f"Đã lưu kỹ năng: {skill.title}",
            metrics={"count": skill.hit_count},
            source="companion",
            base_dir=base_dir,
        )
        state = load_state(base_dir)
        state["pending_skill_offer"] = None
        save_state(state, base_dir=base_dir)
    return skill


def decline_skill_offer(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    config_manager: Optional[Any] = None,
) -> None:
    state = load_state(base_dir)
    offer = state.get("pending_skill_offer") if isinstance(state.get("pending_skill_offer"), dict) else {}
    issue = str((offer or {}).get("issue_class") or "").strip().lower()
    action = str((offer or {}).get("action_key") or "")
    title = str((offer or {}).get("title") or issue)
    stamp = now or datetime.now()
    if issue:
        until = stamp.timestamp() + SKILL_DECLINE_DAYS * 86400
        declined = state.get("declined_skill_until")
        if not isinstance(declined, dict):
            declined = {}
        declined[issue] = datetime.fromtimestamp(until).replace(microsecond=0).isoformat(timespec="seconds")
        state["declined_skill_until"] = declined
    state["pending_skill_offer"] = None
    save_state(state, base_dir=base_dir)
    if issue:
        record_app_event(
            "suggestion_rejected",
            f"Người dùng bỏ qua kỹ năng: {title}",
            source="user",
            now=stamp,
            base_dir=base_dir,
            config_manager=config_manager,
            outcome="rejected",
            tags=["suggestion", issue] + ([action] if action else []),
            coalesce=False,
        )


def note_user_feedback(
    helpful: bool,
    note: str = "",
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    config_manager: Optional[Any] = None,
    topic: str = "",
) -> StageInfo:
    add_feedback(helpful, base_dir=base_dir, now=now)
    summary = "Người dùng thấy AI đồng hành hữu ích." if helpful else "Người dùng thấy gợi ý chưa khớp máy này."
    if note:
        summary = f"{summary} {note}"
    feedback_tags = None
    topic_key = str(topic or "").strip()
    if topic_key:
        try:
            from core.companion_profile import TOPIC_META
            if topic_key in TOPIC_META:
                feedback_tags = ["feedback", topic_key]
        except Exception:
            feedback_tags = None
    record_app_event(
        "user_feedback",
        summary,
        metrics={"helpful": 1 if helpful else 0},
        source="user",
        now=now,
        base_dir=base_dir,
        config_manager=config_manager,
        outcome="accepted" if helpful else "rejected",
        tags=feedback_tags,
    )
    try:
        from core.companion_moment import learn_from_feedback
        learn_from_feedback(
            helpful,
            base_dir=base_dir,
            now=now,
            config_manager=config_manager,
            topic=topic,
        )
    except Exception:
        pass
    if topic_key:
        shift = None
        try:
            from core.companion_profile import record_topic_trust
            shift = record_topic_trust(topic_key, bool(helpful), base_dir=base_dir, now=now)
        except Exception:
            shift = None
        if isinstance(shift, dict) and shift.get("summary"):
            record_app_event(
                "topic_trust",
                str(shift.get("summary") or ""),
                source="companion",
                now=now,
                base_dir=base_dir,
                config_manager=config_manager,
                outcome="neutral",
                tags=["trust", topic_key],
                coalesce=False,
            )
    try:
        from core.companion_learning import apply_micro_update
        apply_micro_update(
            "feedback",
            helpful=bool(helpful),
            topic=topic_key,
            now=now,
            base_dir=base_dir,
        )
    except Exception:
        pass
    return current_stage(config_manager=config_manager, base_dir=base_dir)


def current_stage(
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
) -> StageInfo:
    skills_count = len(load_skills(base_dir))
    consent = bool(_cfg_get(config_manager, "companion_may_propose_actions", True))
    return build_stage_info(
        load_state(base_dir),
        skills_count=skills_count,
        consent_propose=consent,
        base_dir=base_dir,
    )


def diary_digest(
    limit: int = 8,
    days: int = 14,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    return format_digest(days=days, limit=limit, base_dir=base_dir, now=now)


def latest_reflection(base_dir: Optional[str] = None) -> str:
    return load_reflection(base_dir)


def stage_legend_vi() -> str:
    return STAGE_LEGEND_VI


def stage_caption_vi(stage: Optional[StageInfo] = None, config_manager: Optional[Any] = None) -> str:
    info = stage if isinstance(stage, StageInfo) else current_stage(config_manager=config_manager)
    return f"{info.badge_vi()} — {info.blurb_vi}"


def diary_is_empty(base_dir: Optional[str] = None, now: Optional[datetime] = None) -> bool:
    return not recent_events(days=30, limit=1, base_dir=base_dir, now=now)


def list_diary_rows(
    limit: int = 20,
    days: int = 30,
    base_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows = recent_events(days=days, limit=limit, base_dir=base_dir)
    return list(reversed(rows))


def format_diary_browse(
    events: Optional[List[Dict[str, Any]]] = None,
    *,
    limit: int = 20,
    days: int = 30,
    base_dir: Optional[str] = None,
) -> str:
    rows = events if events is not None else list_diary_rows(limit=limit, days=days, base_dir=base_dir)
    if not rows:
        return empty_states_vi()["diary"]
    lines = [format_event_row(item) for item in rows]
    return "\n".join(line for line in lines if line)


def list_skill_rows(base_dir: Optional[str] = None) -> List[CompanionSkill]:
    return load_skills(base_dir)


def format_skills_browse(
    skills: Optional[List[CompanionSkill]] = None,
    *,
    base_dir: Optional[str] = None,
) -> str:
    rows = skills if skills is not None else list_skill_rows(base_dir=base_dir)
    if not rows:
        return empty_states_vi()["skills"]
    lines = [format_skill_row(item) for item in rows]
    return "\n".join(line for line in lines if line)


def format_reflection_feedback(
    result: Any = None,
    *,
    error: Optional[Any] = None,
) -> Dict[str, str]:
    """Copy for manual Phản tỉnh / Viết sổ tay — success / empty / error."""
    if error is not None or isinstance(result, Exception):
        detail = str(error if error is not None else result).strip() or "lỗi không rõ"
        return {
            "status": "error",
            "title": "Không ghi được sổ tay",
            "body": f"Không ghi được sổ tay: {detail}",
        }
    payload = result if isinstance(result, dict) else {}
    source = str(payload.get("source") or "").strip().lower()
    note = str(payload.get("note") or "").strip()
    if source == "empty" or (not note and source != "template"):
        empty = empty_states_vi()
        return {
            "status": "empty",
            "title": "Chưa có nhật ký",
            "body": empty["reflection_empty"],
        }
    if source == "template":
        body = "Đã ghi sổ tay từ số liệu trên máy này (không dùng mô hình ngôn ngữ)."
    elif source == "gemini":
        body = "Đã ghi sổ tay (Gemini) từ nhật ký máy này."
    else:
        body = "Đã ghi sổ tay từ nhật ký máy này."
    return {
        "status": "success",
        "title": "Đã ghi sổ tay",
        "body": body,
    }


def confirm_clear_prompt(target: str) -> Dict[str, str]:
    """Vietnamese confirm copy for delete/clear. Privacy-friendly, no Pro branding."""
    kind = str(target or "").strip().lower()
    if kind == "diary_item":
        return {
            "title": "Xóa mục nhật ký?",
            "body": "Xóa mục nhật ký local này. Copilot sẽ không còn nhớ sự kiện đó. Không thể hoàn tác.",
            "ok": "Xóa mục",
        }
    if kind == "diary":
        return {
            "title": "Xóa nhật ký máy?",
            "body": (
                "Xóa toàn bộ nhật ký local trên máy này. Copilot sẽ không còn nhớ sự kiện cũ. "
                "Giai đoạn (ngày dùng) vẫn giữ. Không thể hoàn tác."
            ),
            "ok": "Xóa nhật ký",
        }
    if kind == "skill_item":
        return {
            "title": "Xóa kỹ năng?",
            "body": "Xóa kỹ năng đã lưu cho máy này. Copilot sẽ không còn gợi ý theo mẹo đó. Không thể hoàn tác.",
            "ok": "Xóa kỹ năng",
        }
    if kind == "skills":
        return {
            "title": "Xóa hết kỹ năng?",
            "body": "Xóa mọi kỹ năng đã lưu trên máy này. Không thể hoàn tác.",
            "ok": "Xóa kỹ năng",
        }
    if kind == "reflection":
        return {
            "title": "Xóa sổ tay?",
            "body": "Xóa sổ tay phản tỉnh local. Có thể viết lại sau. Không thể hoàn tác.",
            "ok": "Xóa sổ tay",
        }
    if kind == "profile":
        return {
            "title": "Xóa hồ sơ thói quen?",
            "body": (
                "Xóa hồ sơ thói quen local (điều AI nhớ về máy này). "
                "Mục tiêu, lời bạn đã sửa và nhật ký vẫn giữ. Không thể hoàn tác."
            ),
            "ok": "Xóa hồ sơ",
        }
    if kind == "correction":
        return {
            "title": "Xóa lời đã sửa?",
            "body": "Xóa câu bạn đã dạy mình. Mình sẽ không nhắc câu đó nữa. Không thể hoàn tác.",
            "ok": "Xóa câu",
        }
    return {
        "title": "Xóa hết bộ nhớ local?",
        "body": (
            "Xóa nhật ký, hồ sơ thói quen, mục tiêu, kỹ năng và sổ tay trên máy này (AppData). "
            "Giai đoạn (ngày dùng) vẫn giữ. Gemini không nhận dữ liệu đã xóa. Không thể hoàn tác."
        ),
        "ok": "Xóa bộ nhớ",
    }


def delete_diary_entry(event: Dict[str, Any], base_dir: Optional[str] = None) -> bool:
    try:
        return bool(delete_event(event, base_dir=base_dir))
    except Exception:
        return False


def clear_diary_memory(base_dir: Optional[str] = None) -> int:
    try:
        return int(clear_events(base_dir=base_dir) or 0)
    except Exception:
        return 0


def delete_saved_skill(skill_id: str, base_dir: Optional[str] = None) -> bool:
    try:
        return bool(delete_skill(skill_id, base_dir=base_dir))
    except Exception:
        return False


def clear_skills_memory(base_dir: Optional[str] = None) -> int:
    try:
        count = int(clear_skills(base_dir=base_dir) or 0)
        state = load_state(base_dir)
        state["pending_skill_offer"] = None
        save_state(state, base_dir=base_dir)
        return count
    except Exception:
        return 0


def clear_reflection_memory(base_dir: Optional[str] = None) -> bool:
    try:
        return bool(clear_reflection(base_dir=base_dir))
    except Exception:
        return False


def clear_profile_habits(base_dir: Optional[str] = None) -> int:
    try:
        from core.companion_profile import clear_habits
        return int(clear_habits(base_dir=base_dir) or 0)
    except Exception:
        return 0


def clear_profile_memory(base_dir: Optional[str] = None) -> int:
    try:
        from core.companion_profile import clear_profile
        return int(clear_profile(base_dir=base_dir) or 0)
    except Exception:
        return 0


def clear_local_memory(
    *,
    diary: bool = True,
    skills: bool = True,
    reflection: bool = True,
    profile: bool = True,
    base_dir: Optional[str] = None,
) -> Dict[str, int]:
    """Privacy clear: diary / profile / skills / sổ tay. Does not reset days-of-use stage."""
    counts = {"diary": 0, "skills": 0, "reflection": 0, "profile": 0}
    if diary:
        counts["diary"] = clear_diary_memory(base_dir=base_dir)
    if skills:
        counts["skills"] = clear_skills_memory(base_dir=base_dir)
    if reflection:
        counts["reflection"] = 1 if clear_reflection_memory(base_dir=base_dir) else 0
    if profile:
        counts["profile"] = clear_profile_memory(base_dir=base_dir)
    try:
        state = load_state(base_dir)
        state["pending_followup"] = None
        state["pending_outcome"] = None
        state["pending_eod"] = None
        save_state(state, base_dir=base_dir)
    except Exception:
        pass
    return counts


def should_emit_postscript(
    signature: str,
    now_ts: Optional[float] = None,
    cooldown_sec: float = POSTSCRIPT_COOLDOWN_SEC,
) -> bool:
    """Avoid repeating the same companion footnote on every Copilot reply."""
    global _last_postscript_at, _last_postscript_sig
    stamp = float(now_ts if now_ts is not None else datetime.now().timestamp())
    wait = max(0.0, float(cooldown_sec or 0.0))
    sig = str(signature or "").strip()
    if sig != _last_postscript_sig:
        _last_postscript_at = stamp
        _last_postscript_sig = sig
        return True
    if stamp - float(_last_postscript_at or 0.0) >= wait:
        _last_postscript_at = stamp
        return True
    return False


def reset_postscript_gate() -> None:
    global _last_postscript_at, _last_postscript_sig
    _last_postscript_at = 0.0
    _last_postscript_sig = ""


def _clip(text: str, limit: int) -> str:
    raw = str(text or "").strip()
    if limit <= 0 or len(raw) <= limit:
        return raw
    if limit == 1:
        return "…"
    return raw[: limit - 1].rstrip() + "…"


def select_relevant_events(
    user_text: str = "",
    events: Optional[List[Dict[str, Any]]] = None,
    limit: int = 4,
    topics: Optional[List[str]] = None,
    goal_topics: Optional[List[str]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Rank diary rows for the question: topic, then goal, then recency. Not a keyword dump."""
    rows = list(events or [])
    if not rows:
        return []
    try:
        from core.companion_profile import infer_topics, rank_events
        wanted = list(topics) if topics is not None else infer_topics(user_text)
        return rank_events(
            user_text,
            rows,
            limit=limit,
            topics=wanted,
            goal_topics=goal_topics,
            now=now,
        )
    except Exception:
        interesting = [item for item in rows if item.get("kind") != "session_day"] or rows
        return interesting[-max(1, int(limit)):]


def _format_context_event(event: Dict[str, Any]) -> str:
    ts = str(event.get("ts") or "")[:10]
    kind = str(event.get("kind") or "")
    outcome = str(event.get("outcome") or "")
    summary = _clip(event.get("summary") or "", 90)
    weight = event_weight(event)
    suffix = f" ×{weight}" if weight > 1 else ""
    return f"- {ts} {kind}/{outcome}: {summary}{suffix}"


def derive_machine_hints(
    events: Optional[List[Dict[str, Any]]] = None,
    skills: Optional[List[CompanionSkill]] = None,
    *,
    limit: int = 3,
    now: Optional[datetime] = None,
    for_nudge: bool = False,
) -> List[Dict[str, str]]:
    """1–3 short machine-specific hints. Not a journal dump."""
    rows = list(events or [])
    stamp = now or datetime.now()
    band = time_band(stamp)
    hints: List[Dict[str, str]] = []

    def _add(issue: str, text: str, bands: Optional[set] = None, recent_kinds: Optional[set] = None) -> None:
        if len(hints) >= max(1, int(limit)):
            return
        if any(item.get("issue_class") == issue for item in hints):
            return
        if for_nudge and bands and band not in bands:
            return
        if for_nudge and recent_kinds and not _has_recent(rows, recent_kinds, stamp, days=3):
            return
        hints.append({"issue_class": issue, "text": _clip(text, 160)})

    late_wifi = _weighted_kinds(rows, {"wifi_weak", "ping_high"}, tags_any=_LATE_BANDS)
    repaired = _weighted_kinds(rows, {"wifi_repaired", "ping_repaired"}, outcome="ok")
    if late_wifi >= 2:
        _add(
            "wifi_weak",
            "Wi-Fi hay yếu buổi tối trên máy này — có thể tắt tiết kiệm điện Wi-Fi, không tự đổi DNS.",
            bands=_LATE_BANDS,
            recent_kinds={"wifi_weak", "ping_high", "wifi_repaired"},
        )
    elif repaired >= 1 and _weighted_kinds(rows, {"wifi_weak", "ping_high"}) >= 2:
        _add(
            "wifi_weak",
            "Sửa Wi-Fi an toàn đã giúp máy này — lần sau ưu tiên reconnect / tắt tiết kiệm pin.",
            recent_kinds={"wifi_weak", "wifi_repaired", "ping_high", "ping_repaired"},
        )
    if _weighted_kinds(rows, {"thermal_warn"}) >= 2:
        _add(
            "thermal",
            "Nhiệt vượt ngưỡng hơn một lần — xem giám sát nhiệt; có thể bật tiết kiệm pin.",
            recent_kinds={"thermal_warn"},
        )
    if _weighted_kinds(rows, {"ram_optimized"}, outcome="ok") >= 1 and _weighted_kinds(rows, {"high_ram"}) >= 2:
        _add(
            "high_ram",
            "RAM hay cao và thu hồi standby đã giúp — gợi ý Thu hồi RAM, không tắt app.",
            recent_kinds={"high_ram", "ram_optimized"},
        )
    elif _weighted_kinds(rows, {"high_ram"}) >= 3:
        _add(
            "high_ram",
            "RAM hay cao trên máy này — có thể thu hồi RAM standby, không tắt app đang dùng.",
            recent_kinds={"high_ram"},
        )
    if _weighted_kinds(rows, {"clean_freed", "clean_light"}) >= 3:
        _add(
            "disk_low",
            "Máy hay dọn rác — lần sau ưu tiên Dọn nhẹ, không WinSxS.",
            recent_kinds={"clean_freed", "clean_light"},
        )
    if _weighted_kinds(rows, {"focus_mode"}) >= 2:
        _add(
            "focus",
            "Bạn hay bật Trước thi / họp — có thể gợi ý lại trước giờ học, không tự bật.",
            bands={"evening", "afternoon"},
            recent_kinds={"focus_mode"},
        )
    if _weighted_kinds(rows, {"update_fail"}) >= 1 and _weighted_kinds(rows, {"update_ok"}) == 0:
        _add(
            "update",
            "Lần cập nhật gần đây không xong — kiểm tra mạng trước khi tải lại.",
            recent_kinds={"update_fail"},
        )
    if skills and not for_nudge and len(hints) < limit:
        for skill in skills:
            if len(hints) >= limit:
                break
            if any(item.get("issue_class") == skill.issue_class for item in hints):
                continue
            _add(skill.issue_class, skill.suggest)
    return hints[: max(1, int(limit))]


def _weighted_kinds(
    events: List[Dict[str, Any]],
    kinds: set,
    *,
    tags_any: Optional[set] = None,
    outcome: str = "",
) -> int:
    total = 0
    for event in events:
        if str(event.get("kind") or "") not in kinds:
            continue
        if outcome and str(event.get("outcome") or "") != outcome:
            continue
        if tags_any and not (set(event.get("tags") or []) & tags_any):
            continue
        total += event_weight(event)
    return total


def _has_recent(events: List[Dict[str, Any]], kinds: set, now: datetime, days: int = 3) -> bool:
    cutoff = now.timestamp() - max(1, int(days)) * 86400
    for event in events:
        if str(event.get("kind") or "") not in kinds:
            continue
        raw = str(event.get("ts") or "")
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "")).timestamp()
        except Exception:
            continue
        if ts >= cutoff:
            return True
    return False


def explain_stage_progress(stage: Optional[StageInfo] = None, *, config_manager: Optional[Any] = None, base_dir: Optional[str] = None) -> str:
    info = stage if isinstance(stage, StageInfo) else current_stage(config_manager=config_manager, base_dir=base_dir)
    return explain_stage_vi(info.active_days, info.positive_feedback, info.skills_count)


def recent_learning_text(
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    limit: int = 2,
) -> str:
    rows = [
        item for item in recent_events(days=14, limit=30, base_dir=base_dir, now=now)
        if item.get("kind") not in ("session_day", "reflection")
    ]
    if not rows:
        return ""
    bits = []
    for item in reversed(rows):
        summary = str(item.get("summary") or "").strip()
        if not summary:
            continue
        weight = event_weight(item)
        if weight > 1:
            summary = f"{summary} (×{weight})"
        bits.append(summary)
        if len(bits) >= max(1, int(limit)):
            break
    if not bits:
        return ""
    return "Mới ghi nhận: " + "; ".join(bits)


def active_guidance_text(base_dir: Optional[str] = None, limit: int = 2) -> str:
    skills = load_skills(base_dir)
    if not skills:
        return ""
    lines = [f"• {skill.suggest}" for skill in skills[: max(1, int(limit))]]
    return "Gợi ý đã học:\n" + "\n".join(lines)


def _grounding_parts(
    user_text: str = "",
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    event_limit: int = 4,
) -> Dict[str, Any]:
    """Profile, goal, and the diary rows that match this question."""
    from core.companion_profile import (
        format_goal_status,
        format_profile_lines,
        goal_status,
        infer_topics,
        load_profile,
        refresh_profile,
    )
    try:
        profile = refresh_profile(base_dir=base_dir, now=now)
    except Exception:
        profile = load_profile(base_dir)
    topics = infer_topics(user_text)
    status = goal_status(base_dir=base_dir, now=now, profile=profile)
    goal_topics = list(status.get("topics") or []) if status else []
    events = recent_events(days=21, limit=40, base_dir=base_dir, now=now)
    # A named topic stays on that topic. A vague question may lean on the goal.
    if topics:
        rank_goal = goal_topics if set(goal_topics) & set(topics) else []
    else:
        rank_goal = goal_topics
    picked = select_relevant_events(
        user_text,
        events,
        limit=event_limit,
        topics=topics,
        goal_topics=rank_goal,
        now=now,
    )
    return {
        "profile": profile,
        "topics": topics,
        "events": events,
        "picked": picked,
        "goal": status,
        "profile_lines": format_profile_lines(profile, topics or None, limit=2),
        "goal_text": format_goal_status(profile, base_dir=base_dir, now=now, events=events),
    }


def build_prompt_context(
    user_text: str = "",
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    char_budget: int = CONTEXT_CHAR_BUDGET,
) -> str:
    if config_manager is not None and not is_enabled(config_manager):
        return ""
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    parts = _grounding_parts(user_text, base_dir=base_dir, now=now, event_limit=4)
    picked = parts["picked"]
    events = parts["events"]
    if picked:
        digest = "\n".join(_format_context_event(item) for item in picked)
    else:
        digest = "Nhật ký máy còn trống (cài mới). Không bịa kỷ niệm."
    skills = match_skills(user_text=user_text, base_dir=base_dir, limit=2)
    skills_text = format_skills_context(skills, empty_vi="Chưa có kỹ năng lưu cho máy này.")
    hints = derive_machine_hints(events, skills, limit=2, now=now, for_nudge=False)
    if parts["topics"]:
        hints = [item for item in hints if _hint_matches_topics(item, parts["topics"])]
    hint_text = "\n".join(f"- {item['text']}" for item in hints[:2]) or "Chưa đủ mẫu lặp để gợi ý riêng máy này."
    note = _clip(latest_reflection(base_dir) or "Chưa có sổ tay (chưa phản tỉnh hoặc cài mới).", 160)
    try:
        from core.companion_moment import exam_focus_is_live, machine_stress_active, stage_voice
        from core.companion_profile import effective_coaching, score_trust
        profile = parts.get("profile") or {}
        asked = parts.get("topics") or []
        voice_topic = asked[0] if len(asked) == 1 else ""
        trust = score_trust(profile=profile, base_dir=base_dir, now=now)
        try:
            from core.companion_learning import voice_tone_kwargs
            tone_extra = voice_tone_kwargs(base_dir)
        except Exception:
            tone_extra = {}
        voice = stage_voice(
            stage.stage,
            coaching=effective_coaching(
                profile,
                topic=voice_topic,
                base_dir=base_dir,
                now=now,
            ),
            may_propose=bool(stage.may_propose_actions),
            trust=str(trust.get("level") or "steady"),
            focus_active=exam_focus_is_live(),
            stressed=machine_stress_active(events, now),
            **tone_extra,
        )
        policy = voice["policy_vi"]
    except Exception:
        policy = (
            "Hỏi nhiều, đề xuất ít."
            if stage.ask_more
            else "Có thể đề xuất dọn nhẹ / Trước thi / thu hồi RAM — không tự chạy, không WinSxS/registry."
        )
        if not stage.may_propose_actions:
            policy += " Người dùng chưa bật quyền đề xuất hành động."
    profile_lines = parts["profile_lines"]
    profile_text = "\n".join(f"- {line}" for line in profile_lines) or "Chưa đủ mẫu để ghi thói quen máy này."
    goal_text = parts["goal_text"] or "Không đặt mục tiêu."
    lines = [
        "[AI đồng hành — bộ nhớ local trên máy này, không phải AGI]",
        f"Giai đoạn: {stage.badge_vi()} ({stage.active_days} ngày dùng máy).",
        stage.blurb_vi,
        f"Quy tắc: {policy}",
    ]
    try:
        from core.companion_learning import prompt_learn_line
        learned_line = prompt_learn_line(base_dir=base_dir, now=now)
    except Exception:
        learned_line = ""
    if learned_line:
        lines.append(learned_line)
    try:
        from core.companion_profile import format_muted_policy
        muted_line = format_muted_policy(base_dir=base_dir, now=now)
    except Exception:
        muted_line = ""
    if muted_line:
        lines.append(muted_line)
    try:
        from core.companion_profile import format_user_note_lines
        taught = format_user_note_lines(parts.get("profile"), parts.get("topics") or None, limit=2)
    except Exception:
        taught = []
    lines.extend([
        "Về máy này:",
        profile_text,
    ])
    if taught:
        lines.append("Lời bạn đã dạy (chỉ nhắc đúng câu này, không bịa thêm phần cứng):")
        lines.extend(f"- {line}" for line in taught)
    lines.extend([
        "Mục tiêu:",
        goal_text,
        "Gợi ý máy này:",
        hint_text,
        "Nhật ký liên quan:",
        digest,
        "Kỹ năng khớp máy này:",
        skills_text,
        "Sổ tay:",
        note,
        "Không bịa kỷ niệm. Nếu nhật ký trống, nói chưa có dữ liệu.",
    ])
    offer = pending_skill_offer(base_dir)
    if offer:
        lines.append(
            f"Gợi ý lưu kỹ năng: {offer.get('title')} "
            f"(đã lặp {offer.get('hit_count')} lần). Chỉ lưu khi người dùng đồng ý."
        )
    text = "\n".join(lines)
    budget = max(240, int(char_budget or CONTEXT_CHAR_BUDGET))
    return _clip(text, budget)


def _hint_matches_topics(hint: Dict[str, str], topics: List[str]) -> bool:
    issue = str(hint.get("issue_class") or "")
    mapping = {
        "wifi_weak": "wifi",
        "thermal": "thermal",
        "high_ram": "ram",
        "disk_low": "disk",
        "focus": "focus",
        "update": "update",
    }
    topic = mapping.get(issue, "")
    return not topic or topic in topics


def is_memory_question(user_text: str) -> bool:
    blob = str(user_text or "").lower()
    return any(token in blob for token in _MEMORY_HINTS)


def local_grounding_text(
    user_text: str = "",
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Short machine-specific note when Gemini is unavailable. Empty if companion is off."""
    if config_manager is not None and not is_enabled(config_manager):
        return ""
    try:
        stage = current_stage(config_manager=config_manager, base_dir=base_dir)
        parts = _grounding_parts(user_text, base_dir=base_dir, now=now, event_limit=2)
    except Exception:
        return ""
    bits = [f"🌱 {stage.badge_vi()}"]
    if stage.stage <= 0:
        try:
            from core.companion_moment import stage_voice
            aside = stage_voice(0).get("aside_vi") or ""
        except Exception:
            aside = ""
        if aside:
            bits.append(aside)
    if stage.empty and not parts["picked"]:
        bits.append("Nhật ký máy còn trống — mình chưa có kỷ niệm trên máy này.")
        return " ".join(bits)
    if parts["profile_lines"]:
        bits.append("Về máy này: " + parts["profile_lines"][0])
    try:
        from core.companion_profile import format_user_note_lines
        taught = format_user_note_lines(
            parts.get("profile"),
            parts.get("topics") or None,
            limit=1,
            include_style=not parts.get("topics"),
        )
    except Exception:
        taught = []
    if taught:
        bits.append(taught[0])
    goal = parts.get("goal")
    topics = parts.get("topics") or []
    if goal and (not topics or goal.get("topic") in topics or set(goal.get("topics") or []) & set(topics)):
        summary = str(goal.get("summary_vi") or "").strip()
        if summary:
            bits.append(summary)
        nxt = str(goal.get("next_action_vi") or "").strip()
        if nxt and int(goal.get("related_count") or 0) > 0:
            bits.append(nxt)
    picked = parts.get("picked") or []
    if picked:
        summary = _clip(picked[-1].get("summary") or "", 90)
        if summary:
            bits.append(f"Nhật ký: {summary}")
    elif stage.ask_more:
        bits.append("Bạn có hay gặp tình trạng này trên máy này không?")
    return " ".join(bit for bit in bits if bit)


def memory_answer(
    user_text: str = "",
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
) -> str:
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    digest = diary_digest(base_dir=base_dir)
    skills = load_skills(base_dir)
    note = latest_reflection(base_dir)
    try:
        from core.companion_profile import format_profile_browse
        profile_text = format_profile_browse(base_dir=base_dir)
    except Exception:
        profile_text = ""
    lines = [
        f"🌱 AI đồng hành — {stage.badge_vi()}",
        stage.blurb_vi,
        "",
        "Hồ sơ máy này:",
        profile_text or "Chưa có hồ sơ thói quen.",
        "",
        "Nhật ký máy này:",
        digest,
        "",
        "Kỹ năng đã lưu:",
        format_skills_context(skills),
        "",
        "Sổ tay:",
        note or f"Chưa có sổ tay. Bấm {REFLECT_BUTTON_VI} khi đã dùng app vài ngày.",
        "",
        "Mình không tự huấn luyện mô hình; chỉ nhớ sự kiện local, riêng tư trên máy này.",
    ]
    offer = pending_skill_offer(base_dir)
    if offer:
        lines.extend([
            "",
            f"Máy này lặp lại «{offer.get('title')}» ({offer.get('hit_count')} lần). "
            "Bạn có muốn lưu thành kỹ năng gợi ý không?",
        ])
    return "\n".join(lines)


def companion_actions(
    user_text: str,
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """Return (action_key, label) the Copilot may attach — never silent, never destructive."""
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    if not stage.may_propose_actions:
        return []
    try:
        from core.companion_moment import action_cap_for_stage
        from core.companion_profile import effective_coaching, load_profile, score_trust
        from core.companion_skills import BLOCKED_ACTION_KEYS
        profile = load_profile(base_dir)
        trust = score_trust(profile=profile, base_dir=base_dir)
        # Low trust narrows the cap. High trust still needs stage.may_propose_actions
        # above, and blocked keys are dropped below.
        cap = action_cap_for_stage(
            stage.stage,
            coaching=effective_coaching(profile, base_dir=base_dir),
            may_propose=True,
            trust=str(trust.get("level") or "steady"),
        )
    except Exception:
        cap = 2
        BLOCKED_ACTION_KEYS = frozenset()
    if cap <= 0:
        return []
    actions: List[Tuple[str, str]] = []
    for skill in match_skills(user_text=user_text, base_dir=base_dir, limit=cap):
        if skill.action_key and skill.action_key not in BLOCKED_ACTION_KEYS:
            actions.append((skill.action_key, skill.suggest[:48]))
    return actions[:cap]


def maybe_run_reflection(
    config_manager: Optional[Any] = None,
    *,
    force: bool = False,
    now: Optional[datetime] = None,
    provider=None,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    if config_manager is not None and not is_enabled(config_manager):
        return None
    if not force and not bool(_cfg_get(config_manager, "companion_reflection_enabled", True)):
        return None
    stamp = now or datetime.now()
    if diary_is_empty(base_dir=base_dir, now=stamp):
        if force:
            return {"note": "", "source": "empty"}
        return None
    state = load_state(base_dir)
    today = stamp.strftime("%Y-%m-%d")
    if not force and state.get("last_reflection_date") == today:
        try:
            from core.companion_learning import ensure_daily_model
            ensure_daily_model(now=stamp, base_dir=base_dir, config_manager=config_manager)
        except Exception:
            pass
        return None
    if not force:
        try:
            hour = int(_cfg_get(config_manager, "companion_reflection_hour", DEFAULT_REFLECTION_HOUR) or DEFAULT_REFLECTION_HOUR)
        except (TypeError, ValueError):
            hour = DEFAULT_REFLECTION_HOUR
        if stamp.hour < hour:
            return None
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    events = recent_events(days=21, limit=0, base_dir=base_dir, now=stamp)
    counts = count_by_kind(events)
    profile_text = ""
    goal_text = ""
    prefer: List[str] = []
    try:
        from core.companion_profile import (
            format_goal_status,
            format_profile_lines,
            goal_issue_classes,
            refresh_profile,
        )
        profile = refresh_profile(base_dir=base_dir, now=stamp, events=events)
        profile_text = "\n".join(format_profile_lines(profile, limit=3))
        goal_text = format_goal_status(profile, base_dir=base_dir, now=stamp, events=events)
        prefer = goal_issue_classes(profile)
    except Exception:
        profile_text = ""
        goal_text = ""
        prefer = []
    new_skills = crystallize_skills(
        counts,
        events,
        base_dir=base_dir,
        max_new=2,
        prefer_issues=prefer,
    )
    if new_skills:
        state_now = load_state(base_dir)
        offer = state_now.get("pending_skill_offer")
        saved_issues = {skill.issue_class for skill in new_skills}
        if isinstance(offer, dict) and str(offer.get("issue_class") or "") in saved_issues:
            state_now["pending_skill_offer"] = None
            save_state(state_now, base_dir=base_dir)
        for skill in new_skills:
            record_app_event(
                "skill_saved",
                f"Đã kết tinh kỹ năng: {skill.title}",
                metrics={"count": skill.hit_count},
                source="companion",
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
                coalesce=False,
            )
    digest = diary_digest(base_dir=base_dir, now=stamp)
    skills_text = format_skills_context(load_skills(base_dir))
    llm = provider if provider is not None else resolve_llm_provider(config_manager)
    result = run_reflection(
        digest=digest,
        kind_counts=counts,
        active_days=stage.active_days,
        stage_label=stage.badge_vi(),
        skills_text=skills_text,
        provider=llm,
        base_dir=base_dir,
        now=stamp,
        profile_text=profile_text,
        goal_text=goal_text,
    )
    if new_skills and result.get("source") == "template":
        titles = ", ".join(skill.title for skill in new_skills)
        extra = f"Đã kết tinh kỹ năng từ thói quen lặp lại: {titles}."
        note = (str(result.get("note") or "").rstrip() + "\n" + extra).strip()
        from core.companion_reflection import save_reflection
        result["note"] = save_reflection(note, source="template", base_dir=base_dir, now=stamp)
    result["skills"] = [skill.issue_class for skill in new_skills]
    state = load_state(base_dir)
    state["last_reflection_date"] = today
    save_state(state, base_dir=base_dir)
    try:
        from core.companion_learning import ensure_daily_model
        ensure_daily_model(now=stamp, base_dir=base_dir, config_manager=config_manager)
    except Exception:
        pass
    record_app_event(
        "reflection",
        "Đã ghi sổ tay buổi tối" if result.get("source") != "template" else "Đã ghi sổ tay từ số liệu (không LLM)",
        source="companion",
        now=stamp,
        base_dir=base_dir,
        config_manager=config_manager,
    )
    return result


def observe_snapshot(
    *,
    ram_percent: Optional[float] = None,
    ram_threshold: float = 80.0,
    wifi_unstable: bool = False,
    ping_ms: Optional[float] = None,
    ping_threshold: float = 180.0,
    thermal_c: Optional[float] = None,
    thermal_warn_c: Optional[float] = None,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Light, cooldown-gated snapshots. No disk-scan listings."""
    if config_manager is not None and not is_enabled(config_manager):
        return []
    stamp = now or datetime.now()
    ts = stamp.timestamp()
    recorded: List[Dict[str, Any]] = []
    state = mark_active_day(now=stamp, base_dir=base_dir)

    def _due(key: str) -> bool:
        last = float(state.get(key) or 0.0)
        return last <= 0 or (ts - last) >= SNAPSHOT_COOLDOWN_SEC

    try:
        stamps: Dict[str, float] = {}
        if ram_percent is not None and float(ram_percent) >= float(ram_threshold) and _due("last_high_ram_ts"):
            event = record_app_event(
                "high_ram",
                f"RAM cao {float(ram_percent):.0f}% (ngưỡng {float(ram_threshold):.0f}%)",
                metrics={"ram_percent": float(ram_percent)},
                source="snapshot",
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
            )
            if event:
                recorded.append(event)
                stamps["last_high_ram_ts"] = ts
        if wifi_unstable and _due("last_wifi_ts"):
            event = record_app_event(
                "wifi_weak",
                "Wi-Fi yếu hoặc không ổn định trên máy này",
                source="snapshot",
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
            )
            if event:
                recorded.append(event)
                stamps["last_wifi_ts"] = ts
        if ping_ms is not None:
            ping_val = float(ping_ms)
            if ping_val > float(ping_threshold) and _due("last_ping_ts"):
                event = record_app_event(
                    "ping_high",
                    f"Ping cao {ping_val:.0f} ms",
                    metrics={"ping_ms": ping_val},
                    source="snapshot",
                    now=stamp,
                    base_dir=base_dir,
                    config_manager=config_manager,
                )
                if event:
                    recorded.append(event)
                    stamps["last_ping_ts"] = ts
        if thermal_c is not None and thermal_warn_c is not None:
            if float(thermal_c) >= float(thermal_warn_c) and _due("last_thermal_ts"):
                event = record_app_event(
                    "thermal_warn",
                    f"Nhiệt đo được {float(thermal_c):.0f}°C (ngưỡng {float(thermal_warn_c):.0f}°C)",
                    metrics={"thermal_c": float(thermal_c)},
                    source="snapshot",
                    now=stamp,
                    base_dir=base_dir,
                    config_manager=config_manager,
                )
                if event:
                    recorded.append(event)
                    stamps["last_thermal_ts"] = ts
        if stamps:
            fresh = load_state(base_dir)
            fresh.update(stamps)
            save_state(fresh, base_dir=base_dir)
    except Exception:
        return recorded
    return recorded


def observe_clean(junk_mb: float, ram_mb: float = 0.0, light: bool = False, **kwargs) -> Optional[Dict[str, Any]]:
    junk = float(junk_mb or 0)
    ram = float(ram_mb or 0)
    if junk < 1 and ram < 1:
        return None
    kind = "clean_light" if light else "clean_freed"
    label = "Dọn nhẹ" if light else "Dọn rác"
    return record_app_event(
        kind,
        f"{label} giải phóng {junk:.0f} MB rác" + (f", {ram:.0f} MB RAM" if ram else ""),
        metrics={"junk_freed_mb": junk, "ram_freed_mb": ram},
        outcome="ok",
        **kwargs,
    )


def observe_ram_optimized(freed_mb: float, ram_percent: Optional[float] = None, **kwargs) -> Optional[Dict[str, Any]]:
    metrics: Dict[str, Any] = {"ram_freed_mb": float(freed_mb or 0)}
    if ram_percent is not None:
        metrics["ram_percent"] = float(ram_percent)
    return record_app_event(
        "ram_optimized",
        f"Thu hồi RAM {float(freed_mb or 0):.0f} MB",
        metrics=metrics,
        **kwargs,
    )


def observe_focus_enabled(result: Optional[Dict[str, Any]] = None, **kwargs) -> Optional[Dict[str, Any]]:
    info = result if isinstance(result, dict) else {}
    if info.get("already_active"):
        return None
    junk = float(info.get("freed_junk_mb") or 0)
    ram = float(info.get("freed_ram_mb") or 0)
    source = str(kwargs.pop("source", "") or "focus")
    event = record_app_event(
        "focus_mode",
        "Người dùng bật Trước thi / họp"
        + (f" (dọn nhẹ {junk:.0f} MB)" if junk else ""),
        metrics={"junk_freed_mb": junk, "ram_freed_mb": ram},
        source=source,
        outcome="ok",
        tags=["focus", "start"],
        **kwargs,
    )
    if event:
        try:
            from core.companion_moment import note_focus_started
            note_focus_started(
                now=kwargs.get("now"),
                base_dir=kwargs.get("base_dir"),
                config_manager=kwargs.get("config_manager"),
            )
        except Exception:
            pass
    return event


def observe_focus_disabled(result: Optional[Dict[str, Any]] = None, **kwargs) -> Optional[Dict[str, Any]]:
    """Diary line when the user turns Trước thi / họp off. Does not turn it on."""
    info = result if isinstance(result, dict) else {}
    if info.get("already_inactive"):
        return None
    try:
        from core.companion_moment import note_focus_ended
        event = note_focus_ended(
            now=kwargs.get("now"),
            base_dir=kwargs.get("base_dir"),
            config_manager=kwargs.get("config_manager"),
            write_diary=True,
        )
    except Exception:
        return None
    return event if isinstance(event, dict) else None


def observe_wifi_repaired(recovered: bool = False, **kwargs) -> Optional[Dict[str, Any]]:
    source = str(kwargs.pop("source", "") or "network")
    return record_app_event(
        "wifi_repaired",
        "Wi-Fi đã ổn định lại" if recovered else "Đã thử sửa Wi-Fi nhưng chưa ổn định",
        source=source,
        outcome="ok" if recovered else "fail",
        tags=["wifi"],
        **kwargs,
    )


def observe_ping_repaired(recovered: bool = False, **kwargs) -> Optional[Dict[str, Any]]:
    return record_app_event(
        "ping_repaired",
        "Ping đã đo được lại" if recovered else "Đã thử sửa mạng nhưng ping chưa đo được",
        outcome="ok" if recovered else "fail",
        tags=["ping", "wifi"],
        source=kwargs.pop("source", None) or "network",
        **kwargs,
    )


def observe_update(success: bool, summary: str = "", **kwargs) -> Optional[Dict[str, Any]]:
    kind = "update_ok" if success else "update_fail"
    text = str(summary or "").strip() or (
        "Đã tải bản cập nhật và mở trình cài" if success else "Cập nhật không thành công"
    )
    return record_app_event(
        kind,
        text,
        source=kwargs.pop("source", None) or "update",
        outcome="ok" if success else "fail",
        tags=["update"],
        **kwargs,
    )


_ACTION_LABELS_VI = {
    "optimize_ram": "thu hồi RAM",
    "optimize_ram_only": "thu hồi RAM",
    "clean_light": "dọn nhẹ",
    "clean_junk": "dọn rác",
    "clean_disk": "dọn ổ đĩa",
    "enable_exam_focus": "Trước thi / họp",
    "toggle_exam_focus": "Trước thi / họp",
    "repair_network_now": "sửa mạng",
    "optimize_network": "tối ưu mạng",
    "view_hardware": "xem nhiệt",
    "open_hardware_dialog": "xem nhiệt",
    "battery_saver": "tiết kiệm pin",
    "enable_game_boost": "Game Boost",
    "auto_optimize_all": "tối ưu toàn diện",
}


def observe_suggestion(accepted: bool, action_key: str = "", title: str = "", **kwargs) -> Optional[Dict[str, Any]]:
    key = str(action_key or "").strip()
    if key.startswith("whitelist_proc:"):
        label = "thêm tiến trình vào danh sách trắng"
        tag = "whitelist"
    else:
        label = str(title or "").strip() or _ACTION_LABELS_VI.get(key) or "một gợi ý"
        tag = key.split(":", 1)[0][:24]
    kind = "suggestion_accepted" if accepted else "suggestion_rejected"
    verb = "làm theo" if accepted else "từ chối"
    tags = ["suggestion"]
    if tag:
        tags.append(tag)
    return record_app_event(
        kind,
        f"Người dùng {verb} gợi ý: {label}",
        source=kwargs.pop("source", None) or "user",
        outcome="accepted" if accepted else "rejected",
        tags=tags,
        **kwargs,
    )


def _nudge_topic_snoozed(issue_class: str, base_dir: Optional[str], now: datetime) -> bool:
    """Đừng nhắc hides that tip family from soft nudges until the 3-day window ends."""
    try:
        from core.companion_profile import topic_for_issue, topic_is_snoozed
        topic = topic_for_issue(issue_class)
        if not topic:
            return False
        return topic_is_snoozed(topic, base_dir=base_dir, now=now)
    except Exception:
        return False


def companion_nudge_snooze_button(tip: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """Đừng nhắc for a soft info nudge.

    Thermal warnings and Wi-Fi/ping emergency toasts are warning or danger
    (or critical=True). Those never get this button.
    """
    try:
        from core.companion_profile import TOPIC_META, tip_snooze_allowed
    except Exception:
        return None
    if not isinstance(tip, dict):
        return None
    if not tip_snooze_allowed(
        level=str(tip.get("level") or "info"),
        critical=bool(tip.get("critical")),
    ):
        return None
    topic = str(tip.get("snooze_topic") or "").strip()
    if topic not in TOPIC_META:
        return None
    return {"label_vi": "Đừng nhắc", "topic": topic}


def _nudge_topic_blocked(issue_class: str, base_dir: Optional[str], now: datetime) -> bool:
    """Muted topics and topic-level ask-more stay out of proactive nudges."""
    try:
        from core.companion_profile import active_muted_topics, topic_asks_more, topic_for_issue
        topic = topic_for_issue(issue_class)
        if not topic:
            return False
        if topic in active_muted_topics(base_dir=base_dir, now=now):
            return True
        return topic_asks_more(topic, base_dir=base_dir)
    except Exception:
        return False


def _notifications_allowed(config_manager: Optional[Any]) -> bool:
    if config_manager is None:
        return True
    show = _cfg_get(config_manager, "show_notifications", True)
    instant = _cfg_get(config_manager, "instant_screen_notifications_enabled", True)
    return bool(show) or bool(instant)


def plan_companion_nudge(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
    commit: bool = True,
) -> Optional[Dict[str, str]]:
    """One calm tip when maturity or evidence is enough. None when throttled or disabled."""
    if config_manager is not None and not is_enabled(config_manager):
        return None
    if not bool(_cfg_get(config_manager, "companion_nudges_enabled", True)):
        return None
    if not _notifications_allowed(config_manager):
        return None
    stamp = now or datetime.now()
    try:
        from core.companion_profile import in_quiet_hours
        if in_quiet_hours(stamp, base_dir=base_dir):
            return None
    except Exception:
        pass
    try:
        from core.companion_moment import exam_focus_is_live
        if exam_focus_is_live():
            return None
    except Exception:
        pass
    events = recent_events(days=21, limit=0, base_dir=base_dir, now=stamp)
    if not events:
        return None
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    watched = ("wifi_weak", "ping_high", "thermal_warn", "high_ram", "focus_mode", "clean_freed", "clean_light")
    evidence = 0
    distinct = 0
    for kind in watched:
        evidence = max(evidence, _weighted_kinds(events, {kind}))
        distinct = max(distinct, sum(1 for item in events if item.get("kind") == kind))
    mature = stage.stage >= 2
    # One coalesced burst is not a habit. Stage 1 needs repeated episodes.
    enough = stage.stage >= 1 and evidence >= 4 and distinct >= 2
    if not mature and not enough:
        return None
    hints = derive_machine_hints(events, load_skills(base_dir), limit=3, now=stamp, for_nudge=True)
    hints = [
        item for item in hints
        if not _nudge_topic_blocked(str(item.get("issue_class") or ""), base_dir, stamp)
        and not _nudge_topic_snoozed(str(item.get("issue_class") or ""), base_dir, stamp)
    ]
    if not hints:
        return None
    chosen = dict(hints[0])
    try:
        from core.companion_profile import WINDOW_PHRASE, active_time_windows, load_profile, topic_for_issue
        topic = topic_for_issue(str(chosen.get("issue_class") or ""))
        windows = active_time_windows(events, now=stamp, profile=load_profile(base_dir))
        if topic and any(str(item.get("topic") or "") == topic for item in windows):
            message = str(chosen.get("text") or "").rstrip()
            if WINDOW_PHRASE not in message:
                message = f"{message} {WINDOW_PHRASE}."
            chosen["text"] = _clip(message, 220)
    except Exception:
        pass
    state = load_state(base_dir)
    now_ts = stamp.timestamp()
    try:
        last_ts = float(state.get("last_nudge_ts") or 0.0)
    except (TypeError, ValueError):
        last_ts = 0.0
    last_class = str(state.get("last_nudge_class") or "")
    if last_ts > 0 and (now_ts - last_ts) < NUDGE_COOLDOWN_SEC:
        return None
    if last_class and last_class == chosen["issue_class"] and last_ts > 0 and (now_ts - last_ts) < NUDGE_SAME_CLASS_SEC:
        return None
    payload = {
        "title": "AI đồng hành",
        "message": chosen["text"],
        "issue_class": chosen["issue_class"],
        "level": "info",
        "critical": False,
    }
    try:
        from core.companion_profile import topic_for_issue
        family = topic_for_issue(str(chosen.get("issue_class") or ""))
        if family:
            payload["snooze_topic"] = family
            payload["snooze_label_vi"] = "Đừng nhắc"
    except Exception:
        pass
    if commit:
        state["last_nudge_ts"] = now_ts
        state["last_nudge_class"] = chosen["issue_class"]
        save_state(state, base_dir=base_dir)
    return payload


MEMORY_EXPORT_KIND = "pc_cleaner_companion_memory"
MEMORY_EXPORT_VERSION = 1
_MEMORY_NOTE_VI = "Bản sao bộ nhớ trên một máy. Không phải đồng bộ đám mây."


_EXPORT_SECRET_KEYS = frozenset({
    "ai_copilot_gemini_api_key",
    "email_report_smtp_password",
    "smtp_password",
    "api_key",
    "gemini_api_key",
    "password",
})


def _redact_tree(value: Any, depth: int = 0) -> Any:
    from core.companion_diary import redact_sensitive
    if depth > 8:
        return None
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if value != value or abs(value) == float("inf"):
            return None
        return value
    if isinstance(value, list):
        return [_redact_tree(item, depth + 1) for item in value[:500]]
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in list(value.items())[:80]:
            if str(key) in _EXPORT_SECRET_KEYS:
                continue
            name = redact_sensitive(str(key))[:64]
            if not name or name == "[redacted]":
                continue
            out[name] = _redact_tree(item, depth + 1)
        return out
    return redact_sensitive(str(value))[:200]


def _drop_blocked_actions(value: Any) -> Any:
    """Strip destructive action keys so an imported file cannot run them."""
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
    except Exception:
        BLOCKED_ACTION_KEYS = frozenset()
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if str(key) == "action_key" and str(item or "") in BLOCKED_ACTION_KEYS:
                continue
            out[str(key)] = _drop_blocked_actions(item)
        return out
    if isinstance(value, list):
        return [_drop_blocked_actions(item) for item in value]
    return value


def _scrub_maturity(raw: Any, *, importing: bool = False) -> Dict[str, Any]:
    from core.companion_maturity import default_state
    base = default_state()
    if not isinstance(raw, dict):
        return base if importing else {}
    cleaned = _drop_blocked_actions(raw)
    if not isinstance(cleaned, dict):
        return base if importing else {}
    payload = dict(base) if importing else {}
    for key in base:
        if key in cleaned:
            payload[key] = cleaned[key]
    session = payload.get("focus_session")
    if importing and isinstance(session, dict):
        session = dict(session)
        session["active"] = False
        payload["focus_session"] = session
    return payload


def _memory_error(message: str) -> Dict[str, Any]:
    return {"ok": False, "message_vi": message}


def export_companion_memory(
    path: str,
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Write profile, maturity, skills, diary, and sổ tay already on this PC.

    Secrets are redacted. Destructive action keys are removed. The file is a
    backup for one computer, not a cloud sync.
    """
    import json
    import os
    target = str(path or "").strip()
    if not target:
        return _memory_error("Chưa chọn nơi lưu bản sao.")
    try:
        from core.companion_diary import read_events, redact_sensitive
        from core.companion_profile import load_profile
        from core.companion_reflection import load_reflection, load_reflection_meta
        folder = os.path.dirname(os.path.abspath(target))
        if folder:
            os.makedirs(folder, exist_ok=True)
        payload = {
            "kind": MEMORY_EXPORT_KIND,
            "version": MEMORY_EXPORT_VERSION,
            "exported_at": datetime.now().replace(microsecond=0).isoformat(timespec="seconds"),
            "note_vi": _MEMORY_NOTE_VI,
            "profile": _redact_tree(load_profile(base_dir)),
            "maturity": _scrub_maturity(load_state(base_dir)),
            "skills": _drop_blocked_actions([
                skill.to_dict() for skill in load_skills(base_dir)
            ]),
            "diary": _redact_tree(read_events(base_dir=base_dir, limit=0)),
            "reflection": redact_sensitive(load_reflection(base_dir)),
            "reflection_meta": _redact_tree(load_reflection_meta(base_dir)),
            "learning_model": _redact_tree(_load_learning_model(base_dir)),
        }
        temporary = target + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    except Exception:
        return _memory_error("Chưa xuất được bộ nhớ. Kiểm tra quyền ghi file rồi thử lại.")
    return {
        "ok": True,
        "message_vi": "Đã lưu bản sao bộ nhớ trên máy này. File chỉ để khôi phục, không gửi lên đám mây.",
        "path": target,
    }


def _read_memory_file(path: str) -> Tuple[Optional[Dict[str, Any]], str]:
    import json
    target = str(path or "").strip()
    if not target:
        return None, "Chưa chọn file bộ nhớ."
    try:
        with open(target, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError:
        return None, "File không phải JSON hợp lệ."
    except OSError:
        return None, "Không đọc được file bộ nhớ."
    except Exception:
        return None, "Không đọc được file bộ nhớ."
    if not isinstance(data, dict) or data.get("kind") != MEMORY_EXPORT_KIND:
        return None, "File này không phải bản sao bộ nhớ AI đồng hành."
    try:
        version = int(data.get("version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version != MEMORY_EXPORT_VERSION:
        return None, "Mình chưa đọc được phiên bản file này."
    if not any(key in data for key in ("profile", "maturity", "skills", "diary", "reflection", "learning_model")):
        return None, "File không có bộ nhớ để nhập."
    if "profile" in data and data.get("profile") is not None and not isinstance(data.get("profile"), dict):
        return None, "Hồ sơ trong file không đúng định dạng."
    if "maturity" in data and data.get("maturity") is not None and not isinstance(data.get("maturity"), dict):
        return None, "Giai đoạn trong file không đúng định dạng."
    if "skills" in data and data.get("skills") is not None and not isinstance(data.get("skills"), list):
        return None, "Kỹ năng trong file không đúng định dạng."
    if "diary" in data and data.get("diary") is not None and not isinstance(data.get("diary"), list):
        return None, "Nhật ký trong file không đúng định dạng."
    if "reflection" in data and data.get("reflection") is not None and not isinstance(data.get("reflection"), str):
        return None, "Sổ tay trong file không đúng định dạng."
    if "learning_model" in data and data.get("learning_model") is not None and not isinstance(data.get("learning_model"), dict):
        return None, "Mô hình học trong file không đúng định dạng."
    return data, ""


def _merge_named(local: Any, incoming: Any) -> List[Any]:
    out: List[Any] = []
    seen = set()
    for item in list(local or []) + list(incoming or []):
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or "")
        if ident:
            if ident in seen:
                continue
            seen.add(ident)
        out.append(item)
    return out


def _merge_profiles(local: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(local)
    out["habits"] = _merge_named(local.get("habits"), incoming.get("habits"))[:6]
    out["corrections"] = _merge_named(local.get("corrections"), incoming.get("corrections"))
    out["preferences"] = _merge_named(local.get("preferences"), incoming.get("preferences"))
    dismissed = [str(item) for item in (local.get("dismissed_insights") or []) if str(item).strip()]
    for item in incoming.get("dismissed_insights") or []:
        text = str(item or "").strip()
        if text and text not in dismissed:
            dismissed.append(text)
    out["dismissed_insights"] = dismissed
    def _count(raw: Any, key: str) -> int:
        try:
            return max(0, int((raw or {}).get(key) or 0))
        except (TypeError, ValueError):
            return 0

    local_fb = local.get("feedback") if isinstance(local.get("feedback"), dict) else {}
    incoming_fb = incoming.get("feedback") if isinstance(incoming.get("feedback"), dict) else {}
    out["feedback"] = {
        "helpful": max(_count(local_fb, "helpful"), _count(incoming_fb, "helpful")),
        "unhelpful": max(_count(local_fb, "unhelpful"), _count(incoming_fb, "unhelpful")),
    }
    if str(incoming.get("coaching") or "") == "ask_more" or str(local.get("coaching") or "") == "ask_more":
        out["coaching"] = "ask_more"
    goal = local.get("goal") if isinstance(local.get("goal"), dict) else None
    if not goal or not str(goal.get("text") or "").strip():
        out["goal"] = incoming.get("goal")
    muted = dict(local.get("muted_topics") or {}) if isinstance(local.get("muted_topics"), dict) else {}
    extra_muted = incoming.get("muted_topics") if isinstance(incoming.get("muted_topics"), dict) else {}
    for topic, meta in extra_muted.items():
        if topic not in muted:
            muted[topic] = meta
    out["muted_topics"] = muted
    coaching = dict(local.get("topic_coaching") or {}) if isinstance(local.get("topic_coaching"), dict) else {}
    extra_coaching = incoming.get("topic_coaching") if isinstance(incoming.get("topic_coaching"), dict) else {}
    for topic, mode in extra_coaching.items():
        if str(mode or "") == "ask_more":
            coaching[str(topic)] = "ask_more"
    out["topic_coaching"] = coaching
    out["quiet_hours"] = local.get("quiet_hours")
    try:
        from core.companion_profile import merge_snoozed_tips
        out["snoozed_tips"] = merge_snoozed_tips(local.get("snoozed_tips"), incoming.get("snoozed_tips"))
    except Exception:
        out["snoozed_tips"] = local.get("snoozed_tips") or {}
    try:
        from core.companion_profile import merge_topic_trust
        out["topic_trust"] = merge_topic_trust(local.get("topic_trust"), incoming.get("topic_trust"))
    except Exception:
        out["topic_trust"] = local.get("topic_trust") or {}
    return out


def _store_profile(raw: Any, base_dir: Optional[str], mode: str) -> None:
    from core.companion_profile import load_profile, save_profile
    incoming = _redact_tree(raw) if isinstance(raw, dict) else {}
    if not isinstance(incoming, dict):
        return
    if mode == "replace":
        save_profile(incoming, base_dir=base_dir)
        return
    save_profile(_merge_profiles(load_profile(base_dir), incoming), base_dir=base_dir)


def _merge_helpful_replay(local: Any, incoming: Any) -> Any:
    """Keep the newer Có ích replay. An unsurfaced row wins over one already shown."""
    options = [
        item for item in (local, incoming)
        if isinstance(item, dict) and str(item.get("action_key") or "").strip()
    ]
    best = None
    for item in options:
        if best is None:
            best = item
            continue
        best_shown = bool(best.get("surfaced"))
        item_shown = bool(item.get("surfaced"))
        if best_shown and not item_shown:
            best = item
            continue
        if best_shown == item_shown and str(item.get("at") or "") > str(best.get("at") or ""):
            best = item
    return best


def _merge_pinned_actions(local: Any, incoming: Any) -> List[Any]:
    """Union of favorites, local first, capped at three allowlisted keys."""
    try:
        from core.companion_maturity import _clean_pinned_actions
        cleaned = _clean_pinned_actions(list(local or []) + list(incoming or []))
    except Exception:
        cleaned = []
    return cleaned


def _merge_week_marker(
    local: Dict[str, Any],
    incoming: Dict[str, Any],
    week_key_name: str,
    pending_name: str,
) -> None:
    """Keep the later calendar week. A pending line fills an empty local slot."""
    local_week = str(local.get(week_key_name) or "")
    incoming_week = str(incoming.get(week_key_name) or "")
    if incoming_week > local_week:
        local[week_key_name] = incoming_week
        local[pending_name] = incoming.get(pending_name)
        return
    if incoming_week and incoming_week == local_week and not local.get(pending_name):
        incoming_pending = incoming.get(pending_name)
        if incoming_pending:
            local[pending_name] = incoming_pending


def _store_maturity(raw: Any, base_dir: Optional[str], mode: str) -> None:
    incoming = _scrub_maturity(raw, importing=True)
    if mode == "replace":
        save_state(incoming, base_dir=base_dir)
        return
    local = load_state(base_dir)
    dates = list(local.get("active_dates") or [])
    for day in incoming.get("active_dates") or []:
        text = str(day or "")[:10]
        if len(text) == 10 and text not in dates:
            dates.append(text)
    local["active_dates"] = dates
    local["positive_feedback"] = max(
        int(local.get("positive_feedback") or 0),
        int(incoming.get("positive_feedback") or 0),
    )
    local["negative_feedback"] = max(
        int(local.get("negative_feedback") or 0),
        int(incoming.get("negative_feedback") or 0),
    )
    if not local.get("first_seen"):
        local["first_seen"] = incoming.get("first_seen") or ""
    for key in (
        "pending_followup",
        "pending_outcome",
        "pending_checkin",
        "pending_eod",
        "pending_goal_conflict",
        "pending_stage_up",
        "pending_skill_offer",
    ):
        if not local.get(key) and incoming.get(key):
            local[key] = incoming.get(key)
    if not local.get("focus_session") and incoming.get("focus_session"):
        local["focus_session"] = incoming.get("focus_session")
    shown = []
    for item in list(local.get("shown_milestones") or []) + list(incoming.get("shown_milestones") or []):
        text = str(item or "").strip()
        if text and text not in shown:
            shown.append(text)
    local["shown_milestones"] = shown
    local_day = str(local.get("last_milestone_date") or "")[:10]
    incoming_day = str(incoming.get("last_milestone_date") or "")[:10]
    if incoming_day > local_day:
        local["last_milestone_date"] = incoming_day
    if not (isinstance(local.get("pending_milestone"), dict) and local.get("pending_milestone", {}).get("text")):
        incoming_pending = incoming.get("pending_milestone")
        if isinstance(incoming_pending, dict) and incoming_pending.get("text"):
            local["pending_milestone"] = incoming_pending
    local["helpful_replay"] = _merge_helpful_replay(local.get("helpful_replay"), incoming.get("helpful_replay"))
    local["pinned_actions"] = _merge_pinned_actions(local.get("pinned_actions"), incoming.get("pinned_actions"))
    _merge_week_marker(local, incoming, "last_weekly_strip_week", "pending_weekly_strip")
    _merge_week_marker(local, incoming, "last_exam_hint_week", "pending_exam_hint")
    save_state(local, base_dir=base_dir)


def _store_skills(raw: Any, base_dir: Optional[str], mode: str) -> None:
    from core.companion_skills import BLOCKED_ACTION_KEYS, save_skills, skill_from_dict
    rows = raw if isinstance(raw, list) else []
    incoming = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        cleaned = _drop_blocked_actions(_redact_tree(item))
        skill = skill_from_dict(cleaned) if isinstance(cleaned, dict) else None
        if skill is None or skill.action_key in BLOCKED_ACTION_KEYS:
            continue
        incoming.append(skill)
    if mode == "replace":
        save_skills(incoming, base_dir=base_dir)
        return
    current = {skill.id: skill for skill in load_skills(base_dir)}
    for skill in incoming:
        old = current.get(skill.id)
        if old is None or int(skill.hit_count) > int(old.hit_count):
            current[skill.id] = skill
    save_skills(list(current.values()), base_dir=base_dir)


def _store_diary(raw: Any, base_dir: Optional[str], mode: str) -> None:
    from core.companion_diary import (
        ALLOWED_KINDS as DIARY_KINDS,
        MAX_DIARY_EVENTS,
        event_identity,
        read_events,
        sanitize_summary,
        write_events,
    )
    cleaned: List[Dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").lower()
        if kind not in DIARY_KINDS:
            continue
        summary = sanitize_summary(item.get("summary"))
        if not summary:
            continue
        row = dict(item)
        row["kind"] = kind
        row["summary"] = summary
        cleaned.append(row)
    if mode == "replace":
        write_events(cleaned[-MAX_DIARY_EVENTS:], base_dir=base_dir)
        return
    local = read_events(base_dir=base_dir, limit=0)
    seen = {event_identity(row) for row in local}
    merged = list(local)
    for row in cleaned:
        ident = event_identity(row)
        if ident in seen:
            continue
        merged.append(row)
        seen.add(ident)
    merged.sort(key=lambda row: str(row.get("ts") or ""))
    write_events(merged[-MAX_DIARY_EVENTS:], base_dir=base_dir)


def _load_learning_model(base_dir: Optional[str]) -> Dict[str, Any]:
    try:
        from core.companion_learning import load_daily_model
        return load_daily_model(base_dir)
    except Exception:
        return {}


def _store_learning_model(raw: Any, base_dir: Optional[str], mode: str) -> None:
    from core.companion_learning import load_daily_model, merge_learning_models, save_daily_model
    if not isinstance(raw, dict):
        return
    if mode == "replace":
        save_daily_model(raw, base_dir=base_dir)
        return
    save_daily_model(merge_learning_models(load_daily_model(base_dir), raw), base_dir=base_dir)


def _store_reflection(raw: Any, base_dir: Optional[str], mode: str) -> None:
    from core.companion_diary import redact_sensitive
    from core.companion_reflection import load_reflection, save_reflection
    text = redact_sensitive(raw if isinstance(raw, str) else "")
    if mode != "replace":
        local = load_reflection(base_dir)
        if local and text and text not in local:
            text = local.rstrip() + "\n\n" + text
        elif local and not text:
            text = local
    if text or mode == "replace":
        save_reflection(text, source="import", base_dir=base_dir)


def import_companion_memory(
    path: str,
    mode: str = "merge",
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge or replace local companion memory. Never runs imported actions.

    Blocked action keys are dropped. A restored focus session is stored inactive
    so this PC does not turn Trước thi / họp on by itself.
    """
    chosen = str(mode or "").strip().lower()
    if chosen not in ("merge", "replace"):
        return _memory_error("Chưa rõ cách nhập: gộp hoặc thay thế.")
    data, error = _read_memory_file(path)
    if error or not isinstance(data, dict):
        return _memory_error(error or "Không đọc được file bộ nhớ.")
    try:
        if "profile" in data:
            _store_profile(data.get("profile"), base_dir, chosen)
        if "maturity" in data:
            _store_maturity(data.get("maturity"), base_dir, chosen)
        if "skills" in data:
            _store_skills(data.get("skills"), base_dir, chosen)
        if "diary" in data:
            _store_diary(data.get("diary"), base_dir, chosen)
        if "reflection" in data:
            _store_reflection(data.get("reflection"), base_dir, chosen)
        if "learning_model" in data:
            _store_learning_model(data.get("learning_model"), base_dir, chosen)
    except Exception:
        return _memory_error("Chưa nhập được bộ nhớ. File có thể chưa đúng hoặc máy không ghi được.")
    verb = "Đã thay bộ nhớ trên máy này." if chosen == "replace" else "Đã gộp bộ nhớ vào máy này."
    return {
        "ok": True,
        "message_vi": verb + " Mình không chạy hành động trong file. Đây là bản sao một máy, không đồng bộ đám mây.",
        "mode": chosen,
    }


def empty_states_vi() -> Dict[str, str]:
    return {
        "stage": EMPTY_STAGE_VI,
        "diary": "Chưa có nhật ký — dùng app vài ngày, nhật ký máy sẽ xuất hiện tại đây.",
        "skills": "Chưa có kỹ năng — khi cùng một vấn đề lặp lại, Copilot sẽ đề nghị lưu mẹo cho máy này.",
        "reflection": (
            f"Chưa có sổ tay. Bấm {REFLECT_BUTTON_VI} khi đã có nhật ký; "
            "không có Gemini thì chỉ ghi số liệu."
        ),
        "reflection_empty": (
            f"Chưa có nhật ký — dùng app vài ngày rồi bấm {REFLECT_BUTTON_VI}."
        ),
        "profile": "Chưa có hồ sơ thói quen — dùng máy vài ngày để AI nhớ điều máy này hay gặp.",
        "goal": "Chưa đặt mục tiêu (tuỳ chọn).",
    }


__all__ = [
    "ALLOWED_KINDS",
    "EMPTY_STAGE_VI",
    "POSTSCRIPT_COOLDOWN_SEC",
    "REFLECT_BUTTON_VI",
    "STAGE_BLURBS_VI",
    "STAGE_LABELS_VI",
    "STAGE_LEGEND_VI",
    "StageInfo",
    "accept_skill_offer",
    "build_prompt_context",
    "clear_diary_memory",
    "clear_local_memory",
    "clear_reflection_memory",
    "clear_skills_memory",
    "companion_actions",
    "compute_stage",
    "confirm_clear_prompt",
    "current_stage",
    "decline_skill_offer",
    "delete_diary_entry",
    "delete_saved_skill",
    "diary_digest",
    "diary_is_empty",
    "empty_states_vi",
    "format_diary_browse",
    "format_reflection_feedback",
    "format_skills_browse",
    "has_skill",
    "is_enabled",
    "is_memory_question",
    "issue_class_for_kind",
    "latest_reflection",
    "list_diary_rows",
    "list_skill_rows",
    "load_reflection_meta",
    "match_skills",
    "maybe_run_reflection",
    "memory_answer",
    "note_user_feedback",
    "CONTEXT_CHAR_BUDGET",
    "active_guidance_text",
    "derive_machine_hints",
    "explain_stage_progress",
    "observe_clean",
    "observe_focus_enabled",
    "observe_focus_disabled",
    "export_companion_memory",
    "import_companion_memory",
    "MEMORY_EXPORT_KIND",
    "observe_ping_repaired",
    "observe_ram_optimized",
    "observe_snapshot",
    "observe_suggestion",
    "observe_update",
    "observe_wifi_repaired",
    "plan_companion_nudge",
    "recent_learning_text",
    "pending_skill_offer",
    "record_app_event",
    "record_session_day",
    "reset_postscript_gate",
    "resolve_llm_provider",
    "should_emit_postscript",
    "stage_caption_vi",
    "stage_legend_vi",
    "clear_profile_habits",
    "clear_profile_memory",
    "local_grounding_text",
]
