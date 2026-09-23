"""
Skill crystallisation — local playbooks, not executable code.

When the same class of issue repeats on this PC, offer to save a structured
tip the Copilot can load into context (if X on this machine → suggest Y).
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config_manager import companion_dir

SKILLS_FILENAME = "skills.json"
REPEAT_THRESHOLD = 3

# Map diary kinds → skill issue class
KIND_TO_CLASS = {
    "high_ram": "high_ram",
    "ram_optimized": "high_ram",
    "wifi_weak": "wifi_weak",
    "wifi_repaired": "wifi_weak",
    "ping_high": "wifi_weak",
    "ping_repaired": "wifi_weak",
    "clean_freed": "disk_low",
    "clean_light": "disk_low",
    "focus_mode": "focus",
    "thermal_warn": "thermal",
}

PLAYBOOKS: Dict[str, Dict[str, str]] = {
    "high_ram": {
        "title": "RAM cao trên máy này",
        "if_condition": "RAM ≥ ngưỡng quá tải trên máy này",
        "suggest": "Thu hồi RAM standby (không tắt app đang dùng)",
        "action_key": "optimize_ram",
    },
    "wifi_weak": {
        "title": "Wi-Fi yếu / ping lỗi trên máy này",
        "if_condition": "Wi-Fi flap hoặc ping không đo được",
        "suggest": "Chẩn đoán rồi sửa an toàn (DNS / DHCP / reconnect SSID)",
        "action_key": "repair_network_now",
    },
    "disk_low": {
        "title": "Ổ C hay đầy rác trên máy này",
        "if_condition": "Thường xuyên dọn rác hoặc dung lượng thấp",
        "suggest": "Dọn nhẹ temp/crash dump — không WinSxS, không thùng rác",
        "action_key": "clean_light",
    },
    "focus": {
        "title": "Thói quen tập trung trên máy này",
        "if_condition": "Người dùng bật Trước thi / họp lặp lại",
        "suggest": "Đề xuất bật chế độ Trước thi / họp (có hoàn tác)",
        "action_key": "enable_exam_focus",
    },
    "thermal": {
        "title": "Máy hay nóng trên laptop này",
        "if_condition": "Nhiệt vượt ngưỡng cảnh báo",
        "suggest": "Xem giám sát nhiệt; có thể bật tiết kiệm pin — không bịa °C",
        "action_key": "view_hardware",
    },
}

# Never stored as skills — destructive / irreversible
BLOCKED_ACTION_KEYS = frozenset({
    "winsxs_cleanup",
    "clean_disk",
    "clean_junk",
    "auto_optimize_all",
    "switch_dns",
})


@dataclass
class CompanionSkill:
    id: str
    issue_class: str
    title: str
    if_condition: str
    suggest: str
    action_key: str
    created_at: str = ""
    hit_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "issue_class": self.issue_class,
            "title": self.title,
            "if_condition": self.if_condition,
            "suggest": self.suggest,
            "action_key": self.action_key,
            "created_at": self.created_at,
            "hit_count": int(self.hit_count),
        }

    def context_line(self) -> str:
        return f"- Nếu {self.if_condition} → {self.suggest}"


def skills_path(base_dir: Optional[str] = None) -> str:
    return os.path.join(base_dir or companion_dir(), SKILLS_FILENAME)


def _atomic_write_json(path: str, data: Any) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _safe_id(issue_class: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", str(issue_class or "skill").lower()).strip("_")
    return slug or "skill"


def skill_from_dict(raw: Dict[str, Any]) -> Optional[CompanionSkill]:
    if not isinstance(raw, dict):
        return None
    issue = str(raw.get("issue_class") or "").strip().lower()
    if issue not in PLAYBOOKS:
        return None
    template = PLAYBOOKS[issue]
    action = str(raw.get("action_key") or template["action_key"]).strip()
    if action in BLOCKED_ACTION_KEYS:
        action = template["action_key"]
    if action in BLOCKED_ACTION_KEYS:
        return None
    return CompanionSkill(
        id=str(raw.get("id") or _safe_id(issue)),
        issue_class=issue,
        title=str(raw.get("title") or template["title"])[:80],
        if_condition=str(raw.get("if_condition") or template["if_condition"])[:120],
        suggest=str(raw.get("suggest") or template["suggest"])[:160],
        action_key=action,
        created_at=str(raw.get("created_at") or ""),
        hit_count=int(raw.get("hit_count") or 0),
    )


def load_skills(base_dir: Optional[str] = None) -> List[CompanionSkill]:
    path = skills_path(base_dir)
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    rows = data if isinstance(data, list) else data.get("skills") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    out: List[CompanionSkill] = []
    seen = set()
    for item in rows:
        skill = skill_from_dict(item) if isinstance(item, dict) else None
        if skill is None or skill.id in seen:
            continue
        seen.add(skill.id)
        out.append(skill)
    return out


def save_skills(skills: List[CompanionSkill], base_dir: Optional[str] = None) -> None:
    payload = [s.to_dict() for s in skills if isinstance(s, CompanionSkill)]
    _atomic_write_json(skills_path(base_dir), payload)


def bump_skill_hit(
    skill_id: str = "",
    issue_class: str = "",
    base_dir: Optional[str] = None,
) -> Optional[CompanionSkill]:
    """+1 hit_count when the user taps a skill-backed insight or check-in button.

    Showing the line does not count. If this stage cannot run the skill's own
    action, the nearest allowlisted button still counts — the tap came from
    that skill.
    """
    wanted_id = str(skill_id or "").strip()
    wanted_issue = str(issue_class or "").strip().lower()
    if not wanted_id and not wanted_issue:
        return None
    skills = load_skills(base_dir)
    found: Optional[CompanionSkill] = None
    for skill in skills:
        if wanted_id and skill.id == wanted_id:
            found = skill
            break
        if wanted_issue and skill.issue_class == wanted_issue:
            found = skill
            break
    if found is None:
        return None
    found.hit_count = int(found.hit_count or 0) + 1
    save_skills(skills, base_dir=base_dir)
    return found


def has_skill(issue_class: str, base_dir: Optional[str] = None) -> bool:
    target = str(issue_class or "").lower()
    return any(s.issue_class == target for s in load_skills(base_dir))


def save_skill(
    issue_class: str,
    hit_count: int = 0,
    base_dir: Optional[str] = None,
    suggest: str = "",
    if_condition: str = "",
) -> Optional[CompanionSkill]:
    issue = str(issue_class or "").strip().lower()
    template = PLAYBOOKS.get(issue)
    if not template:
        return None
    skills = load_skills(base_dir)
    for existing in skills:
        if existing.issue_class == issue:
            existing.hit_count = max(existing.hit_count, int(hit_count or 0))
            save_skills(skills, base_dir=base_dir)
            return existing
    custom_suggest = str(suggest or "").strip() or template["suggest"]
    custom_if = str(if_condition or "").strip() or template["if_condition"]
    skill = CompanionSkill(
        id=_safe_id(issue),
        issue_class=issue,
        title=template["title"],
        if_condition=custom_if[:120],
        suggest=custom_suggest[:160],
        action_key=template["action_key"],
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        hit_count=max(0, int(hit_count or 0)),
    )
    if skill.action_key in BLOCKED_ACTION_KEYS:
        return None
    skills.append(skill)
    save_skills(skills, base_dir=base_dir)
    return skill


def issue_class_for_kind(kind: str) -> str:
    return KIND_TO_CLASS.get(str(kind or "").lower(), "")


def count_issue_classes(kind_counts: Dict[str, int]) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for kind, count in (kind_counts or {}).items():
        issue = issue_class_for_kind(kind)
        if not issue:
            continue
        try:
            n = int(count)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            continue
        totals[issue] = totals.get(issue, 0) + n
    return totals


def _declined_issues(base_dir: Optional[str] = None, now=None) -> set:
    """Issue classes the user skipped recently — don't nag the same offer."""
    try:
        from datetime import datetime
        from core.companion_maturity import load_state
        raw = load_state(base_dir).get("declined_skill_until") or {}
    except Exception:
        return set()
    if not isinstance(raw, dict):
        return set()
    stamp = now or datetime.now()
    active = set()
    for issue, until in raw.items():
        try:
            if datetime.fromisoformat(str(until)) > stamp:
                active.add(str(issue or "").strip().lower())
        except Exception:
            continue
    return active


def pending_offer_from_counts(
    kind_counts: Dict[str, int],
    base_dir: Optional[str] = None,
    threshold: int = REPEAT_THRESHOLD,
    now=None,
) -> Optional[Dict[str, Any]]:
    """If a class repeated enough and is not saved yet, return an offer dict."""
    have = {s.issue_class for s in load_skills(base_dir)}
    declined = _declined_issues(base_dir, now=now)
    for issue, count in count_issue_classes(kind_counts).items():
        if count < int(threshold) or issue in have or issue in declined:
            continue
        template = PLAYBOOKS.get(issue) or {}
        if not template:
            continue
        return {
            "issue_class": issue,
            "hit_count": count,
            "title": template["title"],
            "if_condition": template["if_condition"],
            "suggest": template["suggest"],
            "action_key": template["action_key"],
        }
    return None


def match_skills(
    user_text: str = "",
    issue_class: str = "",
    base_dir: Optional[str] = None,
    limit: int = 3,
) -> List[CompanionSkill]:
    skills = load_skills(base_dir)
    if not skills:
        return []
    wanted = str(issue_class or "").strip().lower()
    if wanted:
        matched = [s for s in skills if s.issue_class == wanted]
        return matched[:limit]

    text = _fold(user_text)
    if not text.strip():
        return skills[:limit]

    scored: List[CompanionSkill] = []
    for skill in skills:
        blob = _fold(f"{skill.title} {skill.if_condition} {skill.suggest} {skill.issue_class}")
        if any(_term_in(text, token) for token in _class_tokens(skill.issue_class)) or any(
            token in blob for token in text.split() if len(token) >= 4
        ):
            scored.append(skill)
    return scored[:limit]


def _term_in(text: str, token: str) -> bool:
    needle = str(token or "").strip().lower()
    if not needle:
        return False
    if " " in needle:
        return needle in text
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", text) is not None


def _class_tokens(issue_class: str) -> List[str]:
    mapping = {
        "high_ram": ("ram", "bo nho", "bộ nhớ", "đơ", "do may", "lag"),
        "wifi_weak": ("wifi", "wi-fi", "mang", "mạng", "ping"),
        "disk_low": ("o c", "ổ c", "rac", "rác", "disk", "dung luong"),
        "focus": ("thi", "hop", "họp", "tap trung", "tập trung", "focus"),
        "thermal": ("nong", "nóng", "nhiet", "nhiệt", "quat", "quạt"),
    }
    return list(mapping.get(issue_class, ()))


def _fold(text: str) -> str:
    s = str(text or "").lower()
    repl = {
        "à": "a", "á": "a", "ả": "a", "ã": "a", "ạ": "a",
        "ă": "a", "ằ": "a", "ắ": "a", "ẳ": "a", "ẵ": "a", "ặ": "a",
        "â": "a", "ầ": "a", "ấ": "a", "ẩ": "a", "ẫ": "a", "ậ": "a",
        "đ": "d",
        "è": "e", "é": "e", "ẻ": "e", "ẽ": "e", "ẹ": "e",
        "ê": "e", "ề": "e", "ế": "e", "ể": "e", "ễ": "e", "ệ": "e",
        "ì": "i", "í": "i", "ỉ": "i", "ĩ": "i", "ị": "i",
        "ò": "o", "ó": "o", "ỏ": "o", "õ": "o", "ọ": "o",
        "ô": "o", "ồ": "o", "ố": "o", "ổ": "o", "ỗ": "o", "ộ": "o",
        "ơ": "o", "ờ": "o", "ớ": "o", "ở": "o", "ỡ": "o", "ợ": "o",
        "ù": "u", "ú": "u", "ủ": "u", "ũ": "u", "ụ": "u",
        "ư": "u", "ừ": "u", "ứ": "u", "ử": "u", "ữ": "u", "ự": "u",
        "ỳ": "y", "ý": "y", "ỷ": "y", "ỹ": "y", "ỵ": "y",
    }
    for src, dst in repl.items():
        s = s.replace(src, dst)
    return s


def format_skills_context(skills: List[CompanionSkill], empty_vi: str = "") -> str:
    if not skills:
        return empty_vi or "Chưa có kỹ năng lưu cho máy này."
    return "\n".join(s.context_line() for s in skills)


def format_skill_row(skill: Optional[CompanionSkill]) -> str:
    if skill is None:
        return ""
    title = str(skill.title or "").strip()
    suggest = str(skill.suggest or "").strip()
    if title and suggest:
        return f"{title} — {suggest}"
    return title or suggest


def delete_skill(skill_id: str, base_dir: Optional[str] = None) -> bool:
    wanted = str(skill_id or "").strip()
    if not wanted:
        return False
    skills = load_skills(base_dir)
    kept = [s for s in skills if s.id != wanted]
    if len(kept) == len(skills):
        return False
    save_skills(kept, base_dir=base_dir)
    return True


def clear_skills(base_dir: Optional[str] = None) -> int:
    skills = load_skills(base_dir)
    save_skills([], base_dir=base_dir)
    return len(skills)


def fold_vi(text: str) -> str:
    return _fold(text)


def _event_weight(event: Dict[str, Any]) -> int:
    metrics = event.get("metrics") if isinstance(event.get("metrics"), dict) else {}
    try:
        weight = int(metrics.get("count") or 1)
    except (TypeError, ValueError):
        weight = 1
    return max(1, weight)


def _weighted(events: Optional[List[Dict[str, Any]]], kinds: set, *, tags_any: Optional[set] = None, outcome: str = "") -> int:
    total = 0
    for event in events or []:
        if str(event.get("kind") or "") not in kinds:
            continue
        if outcome and str(event.get("outcome") or "") != outcome:
            continue
        if tags_any and not (set(event.get("tags") or []) & tags_any):
            continue
        total += _event_weight(event)
    return total


def action_to_issue() -> Dict[str, str]:
    return {str(meta.get("action_key") or ""): issue for issue, meta in PLAYBOOKS.items()}


def rejected_issue_classes(events: Optional[List[Dict[str, Any]]]) -> set:
    """User turned down a suggestion — don't auto-save that playbook."""
    mapping = action_to_issue()
    blocked = set()
    for event in events or []:
        if str(event.get("kind") or "") != "suggestion_rejected":
            continue
        for tag in event.get("tags") or []:
            issue = mapping.get(str(tag)) or (str(tag) if str(tag) in PLAYBOOKS else "")
            if issue:
                blocked.add(issue)
    return blocked


def should_crystallize(
    issue_class: str,
    kind_counts: Optional[Dict[str, int]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    threshold: int = REPEAT_THRESHOLD,
) -> bool:
    """Quality bar: repeats alone are not enough unless the pattern is specific."""
    issue = str(issue_class or "").strip().lower()
    if issue not in PLAYBOOKS:
        return False
    hits = int(count_issue_classes(kind_counts or {}).get(issue) or 0)
    if hits < int(threshold):
        return False
    rows = events or []
    if issue == "wifi_weak":
        late = _weighted(rows, {"wifi_weak", "ping_high"}, tags_any={"evening", "night"})
        repaired = _weighted(rows, {"wifi_repaired", "ping_repaired"}, outcome="ok")
        return late >= 2 or repaired >= 1 or hits >= 5
    if issue == "high_ram":
        optimized = _weighted(rows, {"ram_optimized"}, outcome="ok")
        return optimized >= 1 or hits >= 5
    if issue == "disk_low":
        return hits >= 4
    if issue == "thermal":
        return hits >= 3
    if issue == "focus":
        return hits >= 3
    return False


def evidence_suggest(issue_class: str, events: Optional[List[Dict[str, Any]]] = None) -> str:
    """Short, safe playbook line grounded in what this machine actually did."""
    issue = str(issue_class or "").strip().lower()
    template = (PLAYBOOKS.get(issue) or {}).get("suggest") or ""
    rows = events or []
    if issue == "wifi_weak":
        late = _weighted(rows, {"wifi_weak", "ping_high"}, tags_any={"evening", "night"})
        repaired = _weighted(rows, {"wifi_repaired", "ping_repaired"}, outcome="ok")
        if late >= 2:
            return "Wi-Fi hay yếu buổi tối trên máy này — tắt tiết kiệm điện Wi-Fi, không tự đổi DNS."
        if repaired >= 1:
            return "Sửa Wi-Fi an toàn (reconnect / tắt tiết kiệm pin) đã giúp máy này."
    if issue == "high_ram":
        if _weighted(rows, {"ram_optimized"}, outcome="ok") >= 1:
            return "RAM hay cao — thu hồi RAM standby, không tắt app đang dùng."
    if issue == "disk_low":
        return "Ổ này hay đầy rác — ưu tiên Dọn nhẹ, không WinSxS, không thùng rác."
    if issue == "thermal":
        return "Laptop hay nóng — xem giám sát nhiệt; có thể bật tiết kiệm pin, không bịa °C."
    if issue == "focus":
        return "Bạn hay bật Trước thi / họp — có thể gợi ý lại, không tự bật."
    return template


_OPEN_FAILURES = {
    "wifi_weak": ({"wifi_weak", "ping_high"}, {"wifi_repaired", "ping_repaired"}),
    "thermal": ({"thermal_warn"}, set()),
    "high_ram": ({"high_ram"}, {"ram_optimized"}),
}


def issue_is_open_failure(
    issue_class: str,
    events: Optional[List[Dict[str, Any]]] = None,
    min_warn: int = 3,
) -> bool:
    """Repeated warnings that never recovered — worth a skill more than a one-off."""
    spec = _OPEN_FAILURES.get(str(issue_class or "").strip().lower())
    if not spec:
        return False
    warn_kinds, ok_kinds = spec
    if _weighted(events, warn_kinds) < int(min_warn):
        return False
    if ok_kinds and _weighted(events, ok_kinds, outcome="ok") > 0:
        return False
    return True


def crystallize_skills(
    kind_counts: Optional[Dict[str, int]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    base_dir: Optional[str] = None,
    max_new: int = 2,
    prefer_issues: Optional[List[str]] = None,
) -> List[CompanionSkill]:
    """Save at most 1–2 skills tied to the goal or an open failure.

    When nothing is goal-related or still failing, fall back to the strongest
    repeated playbook so a machine without a goal can still learn.
    """
    counts = kind_counts or {}
    rows = events or []
    rejected = rejected_issue_classes(rows)
    have = {s.issue_class for s in load_skills(base_dir)}
    ranked = sorted(
        count_issue_classes(counts).items(),
        key=lambda item: (-int(item[1]), item[0]),
    )
    hits_by_issue = {issue: int(hits) for issue, hits in ranked}
    qualified: List[str] = []
    for issue, hits in ranked:
        if issue in have or issue in rejected:
            continue
        if not should_crystallize(issue, counts, rows):
            continue
        qualified.append(issue)
    requested = [str(issue or "").strip().lower() for issue in (prefer_issues or []) if str(issue or "").strip()]
    preferred = [issue for issue in requested if issue in qualified]
    failures = [issue for issue in qualified if issue_is_open_failure(issue, rows)]
    # A set goal narrows new skills to that goal or an open failure — not every playbook.
    if requested or failures:
        pool = []
        for issue in preferred + failures:
            if issue not in pool:
                pool.append(issue)
    else:
        pool = list(qualified)
    saved: List[CompanionSkill] = []
    for issue in pool:
        if len(saved) >= max(1, int(max_new)):
            break
        skill = save_skill(
            issue,
            hit_count=int(hits_by_issue.get(issue) or 0),
            base_dir=base_dir,
            suggest=evidence_suggest(issue, rows),
        )
        if skill is None or skill.action_key in BLOCKED_ACTION_KEYS:
            continue
        saved.append(skill)
    return saved
