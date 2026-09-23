"""
In-the-moment companion: chat memory, insight actions, stage voice, weekly note.

Local only. Gemini may polish the weekly sổ tay when a key is already configured.
No Ollama, no model training, no full chat transcripts.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core.companion_diary import redact_sensitive, recent_events, sanitize_summary
from core.companion_maturity import load_state, save_state
from core.companion_profile import (
    TOPIC_META,
    event_topic,
    format_goal_status,
    infer_topics,
    load_profile,
    save_profile,
)
from core.companion_reflection import (
    WEEKLY_MARKER,
    load_reflection,
    resolve_llm_provider,
    save_reflection,
)
from core.companion_skills import fold_vi

CHAT_DEBOUNCE_SEC = 30 * 60
CHAT_TOPICS = frozenset({"wifi", "thermal", "disk", "focus", "update"})
_MIN_USER_CHARS = 4
_MIN_ANSWER_CHARS = 8
_FEEDBACK_TTL_SEC = 2 * 3600
_QUESTION_CLIP = 90

# One optional insight button. No registry, WinSxS, or full-disk clean.
# clean_light / optimize_ram / repair_network_now are safe actions the app already
# runs from other buttons. The default disk insight still opens memory; Dọn nhẹ
# is only preferred when a saved skill matches.
INSIGHT_ACTION_ALLOWLIST: Dict[str, Dict[str, Any]] = {
    "open_companion_memory": {
        "label_vi": "Mở bộ nhớ đồng hành",
        "min_stage": 0,
        "needs_propose": False,
        "topics": frozenset(),
    },
    "open_wifi_stability": {
        "label_vi": "Mở hướng dẫn Wi-Fi",
        "min_stage": 1,
        "needs_propose": False,
        "topics": frozenset({"wifi"}),
    },
    "disable_wifi_power_save": {
        "label_vi": "Tắt tiết kiệm điện Wi-Fi",
        "min_stage": 2,
        "needs_propose": True,
        "topics": frozenset({"wifi"}),
    },
    "enable_exam_focus": {
        "label_vi": "Bật Trước thi / họp",
        "min_stage": 2,
        "needs_propose": True,
        "topics": frozenset({"focus"}),
    },
    "open_thermal_card": {
        "label_vi": "Mở thẻ nhiệt",
        "min_stage": 1,
        "needs_propose": False,
        "topics": frozenset({"thermal"}),
    },
    "optimize_ram": {
        "label_vi": "Thu hồi RAM",
        "min_stage": 2,
        "needs_propose": True,
        "topics": frozenset({"ram"}),
    },
    "clean_light": {
        "label_vi": "Dọn nhẹ",
        "min_stage": 2,
        "needs_propose": True,
        "topics": frozenset({"disk"}),
    },
    "repair_network_now": {
        "label_vi": "Sửa mạng an toàn",
        "min_stage": 2,
        "needs_propose": True,
        "topics": frozenset({"wifi"}),
    },
    "view_hardware": {
        "label_vi": "Xem nhiệt",
        "min_stage": 1,
        "needs_propose": False,
        "topics": frozenset({"thermal"}),
    },
}

# Saved-skill keys → an allowlisted button. Unwired keys fall through to the
# topic's existing button instead of a dead control.
SKILL_ACTION_TO_INSIGHT = {
    "optimize_ram": "optimize_ram",
    "optimize_ram_only": "optimize_ram",
    "clean_light": "clean_light",
    "repair_network_now": "repair_network_now",
    "optimize_network": "repair_network_now",
    "enable_exam_focus": "enable_exam_focus",
    "toggle_exam_focus": "enable_exam_focus",
    "view_hardware": "view_hardware",
    "open_hardware_dialog": "view_hardware",
    "open_thermal_card": "open_thermal_card",
    "open_wifi_stability": "open_wifi_stability",
    "disable_wifi_power_save": "disable_wifi_power_save",
    "open_companion_memory": "open_companion_memory",
    "battery_saver": "open_thermal_card",
    "open_network_dialog": "open_wifi_stability",
}

_PRESSURE_ISSUE = {
    "wifi_weak": "wifi_weak",
    "ping_high": "wifi_weak",
    "wifi_repaired": "wifi_weak",
    "ping_repaired": "wifi_weak",
    "thermal_warn": "thermal",
    "high_ram": "high_ram",
    "ram_optimized": "high_ram",
    "clean_light": "disk_low",
    "clean_freed": "disk_low",
    "focus_mode": "focus",
}
_PRESSURE_WARN = frozenset({"wifi_weak", "ping_high", "thermal_warn", "high_ram"})

# Topic → the one button an insight may show. Power-save stays on the Wi-Fi card.
_TOPIC_ACTION = {
    "wifi": "open_wifi_stability",
    "thermal": "open_thermal_card",
    "focus": "enable_exam_focus",
    "disk": "open_companion_memory",
    "update": "open_companion_memory",
    "ram": "open_companion_memory",
}

_STAGE_VOICE = {
    0: (
        "shy",
        "Nói rất ngắn, đơn giản, hỏi lại. Chưa đề xuất việc cần làm.",
    ),
    1: (
        "ask",
        "Hỏi trước khi gợi ý. Chỉ nhắc điều đã thấy, không khẳng định quá.",
    ),
    2: (
        "suggest",
        "Có thể đề xuất một việc an toàn — không tự chạy, không WinSxS hay registry.",
    ),
    3: (
        "specific",
        "Nói cụ thể theo nhật ký máy này (số lần, buổi). Vẫn không tự chạy việc phá hủy.",
    ),
}

_TOPIC_ASK_VI = {
    "wifi": "Wi-Fi",
    "thermal": "nhiệt",
    "disk": "dọn máy",
    "focus": "Trước thi / họp",
    "update": "cập nhật",
    "ram": "RAM",
}


def _cfg_enabled(config_manager: Optional[Any]) -> bool:
    try:
        from core.companion import is_enabled
        return bool(is_enabled(config_manager))
    except Exception:
        return True


def _topic_name(topic: str) -> str:
    if topic in _TOPIC_ASK_VI:
        return _TOPIC_ASK_VI[topic]
    return str((TOPIC_META.get(topic) or {}).get("name") or topic)


def _goal(base_dir: Optional[str]) -> Optional[Dict[str, Any]]:
    goal = load_profile(base_dir).get("goal")
    return goal if isinstance(goal, dict) else None


def relevant_chat_topics(user_text: str, base_dir: Optional[str] = None) -> List[str]:
    """Wi-Fi, nhiệt, dọn, Trước thi, cập nhật, or the active goal — nothing else."""
    topics = [item for item in infer_topics(user_text) if item in CHAT_TOPICS or item in TOPIC_META]
    goal = _goal(base_dir)
    goal_topics = [str(item) for item in ((goal or {}).get("topics") or []) if str(item)]
    primary = str((goal or {}).get("topic") or (goal_topics[0] if goal_topics else ""))
    folded = fold_vi(user_text)
    mentions_goal = "muc tieu" in folded
    picked: List[str] = []
    for topic in topics:
        if topic in CHAT_TOPICS or (primary and topic == primary) or topic in goal_topics:
            if topic not in picked:
                picked.append(topic)
    if primary and (mentions_goal or primary in picked or set(picked) & set(goal_topics)):
        if primary not in picked:
            picked.insert(0, primary)
    if not picked and primary and mentions_goal:
        picked.append(primary)
    return [topic for topic in picked if topic in TOPIC_META]


def _clip_question(user_text: str) -> str:
    clean = sanitize_summary(redact_sensitive(user_text))
    if len(clean) > _QUESTION_CLIP:
        clean = clean[: _QUESTION_CLIP - 1].rstrip() + "…"
    return clean


def _remember_chat(topic: str, now: datetime, base_dir: Optional[str]) -> None:
    profile = load_profile(base_dir)
    profile["last_chat"] = {
        "topic": str(topic or "")[:24],
        "at": now.replace(microsecond=0).isoformat(timespec="seconds"),
    }
    save_profile(profile, base_dir=base_dir)


def _recent_chat_topic(now: datetime, base_dir: Optional[str]) -> str:
    last = load_profile(base_dir).get("last_chat")
    if not isinstance(last, dict):
        return ""
    topic = str(last.get("topic") or "")
    if topic not in TOPIC_META:
        return ""
    raw = str(last.get("at") or "")
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", ""))
    except Exception:
        return ""
    if abs((now - stamp).total_seconds()) > _FEEDBACK_TTL_SEC:
        return ""
    return topic


def learn_from_chat(
    user_text: str,
    assistant_text: str = "",
    *,
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Store one compact diary line after a real question and answer.

    Same topic inside 30 minutes updates the open line instead of a new one.
    The assistant reply is never written. API keys are redacted.
    """
    if not _cfg_enabled(config_manager):
        return None
    question = str(user_text or "").strip()
    answer = str(assistant_text or "").strip()
    if len(question) < _MIN_USER_CHARS:
        return None
    stamp = now or datetime.now()
    # A clear correction is one short line in the profile, even when the
    # question is not a tracked topic. The assistant reply is never stored.
    try:
        _maybe_learn_correction(
            question,
            config_manager=config_manager,
            base_dir=base_dir,
            now=stamp,
        )
    except Exception:
        pass
    if len(answer) < _MIN_ANSWER_CHARS:
        return None
    topics = relevant_chat_topics(question, base_dir=base_dir)
    if not topics:
        return None
    topic = topics[0]
    clipped = _clip_question(question)
    if not clipped or clipped == "[redacted]":
        return None
    summary = f"Bạn hỏi về {_topic_name(topic)}: {clipped}"
    try:
        from core.companion import record_app_event
        event = record_app_event(
            "chat_note",
            summary,
            source="copilot",
            now=stamp,
            base_dir=base_dir,
            config_manager=config_manager,
            outcome="neutral",
            tags=["chat", topic],
            coalesce=True,
        )
    except Exception:
        return None
    if event:
        try:
            _remember_chat(topic, stamp, base_dir)
        except Exception:
            pass
    return event


def _maybe_learn_correction(
    user_text: str,
    *,
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Store a sanitized correction. Full transcripts and the assistant reply stay out."""
    if not _cfg_enabled(config_manager):
        return None
    try:
        from core.companion_profile import add_user_note, is_clear_correction
    except Exception:
        return None
    if not is_clear_correction(user_text):
        return None
    # Ignore a bare "đừng" / "sai rồi". Keep one short sentence, not a transcript.
    if len(sanitize_summary(user_text)) < 8:
        return None
    return add_user_note(
        user_text,
        source="chat",
        base_dir=base_dir,
        now=now,
    )


def learn_from_feedback(
    helpful: bool,
    *,
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    topic: str = "",
) -> Optional[Dict[str, Any]]:
    """If the last chat was about a known topic, remember the explicit rating."""
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    chat_topic = _recent_chat_topic(stamp, base_dir)
    explicit = str(topic or "").strip()
    if explicit not in TOPIC_META:
        explicit = ""
    known = chat_topic or explicit
    event = None
    if chat_topic:
        name = _topic_name(chat_topic)
        summary = (
            f"Bạn thấy gợi ý {name} hữu ích."
            if helpful
            else f"Bạn thấy gợi ý {name} chưa khớp."
        )
        try:
            from core.companion import record_app_event
            event = record_app_event(
                "chat_note",
                summary,
                source="copilot",
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
                outcome="accepted" if helpful else "rejected",
                tags=["chat", "feedback", chat_topic],
                coalesce=True,
            )
        except Exception:
            event = None
    if known:
        _apply_topic_feedback(known, helpful, base_dir=base_dir, now=stamp)
    return event


def _apply_topic_feedback(
    topic: str,
    helpful: bool,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Negative feedback soft-mutes that topic and asks more. It does not replace global coaching."""
    try:
        from core.companion_profile import (
            SOFT_MUTE_DAYS,
            clear_feedback_mute,
            mute_topic,
            set_topic_coaching,
        )
    except Exception:
        return
    if helpful:
        try:
            set_topic_coaching(topic, False, base_dir=base_dir)
            clear_feedback_mute(topic, base_dir=base_dir)
        except Exception:
            return
        return
    try:
        mute_topic(topic, days=SOFT_MUTE_DAYS, reason="feedback", base_dir=base_dir, now=now)
        set_topic_coaching(topic, True, base_dir=base_dir)
    except Exception:
        return


def is_allowed_insight_action(action_key: str) -> bool:
    return str(action_key or "") in INSIGHT_ACTION_ALLOWLIST


def resolve_insight_action(
    topic: str,
    *,
    stage: int = 0,
    may_propose: bool = True,
    coaching: str = "steady",
    prefer_key: str = "",
) -> Optional[Dict[str, str]]:
    """One safe button, or none. Destructive cleanup is not in the allowlist.

    prefer_key is a saved skill's action. It wins only when that key (or its
    nearest safe substitute) is allowlisted for this stage. Otherwise the
    topic's existing button is used, so the control is never dead.
    """
    try:
        stage_n = max(0, min(3, int(stage)))
    except (TypeError, ValueError):
        stage_n = 0
    topic_key = str(topic or "")
    preferred = _accepted_skill_action(prefer_key, topic_key, stage_n, may_propose, coaching)
    if preferred:
        return preferred
    # Stage 2+ may use the existing power-save flow; earlier stages only open guidance.
    if topic_key == "wifi" and stage_n >= 2 and may_propose and coaching != "ask_more":
        key = "disable_wifi_power_save"
    else:
        key = _TOPIC_ACTION.get(topic_key)
    if not key:
        return None
    spec = INSIGHT_ACTION_ALLOWLIST.get(key) or {}
    if coaching == "ask_more" and spec.get("needs_propose"):
        key = "open_companion_memory"
        spec = INSIGHT_ACTION_ALLOWLIST[key]
    if stage_n < int(spec.get("min_stage") or 0) or (spec.get("needs_propose") and not may_propose):
        key = "open_companion_memory"
        spec = INSIGHT_ACTION_ALLOWLIST[key]
        if stage_n < int(spec.get("min_stage") or 0):
            return None
    if key not in INSIGHT_ACTION_ALLOWLIST:
        return None
    return {"key": key, "label_vi": str(spec.get("label_vi") or "")}


def _accepted_skill_action(
    prefer_key: str,
    topic: str,
    stage_n: int,
    may_propose: bool,
    coaching: str,
) -> Optional[Dict[str, str]]:
    raw = str(prefer_key or "").strip()
    if not raw:
        return None
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
    except Exception:
        BLOCKED_ACTION_KEYS = frozenset()
    if raw in BLOCKED_ACTION_KEYS:
        return None
    key = SKILL_ACTION_TO_INSIGHT.get(raw, raw if raw in INSIGHT_ACTION_ALLOWLIST else "")
    if not key or key in BLOCKED_ACTION_KEYS or key not in INSIGHT_ACTION_ALLOWLIST:
        return None
    spec = INSIGHT_ACTION_ALLOWLIST[key]
    topics = spec.get("topics") or frozenset()
    if topics and topic and topic not in topics:
        return None
    if coaching == "ask_more" and spec.get("needs_propose"):
        return None
    if stage_n < int(spec.get("min_stage") or 0):
        return None
    if spec.get("needs_propose") and not may_propose:
        return None
    return {"key": key, "label_vi": str(spec.get("label_vi") or "")}


def recent_pressure_issue(
    events: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    days: int = 3,
) -> str:
    """Issue class with the most weight in the last few days. Empty when quiet."""
    stamp = now or datetime.now()
    cutoff = stamp.timestamp() - max(1, int(days)) * 86400
    scores: Dict[str, int] = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind") or "")
        issue = _PRESSURE_ISSUE.get(kind)
        if not issue:
            continue
        raw = str(event.get("ts") or "")
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "")).timestamp()
        except Exception:
            continue
        if ts < cutoff:
            continue
        metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
        try:
            weight = max(1, int(metrics.get("count") or 1))
        except (TypeError, ValueError):
            weight = 1
        if kind in _PRESSURE_WARN:
            weight += 1
        scores[issue] = scores.get(issue, 0) + weight
    if not scores:
        return ""
    return max(scores, key=lambda item: (scores[item], item))


def skill_for_insight(
    topic: str = "",
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    events: Optional[List[Dict[str, Any]]] = None,
):
    """Saved skill for this insight topic, or for recent pressure when the topic is blank."""
    try:
        from core.companion_profile import topic_issue
        from core.companion_skills import load_skills
    except Exception:
        return None
    skills = {skill.issue_class: skill for skill in load_skills(base_dir)}
    if not skills:
        return None
    issue = topic_issue(topic) if topic else ""
    if issue and issue in skills:
        return skills[issue]
    if topic:
        return None
    rows = events
    if rows is None:
        try:
            rows = recent_events(days=3, limit=0, base_dir=base_dir, now=now)
        except Exception:
            rows = []
    pressured = recent_pressure_issue(rows, now)
    if pressured and pressured in skills:
        return skills[pressured]
    return None


def attach_insight_action(
    insight: Optional[Dict[str, str]],
    *,
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, str]]:
    if not isinstance(insight, dict) or not insight.get("text"):
        return insight
    skill = None
    action = None
    focus_on = False
    stressed = False
    stage = None
    try:
        from core.companion import current_stage
        from core.companion_profile import effective_coaching
        stage = current_stage(config_manager=config_manager, base_dir=base_dir)
        profile = load_profile(base_dir)
        topic = str(insight.get("topic") or "")
        # Low trust and a muted / ask-more topic both land on ask_more here.
        # High trust does not skip the stage gate inside resolve_insight_action.
        coaching = effective_coaching(profile, topic=topic, base_dir=base_dir, now=now)
        skill = skill_for_insight(topic, base_dir=base_dir, now=now)
        fallback = str(getattr(skill, "action_key", "") or "")
        try:
            from core.companion_learning import rank_propose_key
            prefer = rank_propose_key(topic, base_dir=base_dir, fallback=fallback, now=now)
        except Exception:
            prefer = fallback
        action = resolve_insight_action(
            topic,
            stage=stage.stage,
            may_propose=bool(stage.may_propose_actions),
            coaching=coaching,
            prefer_key=prefer,
        )
        rows = recent_events(days=1, limit=0, base_dir=base_dir, now=now)
        focus_on = exam_focus_is_live()
        stressed = machine_stress_active(rows, now or datetime.now())
        if stressed:
            try:
                from core.companion_learning import apply_micro_update
                apply_micro_update("rough_day", now=now, base_dir=base_dir)
            except Exception:
                pass
        action = _calm_insight_action(action, focus_active=focus_on, stressed=stressed)
    except Exception:
        action = None
        skill = None
        focus_on = False
        stressed = False
        stage = None
    out = dict(insight)
    for extra in ("action_key", "action_label_vi", "skill_id", "skill_issue"):
        out.pop(extra, None)
    if action and action.get("key") and action.get("label_vi"):
        out["action_key"] = action["key"]
        out["action_label_vi"] = action["label_vi"]
        # hit_count rises on tap, not when this line is shown. See bump_skill_hit.
        if skill is not None:
            out["skill_id"] = str(getattr(skill, "id", "") or "")
            out["skill_issue"] = str(getattr(skill, "issue_class", "") or "")
    replay_used = False
    try:
        if not out.get("action_key"):
            attached = maybe_attach_helpful_replay(
                out,
                now=now,
                base_dir=base_dir,
                config_manager=config_manager,
                surface="insight",
                mark=False,
            )
            if isinstance(attached, dict) and attached.get("helpful_replay"):
                out = attached
                replay_used = True
    except Exception:
        replay_used = False
    try:
        from core.companion_profile import in_quiet_hours, quiet_hours_allow_actions
        stamp = now or datetime.now()
        if in_quiet_hours(stamp, base_dir=base_dir) and not quiet_hours_allow_actions(
            stamp, base_dir=base_dir
        ):
            for extra in ("action_key", "action_label_vi", "skill_id", "skill_issue"):
                out.pop(extra, None)
            out.pop("helpful_replay", None)
            out["quiet"] = True
            replay_used = False
    except Exception:
        pass
    if replay_used and out.get("action_key"):
        try:
            mark_helpful_replay_surfaced(base_dir)
        except Exception:
            pass
    if (focus_on or stressed) and stage is not None:
        try:
            from core.companion_profile import effective_coaching, score_trust
            profile = load_profile(base_dir)
            trust = score_trust(profile=profile, base_dir=base_dir, now=now)
            try:
                from core.companion_learning import voice_tone_kwargs
                tone_extra = voice_tone_kwargs(base_dir)
            except Exception:
                tone_extra = {}
            voice = stage_voice(
                stage.stage,
                coaching=effective_coaching(profile, base_dir=base_dir, now=now),
                may_propose=bool(stage.may_propose_actions),
                trust=str(trust.get("level") or "steady"),
                focus_active=focus_on,
                stressed=stressed,
                **tone_extra,
            )
            aside = str(voice.get("aside_vi") or "").strip()
            text = str(out.get("text") or "")
            if aside and aside not in text and stage.stage >= 1:
                out["text"] = (text.rstrip() + " " + aside).strip()
        except Exception:
            pass
    return out


def stage_voice(
    stage: int,
    *,
    coaching: str = "steady",
    may_propose: bool = True,
    trust: str = "steady",
    focus_active: bool = False,
    stressed: bool = False,
    learned_vi: str = "",
    confidence: Optional[float] = None,
    maturity_signal: str = "",
) -> Dict[str, str]:
    """Short tone cue. Stage 0 stays shy; stage 3 may cite this machine.

    Trust sits on top of the global coaching flag and does not replace it:
    low trust (accept/reject, see score_trust) uses the ask-more voice, so
    action_cap_for_stage returns 0 and check-ins stay soft. High trust does
    not raise the cap and does not set may_propose — stage ≥ 2 plus the
    consent flag still decide, and BLOCKED_ACTION_KEYS stay out of the
    allowlist. A topic mute is applied by the caller as coaching="ask_more"
    and is not undone when trust is high.

    An open Trước thi / họp session, or two stress signals on the same day,
    softens stage 1+ to the ask voice. Stage 0 stays shy either way.

    confidence / maturity_signal come from the local learning snapshot. They
    only add a short tone phrase. They do not change boldness, so mute, quiet
    hours, focus, and a rough day still decide whether a button may appear.
    """
    try:
        stage_n = max(0, min(3, int(stage)))
    except (TypeError, ValueError):
        stage_n = 0
    boldness, tone = _STAGE_VOICE[stage_n]
    trust_level = str(trust or "steady")
    if trust_level == "low" and stage_n >= 1:
        boldness = "ask"
        tone = "Bạn hay từ chối hoặc tắt gợi ý — hỏi thêm, đề xuất ít. " + tone
    elif coaching == "ask_more" and stage_n >= 1:
        boldness = "ask"
        tone = "Phản hồi gần đây chưa khớp — hỏi thêm, đề xuất ít. " + tone
    elif stage_n >= 2 and not may_propose:
        boldness = "ask"
        tone = tone + " Người dùng chưa bật quyền đề xuất hành động."
    calm = stage_n >= 1 and (bool(focus_active) or bool(stressed))
    if calm:
        boldness = "ask"
        if focus_active and stressed:
            tone = "Đang tập trung và máy có vài dấu hiệu cùng lúc — nói nhẹ, hỏi thêm. " + tone
        elif focus_active:
            tone = "Đang Trước thi / họp — nói nhẹ, chỉ nhắc việc tập trung. " + tone
        else:
            tone = "Hôm nay máy có vài dấu hiệu cùng lúc — hỏi thêm, chưa xếp nhiều nút. " + tone
    # Learning-model confidence tints tone only after the calm gates above.
    try:
        conf = None if confidence is None else float(confidence)
    except (TypeError, ValueError):
        conf = None
    if conf is not None:
        conf = max(0.0, min(1.0, conf))
    signal = str(maturity_signal or "")
    if conf is not None and not calm and stage_n >= 1:
        if conf < 0.34:
            tone = "Mình còn học máy này, nói ngắn. " + tone
        elif conf >= 0.72 and signal == "familiar":
            tone = (tone.rstrip() + " Mình đã quen máy này một chút.").strip()
    aside = ""
    if stage_n <= 0:
        aside = "Mình mới gặp máy này — nói ngắn và hỏi lại."
    elif focus_active and stressed and stage_n >= 1:
        aside = "Mình nói nhẹ và hỏi thêm trong buổi này."
    elif focus_active and stage_n >= 1:
        aside = "Mình hỏi nhiều hơn trong buổi tập trung."
    elif stressed and stage_n >= 1:
        aside = "Mình nói nhẹ hơn hôm nay."
    elif stage_n >= 3 and boldness == "specific":
        aside = "Theo nhật ký máy này."
    learned = " ".join(str(learned_vi or "").split())[:140]
    if learned and not calm and stage_n >= 1 and learned not in tone:
        tone = (tone.rstrip() + " " + learned).strip()
    return {
        "boldness": boldness,
        "tone_vi": tone,
        "policy_vi": tone,
        "aside_vi": aside,
        "learned_vi": learned,
    }


def action_cap_for_stage(
    stage: int,
    *,
    coaching: str = "steady",
    may_propose: bool = True,
    trust: str = "steady",
    focus_active: bool = False,
    stressed: bool = False,
) -> int:
    voice = stage_voice(
        stage,
        coaching=coaching,
        may_propose=may_propose,
        trust=trust,
        focus_active=focus_active,
        stressed=stressed,
    )
    if voice["boldness"] in ("shy", "ask"):
        return 0
    if voice["boldness"] == "suggest":
        return 1
    return 2


# Two different stress families on the same calendar day. One family, even if
# it repeats, is not "the machine is having a rough day".
_STRESS_GROUPS = {
    "network": frozenset({"wifi_weak", "ping_high"}),
    "thermal": frozenset({"thermal_warn"}),
    "ram": frozenset({"high_ram"}),
}
_STRESS_RECOVERY = {
    "network": frozenset({"wifi_repaired", "ping_repaired"}),
    "thermal": frozenset(),
    "ram": frozenset({"ram_optimized"}),
}


def exam_focus_is_live() -> bool:
    """True only while the user has Trước thi / họp on. Never turns it on."""
    try:
        from core.exam_focus import ExamMeetingFocus
        return bool(ExamMeetingFocus.is_active())
    except Exception:
        return False


def _event_stamp(event: Dict[str, Any]) -> Optional[datetime]:
    return _parse_iso(event.get("ts"))


def machine_stress_groups(
    events: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> List[str]:
    """Stress families still open today. No temperatures or extra metrics.

    A family counts when its latest row today is a warning, not a later recovery.
    Thermal has no recovery row, so it stays until the next calendar day.
    """
    stamp = now or datetime.now()
    day = stamp.strftime("%Y-%m-%d")
    latest: Dict[str, Any] = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        if str(event.get("ts") or "")[:10] != day:
            continue
        kind = str(event.get("kind") or "")
        moment = _event_stamp(event)
        ts = moment.timestamp() if moment is not None else 0.0
        outcome = str(event.get("outcome") or "")
        for group, kinds in _STRESS_GROUPS.items():
            if kind in kinds and outcome in ("warn", "fail", ""):
                prev = latest.get(group)
                if prev is None or ts >= prev[0]:
                    latest[group] = (ts, "warn")
            elif kind in _STRESS_RECOVERY.get(group, ()) and outcome in ("ok", "accepted", ""):
                prev = latest.get(group)
                if prev is None or ts >= prev[0]:
                    latest[group] = (ts, "calm")
    return sorted(group for group, (_ts, state) in latest.items() if state == "warn")


def machine_stress_active(
    events: Optional[List[Dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> bool:
    """True when at least two stress families are still open today."""
    return len(machine_stress_groups(events, now)) >= 2


def _session_dict(base_dir: Optional[str]) -> Dict[str, Any]:
    raw = load_state(base_dir).get("focus_session")
    return dict(raw) if isinstance(raw, dict) else {}


def note_focus_started(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Remember that the user started a session. Does not enable the mode."""
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    state = load_state(base_dir)
    payload = {
        "active": True,
        "started_at": stamp.replace(microsecond=0).isoformat(timespec="seconds"),
        "ended_at": "",
        "followup_for": "",
    }
    state["focus_session"] = payload
    save_state(state, base_dir=base_dir)
    return payload


def schedule_focus_session_followup(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """One yes/no after the session, reusing the open follow-up slot.

    Due immediately. Quiet hours and a muted focus topic hide it later.
    Does not record a recovery expectation, so the end line is not auto-credit.
    """
    if not _cfg_enabled(config_manager):
        return None
    try:
        from core.companion_profile import topic_is_muted
        if topic_is_muted("focus", base_dir=base_dir, now=now):
            return None
    except Exception:
        return None
    state = load_state(base_dir)
    existing = state.get("pending_followup")
    if isinstance(existing, dict) and str(existing.get("question_vi") or "").strip():
        return None
    stamp = now or datetime.now()
    iso = stamp.replace(microsecond=0).isoformat(timespec="seconds")
    payload = {
        "action_key": "enable_exam_focus",
        "topic": "focus",
        "skill_id": "",
        "since": iso,
        "due_at": iso,
        "question_vi": _FOLLOWUP_QUESTION["focus"],
        "source": "focus_session",
    }
    state["pending_followup"] = payload
    save_state(state, base_dir=base_dir)
    return payload


def note_focus_ended(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
    write_diary: bool = True,
) -> Optional[Dict[str, Any]]:
    """Close the remembered session and ask once whether it helped.

    A second call for the same start does not write another line or question.
    """
    if not _cfg_enabled(config_manager):
        return None
    session = _session_dict(base_dir)
    started = str(session.get("started_at") or "")
    if (
        started
        and session.get("followup_for") == started
        and not session.get("active")
    ):
        return None
    stamp = now or datetime.now()
    ended = stamp.replace(microsecond=0).isoformat(timespec="seconds")
    event = None
    if write_diary:
        try:
            from core.companion import record_app_event
            event = record_app_event(
                "focus_end",
                "Người dùng tắt Trước thi / họp",
                source="focus",
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
                outcome="neutral",
                tags=["focus", "end"],
                coalesce=False,
            )
        except Exception:
            event = None
    state = load_state(base_dir)
    state["focus_session"] = {
        "active": False,
        "started_at": started,
        "ended_at": ended,
        "followup_for": started or ended,
    }
    save_state(state, base_dir=base_dir)
    schedule_focus_session_followup(now=stamp, base_dir=base_dir, config_manager=config_manager)
    try:
        from core.companion_learning import apply_micro_update
        apply_micro_update("focus_end", topic="focus", now=stamp, base_dir=base_dir)
    except Exception:
        pass
    return event or {"ended_at": ended}


def sync_focus_session(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Next open after a session that ended without a disable hook.

    If the mode is still on, leave it alone. This never calls enable.
    """
    session = _session_dict(base_dir)
    if not session.get("active"):
        return None
    if exam_focus_is_live():
        return None
    return note_focus_ended(
        now=now,
        base_dir=base_dir,
        config_manager=config_manager,
        write_diary=True,
    )


def _calm_insight_action(
    action: Optional[Dict[str, str]],
    *,
    focus_active: bool = False,
    stressed: bool = False,
) -> Optional[Dict[str, str]]:
    """During focus or a rough day, do not pile propose buttons.

    Focus keeps only a focus action that does not need a proposal — turning
    the mode on again is not one of those. Stress drops propose buttons and
    leaves a plain open-the-card button if one was already chosen.
    """
    if not action or not action.get("key"):
        return None
    spec = INSIGHT_ACTION_ALLOWLIST.get(str(action.get("key") or "")) or {}
    if focus_active:
        topics = spec.get("topics") or frozenset()
        if "focus" not in topics or spec.get("needs_propose"):
            return None
        return action
    if stressed and spec.get("needs_propose"):
        return None
    return action


def week_key(now: Optional[datetime] = None) -> str:
    stamp = now or datetime.now()
    iso = stamp.isocalendar()
    return f"{int(iso[0])}-W{int(iso[1]):02d}"


def weekly_digest_due(
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
) -> bool:
    state = load_state(base_dir)
    return str(state.get("last_weekly_digest_week") or "") != week_key(now)


def _week_events(now: datetime, base_dir: Optional[str]) -> List[Dict[str, Any]]:
    rows = recent_events(days=7, limit=0, base_dir=base_dir, now=now)
    return [item for item in rows if str(item.get("kind") or "") != "reflection"]


def _has_weekly_material(now: datetime, base_dir: Optional[str]) -> bool:
    if _week_events(now, base_dir):
        return True
    return bool(_goal(base_dir))


def _count_line(events: List[Dict[str, Any]]) -> str:
    labels = {
        "wifi_weak": "Wi-Fi yếu",
        "wifi_repaired": "Wi-Fi ổn lại",
        "ping_high": "ping cao",
        "thermal_warn": "nhiệt cao",
        "focus_mode": "Trước thi / họp",
        "clean_light": "dọn nhẹ",
        "clean_freed": "dọn rác",
        "update_ok": "cập nhật xong",
        "update_fail": "cập nhật lỗi",
        "chat_note": "câu hỏi Copilot",
        "high_ram": "RAM cao",
        "ram_optimized": "thu hồi RAM",
    }
    counts: Dict[str, int] = {}
    for event in events:
        kind = str(event.get("kind") or "")
        if kind not in labels:
            continue
        try:
            weight = int((event.get("metrics") or {}).get("count") or 1)
        except (TypeError, ValueError):
            weight = 1
        counts[kind] = counts.get(kind, 0) + max(1, weight)
    bits = [f"{labels[kind]} {n}" for kind, n in counts.items() if n]
    if not bits:
        return ""
    return "Trong tuần: " + ", ".join(bits) + "."


def _loose_topic(event: Dict[str, Any]) -> str:
    topic = event_topic(event)
    if topic:
        return topic
    kind = str(event.get("kind") or "")
    if kind in ("focus_mode", "focus_end"):
        return "focus"
    for tag in event.get("tags") or []:
        if str(tag) in TOPIC_META:
            return str(tag)
    return ""


def _focus_session_times(
    events: List[Dict[str, Any]],
    now: datetime,
    *,
    days: int = 7,
) -> List[datetime]:
    """One stamp per Trước thi / họp session in the window. Start+end is not two sessions."""
    cutoff = now - timedelta(days=max(1, int(days)))
    starts: List[datetime] = []
    ends: List[datetime] = []
    for event in events:
        moment = _event_stamp(event)
        if moment is None or moment < cutoff or moment > now + timedelta(minutes=1):
            continue
        kind = str(event.get("kind") or "")
        if kind == "focus_mode":
            starts.append(moment)
        elif kind == "focus_end":
            ends.append(moment)
    sessions = list(ends)
    for start in starts:
        if any(timedelta(0) <= end - start <= timedelta(hours=18) for end in ends):
            continue
        sessions.append(start)
    sessions.sort()
    return sessions


def _rough_day_count(
    events: List[Dict[str, Any]],
    now: datetime,
    muted: set,
    *,
    days: int = 7,
) -> int:
    total = 0
    for offset in range(max(1, int(days))):
        day = now - timedelta(days=offset)
        groups = machine_stress_groups(events, day)
        if len(groups) < 2:
            continue
        topics = [_STRESS_TOPIC.get(group, "") for group in groups]
        if topics and all(topic in muted for topic in topics if topic):
            continue
        total += 1
    return total


def local_weekly_bullets(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
) -> List[Dict[str, str]]:
    """1–3 short local bullets from diary, profile, milestones, focus, and rough days.

    No Gemini. Muted topics are left out. An empty week returns no bullets.
    """
    stamp = now or datetime.now()
    try:
        from core.companion_profile import active_muted_topics, load_profile
        muted = set(active_muted_topics(now=stamp, base_dir=base_dir))
        profile = load_profile(base_dir)
    except Exception:
        muted = set()
        profile = {}
    events = _week_events(stamp, base_dir)
    labels = {
        "wifi_weak": "Wi-Fi yếu",
        "wifi_repaired": "Wi-Fi ổn lại",
        "ping_high": "ping cao",
        "thermal_warn": "nhiệt cao",
        "high_ram": "RAM cao",
        "ram_optimized": "đã thu hồi RAM",
        "clean_light": "dọn nhẹ",
        "clean_freed": "dọn rác",
        "focus_mode": "Trước thi / họp",
        "focus_end": "kết thúc Trước thi / họp",
    }
    by_topic: Dict[str, Dict[str, int]] = {}
    for event in events:
        kind = str(event.get("kind") or "")
        if kind not in labels:
            continue
        topic = _loose_topic(event)
        if not topic or topic in muted:
            continue
        try:
            weight = int((event.get("metrics") or {}).get("count") or 1)
        except (TypeError, ValueError):
            weight = 1
        bucket = by_topic.setdefault(topic, {})
        bucket[kind] = bucket.get(kind, 0) + max(1, weight)
    items: List[Dict[str, str]] = []
    try:
        from core.companion_learning import weekly_learn_line
        learned = weekly_learn_line(base_dir=base_dir, now=stamp, muted=muted)
    except Exception:
        learned = ""
    if learned:
        items.append({"text": learned, "topic": ""})
    for topic, kinds in by_topic.items():
        if topic == "focus":
            continue
        bits = [f"{labels[kind]} {n} lần" for kind, n in kinds.items() if n]
        if not bits:
            continue
        items.append({"text": ", ".join(bits[:2]) + ".", "topic": topic})
    focus_n = len(_focus_session_times(events, stamp))
    if focus_n and "focus" not in muted:
        items.append({"text": f"Trước thi / họp {focus_n} lần.", "topic": "focus"})
    rough_n = _rough_day_count(events, stamp, muted)
    if rough_n:
        items.append({"text": f"{rough_n} ngày máy hơi nặng.", "topic": ""})
    try:
        state = load_state(base_dir)
        marked = str(state.get("last_milestone_date") or "")[:10]
        if len(marked) == 10:
            marked_day = datetime.fromisoformat(marked).date()
            if 0 <= (stamp.date() - marked_day).days <= 6:
                items.append({"text": "Có một cột mốc trong tuần.", "topic": ""})
    except Exception:
        pass
    for habit in (profile.get("habits") or []) if isinstance(profile, dict) else []:
        if not isinstance(habit, dict):
            continue
        topic = str(habit.get("topic") or "")
        if topic in muted:
            continue
        detail = str(habit.get("detail_vi") or habit.get("label_vi") or "").strip()
        if not detail:
            continue
        if not detail.endswith("."):
            detail += "."
        if len(detail) > 90:
            detail = detail[:89].rstrip() + "…"
        items.append({"text": detail, "topic": topic})
        break
    unique: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append({"text": text, "topic": str(item.get("topic") or "")})
        if len(unique) >= 3:
            break
    return unique


def format_weekly_strip(items: List[Dict[str, str]]) -> str:
    lines = ["Tóm tắt tuần:"]
    for item in items[:3]:
        text = str(item.get("text") or "").strip()
        if text:
            lines.append("• " + text)
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def local_weekly_summary(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    stage_label: str = "",
) -> str:
    stamp = now or datetime.now()
    events = _week_events(stamp, base_dir)
    iso = stamp.isocalendar()
    lines = [
        f"{WEEKLY_MARKER} tuần {int(iso[1])} (đến {stamp.strftime('%d/%m')}), chỉ số liệu máy này.",
    ]
    if stage_label:
        lines.append(f"Giai đoạn: {stage_label}.")
    detail = _count_line(events)
    if detail:
        lines.append(detail)
    elif events:
        lines.append(f"Nhật ký tuần này có {len(events)} dòng, chưa gom thành một thói quen.")
    else:
        lines.append("Tuần này chưa có diễn biến mới trên máy này.")
    goal_line = format_goal_status(base_dir=base_dir, now=stamp)
    if goal_line:
        lines.append(goal_line.split("\n", 1)[0])
    asked = [
        event_topic(item)
        for item in events
        if str(item.get("kind") or "") == "chat_note" and "feedback" not in (item.get("tags") or [])
    ]
    asked = [topic for topic in asked if topic]
    if asked:
        names = []
        for topic in asked:
            name = _topic_name(topic)
            if name not in names:
                names.append(name)
        lines.append("Bạn đã hỏi về " + ", ".join(names[:3]) + ".")
    try:
        from core.companion_learning import weekly_learn_line
        from core.companion_profile import active_muted_topics
        learned = weekly_learn_line(
            base_dir=base_dir,
            now=stamp,
            muted=set(active_muted_topics(now=stamp, base_dir=base_dir)),
        )
    except Exception:
        learned = ""
    if learned and learned not in lines:
        lines.append(learned)
    lines.append("Không phải AGI; không tự chạy việc phá hủy.")
    try:
        extra = local_weekly_bullets(now=stamp, base_dir=base_dir)
    except Exception:
        extra = []
    for item in extra:
        bullet = "• " + str(item.get("text") or "").strip()
        if bullet != "•" and bullet not in lines:
            lines.append(bullet)
    return "\n".join(lines)


def _compose_journal(existing: str, weekly_body: str) -> str:
    block = str(weekly_body or "").strip()
    if not block.startswith(WEEKLY_MARKER):
        block = WEEKLY_MARKER + "\n" + block
    prior = str(existing or "")
    if WEEKLY_MARKER in prior:
        prior = prior.split(WEEKLY_MARKER, 1)[0].rstrip()
    if prior.strip():
        return (block + "\n\n" + prior.strip()).strip()
    return block


def maybe_weekly_digest(
    *,
    force: bool = False,
    now: Optional[datetime] = None,
    config_manager: Optional[Any] = None,
    provider=None,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Write one sổ tay note per ISO week. Manual force rewrites the same week.

    No toast. Gemini only when the configured provider is not the local template.
    """
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    if not force and not weekly_digest_due(now=stamp, base_dir=base_dir):
        return None
    if not _has_weekly_material(stamp, base_dir):
        return {"note": "", "source": "empty"}
    try:
        from core.companion_learning import ensure_daily_model
        ensure_daily_model(now=stamp, base_dir=base_dir, config_manager=config_manager)
    except Exception:
        pass
    try:
        from core.companion import current_stage, record_app_event
        stage = current_stage(config_manager=config_manager, base_dir=base_dir)
        stage_label = stage.badge_vi()
    except Exception:
        record_app_event = None  # type: ignore
        stage_label = ""
    local = local_weekly_summary(now=stamp, base_dir=base_dir, stage_label=stage_label)
    note = redact_sensitive(local).strip()
    source = "template"
    llm = provider if provider is not None else resolve_llm_provider(config_manager)
    if getattr(llm, "name", "") not in ("", "template"):
        prompt = (
            "Viết lại đoạn sau bằng tiếng Việt, tối đa 6 câu. "
            "Không thêm sự kiện, không hỏi API key, không nhận là AGI.\n"
            f"{local}"
        )
        try:
            generated = llm.generate(prompt, timeout=8.0)
        except Exception:
            generated = None
        polished = redact_sensitive(generated or "").strip()
        if len(polished) >= 20:
            if not polished.startswith(WEEKLY_MARKER):
                polished = WEEKLY_MARKER + " " + polished
            note = polished
            source = "gemini"
    merged = _compose_journal(load_reflection(base_dir), note)
    saved = save_reflection(merged, source="weekly" if source == "template" else "weekly-gemini", base_dir=base_dir, now=stamp)
    state = load_state(base_dir)
    state["last_weekly_digest_week"] = week_key(stamp)
    save_state(state, base_dir=base_dir)
    if record_app_event is not None:
        try:
            record_app_event(
                "reflection",
                "Đã ghi tóm tắt tuần",
                source="companion",
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
                coalesce=False,
            )
        except Exception:
            pass
    return {"note": saved, "source": source}


def format_weekly_feedback(result: Any = None, *, error: Optional[Any] = None) -> Dict[str, str]:
    if error is not None or isinstance(result, Exception):
        detail = str(error if error is not None else result).strip() or "lỗi không rõ"
        return {
            "status": "error",
            "title": "Chưa ghi được tóm tắt tuần",
            "body": f"Chưa ghi được tóm tắt tuần: {detail}",
        }
    payload = result if isinstance(result, dict) else {}
    source = str(payload.get("source") or "")
    note = str(payload.get("note") or "").strip()
    if source == "empty" or not note:
        return {
            "status": "empty",
            "title": "Chưa đủ nhật ký",
            "body": "Chưa đủ nhật ký tuần này để tóm tắt. Dùng app thêm rồi bấm lại.",
        }
    if source == "gemini":
        body = "Đã ghi tóm tắt tuần (Gemini) vào sổ tay."
    else:
        body = "Đã ghi tóm tắt tuần từ số liệu máy này (không dùng mô hình ngôn ngữ)."
    return {"status": "success", "title": "Đã ghi tóm tắt tuần", "body": body}


def _filter_weekly_items(
    items: List[Dict[str, str]],
    *,
    now: datetime,
    base_dir: Optional[str],
) -> List[Dict[str, str]]:
    try:
        from core.companion_profile import topic_is_muted
    except Exception:
        topic_is_muted = None  # type: ignore
    try:
        from core.companion_profile import active_muted_topics
        muted_names = set(active_muted_topics(now=now, base_dir=base_dir))
    except Exception:
        muted_names = set()
    try:
        from core.companion_learning import _mentions_muted
    except Exception:
        _mentions_muted = None  # type: ignore
    kept: List[Dict[str, str]] = []
    for item in items:
        topic = str(item.get("topic") or "")
        if topic and topic_is_muted is not None and topic_is_muted(topic, base_dir=base_dir, now=now):
            continue
        text = str(item.get("text") or "").strip()
        if text and _mentions_muted is not None and _mentions_muted(text, muted_names):
            continue
        if text:
            kept.append({"text": text, "topic": topic})
        if len(kept) >= 3:
            break
    return kept


def sync_weekly_strip(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """One local weekly strip per ISO week. Quiet hours wait; Gemini is not called.

    Dismissing keeps the week consumed. An empty week does not consume the slot.
    """
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    try:
        from core.companion_learning import ensure_daily_model
        ensure_daily_model(now=stamp, base_dir=base_dir, config_manager=config_manager)
    except Exception:
        pass
    week = week_key(stamp)
    try:
        from core.companion_profile import in_quiet_hours
        quiet = in_quiet_hours(stamp, base_dir=base_dir)
    except Exception:
        quiet = False
    state = load_state(base_dir)
    pending = state.get("pending_weekly_strip")
    if isinstance(pending, dict) and str(pending.get("week") or "") == week and pending.get("text"):
        if quiet:
            return None
        items = _filter_weekly_items(
            list(pending.get("items") or []),
            now=stamp,
            base_dir=base_dir,
        )
        if not items:
            return None
        shown = dict(pending)
        shown["items"] = items
        shown["text"] = format_weekly_strip(items)
        return shown
    if str(state.get("last_weekly_strip_week") or "") == week:
        return None
    if quiet:
        return None
    items = local_weekly_bullets(now=stamp, base_dir=base_dir)
    items = _filter_weekly_items(items, now=stamp, base_dir=base_dir)
    text = format_weekly_strip(items)
    if not text:
        return None
    payload = {"week": week, "text": text, "items": items}
    state["pending_weekly_strip"] = payload
    state["last_weekly_strip_week"] = week
    save_state(state, base_dir=base_dir)
    return payload


def dismiss_weekly_strip(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Hide this week's strip. It does not come back until next week."""
    stamp = now or datetime.now()
    state = load_state(base_dir)
    state["pending_weekly_strip"] = None
    state["last_weekly_strip_week"] = week_key(stamp)
    save_state(state, base_dir=base_dir)


def digest_backoff(now: Optional[datetime] = None, hours: int = 3) -> datetime:
    stamp = now or datetime.now()
    return stamp + timedelta(hours=max(1, int(hours)))


_YESTERDAY_LINE = {
    "wifi": "Wi-Fi trên máy này không ổn",
    "thermal": "nhiệt máy vượt ngưỡng",
    "focus": "bạn bật Trước thi / họp",
    "ram": "RAM trên máy này cao",
    "disk": "máy được dọn",
    "update": "cập nhật không xong",
}
_CHECKIN_SKIP_KINDS = frozenset({
    "session_day",
    "reflection",
    "stage_up",
    "user_feedback",
    "skill_saved",
    "tip_snooze",
    "topic_trust",
})
_CHECKIN_LIMIT = 360
# One extra morning sentence, in this order. Goal title stays in the existing
# check-in sentence; it is not stacked on top of a second hint.
_MORNING_HINT_ORDER = ("rough_yesterday", "quiet_ended", "battery_low")
_BATTERY_LOW_PERCENT = 30
# Minutes after quiet hours end when the greeting may mention that they ended.
_QUIET_END_GREETING_MIN = 90
_STRESS_TOPIC = {"network": "wifi", "thermal": "thermal", "ram": "ram"}


def _checkin_weight(event: Dict[str, Any]) -> int:
    metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
    try:
        return max(1, int(metrics.get("count") or 1))
    except (TypeError, ValueError):
        return 1


def _yesterday_counts(
    events: List[Dict[str, Any]],
    yesterday: str,
    muted: set,
) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for event in events:
        if str(event.get("ts") or "")[:10] != yesterday:
            continue
        kind = str(event.get("kind") or "")
        if kind in _CHECKIN_SKIP_KINDS:
            continue
        if kind == "update_ok":
            continue
        topic = event_topic(event)
        if not topic or topic in muted:
            continue
        counts[topic] = counts.get(topic, 0) + _checkin_weight(event)
    return counts


def _clip_checkin(text: str) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= _CHECKIN_LIMIT:
        return raw
    return raw[: _CHECKIN_LIMIT - 1].rstrip() + "…"


def light_battery_hint() -> Optional[Dict[str, Any]]:
    """Percent from the local battery sensor. Unknown → None.

    Uses psutil only. No powercfg, no network, no Gemini.
    """
    try:
        import psutil
        battery = psutil.sensors_battery()
    except Exception:
        return None
    if battery is None:
        return None
    try:
        percent = int(battery.percent)
    except (TypeError, ValueError):
        return None
    return {
        "has_battery": True,
        "percent": max(0, min(100, percent)),
        "power_plugged": bool(getattr(battery, "power_plugged", False)),
    }


def _normalize_battery(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict) or not raw.get("has_battery"):
        return None
    try:
        percent = int(raw.get("percent"))
    except (TypeError, ValueError):
        return None
    return {
        "has_battery": True,
        "percent": max(0, min(100, percent)),
        "power_plugged": bool(raw.get("power_plugged")),
    }


def quiet_hours_just_ended(
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    profile: Optional[Dict[str, Any]] = None,
) -> bool:
    """True in the short window after quiet hours end. Still-quiet stays false."""
    stamp = now or datetime.now()
    try:
        from core.companion_profile import in_quiet_hours, quiet_hours_settings
        settings = quiet_hours_settings(profile, base_dir)
        if not settings.get("enabled"):
            return False
        if in_quiet_hours(stamp, base_dir=base_dir, profile=profile):
            return False
        end = str(settings.get("end") or "")
        hour_s, minute_s = end.split(":", 1)
        end_m = int(hour_s) * 60 + int(minute_s)
    except Exception:
        return False
    now_m = stamp.hour * 60 + stamp.minute
    delta = (now_m - end_m) % (24 * 60)
    return delta <= _QUIET_END_GREETING_MIN


def _morning_hint_line(
    *,
    now: datetime,
    base_dir: Optional[str],
    profile: Dict[str, Any],
    events: List[Dict[str, Any]],
    hidden: set,
    focus_on: bool,
    battery: Optional[Dict[str, Any]],
) -> str:
    """At most one calm clause. Focus mode adds nothing extra.

    Priority: yesterday's rough day, quiet hours just ended, then a known low
    battery. The active goal is already a sentence in the check-in body.
    """
    if focus_on:
        return ""
    yesterday = now - timedelta(days=1)
    groups = [
        group for group in machine_stress_groups(events, yesterday)
        if _STRESS_TOPIC.get(group, "") not in hidden
    ]
    choices = {
        "rough_yesterday": (
            "Hôm qua máy hơi nặng, hôm nay mình nói nhẹ."
            if len(groups) >= 2
            else ""
        ),
        "quiet_ended": (
            "Giờ yên vừa hết, mình chào nhẹ."
            if quiet_hours_just_ended(now, base_dir=base_dir, profile=profile)
            else ""
        ),
        "battery_low": "",
    }
    known = _normalize_battery(battery)
    if known is not None and int(known["percent"]) <= _BATTERY_LOW_PERCENT:
        choices["battery_low"] = "Pin đang thấp, mình chào ngắn thôi."
    for key in _MORNING_HINT_ORDER:
        line = str(choices.get(key) or "").strip()
        if line:
            return line
    return ""


def compose_daily_checkin(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
    battery: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """One local morning line from this PC. No Gemini and no network.

    Uses yesterday's journal, the goal title, and at most one extra hint:
    a rough day yesterday, quiet hours just ending, or a known low battery.
    Pass ``battery`` to skip the sensor (tests). ``None`` reads psutil only.
    """
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    try:
        from core.companion import current_stage
        from core.companion_profile import (
            active_muted_topics,
            active_snoozed_topics,
            active_time_windows,
            annotate_learned_line,
            effective_coaching,
            score_trust,
            topic_asks_more,
            topic_for_issue,
        )
        from core.companion_skills import load_skills
        stage = current_stage(config_manager=config_manager, base_dir=base_dir)
        profile = load_profile(base_dir)
        skills = load_skills(base_dir)
        events = recent_events(days=2, limit=0, base_dir=base_dir, now=stamp)
        wider = recent_events(days=21, limit=0, base_dir=base_dir, now=stamp)
    except Exception:
        return None
    muted = set(active_muted_topics(now=stamp, profile=profile))
    snoozed = set(active_snoozed_topics(now=stamp, profile=profile))
    hidden = muted | snoozed
    yesterday = (stamp - timedelta(days=1)).strftime("%Y-%m-%d")
    counts = _yesterday_counts(events, yesterday, hidden)
    goal = profile.get("goal") if isinstance(profile.get("goal"), dict) else None
    goal_text = str((goal or {}).get("text") or "").strip()
    goal_topic = str((goal or {}).get("topic") or "")
    habits = [item for item in (profile.get("habits") or []) if isinstance(item, dict)]
    has_local = bool(counts or (goal_text and goal_topic not in hidden) or habits or skills)
    if stage.stage <= 0 and not has_local:
        return None
    trust = score_trust(profile=profile, base_dir=base_dir, now=stamp)
    coaching = effective_coaching(profile, base_dir=base_dir, now=stamp)
    focus_on = exam_focus_is_live()
    stressed = machine_stress_active(events, stamp)
    try:
        from core.companion_learning import morning_learn_clause, voice_tone_kwargs
        learned_clause = morning_learn_clause(base_dir=base_dir, now=stamp, hidden=hidden)
        tone_extra = voice_tone_kwargs(base_dir)
    except Exception:
        learned_clause = ""
        tone_extra = {}
    if stressed:
        try:
            from core.companion_learning import apply_micro_update
            apply_micro_update("rough_day", now=stamp, base_dir=base_dir)
        except Exception:
            pass
    voice = stage_voice(
        stage.stage,
        coaching=coaching,
        may_propose=bool(stage.may_propose_actions),
        trust=str(trust.get("level") or "steady"),
        focus_active=focus_on,
        stressed=stressed,
        learned_vi=learned_clause,
        **tone_extra,
    )
    shy = voice.get("boldness") in ("shy", "ask")
    parts: List[str] = []
    lead = ""
    if counts:
        lead = max(counts, key=lambda item: (counts[item], item))
        phrase = _YESTERDAY_LINE.get(lead) or _topic_name(lead)
        if stage.stage >= 3 and counts[lead] > 1:
            parts.append(f"Hôm qua {phrase} ({counts[lead]} lần).")
        else:
            parts.append(f"Hôm qua {phrase}.")
    if goal_text and goal_topic not in hidden:
        if shy or stage.stage <= 1:
            parts.append(f"Mục tiêu còn mở: «{goal_text}».")
        else:
            parts.append(f"Mình nhớ mục tiêu «{goal_text}».")
        if not lead:
            lead = goal_topic
    if not parts:
        for habit in habits:
            topic = str(habit.get("topic") or "")
            if topic in hidden:
                continue
            detail = str(habit.get("detail_vi") or habit.get("label_vi") or "").strip()
            if not detail:
                continue
            if not detail.endswith("."):
                detail += "."
            parts.append(detail)
            lead = lead or topic
            break
    if not parts and skills:
        for skill in skills:
            topic = topic_for_issue(getattr(skill, "issue_class", ""))
            if topic in hidden:
                continue
            suggest = str(getattr(skill, "suggest", "") or "").strip()
            if not suggest:
                continue
            parts.append(f"Mình còn nhớ: {suggest}.")
            lead = lead or topic
            break
    if not parts:
        if stage.stage <= 0:
            return None
        if shy:
            parts.append("Hôm qua máy này yên. Mình đang làm quen, chưa có gì mới để kể.")
        else:
            parts.append("Hôm qua máy này yên — mình chưa có gì mới để kể.")
    if lead and lead not in hidden:
        for window in active_time_windows(wider, now=stamp, profile=profile):
            if str(window.get("topic") or "") != lead:
                continue
            phrase = str(window.get("text") or "").strip()
            if phrase and phrase not in " ".join(parts):
                parts.append(phrase)
            break
    if str(trust.get("level") or "") == "low" and parts:
        parts.append("Mình hỏi thêm, chưa đề xuất việc cần làm.")
    known_battery = battery if battery is not None else light_battery_hint()
    hint = _morning_hint_line(
        now=stamp,
        base_dir=base_dir,
        profile=profile,
        events=wider,
        hidden=hidden,
        focus_on=focus_on,
        battery=known_battery if isinstance(known_battery, dict) else None,
    )
    if hint and hint not in " ".join(parts):
        parts.append(hint)
    aside = str(voice.get("aside_vi") or "").strip()
    if aside and (focus_on or stressed) and stage.stage >= 1 and aside not in " ".join(parts):
        parts.append(aside)
    action = None
    skill_id = ""
    if (
        stage.stage >= 2
        and stage.may_propose_actions
        and not shy
        and lead
        and lead not in hidden
        and not topic_asks_more(lead, profile=profile)
    ):
        skill = skill_for_insight(lead, base_dir=base_dir, now=stamp, events=events)
        prefer = str(getattr(skill, "action_key", "") or "")
        try:
            from core.companion_learning import rank_propose_key
            prefer = rank_propose_key(lead, base_dir=base_dir, fallback=prefer, now=stamp)
        except Exception:
            pass
        try:
            action = resolve_insight_action(
                lead,
                stage=stage.stage,
                may_propose=True,
                coaching=effective_coaching(profile, topic=lead, base_dir=base_dir, now=stamp),
                prefer_key=prefer,
            )
        except Exception:
            action = None
        if not action or action.get("key") == "open_companion_memory":
            action = None
        elif skill is not None:
            skill_id = str(getattr(skill, "id", "") or "")
        if action:
            parts.append("Có một việc an toàn nếu bạn muốn — mình không tự chạy.")
    learned = str(voice.get("learned_vi") or learned_clause or "").strip()
    if learned and learned not in " ".join(parts):
        parts.append(learned)
    text = annotate_learned_line(" ".join(parts), lead, profile)
    text = _clip_checkin(redact_sensitive(text))
    if not text:
        return None
    payload: Dict[str, Any] = {
        "date": stamp.strftime("%Y-%m-%d"),
        "text": text,
        "topic": lead,
    }
    if action and action.get("key") and action.get("label_vi"):
        payload["action_key"] = action["key"]
        payload["action_label_vi"] = action["label_vi"]
        if skill_id:
            payload["skill_id"] = skill_id
    return payload


def sync_daily_checkin(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """First meaningful open of the calendar day. Later opens reuse the same line."""
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    try:
        from core.companion_learning import ensure_daily_model
        ensure_daily_model(now=stamp, base_dir=base_dir, config_manager=config_manager)
    except Exception:
        pass
    try:
        from core.companion_profile import in_quiet_hours
        if in_quiet_hours(stamp, base_dir=base_dir):
            return None
    except Exception:
        pass
    today = stamp.strftime("%Y-%m-%d")
    state = load_state(base_dir)
    if str(state.get("last_checkin_date") or "") == today:
        pending = state.get("pending_checkin")
        if isinstance(pending, dict) and str(pending.get("date") or "") == today and pending.get("text"):
            return maybe_attach_pinned_action(
                pending,
                now=stamp,
                base_dir=base_dir,
                config_manager=config_manager,
            )
        return None
    payload = compose_daily_checkin(now=stamp, base_dir=base_dir, config_manager=config_manager)
    if payload:
        payload = maybe_attach_helpful_replay(
            payload,
            now=stamp,
            base_dir=base_dir,
            config_manager=config_manager,
            surface="checkin",
            mark=True,
        )
    state = load_state(base_dir)
    state["last_checkin_date"] = today
    state["pending_checkin"] = payload
    save_state(state, base_dir=base_dir)
    return maybe_attach_pinned_action(
        payload,
        now=stamp,
        base_dir=base_dir,
        config_manager=config_manager,
    )


def dismiss_daily_checkin(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    stamp = now or datetime.now()
    state = load_state(base_dir)
    state["last_checkin_date"] = stamp.strftime("%Y-%m-%d")
    state["pending_checkin"] = None
    save_state(state, base_dir=base_dir)


# A Có ích on an allowlisted tap can be offered once more, within this window.
HELPFUL_REPLAY_DAYS = 7
_HELPFUL_REPLAY_NOTE = "Lần trước có ích — mình để lại nút, không tự chạy."


def remember_helpful_action(
    action_key: str,
    *,
    topic: str = "",
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Remember one allowlisted action the user marked Có ích. Blocked keys are ignored."""
    key = str(action_key or "").strip()
    if not is_allowed_insight_action(key):
        return None
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
        if key in BLOCKED_ACTION_KEYS:
            return None
    except Exception:
        return None
    stamp = now or datetime.now()
    payload = {
        "action_key": key,
        "topic": _topic_for_allowlisted(key) or str(topic or "")[:24],
        "at": stamp.replace(microsecond=0).isoformat(timespec="seconds"),
        "surfaced": False,
    }
    state = load_state(base_dir)
    state["helpful_replay"] = payload
    save_state(state, base_dir=base_dir)
    return payload


def clear_helpful_replay(
    action_key: str = "",
    base_dir: Optional[str] = None,
) -> None:
    """Drop a replay. A key only clears that same action."""
    state = load_state(base_dir)
    current = state.get("helpful_replay")
    if not isinstance(current, dict):
        return
    wanted = str(action_key or "").strip()
    if wanted and str(current.get("action_key") or "") != wanted:
        return
    state["helpful_replay"] = None
    save_state(state, base_dir=base_dir)


def mark_helpful_replay_surfaced(base_dir: Optional[str] = None) -> None:
    state = load_state(base_dir)
    replay = state.get("helpful_replay")
    if not isinstance(replay, dict) or not replay.get("action_key"):
        return
    replay = dict(replay)
    replay["surfaced"] = True
    state["helpful_replay"] = replay
    save_state(state, base_dir=base_dir)


def eligible_helpful_replay(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, str]]:
    """The Có ích action, if propose rules still allow that button.

    Mute, snooze, quiet hours, focus, and a rough day use the same gates as
    other propose buttons. Nothing here invents a key outside the allowlist.
    """
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    state = load_state(base_dir)
    replay = state.get("helpful_replay")
    if not isinstance(replay, dict) or replay.get("surfaced"):
        return None
    key = str(replay.get("action_key") or "").strip()
    if not is_allowed_insight_action(key):
        return None
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
        if key in BLOCKED_ACTION_KEYS:
            return None
    except Exception:
        return None
    at = _parse_iso(replay.get("at"))
    if at is None or stamp - at > timedelta(days=HELPFUL_REPLAY_DAYS):
        return None
    topic = str(replay.get("topic") or "") or _topic_for_allowlisted(key)
    try:
        from core.companion_profile import (
            effective_coaching,
            in_quiet_hours,
            load_profile,
            quiet_hours_allow_actions,
            score_trust,
            topic_asks_more,
            topic_is_muted,
            topic_is_snoozed,
        )
        from core.companion import current_stage
        if topic and (topic_is_muted(topic, base_dir=base_dir, now=stamp) or topic_is_snoozed(topic, base_dir=base_dir, now=stamp)):
            return None
        if in_quiet_hours(stamp, base_dir=base_dir) and not quiet_hours_allow_actions(stamp, base_dir=base_dir):
            return None
        profile = load_profile(base_dir)
        stage = current_stage(config_manager=config_manager, base_dir=base_dir)
        trust = score_trust(profile=profile, base_dir=base_dir, now=stamp)
        coaching = effective_coaching(profile, topic=topic, base_dir=base_dir, now=stamp)
        rows = recent_events(days=1, limit=0, base_dir=base_dir, now=stamp)
        focus_on = exam_focus_is_live()
        stressed = machine_stress_active(rows, stamp)
        voice = stage_voice(
            stage.stage,
            coaching=coaching,
            may_propose=bool(stage.may_propose_actions),
            trust=str(trust.get("level") or "steady"),
            focus_active=focus_on,
            stressed=stressed,
        )
        spec = INSIGHT_ACTION_ALLOWLIST.get(key) or {}
        if spec.get("needs_propose") and voice.get("boldness") in ("shy", "ask"):
            return None
        if topic and topic_asks_more(topic, profile=profile):
            return None
        action = _calm_insight_action(
            {"key": key, "label_vi": str(spec.get("label_vi") or "")},
            focus_active=focus_on,
            stressed=stressed,
        )
        return action
    except Exception:
        return None


def maybe_attach_helpful_replay(
    payload: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
    surface: str = "checkin",
    mark: bool = True,
) -> Optional[Dict[str, Any]]:
    """Offer the last Có ích action once, on the morning line or a matching insight."""
    if not isinstance(payload, dict) or not payload.get("text"):
        return payload
    if payload.get("action_key"):
        return payload
    action = eligible_helpful_replay(now=now, base_dir=base_dir, config_manager=config_manager)
    if not action or not action.get("key"):
        return payload
    if surface == "insight":
        topic = str(payload.get("topic") or "")
        replay_topic = _topic_for_allowlisted(str(action.get("key") or ""))
        if topic and replay_topic and topic != replay_topic:
            return payload
    out = dict(payload)
    out["action_key"] = action["key"]
    out["action_label_vi"] = action.get("label_vi") or ""
    out["helpful_replay"] = True
    text = str(out.get("text") or "")
    if _HELPFUL_REPLAY_NOTE not in text:
        out["text"] = _clip_checkin((text + " " + _HELPFUL_REPLAY_NOTE).strip())
    if mark:
        mark_helpful_replay_surfaced(base_dir)
    return out


# Up to three allowlisted one-tap favorites. Pinning never runs the action.
MAX_PINNED_ACTIONS = 3
_PINNED_CHECKIN_NOTE = "Bạn đã ghim — mình để nút, không tự chạy."


def list_pinned_actions(base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Favorites already stored. Blocked keys are absent after load."""
    rows = load_state(base_dir).get("pinned_actions")
    return [dict(item) for item in rows] if isinstance(rows, list) else []


def pin_favorite_action(
    action_key: str,
    *,
    topic: str = "",
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Pin one allowlisted action. A fourth new key is refused. Blocked keys never stick.

    Pinning does not run the action and does not turn Trước thi / họp on.
    """
    key = str(action_key or "").strip()
    if not is_allowed_insight_action(key):
        return None
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
        if key in BLOCKED_ACTION_KEYS:
            return None
    except Exception:
        return None
    stamp = now or datetime.now()
    state = load_state(base_dir)
    rows = [dict(item) for item in (state.get("pinned_actions") or []) if isinstance(item, dict)]
    for item in rows:
        if str(item.get("action_key") or "") == key:
            return item
    if len(rows) >= MAX_PINNED_ACTIONS:
        return None
    spec = INSIGHT_ACTION_ALLOWLIST.get(key) or {}
    topics = [str(item) for item in (spec.get("topics") or []) if str(item)]
    stored_topic = topics[0] if len(topics) == 1 else str(topic or "")[:24]
    entry = {
        "action_key": key,
        "topic": stored_topic,
        "label_vi": str(spec.get("label_vi") or ""),
        "pinned_at": stamp.replace(microsecond=0).isoformat(timespec="seconds"),
    }
    rows.append(entry)
    state["pinned_actions"] = rows
    save_state(state, base_dir=base_dir)
    try:
        from core.companion_learning import apply_micro_update
        apply_micro_update("pin", topic=stored_topic, action_key=key, now=stamp, base_dir=base_dir)
    except Exception:
        pass
    cleaned = list_pinned_actions(base_dir)
    for item in cleaned:
        if item.get("action_key") == key:
            return item
    return None


def unpin_favorite_action(
    action_key: str,
    base_dir: Optional[str] = None,
) -> bool:
    """Drop one favorite. Unknown keys are a no-op."""
    key = str(action_key or "").strip()
    if not key:
        return False
    state = load_state(base_dir)
    rows = [item for item in (state.get("pinned_actions") or []) if isinstance(item, dict)]
    kept = [item for item in rows if str(item.get("action_key") or "") != key]
    if len(kept) == len(rows):
        return False
    state["pinned_actions"] = kept
    save_state(state, base_dir=base_dir)
    return True


def eligible_pinned_actions(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> List[Dict[str, str]]:
    """Pinned buttons that may show. Mute, snooze, quiet hours, focus, and a rough day hide them.

    The same propose gates as the last Có ích replay. Nothing here runs an action.
    """
    if not _cfg_enabled(config_manager):
        return []
    stamp = now or datetime.now()
    try:
        from core.companion import current_stage
        from core.companion_profile import (
            effective_coaching,
            in_quiet_hours,
            load_profile,
            quiet_hours_allow_actions,
            score_trust,
            topic_asks_more,
            topic_is_muted,
            topic_is_snoozed,
        )
    except Exception:
        return []
    if in_quiet_hours(stamp, base_dir=base_dir) and not quiet_hours_allow_actions(stamp, base_dir=base_dir):
        return []
    profile = load_profile(base_dir)
    stage = current_stage(config_manager=config_manager, base_dir=base_dir)
    trust = score_trust(profile=profile, base_dir=base_dir, now=stamp)
    rows = recent_events(days=1, limit=0, base_dir=base_dir, now=stamp)
    focus_on = exam_focus_is_live()
    stressed = machine_stress_active(rows, stamp)
    out: List[Dict[str, str]] = []
    for pin in list_pinned_actions(base_dir):
        key = str(pin.get("action_key") or "")
        if not is_allowed_insight_action(key):
            continue
        topic = str(pin.get("topic") or "") or _topic_for_allowlisted(key)
        if topic and (
            topic_is_muted(topic, base_dir=base_dir, now=stamp)
            or topic_is_snoozed(topic, base_dir=base_dir, now=stamp)
        ):
            continue
        coaching = effective_coaching(profile, topic=topic, base_dir=base_dir, now=stamp)
        voice = stage_voice(
            stage.stage,
            coaching=coaching,
            may_propose=bool(stage.may_propose_actions),
            trust=str(trust.get("level") or "steady"),
            focus_active=focus_on,
            stressed=stressed,
        )
        spec = INSIGHT_ACTION_ALLOWLIST.get(key) or {}
        if spec.get("needs_propose") and voice.get("boldness") in ("shy", "ask"):
            continue
        if int(spec.get("min_stage") or 0) > int(stage.stage):
            continue
        if topic and topic_asks_more(topic, profile=profile):
            continue
        action = _calm_insight_action(
            {"key": key, "label_vi": str(spec.get("label_vi") or pin.get("label_vi") or "")},
            focus_active=focus_on,
            stressed=stressed,
        )
        if not action or not action.get("key"):
            continue
        out.append({
            "key": str(action.get("key") or ""),
            "label_vi": str(action.get("label_vi") or ""),
            "topic": topic,
        })
    return out


def maybe_attach_pinned_action(
    payload: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Put one favorite on a check-in that does not already have a button.

    The last Có ích action wins when it is already attached. Other favorites
    still show on the card row. This does not write the pin into the saved line.
    """
    if not isinstance(payload, dict) or not payload.get("text"):
        return payload
    if payload.get("action_key"):
        return payload
    pins = eligible_pinned_actions(now=now, base_dir=base_dir, config_manager=config_manager)
    if not pins or not pins[0].get("key"):
        return payload
    out = dict(payload)
    out["action_key"] = pins[0]["key"]
    out["action_label_vi"] = pins[0].get("label_vi") or ""
    out["pinned_action"] = True
    text = str(out.get("text") or "")
    if _PINNED_CHECKIN_NOTE not in text:
        out["text"] = _clip_checkin((text + " " + _PINNED_CHECKIN_NOTE).strip())
    return out


# One local yes/no after an allowlisted tap. No second question while one is open.
FOLLOWUP_DELAY_MIN = {
    "wifi": 60,
    "ram": 30,
    "disk": 45,
    "focus": 90,
    "thermal": 40,
}
_FOLLOWUP_QUESTION = {
    "wifi": "Việc Wi-Fi vừa rồi có giúp máy này không?",
    "ram": "Thu hồi RAM vừa rồi có giúp máy này không?",
    "focus": "Trước thi / họp vừa rồi có giúp bạn không?",
    "disk": "Dọn nhẹ vừa rồi có giúp máy này không?",
    "thermal": "Việc xem nhiệt vừa rồi có giúp bạn không?",
}
_RECOVERY_KINDS = {
    "wifi": ("wifi_repaired", "ping_repaired"),
    "ram": ("ram_optimized",),
    "disk": ("clean_light", "clean_freed"),
    "focus": ("focus_mode",),
    "thermal": (),
}
EOD_HOUR = 18
_EOD_SKIP = frozenset({
    "session_day",
    "reflection",
    "stage_up",
    "skill_saved",
    "user_feedback",
    "suggestion_accepted",
    "suggestion_rejected",
    "tip_snooze",
    "topic_trust",
})
_EOD_LABEL = (
    ("wifi_weak", "Wi-Fi chưa ổn"),
    ("ping_high", "ping cao"),
    ("wifi_repaired", "Wi-Fi ổn lại"),
    ("ping_repaired", "ping đo lại được"),
    ("thermal_warn", "nhiệt cao"),
    ("high_ram", "RAM cao"),
    ("ram_optimized", "đã thu hồi RAM"),
    ("clean_light", "đã dọn nhẹ"),
    ("clean_freed", "đã dọn rác"),
    ("focus_mode", "đã bật Trước thi / họp"),
    ("chat_note", "bạn đã hỏi mình"),
    ("update_fail", "cập nhật chưa xong"),
    ("update_ok", "cập nhật xong"),
)


def _parse_iso(value: Any) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", ""))
    except Exception:
        return None


def _topic_for_allowlisted(action_key: str) -> str:
    spec = INSIGHT_ACTION_ALLOWLIST.get(str(action_key or "")) or {}
    topics = [str(item) for item in (spec.get("topics") or []) if str(item)]
    if len(topics) == 1 and topics[0] in _FOLLOWUP_QUESTION:
        return topics[0]
    return ""


def schedule_action_followup(
    action_key: str,
    *,
    skill_id: str = "",
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Remember one yes/no for later. A second tap does not replace the open one.

    Only allowlisted Wi-Fi / RAM / focus / clean / thermal actions. Destructive
    keys stay out. The question is fixed Vietnamese — no model call.
    """
    if not _cfg_enabled(config_manager):
        return None
    key = str(action_key or "").strip()
    if not is_allowed_insight_action(key):
        return None
    try:
        from core.companion_skills import BLOCKED_ACTION_KEYS
        if key in BLOCKED_ACTION_KEYS:
            return None
    except Exception:
        return None
    topic = _topic_for_allowlisted(key)
    if not topic:
        return None
    state = load_state(base_dir)
    existing = state.get("pending_followup")
    if isinstance(existing, dict) and str(existing.get("question_vi") or "").strip():
        return None
    stamp = now or datetime.now()
    try:
        delay = int(FOLLOWUP_DELAY_MIN.get(topic) or 45)
    except (TypeError, ValueError):
        delay = 45
    delay = max(30, min(120, delay))
    due = stamp + timedelta(minutes=delay)
    since = stamp.replace(microsecond=0).isoformat(timespec="seconds")
    payload = {
        "action_key": key,
        "topic": topic,
        "skill_id": str(skill_id or "")[:40],
        "since": since,
        "due_at": due.replace(microsecond=0).isoformat(timespec="seconds"),
        "question_vi": _FOLLOWUP_QUESTION[topic],
    }
    state["pending_followup"] = payload
    expect = [item for item in (_RECOVERY_KINDS.get(topic) or ()) if item]
    if expect:
        state["pending_outcome"] = {
            "action_key": key,
            "topic": topic,
            "skill_id": payload["skill_id"],
            "since": since,
            "expect": expect,
            "credited": False,
        }
    save_state(state, base_dir=base_dir)
    return payload


def due_action_followup(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, str]]:
    """The open question once it is due.

    Hidden during quiet hours or while its topic is muted. The question stays
    pending so it can show again after those lift.
    """
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    try:
        from core.companion_profile import in_quiet_hours
        if in_quiet_hours(stamp, base_dir=base_dir):
            return None
    except Exception:
        pass
    pending = load_state(base_dir).get("pending_followup")
    if not isinstance(pending, dict):
        return None
    question = str(pending.get("question_vi") or "").strip()
    if not question:
        return None
    try:
        from core.companion_profile import topic_is_muted
        if topic_is_muted(str(pending.get("topic") or ""), base_dir=base_dir, now=stamp):
            return None
    except Exception:
        pass
    due = _parse_iso(pending.get("due_at"))
    if due is not None and stamp < due:
        return None
    return {
        "question_vi": question,
        "topic": str(pending.get("topic") or ""),
        "action_key": str(pending.get("action_key") or ""),
        "skill_id": str(pending.get("skill_id") or ""),
    }


def answer_action_followup(
    helpful: bool,
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Có ích / Chưa. Writes the diary, feeds trust, and nudges skill quality.

    «Chưa» reuses the soft-mute / ask-more path. It does not invent a second mute.
    """
    state = load_state(base_dir)
    pending = state.get("pending_followup")
    if not isinstance(pending, dict) or not str(pending.get("question_vi") or "").strip():
        return None
    topic = str(pending.get("topic") or "")
    skill_id = str(pending.get("skill_id") or "")
    action_key = str(pending.get("action_key") or "")
    state["pending_followup"] = None
    save_state(state, base_dir=base_dir)
    stamp = now or datetime.now()
    try:
        from core.companion import note_user_feedback
        note_user_feedback(
            bool(helpful),
            note="Có ích." if helpful else "Chưa giúp.",
            base_dir=base_dir,
            now=stamp,
            config_manager=config_manager,
            topic=topic,
        )
    except Exception:
        pass
    try:
        from core.companion_profile import topic_issue
        from core.companion_skills import bump_skill_hit
        bump_skill_hit(
            skill_id=skill_id,
            issue_class=topic_issue(topic) if topic else "",
            delta=1 if helpful else -1,
            base_dir=base_dir,
        )
    except Exception:
        pass
    if helpful and action_key:
        try:
            remember_helpful_action(action_key, topic=topic, now=stamp, base_dir=base_dir)
        except Exception:
            pass
    elif action_key:
        try:
            clear_helpful_replay(action_key, base_dir=base_dir)
        except Exception:
            pass
    return {"helpful": bool(helpful), "topic": topic, "action_key": action_key}


def dismiss_action_followup(base_dir: Optional[str] = None) -> None:
    """Hide the question without treating it as «Chưa»."""
    state = load_state(base_dir)
    state["pending_followup"] = None
    save_state(state, base_dir=base_dir)


def note_mute_after_action(
    topic: str,
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> bool:
    """A mute right after a companion action weakens that skill. The mute itself is unchanged.

    Boldness still comes from the existing mute / ask-more rules, not a new flag.
    """
    del now  # the mute timestamp is stored by mute_topic; this only retires the open action
    key = str(topic or "").strip()
    if key not in TOPIC_META:
        return False
    state = load_state(base_dir)
    follow = state.get("pending_followup") if isinstance(state.get("pending_followup"), dict) else {}
    outcome = state.get("pending_outcome") if isinstance(state.get("pending_outcome"), dict) else {}
    if str(follow.get("topic") or "") != key and str(outcome.get("topic") or "") != key:
        return False
    skill_id = str(outcome.get("skill_id") or follow.get("skill_id") or "")
    try:
        from core.companion_profile import topic_issue
        from core.companion_skills import bump_skill_hit
        bump_skill_hit(
            skill_id=skill_id,
            issue_class=topic_issue(key),
            delta=-1,
            base_dir=base_dir,
        )
    except Exception:
        pass
    state = load_state(base_dir)
    state["pending_followup"] = None
    state["pending_outcome"] = None
    save_state(state, base_dir=base_dir)
    return True


def maybe_credit_action_outcome(
    event: Optional[Dict[str, Any]],
    *,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
    config_manager: Optional[Any] = None,
) -> bool:
    """When the diary later shows recovery, strengthen that skill and trust once.

    Trust uses the existing user_feedback accept count. This does not clear a mute
    and does not add a stage point — the bump stays small.
    """
    if not isinstance(event, dict):
        return False
    kind = str(event.get("kind") or "")
    if str(event.get("outcome") or "") not in ("ok", "accepted"):
        return False
    state = load_state(base_dir)
    pending = state.get("pending_outcome")
    if not isinstance(pending, dict) or pending.get("credited"):
        return False
    expect = {str(item) for item in (pending.get("expect") or []) if str(item)}
    if kind not in expect:
        return False
    since = _parse_iso(pending.get("since"))
    stamp = now or _parse_iso(event.get("ts")) or datetime.now()
    if since is not None and stamp < since:
        return False
    topic = str(pending.get("topic") or "")
    skill_id = str(pending.get("skill_id") or "")
    pending = dict(pending)
    pending["credited"] = True
    state["pending_outcome"] = pending
    save_state(state, base_dir=base_dir)
    name = _topic_name(topic) if topic else "việc vừa rồi"
    try:
        from core.companion import record_app_event
        record_app_event(
            "user_feedback",
            f"Nhật ký cho thấy {name} khá hơn sau gợi ý trên máy này.",
            metrics={"helpful": 1},
            source="companion",
            now=stamp,
            base_dir=base_dir,
            config_manager=config_manager,
            outcome="accepted",
            tags=["outcome", topic] if topic else ["outcome"],
            coalesce=False,
        )
    except Exception:
        pass
    try:
        from core.companion_profile import topic_issue
        from core.companion_skills import bump_skill_hit
        bump_skill_hit(
            skill_id=skill_id,
            issue_class=topic_issue(topic) if topic else "",
            delta=1,
            base_dir=base_dir,
        )
    except Exception:
        pass
    return True


def _eod_counts(
    events: List[Dict[str, Any]],
    day: str,
    muted: set,
) -> Dict[str, int]:
    labels = {kind for kind, _label in _EOD_LABEL}
    counts: Dict[str, int] = {}
    for event in events:
        if str(event.get("ts") or "")[:10] != day:
            continue
        kind = str(event.get("kind") or "")
        if kind in _EOD_SKIP or kind not in labels:
            continue
        topic = event_topic(event)
        if topic and topic in muted:
            continue
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def compose_eod_wrap(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """One local evening line from today's diary, the goal, and one matching note."""
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    if stamp.hour < EOD_HOUR:
        return None
    try:
        from core.companion_profile import (
            active_muted_topics,
            annotate_learned_line,
            load_profile,
        )
        profile = load_profile(base_dir)
        events = recent_events(days=2, limit=0, base_dir=base_dir, now=stamp)
        muted = set(active_muted_topics(now=stamp, profile=profile))
    except Exception:
        return None
    day = stamp.strftime("%Y-%m-%d")
    counts = _eod_counts(events, day, muted)
    if not counts:
        return None
    bits: List[str] = []
    lead = ""
    lead_n = 0
    for kind, label in _EOD_LABEL:
        n = int(counts.get(kind) or 0)
        if n <= 0:
            continue
        bits.append(f"{label} ({n})" if n > 1 else label)
        topic = event_topic({"kind": kind})
        if n > lead_n and topic:
            lead = topic
            lead_n = n
    if not bits:
        return None
    parts = ["Cuối ngày: hôm nay " + ", ".join(bits) + "."]
    goal = profile.get("goal") if isinstance(profile.get("goal"), dict) else None
    goal_text = str((goal or {}).get("text") or "").strip()
    goal_topic = str((goal or {}).get("topic") or "")
    if goal_text and goal_topic not in muted:
        parts.append(f"Mục tiêu «{goal_text}» vẫn để đó.")
        if not lead:
            lead = goal_topic
    text = " ".join(parts)
    if lead:
        text = annotate_learned_line(text, lead, profile)
    text = _clip_checkin(redact_sensitive(text))
    if not text or text == "Cuối ngày:":
        return None
    return {"date": day, "text": text, "topic": lead}


def sync_eod_wrap(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """First open after 18:00. Empty days and quiet hours stay quiet and do not consume the slot."""
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    today = stamp.strftime("%Y-%m-%d")
    try:
        from core.companion_profile import in_quiet_hours
        quiet = in_quiet_hours(stamp, base_dir=base_dir)
    except Exception:
        quiet = False
    state = load_state(base_dir)
    if stamp.hour >= EOD_HOUR:
        try:
            from core.companion_learning import ensure_daily_model
            ensure_daily_model(now=stamp, base_dir=base_dir, config_manager=config_manager)
        except Exception:
            pass
    if str(state.get("last_eod_date") or "") == today:
        if quiet:
            return None
        pending = state.get("pending_eod")
        if isinstance(pending, dict) and str(pending.get("text") or "").strip():
            return pending
        return None
    if stamp.hour < EOD_HOUR or quiet:
        return None
    payload = compose_eod_wrap(now=stamp, base_dir=base_dir, config_manager=config_manager)
    if not payload:
        return None
    state = load_state(base_dir)
    state["last_eod_date"] = today
    state["pending_eod"] = payload
    save_state(state, base_dir=base_dir)
    return payload


def dismiss_eod_wrap(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    stamp = now or datetime.now()
    state = load_state(base_dir)
    state["last_eod_date"] = stamp.strftime("%Y-%m-%d")
    state["pending_eod"] = None
    save_state(state, base_dir=base_dir)


# Half a reminder band inside quiet hours means the main reminder is blocked.
_BAND_RANGES = {
    "morning": ((5 * 60, 11 * 60),),
    "afternoon": ((11 * 60, 17 * 60),),
    "evening": ((17 * 60, 22 * 60),),
    "night": ((22 * 60, 24 * 60), (0, 5 * 60)),
}
_BAND_NAME = {
    "morning": "buổi sáng",
    "afternoon": "buổi chiều",
    "evening": "buổi tối",
    "night": "đêm",
}


def _hhmm_to_minutes(value: Any) -> Optional[int]:
    parts = str(value or "").strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError):
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _quiet_ranges(settings: Dict[str, Any]) -> List[tuple]:
    start = _hhmm_to_minutes(settings.get("start"))
    end = _hhmm_to_minutes(settings.get("end"))
    if start is None or end is None or start == end:
        return []
    if start < end:
        return [(start, end)]
    return [(start, 24 * 60), (0, end)]


def _ranges_overlap(left: List[tuple], right: tuple) -> int:
    total = 0
    for a0, a1 in left:
        for b0, b1 in right:
            total += max(0, min(a1, b1) - max(a0, b0))
    return total


def quiet_covers_reminder_band(band: str, settings: Dict[str, Any]) -> bool:
    """True when quiet hours cover at least half of a reminder band."""
    ranges = _BAND_RANGES.get(str(band or ""))
    if not ranges or not settings.get("enabled"):
        return False
    length = sum(end - start for start, end in ranges)
    if length <= 0:
        return False
    return _ranges_overlap(_quiet_ranges(settings), ranges) * 2 >= length


def _dominant_topic_band(events: Optional[List[Dict[str, Any]]], topic: str) -> str:
    """Band where this topic shows up on at least two different days."""
    if not topic:
        return ""
    try:
        from core.companion_diary import time_band
    except Exception:
        return ""
    days: Dict[str, set] = {}
    for event in events or []:
        if event_topic(event) != topic:
            continue
        moment = _parse_iso(event.get("ts"))
        if moment is None:
            continue
        band = time_band(moment)
        days.setdefault(band, set()).add(moment.strftime("%Y-%m-%d"))
    if not days:
        return ""
    best = max(days, key=lambda item: (len(days[item]), item))
    if len(days[best]) < 2:
        return ""
    return best


def compose_goal_conflict(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """One honest line when a goal cannot be reminded the usual way.

    A muted goal topic, or quiet hours covering the morning check-in (or the
    topic's usual band), is the conflict. No line when the goal can still be said.
    """
    if not _cfg_enabled(config_manager):
        return None
    try:
        from core.companion_profile import (
            load_profile,
            quiet_hours_settings,
            topic_is_muted,
        )
        profile = load_profile(base_dir)
    except Exception:
        return None
    goal = profile.get("goal") if isinstance(profile.get("goal"), dict) else None
    if not goal:
        return None
    text = str(goal.get("text") or "").strip()
    topic = str(goal.get("topic") or "")
    if not text:
        return None
    stamp = now or datetime.now()
    muted = bool(topic) and topic_is_muted(topic, base_dir=base_dir, now=stamp, profile=profile)
    settings = quiet_hours_settings(profile)
    covered = ""
    if settings.get("enabled"):
        bands = ["morning"]
        try:
            rows = recent_events(days=21, limit=0, base_dir=base_dir, now=stamp)
        except Exception:
            rows = []
        extra = _dominant_topic_band(rows, topic)
        if extra and extra not in bands:
            bands.append(extra)
        for band in bands:
            if quiet_covers_reminder_band(band, settings):
                covered = _BAND_NAME.get(band, band)
                break
    if not muted and not covered:
        return None
    name = _topic_name(topic) if topic else ""
    window = f"{settings.get('start')}–{settings.get('end')}"
    if muted and covered and name:
        body = (
            f"Mục tiêu «{text}» đang về {name}, nhưng chủ đề này đang im "
            f"và giờ yên lặng {window} cũng che {covered} — mình sẽ không nhắc. "
            "Bạn có thể bỏ im hoặc đổi mục tiêu."
        )
    elif muted and name:
        body = (
            f"Mục tiêu «{text}» đang về {name}, nhưng chủ đề này đang im — mình sẽ không nhắc. "
            "Bạn có thể bỏ im hoặc đổi mục tiêu."
        )
    elif covered:
        body = (
            f"Mục tiêu «{text}» hay được nhắc {covered}, nhưng giờ yên lặng {window} che lúc đó — "
            "mình không nhắc trong giờ yên. Bạn có thể đổi mục tiêu."
        )
    else:
        return None
    body = _clip_checkin(redact_sensitive(body))
    if not body:
        return None
    return {
        "date": stamp.strftime("%Y-%m-%d"),
        "text": body,
        "topic": topic,
        "unmute": bool(muted and topic),
        "edit_goal": True,
    }


def sync_goal_conflict(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Show the conflict at most once per calendar day. Later opens reuse it."""
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    today = stamp.strftime("%Y-%m-%d")
    state = load_state(base_dir)
    if str(state.get("last_goal_conflict_date") or "") == today:
        pending = state.get("pending_goal_conflict")
        if isinstance(pending, dict) and str(pending.get("text") or "").strip():
            return pending
        return None
    payload = compose_goal_conflict(now=stamp, base_dir=base_dir, config_manager=config_manager)
    if not payload:
        return None
    state = load_state(base_dir)
    state["last_goal_conflict_date"] = today
    state["pending_goal_conflict"] = payload
    save_state(state, base_dir=base_dir)
    return payload


def dismiss_goal_conflict(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Hide today's conflict line without changing the goal or the mute."""
    stamp = now or datetime.now()
    state = load_state(base_dir)
    state["last_goal_conflict_date"] = stamp.strftime("%Y-%m-%d")
    state["pending_goal_conflict"] = None
    save_state(state, base_dir=base_dir)


# Local milestones from diary + profile. One celebration a day, each id once.
# Stage-up is not a milestone: pending_stage_up already celebrates it.
USEFUL_ANSWER_GOAL = 5
_MILESTONE_TEXT = {
    "first_week": "Cột mốc: đủ một tuần mình ở cạnh máy này. Cảm ơn bạn đã để mình học dần.",
    "useful_answers": "Cột mốc: bạn đã bảo Có ích năm lần. Mình nhớ những việc thật sự giúp máy này.",
    "focus_session": "Cột mốc: buổi Trước thi / họp đầu tiên đã có lời bạn. Mình sẽ giữ nhẹ.",
}


def _useful_answer_count(events: Optional[List[Dict[str, Any]]]) -> int:
    total = 0
    for event in events or []:
        if str(event.get("kind") or "") != "user_feedback":
            continue
        if "Có ích" not in str(event.get("summary") or ""):
            continue
        if str(event.get("outcome") or "") not in ("accepted", "ok", ""):
            continue
        total += 1
    return total


def _focus_session_with_feedback(events: Optional[List[Dict[str, Any]]]) -> bool:
    ended = False
    answered = False
    for event in events or []:
        kind = str(event.get("kind") or "")
        if kind == "focus_end":
            ended = True
            continue
        if kind != "user_feedback":
            continue
        tags = {str(tag) for tag in (event.get("tags") or [])}
        summary = str(event.get("summary") or "")
        if "focus" in tags or "Trước thi" in summary:
            answered = True
    return ended and answered


def milestone_candidates(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, str]]:
    """Unshown ids are filtered by the caller. This list never includes stage-up."""
    del now  # candidates are facts already on disk, not a clock trick
    try:
        from core.companion_diary import read_events
        events = read_events(base_dir=base_dir, limit=0)
    except Exception:
        events = []
    state = load_state(base_dir)
    dates = state.get("active_dates") if isinstance(state.get("active_dates"), list) else []
    found: List[Dict[str, str]] = []
    if len(dates) >= 7:
        found.append({"id": "first_week", "text": _MILESTONE_TEXT["first_week"]})
    if _useful_answer_count(events) >= USEFUL_ANSWER_GOAL:
        found.append({"id": "useful_answers", "text": _MILESTONE_TEXT["useful_answers"]})
    if _focus_session_with_feedback(events):
        found.append({"id": "focus_session", "text": _MILESTONE_TEXT["focus_session"]})
    return found


def _stage_banner_open(base_dir: Optional[str], today: str) -> bool:
    pending = load_state(base_dir).get("pending_stage_up")
    if not isinstance(pending, dict) or not str(pending.get("text") or "").strip():
        return False
    day = str(pending.get("date") or "")[:10]
    return (not day) or day >= today


def sync_milestone(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """At most one warm line per day. Quiet hours and Trước thi / họp wait.

    A stage-up banner that is still open today blocks a new milestone so the
    same climb is not celebrated twice. Dismissing the stage banner does not
    mark the milestone shown.
    """
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    today = stamp.strftime("%Y-%m-%d")
    try:
        from core.companion_profile import in_quiet_hours
        quiet = in_quiet_hours(stamp, base_dir=base_dir)
    except Exception:
        quiet = False
    if quiet or exam_focus_is_live():
        return None
    state = load_state(base_dir)
    pending = state.get("pending_milestone")
    if (
        isinstance(pending, dict)
        and str(pending.get("text") or "").strip()
        and str(pending.get("date") or "")[:10] == today
    ):
        return pending
    if str(state.get("last_milestone_date") or "") == today:
        return None
    if _stage_banner_open(base_dir, today):
        return None
    shown = [str(item) for item in (state.get("shown_milestones") or [])]
    chosen = None
    for item in milestone_candidates(base_dir=base_dir, now=stamp):
        if str(item.get("id") or "") in shown:
            continue
        chosen = dict(item)
        break
    if not chosen:
        return None
    chosen["date"] = today
    if chosen["id"] not in shown:
        shown.append(chosen["id"])
    state["shown_milestones"] = shown
    state["last_milestone_date"] = today
    state["pending_milestone"] = chosen
    save_state(state, base_dir=base_dir)
    return chosen


def dismiss_milestone(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Hide today's cột mốc. The id stays shown so it does not fire again."""
    stamp = now or datetime.now()
    state = load_state(base_dir)
    state["pending_milestone"] = None
    state["last_milestone_date"] = stamp.strftime("%Y-%m-%d")
    save_state(state, base_dir=base_dir)


def count_focus_sessions_with_feedback(
    events: Optional[List[Dict[str, Any]]],
    now: datetime,
    *,
    days: int = 7,
) -> int:
    """Sessions in the window that also have a Trước thi / họp Có ích or Chưa nearby."""
    sessions = _focus_session_times(list(events or []), now, days=days)
    cutoff = now - timedelta(days=max(1, int(days)))
    feedbacks: List[datetime] = []
    for event in events or []:
        moment = _event_stamp(event)
        if moment is None or moment < cutoff or moment > now + timedelta(minutes=1):
            continue
        if str(event.get("kind") or "") != "user_feedback":
            continue
        tags = {str(tag) for tag in (event.get("tags") or [])}
        summary = str(event.get("summary") or "")
        if "focus" in tags or "Trước thi" in summary:
            feedbacks.append(moment)
    used = [False] * len(feedbacks)
    count = 0
    for sess in sessions:
        for index, feedback in enumerate(feedbacks):
            if used[index]:
                continue
            delta = feedback - sess
            if timedelta(hours=-2) <= delta <= timedelta(hours=36):
                used[index] = True
                count += 1
                break
    return count


_EXAM_HINT_TEXT = (
    "Hôm nay: Bạn đã dùng Trước thi / họp vài lần và có lời. "
    "Khi cần tập trung, bạn có thể tự bật — mình không tự bật."
)


def _exam_hint_blocked(
    stamp: datetime,
    base_dir: Optional[str],
) -> bool:
    """Quiet hours, mute, Đừng nhắc, or an already-on session hide the suggestion."""
    if exam_focus_is_live():
        return True
    try:
        from core.companion_profile import in_quiet_hours, topic_is_muted, topic_is_snoozed
        if in_quiet_hours(stamp, base_dir=base_dir):
            return True
        if topic_is_muted("focus", base_dir=base_dir, now=stamp):
            return True
        if topic_is_snoozed("focus", base_dir=base_dir, now=stamp):
            return True
    except Exception:
        return True
    return False


def sync_exam_season_hint(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """One soft line per ISO week when focus sessions keep showing up with feedback.

    Does not enable Trước thi / họp. Snooze, mute, and quiet hours hold the line
    without burning the week if it has not been shown yet. A snooze after it
    was shown only hides the same line.
    """
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    week = week_key(stamp)
    state = load_state(base_dir)
    pending = state.get("pending_exam_hint")
    blocked = _exam_hint_blocked(stamp, base_dir)
    if isinstance(pending, dict) and str(pending.get("week") or "") == week and pending.get("text"):
        if blocked:
            return None
        return dict(pending)
    if str(state.get("last_exam_hint_week") or "") == week:
        return None
    if blocked:
        return None
    try:
        from core.companion_profile import load_profile
        if str(load_profile(base_dir).get("insight_snooze_date") or "") == stamp.strftime("%Y-%m-%d"):
            return None
    except Exception:
        pass
    try:
        from core.companion_diary import read_events
        events = read_events(base_dir=base_dir, limit=0)
    except Exception:
        events = []
    if count_focus_sessions_with_feedback(events, stamp) < 2:
        return None
    if machine_stress_active(recent_events(days=1, limit=0, base_dir=base_dir, now=stamp), stamp):
        # A rough day waits. The week stays open so the line can appear once it is calm.
        return None
    payload = {
        "id": f"exam_season:{week}",
        "week": week,
        "text": _EXAM_HINT_TEXT,
        "topic": "focus",
    }
    state["pending_exam_hint"] = payload
    state["last_exam_hint_week"] = week
    save_state(state, base_dir=base_dir)
    return dict(payload)


def dismiss_exam_season_hint(
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> None:
    """Hide this week's gợi ý mùa thi. It does not enable anything."""
    stamp = now or datetime.now()
    state = load_state(base_dir)
    state["pending_exam_hint"] = None
    state["last_exam_hint_week"] = week_key(stamp)
    save_state(state, base_dir=base_dir)


def present_exam_season_hint(
    *,
    now: Optional[datetime] = None,
    base_dir: Optional[str] = None,
    config_manager: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """The weekly focus suggestion plus the existing Bật Trước thi / họp button when allowed.

    The button is only the allowlisted key the app already runs when the user taps it.
    This function never calls enable.
    """
    hint = sync_exam_season_hint(now=now, base_dir=base_dir, config_manager=config_manager)
    if not hint:
        return None
    try:
        attached = attach_insight_action(
            hint,
            config_manager=config_manager,
            base_dir=base_dir,
            now=now,
        )
    except Exception:
        attached = dict(hint)
    if not isinstance(attached, dict):
        return dict(hint)
    if attached.get("action_key") != "enable_exam_focus":
        for extra in ("action_key", "action_label_vi", "skill_id", "skill_issue", "helpful_replay"):
            attached.pop(extra, None)
    return attached
