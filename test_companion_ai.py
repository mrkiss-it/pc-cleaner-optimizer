"""
Unit tests for growing companion AI: stage rules, diary, skills, offline reflection.

No network. Uses a temp companion dir. Stubs winreg on Linux CI.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import urllib.error
from datetime import datetime, timedelta
from unittest.mock import patch

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "winreg" not in sys.modules:
        winreg = types.ModuleType("winreg")
        winreg.HKEY_CURRENT_USER = 1
        winreg.HKEY_LOCAL_MACHINE = 2
        winreg.KEY_READ = 0
        winreg.KEY_WRITE = 0
        winreg.REG_DWORD = 4
        winreg.REG_SZ = 1
        winreg.KEY_WOW64_64KEY = 0x0100

        def _missing(*_a, **_k):
            raise FileNotFoundError("winreg stub")

        winreg.OpenKey = _missing
        winreg.CreateKey = _missing
        winreg.CloseKey = lambda *_a, **_k: None
        winreg.QueryValueEx = _missing
        winreg.SetValueEx = _missing
        winreg.DeleteValue = _missing
        winreg.EnumKey = _missing
        winreg.error = OSError
        sys.modules["winreg"] = winreg
    import ctypes
    if not hasattr(ctypes, "windll"):
        class _P:
            def __getattr__(self, _n):
                return _P()
            def __call__(self, *_a, **_k):
                return 0
        ctypes.windll = _P()  # type: ignore


def _fresh_dir():
    path = tempfile.mkdtemp(prefix="companion-test-")
    os.environ["PCAUTOCLEANER_COMPANION_DIR"] = path
    return path


from core.companion_maturity import compute_stage, build_stage_info, load_state, mark_active_day
from core.companion_diary import (
    append_event,
    format_digest,
    make_event,
    read_events,
    sanitize_summary,
)
from core.companion_skills import (
    BLOCKED_ACTION_KEYS,
    match_skills,
    pending_offer_from_counts,
    save_skill,
)
from core.companion_reflection import (
    OllamaReflectionProvider,
    TemplateReflectionProvider,
    resolve_llm_provider,
    run_reflection,
    template_reflection,
)
from core.companion import (
    accept_skill_offer,
    build_prompt_context,
    current_stage,
    diary_digest,
    empty_states_vi,
    maybe_run_reflection,
    memory_answer,
    note_user_feedback,
    observe_snapshot,
    record_app_event,
    record_session_day,
)
from config_manager import DEFAULT_CONFIG, companion_dir
from app_meta import APP_NAME


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---------------------------------------------------------------------------
# Stage rules
# ---------------------------------------------------------------------------

check(compute_stage(0) == 0, "0 active days → stage 0")
check(compute_stage(1) == 1, "1 active day → stage 1")
check(compute_stage(6) == 1, "6 days no feedback → still stage 1")
check(compute_stage(7) == 2, "7 active days → stage 2")
check(compute_stage(5, positive_feedback=1) == 2, "5 days + feedback → stage 2")
check(compute_stage(5, skills_count=1) == 2, "5 days + skill → stage 2")
check(compute_stage(14) == 2, "14 days no feedback → stage 2 not 3")
check(compute_stage(21) == 3, "21 days → stage 3")
check(compute_stage(14, positive_feedback=2) == 3, "14 days + 2 feedback → stage 3")
check(compute_stage(14, skills_count=1) == 3, "14 days + skill → stage 3")
check(compute_stage(40) == 3, "long use → stage 3")
print(" [PASS] stage rules 0→3 (days of use + optional feedback)")

root = _fresh_dir()
info = current_stage(base_dir=root)
check(info.stage == 0 and info.empty, "fresh install empty stage 0")
check("Mới gặp" in info.badge_vi(), "Vietnamese stage label")
check(info.ask_more is True, "stage 0 asks more")
check(info.may_propose_actions is False, "stage 0 does not propose actions")
# Wall-clock first_seen without active days still stage 0
state = load_state(root)
state["first_seen"] = (datetime.now() - timedelta(days=40)).isoformat()
from core.companion_maturity import save_state
save_state(state, base_dir=root)
info = current_stage(base_dir=root)
check(info.stage == 0, "40 wall-clock days with 0 use days stays stage 0")
print(" [PASS] wall-clock alone does not advance stage")


# ---------------------------------------------------------------------------
# Diary append / read / privacy
# ---------------------------------------------------------------------------

root = _fresh_dir()
ev = append_event(
    "high_ram",
    r"RAM cao; path C:\Users\alice\secret.txt key=AIzaSyABCDEFGHIJ password=hunter2",
    metrics={"ram_percent": 87.4, "command_line": "evil", "path": "C:\\x"},
    source="test",
    base_dir=root,
)
check(ev is not None, "valid event appended")
check("[path]" in ev["summary"] or "secret.txt" not in ev["summary"], "file path stripped")
check("AIza" not in ev["summary"], "api-key-like token redacted")
check("command_line" not in ev["metrics"], "unknown metric keys dropped")
check(ev["metrics"].get("ram_percent") == 87.4, "allowed metric kept")
check(append_event("disk_scan_full", "should drop", base_dir=root) is None, "unknown kind rejected")
check(make_event("high_ram", "") is None, "empty summary rejected")

rows = read_events(base_dir=root)
check(len(rows) == 1, "one diary row")
digest = format_digest(base_dir=root)
check("RAM cao" in digest, "digest cites event")

empty_root = _fresh_dir()
empty_digest = format_digest(base_dir=empty_root)
check("trống" in empty_digest or "cài mới" in empty_digest, "honest empty diary")
check("không bịa" in empty_digest.lower() or "Không bịa" in empty_digest, "no fake memories")
print(" [PASS] diary append/read + privacy sanitization")


# ---------------------------------------------------------------------------
# Skills: match, offer after repeats, not executable
# ---------------------------------------------------------------------------

root = _fresh_dir()
for _ in range(3):
    record_app_event("high_ram", "RAM cao 90%", metrics={"ram_percent": 90}, base_dir=root)
offer = pending_offer_from_counts({"high_ram": 3}, base_dir=root)
check(offer is not None and offer["issue_class"] == "high_ram", "3 repeats → skill offer")
check(offer["action_key"] == "optimize_ram", "offer maps to existing app action")
check(offer["action_key"] not in BLOCKED_ACTION_KEYS, "no destructive skill actions")

skill = accept_skill_offer("high_ram", base_dir=root)
check(skill is not None, "skill saved")
check(skill.action_key == "optimize_ram", "saved playbook is data + action key")
matched = match_skills("tại sao máy ngốn RAM", base_dir=root)
check(len(matched) >= 1 and matched[0].issue_class == "high_ram", "skill match by user text")
check(pending_offer_from_counts({"high_ram": 5}, base_dir=root) is None, "no re-offer after save")
print(" [PASS] skill crystallisation / match")


# ---------------------------------------------------------------------------
# Reflection without network
# ---------------------------------------------------------------------------

root = _fresh_dir()
record_app_event("clean_freed", "Dọn rác giải phóng 120 MB", metrics={"junk_freed_mb": 120}, base_dir=root)
note = template_reflection(
    digest=diary_digest(base_dir=root),
    kind_counts={"clean_freed": 1},
    active_days=1,
    stage_label="Giai đoạn 1 · Đang học",
)
check("Sổ tay" in note, "template has sổ tay header")
check("không dùng mô hình" in note.lower() or "Không dùng mô hình" in note, "honest no-LLM")
check("AGI" in note, "disclaims AGI")
check("120" in note or "dọn rác" in note.lower() or "Dọn rác" in note, "cites metrics")

net_calls = []

def _boom(*_a, **_k):
    net_calls.append(1)
    raise urllib.error.URLError("network disabled")

with patch("urllib.request.urlopen", side_effect=_boom):
    result = run_reflection(
        digest=diary_digest(base_dir=root),
        kind_counts={"clean_freed": 1},
        active_days=1,
        stage_label="Giai đoạn 1 · Đang học",
        provider=TemplateReflectionProvider(),
        base_dir=root,
    )
check(result["source"] == "template", "template provider used")
check(net_calls == [], "template reflection does not touch network")
check(os.path.exists(os.path.join(root, "so_tay.txt")), "sổ tay persisted")

class _Cfg(dict):
    def get(self, k, default=None):
        return super().get(k, default)

cfg_local = _Cfg(ai_copilot_ollama_enabled=True, ai_copilot_ollama_host="http://127.0.0.1:11434")
provider = resolve_llm_provider(cfg_local)
check(provider.name == "ollama", "prefer Ollama hook when configured")

cfg_off = _Cfg()
check(resolve_llm_provider(cfg_off).name == "template", "no LLM → template")

forced = maybe_run_reflection(_Cfg(), force=True, provider=TemplateReflectionProvider(), base_dir=root)
check(forced and forced["source"] == "template", "on-demand reflection works offline")
print(" [PASS] reflection without network + ollama provider hook")


# ---------------------------------------------------------------------------
# Prompt injection + memory answer
# ---------------------------------------------------------------------------

root = _fresh_dir()
record_app_event("wifi_weak", "Wi-Fi yếu trên máy này", base_dir=root)
ctx = build_prompt_context("wifi chậm", base_dir=root)
check("AI đồng hành" in ctx, "prompt has companion block")
check("không phải AGI" in ctx.lower() or "Không phải AGI" in ctx or "không phải AGI" in ctx, "honest AGI disclaimer")
check("Wi-Fi" in ctx or "wifi" in ctx.lower(), "diary cited in prompt")
ans = memory_answer("Nhật ký máy này nhớ gì?", base_dir=root)
check("Giai đoạn" in ans, "memory answer shows stage")
check("Wi-Fi" in ans or "wifi" in ans.lower(), "memory answer cites diary")

empty = empty_states_vi()
check("Chưa có nhật ký" in empty["diary"], "honest empty diary copy")
check("Chưa có kỹ năng" in empty["skills"], "honest empty skills copy")
check("Pro" not in empty["stage"], "no Pro branding")
check("&" in APP_NAME or "Optimizer" in APP_NAME, "APP_NAME used")
print(" [PASS] prompt injection + honest empty states")

from core.ai_copilot import AICopilotEngine
eng = AICopilotEngine()
hook_lines = eng.extra_prompt_context(user_prompt="wifi chậm")
hook_blob = "\n".join(hook_lines)
check("AI đồng hành" in hook_blob, "extra_context_provider default injects companion")
check("Wi-Fi" in hook_blob or "wifi" in hook_blob.lower(), "Gemini/Ollama share diary via extra_context")
print(" [PASS] extra_context hook shares companion memory")


# ---------------------------------------------------------------------------
# Session day vs snapshot cooldown
# ---------------------------------------------------------------------------

root = _fresh_dir()
now = datetime(2026, 9, 20, 21, 15, 0)
a = record_session_day(now=now, base_dir=root)
b = record_session_day(now=now, base_dir=root)
check(a is not None, "first session_day written")
check(b is None, "second session_day same day skipped")
check(current_stage(base_dir=root).active_days == 1, "one active day")

observe_snapshot(ram_percent=91, ram_threshold=80, now=now, base_dir=root)
observe_snapshot(ram_percent=91, ram_threshold=80, now=now, base_dir=root)
kinds = [e["kind"] for e in read_events(base_dir=root)]
check(kinds.count("high_ram") == 1, "high_ram snapshot cooldown")
print(" [PASS] session day uniqueness + snapshot cooldown")

check(DEFAULT_CONFIG.get("companion_enabled") is True, "companion on by default (local)")
check("companion_may_propose_actions" in DEFAULT_CONFIG, "consent setting exists")
check(companion_dir() == os.environ["PCAUTOCLEANER_COMPANION_DIR"], "env override for tests")
print(" [PASS] config defaults")

print(" [PASS] companion AI suite")
