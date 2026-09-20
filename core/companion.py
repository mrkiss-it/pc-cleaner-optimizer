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
    count_by_kind,
    format_digest,
    recent_events,
)
from core.companion_maturity import (
    EMPTY_STAGE_VI,
    STAGE_BLURBS_VI,
    STAGE_LABELS_VI,
    StageInfo,
    add_feedback,
    build_stage_info,
    compute_stage,
    load_state,
    mark_active_day,
    save_state,
)
from core.companion_reflection import (
    load_reflection,
    load_reflection_meta,
    resolve_llm_provider,
    run_reflection,
)
from core.companion_skills import (
    CompanionSkill,
    format_skills_context,
    has_skill,
    issue_class_for_kind,
    load_skills,
    match_skills,
    pending_offer_from_counts,
    save_skill,
)

SNAPSHOT_COOLDOWN_SEC = 3 * 3600
DEFAULT_REFLECTION_HOUR = 20

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
) -> Optional[Dict[str, Any]]:
    if config_manager is not None and not is_enabled(config_manager):
        return None
    try:
        event = append_event(
            kind,
            summary,
            metrics=metrics,
            source=source,
            now=now,
            base_dir=base_dir,
        )
        if event:
            mark_active_day(now=now, base_dir=base_dir)
            _refresh_skill_offer(base_dir=base_dir, now=now)
        return event
    except Exception:
        return None


def _refresh_skill_offer(base_dir: Optional[str] = None, now: Optional[datetime] = None) -> None:
    try:
        counts = count_by_kind(days=21, base_dir=base_dir, now=now)
        offer = pending_offer_from_counts(counts, base_dir=base_dir)
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


def decline_skill_offer(base_dir: Optional[str] = None) -> None:
    state = load_state(base_dir)
    state["pending_skill_offer"] = None
    save_state(state, base_dir=base_dir)


def note_user_feedback(
    helpful: bool,
    note: str = "",
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    config_manager: Optional[Any] = None,
) -> StageInfo:
    add_feedback(helpful, base_dir=base_dir, now=now)
    summary = "Người dùng thấy AI đồng hành hữu ích." if helpful else "Người dùng thấy gợi ý chưa khớp máy này."
    if note:
        summary = f"{summary} {note}"
    record_app_event(
        "user_feedback",
        summary,
        metrics={"helpful": 1 if helpful else 0},
        source="user",
        now=now,
        base_dir=base_dir,
        config_manager=config_manager,
    )
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


def diary_digest(limit: int = 8, days: int = 14, base_dir: Optional[str] = None) -> str:
    return format_digest(days=days, limit=limit, base_dir=base_dir)


def latest_reflection(base_dir: Optional[str] = None) -> str:
    return load_reflection(base_dir)


def build_prompt_context(
    user_text: str = "",
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
) -> str:
    if config_manager is not None and not is_enabled(config_manager):
        return ""
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    digest = diary_digest(limit=8, days=14, base_dir=base_dir)
    skills = match_skills(user_text=user_text, base_dir=base_dir, limit=3)
    skills_text = format_skills_context(skills, empty_vi="Chưa có kỹ năng lưu cho máy này.")
    note = latest_reflection(base_dir) or "Chưa có sổ tay (chưa phản tỉnh hoặc cài mới)."
    policy = (
        "Hỏi nhiều, đề xuất ít."
        if stage.ask_more
        else "Có thể đề xuất dọn nhẹ / Trước thi / thu hồi RAM — không tự chạy, không WinSxS/registry."
    )
    if not stage.may_propose_actions:
        policy += " Người dùng chưa bật quyền đề xuất hành động."
    lines = [
        "[AI đồng hành — bộ nhớ local trên máy này, không phải AGI]",
        f"Giai đoạn: {stage.badge_vi()} ({stage.active_days} ngày dùng máy).",
        stage.blurb_vi,
        f"Quy tắc: {policy}",
        "Nhật ký gần đây:",
        digest,
        "Kỹ năng khớp máy này:",
        skills_text,
        "Sổ tay:",
        note,
        "Không bịa kỷ niệm. Nếu nhật ký trống, nói chưa có dữ liệu.",
    ]
    offer = pending_skill_offer(base_dir)
    if offer:
        lines.append(
            f"Gợi ý lưu kỹ năng: {offer.get('title')} "
            f"(đã lặp {offer.get('hit_count')} lần). Chỉ lưu khi người dùng đồng ý."
        )
    return "\n".join(lines)


def is_memory_question(user_text: str) -> bool:
    blob = str(user_text or "").lower()
    return any(token in blob for token in _MEMORY_HINTS)


def memory_answer(
    user_text: str = "",
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
) -> str:
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    digest = diary_digest(base_dir=base_dir)
    skills = load_skills(base_dir)
    note = latest_reflection(base_dir)
    lines = [
        f"### 🌱 AI đồng hành — {stage.badge_vi()}",
        stage.blurb_vi,
        "",
        "**Nhật ký máy này:**",
        digest,
        "",
        "**Kỹ năng đã lưu:**",
        format_skills_context(skills),
        "",
        "**Sổ tay:**",
        note or "Chưa có sổ tay. Bấm Ghi sổ tay hoặc đợi phản tỉnh buổi tối.",
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
    actions: List[Tuple[str, str]] = []
    for skill in match_skills(user_text=user_text, base_dir=base_dir, limit=2):
        if skill.action_key:
            actions.append((skill.action_key, skill.suggest[:48]))
    return actions


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
    state = load_state(base_dir)
    today = stamp.strftime("%Y-%m-%d")
    if not force and state.get("last_reflection_date") == today:
        return None
    if not force:
        try:
            hour = int(_cfg_get(config_manager, "companion_reflection_hour", DEFAULT_REFLECTION_HOUR) or DEFAULT_REFLECTION_HOUR)
        except (TypeError, ValueError):
            hour = DEFAULT_REFLECTION_HOUR
        if stamp.hour < hour:
            return None
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    digest = diary_digest(base_dir=base_dir)
    counts = count_by_kind(days=14, base_dir=base_dir, now=stamp)
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
    )
    state = load_state(base_dir)
    state["last_reflection_date"] = today
    save_state(state, base_dir=base_dir)
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
    kind = "clean_light" if light else "clean_freed"
    label = "Dọn nhẹ" if light else "Dọn rác"
    return record_app_event(
        kind,
        f"{label} giải phóng {float(junk_mb or 0):.0f} MB rác"
        + (f", {float(ram_mb):.0f} MB RAM" if ram_mb else ""),
        metrics={"junk_freed_mb": float(junk_mb or 0), "ram_freed_mb": float(ram_mb or 0)},
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
    return record_app_event(
        "focus_mode",
        "Người dùng bật Trước thi / họp"
        + (f" (dọn nhẹ {junk:.0f} MB)" if junk else ""),
        metrics={"junk_freed_mb": junk, "ram_freed_mb": ram},
        source="focus",
        **kwargs,
    )


def observe_wifi_repaired(recovered: bool = False, **kwargs) -> Optional[Dict[str, Any]]:
    return record_app_event(
        "wifi_repaired",
        "Wi-Fi đã ổn định lại" if recovered else "Đã thử sửa Wi-Fi trên máy này",
        source="network",
        **kwargs,
    )


def empty_states_vi() -> Dict[str, str]:
    return {
        "stage": EMPTY_STAGE_VI,
        "diary": "Chưa có nhật ký — dùng app một ngày, nhật ký máy sẽ xuất hiện tại đây.",
        "skills": "Chưa có kỹ năng — khi cùng một vấn đề lặp lại, Copilot sẽ đề nghị lưu mẹo cho máy này.",
        "reflection": "Chưa có sổ tay. Buổi tối app có thể tóm tắt nhật ký; không có LLM thì chỉ ghi số liệu.",
    }


__all__ = [
    "ALLOWED_KINDS",
    "EMPTY_STAGE_VI",
    "STAGE_BLURBS_VI",
    "STAGE_LABELS_VI",
    "StageInfo",
    "accept_skill_offer",
    "build_prompt_context",
    "companion_actions",
    "compute_stage",
    "current_stage",
    "decline_skill_offer",
    "diary_digest",
    "empty_states_vi",
    "has_skill",
    "is_enabled",
    "is_memory_question",
    "issue_class_for_kind",
    "latest_reflection",
    "load_reflection_meta",
    "match_skills",
    "maybe_run_reflection",
    "memory_answer",
    "note_user_feedback",
    "observe_clean",
    "observe_focus_enabled",
    "observe_ram_optimized",
    "observe_snapshot",
    "observe_wifi_repaired",
    "pending_skill_offer",
    "record_app_event",
    "record_session_day",
    "resolve_llm_provider",
]
