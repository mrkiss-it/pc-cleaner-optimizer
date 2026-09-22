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

# One optional insight button. Nothing here deletes files or edits the registry.
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
}

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
    if len(question) < _MIN_USER_CHARS or len(answer) < _MIN_ANSWER_CHARS:
        return None
    topics = relevant_chat_topics(question, base_dir=base_dir)
    if not topics:
        return None
    topic = topics[0]
    clipped = _clip_question(question)
    if not clipped or clipped == "[redacted]":
        return None
    stamp = now or datetime.now()
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


def learn_from_feedback(
    helpful: bool,
    *,
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """If the last chat was about a known topic, remember the explicit rating."""
    if not _cfg_enabled(config_manager):
        return None
    stamp = now or datetime.now()
    topic = _recent_chat_topic(stamp, base_dir)
    if not topic:
        return None
    name = _topic_name(topic)
    summary = (
        f"Bạn thấy gợi ý {name} hữu ích."
        if helpful
        else f"Bạn thấy gợi ý {name} chưa khớp."
    )
    try:
        from core.companion import record_app_event
        return record_app_event(
            "chat_note",
            summary,
            source="copilot",
            now=stamp,
            base_dir=base_dir,
            config_manager=config_manager,
            outcome="accepted" if helpful else "rejected",
            tags=["chat", "feedback", topic],
            coalesce=True,
        )
    except Exception:
        return None


def is_allowed_insight_action(action_key: str) -> bool:
    return str(action_key or "") in INSIGHT_ACTION_ALLOWLIST


def resolve_insight_action(
    topic: str,
    *,
    stage: int = 0,
    may_propose: bool = True,
    coaching: str = "steady",
) -> Optional[Dict[str, str]]:
    """One safe button, or none. Destructive cleanup is not in the allowlist."""
    try:
        stage_n = max(0, min(3, int(stage)))
    except (TypeError, ValueError):
        stage_n = 0
    topic_key = str(topic or "")
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


def attach_insight_action(
    insight: Optional[Dict[str, str]],
    *,
    config_manager: Optional[Any] = None,
    base_dir: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    if not isinstance(insight, dict) or not insight.get("text"):
        return insight
    try:
        from core.companion import current_stage
        stage = current_stage(config_manager=config_manager, base_dir=base_dir)
        coaching = str(load_profile(base_dir).get("coaching") or "steady")
        action = resolve_insight_action(
            str(insight.get("topic") or ""),
            stage=stage.stage,
            may_propose=bool(stage.may_propose_actions),
            coaching=coaching,
        )
    except Exception:
        action = None
    out = dict(insight)
    out.pop("action_key", None)
    out.pop("action_label_vi", None)
    if action and action.get("key") and action.get("label_vi"):
        out["action_key"] = action["key"]
        out["action_label_vi"] = action["label_vi"]
    return out


def stage_voice(
    stage: int,
    *,
    coaching: str = "steady",
    may_propose: bool = True,
) -> Dict[str, str]:
    """Short tone cue. Stage 0 stays shy; stage 3 may cite this machine."""
    try:
        stage_n = max(0, min(3, int(stage)))
    except (TypeError, ValueError):
        stage_n = 0
    boldness, tone = _STAGE_VOICE[stage_n]
    if coaching == "ask_more" and stage_n >= 1:
        boldness = "ask"
        tone = "Phản hồi gần đây chưa khớp — hỏi thêm, đề xuất ít. " + tone
    elif stage_n >= 2 and not may_propose:
        boldness = "ask"
        tone = tone + " Người dùng chưa bật quyền đề xuất hành động."
    aside = ""
    if stage_n <= 0:
        aside = "Mình mới gặp máy này — nói ngắn và hỏi lại."
    elif stage_n >= 3 and boldness == "specific":
        aside = "Theo nhật ký máy này."
    return {"boldness": boldness, "tone_vi": tone, "policy_vi": tone, "aside_vi": aside}


def action_cap_for_stage(stage: int, *, coaching: str = "steady", may_propose: bool = True) -> int:
    voice = stage_voice(stage, coaching=coaching, may_propose=may_propose)
    if voice["boldness"] in ("shy", "ask"):
        return 0
    if voice["boldness"] == "suggest":
        return 1
    return 2


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
    lines.append("Không phải AGI; không tự chạy việc phá hủy.")
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


def digest_backoff(now: Optional[datetime] = None, hours: int = 3) -> datetime:
    stamp = now or datetime.now()
    return stamp + timedelta(hours=max(1, int(hours)))
