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


def has_skill(issue_class: str, base_dir: Optional[str] = None) -> bool:
    target = str(issue_class or "").lower()
    return any(s.issue_class == target for s in load_skills(base_dir))


def save_skill(
    issue_class: str,
    hit_count: int = 0,
    base_dir: Optional[str] = None,
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
    skill = CompanionSkill(
        id=_safe_id(issue),
        issue_class=issue,
        title=template["title"],
        if_condition=template["if_condition"],
        suggest=template["suggest"],
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


def pending_offer_from_counts(
    kind_counts: Dict[str, int],
    base_dir: Optional[str] = None,
    threshold: int = REPEAT_THRESHOLD,
) -> Optional[Dict[str, Any]]:
    """If a class repeated enough and is not saved yet, return an offer dict."""
    have = {s.issue_class for s in load_skills(base_dir)}
    for issue, count in count_issue_classes(kind_counts).items():
        if count < int(threshold) or issue in have:
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
        if any(token in text for token in _class_tokens(skill.issue_class)) or any(
            token in blob for token in text.split() if len(token) >= 4
        ):
            scored.append(skill)
    return (scored or skills)[:limit]


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
