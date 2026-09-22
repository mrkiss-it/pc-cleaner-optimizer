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
    load_skills,
    match_skills,
    pending_offer_from_counts,
    save_skill,
)
from core.companion_reflection import (
    TemplateReflectionProvider,
    resolve_llm_provider,
    run_reflection,
    template_reflection,
)
from core.companion import (
    REFLECT_BUTTON_VI,
    accept_skill_offer,
    build_prompt_context,
    clear_diary_memory,
    clear_local_memory,
    clear_skills_memory,
    confirm_clear_prompt,
    current_stage,
    delete_diary_entry,
    delete_saved_skill,
    diary_digest,
    diary_is_empty,
    empty_states_vi,
    format_diary_browse,
    format_reflection_feedback,
    format_skills_browse,
    maybe_run_reflection,
    memory_answer,
    note_user_feedback,
    observe_snapshot,
    record_app_event,
    record_session_day,
    reset_postscript_gate,
    should_emit_postscript,
    stage_caption_vi,
    stage_legend_vi,
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

cfg_gemini = _Cfg(ai_copilot_provider="gemini", ai_copilot_gemini_api_key="AIzaSy-test")
check(resolve_llm_provider(cfg_gemini).name == "gemini", "prefer Gemini when key is set")

cfg_legacy_ollama = _Cfg(ai_copilot_provider="ollama", ai_copilot_gemini_api_key="AIzaSy-test")
check(resolve_llm_provider(cfg_legacy_ollama).name == "gemini", "retired ollama provider with key → Gemini")

cfg_off = _Cfg()
check(resolve_llm_provider(cfg_off).name == "template", "no LLM → template")

forced = maybe_run_reflection(_Cfg(), force=True, provider=TemplateReflectionProvider(), base_dir=root)
check(forced and forced["source"] == "template", "on-demand reflection works offline")
print(" [PASS] reflection without network + Gemini provider hook")


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

from core.ai_copilot import AICopilotEngine, CloudAIBrain, TelemetryCollector
eng = AICopilotEngine()
hook_lines = eng.extra_prompt_context(user_prompt="wifi chậm")
hook_blob = "\n".join(hook_lines)
check("AI đồng hành" in hook_blob, "extra_context_provider default injects companion")
check("Wi-Fi" in hook_blob or "wifi" in hook_blob.lower(), "Gemini extra_context has diary")

class _AskCfg:
    def __init__(self, **store):
        self.store = dict(store)

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value):
        self.store[key] = value

captured = {}
_tel = {
    "ram": {"percent": 10.0, "used_gb": 1.0, "total_gb": 8.0},
    "cpu": {"percent": 5.0, "count": 4},
    "disk": {"free_gb": 50.0, "total_gb": 256.0},
    "net": {},
}

def _fake_gemini(*_a, **kwargs):
    captured["gemini"] = kwargs.get("extra_context")
    return "ok-gemini"

captured.clear()
eng_g = AICopilotEngine(config_manager=_AskCfg(
    ai_copilot_provider="gemini",
    ai_copilot_gemini_api_key="AIzaSy-test-key",
))
with patch.object(CloudAIBrain, "query_gemini", side_effect=_fake_gemini), \
        patch.object(TelemetryCollector, "collect", return_value=_tel):
    msg_g = eng_g.ask("wifi chậm")
blob_g = "\n".join(captured.get("gemini") or [])
check(msg_g.source == "cloud_gemini", "gemini path used")
check("AI đồng hành" in blob_g, "Gemini extra_context has companion")
check("Wi-Fi" in blob_g or "wifi" in blob_g.lower(), "Gemini extra_context has diary")

captured.clear()
eng_auto = AICopilotEngine(config_manager=_AskCfg(ai_copilot_provider="auto"))
with patch.object(CloudAIBrain, "query_gemini", side_effect=_fake_gemini), \
        patch.object(TelemetryCollector, "collect", return_value=_tel):
    msg_auto = eng_auto.ask("wifi chậm")
check(captured.get("gemini") is None, "auto without API key does not call Gemini HTTP")
check(msg_auto.source == "offline_expert", "auto without key uses Offline Expert")
check("cần mạng" in msg_auto.content.lower() or "API key" in msg_auto.content, "honest Gemini network/key message")
check("AI đồng hành" in "\n".join(eng_auto.extra_prompt_context(user_prompt="wifi chậm")), "companion still injects without Gemini")
print(" [PASS] extra_context hook injects companion memory into Gemini")


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


# ---------------------------------------------------------------------------
# Manage / delete / reflection UI helpers (no Qt)
# ---------------------------------------------------------------------------

check(REFLECT_BUTTON_VI == "Phản tỉnh / Viết sổ tay", "manual reflection button copy")
legend = stage_legend_vi()
for label in ("Mới gặp", "Đang học", "Lớn dần", "Đồng hành"):
    check(label in legend, f"legend has {label}")
check("ngày dùng" in legend, "legend explains days of use")
check("Pro" not in legend, "no Pro in stage legend")
info0 = current_stage(base_dir=_fresh_dir())
caption = stage_caption_vi(info0)
check("Giai đoạn 0" in caption and "Mới gặp" in caption, "stage caption has Vietnamese badge")
check(info0.blurb_vi in caption, "stage caption has short explanation")

empty = empty_states_vi()
check("vài ngày" in empty["diary"], "empty diary asks user to use the app a few days")
check(REFLECT_BUTTON_VI in empty["reflection_empty"], "empty reflection mentions the button")
check("Pro" not in empty["diary"] and "Pro" not in empty["skills"], "no Pro in empty states")

root = _fresh_dir()
check(diary_is_empty(base_dir=root), "fresh dir is empty diary")
check("Chưa có nhật ký" in format_diary_browse(base_dir=root), "browse empty diary copy")
check("Chưa có kỹ năng" in format_skills_browse(base_dir=root), "browse empty skills copy")

ev1 = record_app_event("high_ram", "RAM cao 88%", metrics={"ram_percent": 88}, base_dir=root)
ev2 = record_app_event("wifi_weak", "Wi-Fi yếu trên máy này", base_dir=root)
browse = format_diary_browse(base_dir=root)
check("RAM cao" in browse and "Wi-Fi" in browse, "browse lists recent diary rows")
check(delete_diary_entry(ev1, base_dir=root) is True, "delete one diary row")
left = format_diary_browse(base_dir=root)
check("RAM cao" not in left and "Wi-Fi" in left, "other diary rows kept")
n_cleared = clear_diary_memory(base_dir=root)
check(n_cleared == 1, "clear diary removes remaining rows")
check(diary_is_empty(base_dir=root), "diary empty after clear")

root = _fresh_dir()
for _ in range(3):
    record_app_event("high_ram", "RAM cao 90%", metrics={"ram_percent": 90}, base_dir=root)
skill = accept_skill_offer("high_ram", base_dir=root)
check(skill is not None, "skill for delete tests")
check("RAM" in format_skills_browse(base_dir=root), "browse shows saved skill")
check(delete_saved_skill(skill.id, base_dir=root) is True, "delete one skill")
check("Chưa có kỹ năng" in format_skills_browse(base_dir=root), "skills empty after delete")
save_skill("wifi_weak", hit_count=3, base_dir=root)
check(clear_skills_memory(base_dir=root) == 1, "clear skills count")
check("Chưa có kỹ năng" in format_skills_browse(base_dir=root), "skills empty after clear")

root = _fresh_dir()
record_app_event("clean_light", "Dọn nhẹ 10 MB", metrics={"junk_freed_mb": 10}, base_dir=root)
save_skill("disk_low", hit_count=4, base_dir=root)
maybe_run_reflection(_Cfg(), force=True, provider=TemplateReflectionProvider(), base_dir=root)
cleared = clear_local_memory(base_dir=root)
check(cleared["diary"] >= 1, "clear all removes diary")
check(cleared["skills"] >= 1, "clear all removes skills")
check(cleared["reflection"] >= 1, "clear all removes sổ tay")
check(diary_is_empty(base_dir=root), "privacy clear emptied diary")
check(current_stage(base_dir=root).active_days >= 1, "clear memory keeps days-of-use stage")

prompt = confirm_clear_prompt("diary")
check("Xóa nhật ký" in prompt["title"] or "Xóa nhật ký" in prompt["ok"], "confirm diary title")
check("Không thể hoàn tác" in prompt["body"], "confirm is irreversible")
check("Pro" not in prompt["body"] and "Pro" not in prompt["title"], "no Pro in confirm")
all_prompt = confirm_clear_prompt("all")
check("bộ nhớ" in all_prompt["title"].lower() or "bộ nhớ" in all_prompt["ok"].lower() or "bộ nhớ" in all_prompt["body"], "all-clear mentions memory")
check("AppData" in all_prompt["body"] or "local" in all_prompt["body"].lower(), "privacy mentions local storage")

fb_empty = format_reflection_feedback({"note": "", "source": "empty"})
check(fb_empty["status"] == "empty", "empty reflection status")
check("vài ngày" in fb_empty["body"], "empty reflection tells user to use the app")
fb_ok = format_reflection_feedback({"note": "Sổ tay test", "source": "template"})
check(fb_ok["status"] == "success", "template reflection success")
check("số liệu" in fb_ok["body"], "honest metrics-only success copy")
fb_g = format_reflection_feedback({"note": "Sổ tay gemini", "source": "gemini"})
check(fb_g["status"] == "success" and "Gemini" in fb_g["body"], "gemini success copy")
fb_err = format_reflection_feedback(RuntimeError("disk full"))
check(fb_err["status"] == "error" and "disk full" in fb_err["body"], "error reflection copy")

empty_root = _fresh_dir()
empty_result = maybe_run_reflection(_Cfg(), force=True, provider=TemplateReflectionProvider(), base_dir=empty_root)
check(empty_result and empty_result.get("source") == "empty", "manual reflect on empty diary is empty")
check(not os.path.exists(os.path.join(empty_root, "so_tay.txt")), "empty reflect does not invent sổ tay")

reset_postscript_gate()
check(should_emit_postscript("sig-a", now_ts=1000.0, cooldown_sec=60) is True, "first postscript allowed")
check(should_emit_postscript("sig-a", now_ts=1010.0, cooldown_sec=60) is False, "same postscript cools down")
check(should_emit_postscript("sig-b", now_ts=1011.0, cooldown_sec=60) is True, "new signature allowed")
check(should_emit_postscript("sig-b", now_ts=1080.0, cooldown_sec=60) is True, "cooldown elapsed")
print(" [PASS] manage/delete/reflection UI helpers")


# ---------------------------------------------------------------------------
# Structured episodes, coalesce, context budget, skills, nudges
# ---------------------------------------------------------------------------

from core.companion_diary import count_by_kind, event_weight
from core.companion_maturity import explain_stage_vi
from core.companion import (
    CONTEXT_CHAR_BUDGET,
    crystallize_skills,
    decline_skill_offer,
    derive_machine_hints,
    explain_stage_progress,
    observe_clean,
    observe_suggestion,
    observe_update,
    observe_wifi_repaired,
    pending_skill_offer,
    plan_companion_nudge,
    recent_learning_text,
)
from core.companion_skills import should_crystallize

check("ngày dùng" in explain_stage_vi(0), "stage 0 explains missing use days")
check("Đang học" in explain_stage_vi(3), "stage 1 names Đang học")
check("Lớn dần" in explain_stage_vi(8), "stage 2 names Lớn dần")
check("Đồng hành" in explain_stage_vi(21), "stage 3 names Đồng hành")
check("phá hủy" in explain_stage_vi(21), "stage 3 still refuses destructive auto-run")
print(" [PASS] stage reason copy")

root = _fresh_dir()
evening = datetime(2026, 9, 20, 21, 10, 0)
for _ in range(5):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối trên máy này",
        now=evening,
        base_dir=root,
    )
rows = read_events(base_dir=root)
check(len(rows) == 1, "noisy wifi episodes coalesce to one row")
check(rows[0].get("outcome") == "warn", "wifi episode has outcome")
check("wifi" in (rows[0].get("tags") or []), "wifi episode is tagged")
check("evening" in (rows[0].get("tags") or []), "evening band tagged")
check(event_weight(rows[0]) == 5, "coalesced episode keeps repeat count")
check(count_by_kind(rows).get("wifi_weak") == 5, "kind counts use repeat weight")
check(pending_skill_offer(base_dir=root)["issue_class"] == "wifi_weak", "coalesced repeats still offer a skill")
check(observe_clean(0, ram_mb=0, base_dir=root) is None, "zero-byte clean is not a diary episode")
updated = observe_update(False, "Không tải được bản cập nhật", base_dir=root, now=evening)
check(updated and updated["kind"] == "update_fail" and updated["outcome"] == "fail", "update failure is structured")
repaired = observe_wifi_repaired(True, base_dir=root, now=evening + timedelta(minutes=40))
check(repaired and repaired["outcome"] == "ok", "wifi recovery records ok outcome")
print(" [PASS] structured diary + debounce/coalesce")

root = _fresh_dir()
noon = datetime(2026, 9, 18, 12, 0, 0)
record_app_event(
    "clean_freed",
    "Dọn rác giải phóng 80 MB",
    metrics={"junk_freed_mb": 80},
    now=noon,
    base_dir=root,
    coalesce=False,
)
record_app_event(
    "wifi_weak",
    "Wi-Fi yếu trên máy này",
    now=evening,
    base_dir=root,
    coalesce=False,
)
ctx = build_prompt_context("wifi chậm", base_dir=root, now=evening)
check("AI đồng hành" in ctx, "budgeted prompt still names companion")
check("không phải AGI" in ctx, "budgeted prompt stays honest")
check("wifi_weak" in ctx or "Wi-Fi" in ctx, "wifi question retrieves wifi episode")
check("clean_freed" not in ctx, "unrelated clean episode stays out of wifi context")
check("Gợi ý máy này" in ctx, "prompt includes machine hints section")
check(len(ctx) <= CONTEXT_CHAR_BUDGET, "default context stays inside char budget")
long_root = _fresh_dir()
for i in range(12):
    record_app_event(
        "clean_freed",
        "Dọn rác " + ("x" * 120),
        metrics={"junk_freed_mb": 10 + i},
        now=noon + timedelta(hours=5 * i),
        base_dir=long_root,
        coalesce=False,
    )
short = build_prompt_context("ổ C đầy rác", base_dir=long_root, now=noon, char_budget=480)
check(len(short) <= 480, "explicit char budget is enforced")
check("AI đồng hành" in short[:120], "budget keeps the companion header")
check(short.endswith("…"), "over-budget context is clipped")
print(" [PASS] copilot context retrieval + char budget")

root = _fresh_dir()
for i in range(3):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=evening + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
events = read_events(base_dir=root)
check(should_crystallize("wifi_weak", count_by_kind(events), events), "evening wifi pattern is worth a skill")
check(not should_crystallize("wifi_weak", {"wifi_weak": 2}, events[:2]), "two repeats are not enough")
reflected = maybe_run_reflection(
    _Cfg(),
    force=True,
    provider=TemplateReflectionProvider(),
    base_dir=root,
    now=evening + timedelta(days=3),
)
check(reflected and "wifi_weak" in (reflected.get("skills") or []), "reflection crystallizes wifi skill")
check("kết tinh" in (reflected.get("note") or ""), "template sổ tay mentions the new skill")
browse = format_skills_browse(base_dir=root)
check("tiết kiệm" in browse or "buổi tối" in browse, "skill text is machine-specific and safe")
check("WinSxS" not in browse or "không" in browse, "wifi skill does not push destructive cleanup")
again = maybe_run_reflection(
    _Cfg(),
    force=True,
    provider=TemplateReflectionProvider(),
    base_dir=root,
    now=evening + timedelta(days=4),
)
check(again and not again.get("skills"), "second reflection does not duplicate the skill")
check(len(load_skills(base_dir=root)) == 1, "one wifi skill remains")

blocked = _fresh_dir()
for i in range(3):
    record_app_event(
        "thermal_warn",
        "Nhiệt cao",
        metrics={"thermal_c": 92},
        now=evening + timedelta(days=i),
        base_dir=blocked,
        coalesce=False,
    )
observe_suggestion(False, action_key="view_hardware", base_dir=blocked, now=evening, coalesce=False)
blocked_events = read_events(base_dir=blocked)
saved = crystallize_skills(count_by_kind(blocked_events), blocked_events, base_dir=blocked)
check(saved == [], "rejected thermal suggestion is not auto-saved")
check(should_crystallize("disk_low", {"clean_freed": 3}, []) is False, "three cleans are not auto-crystallized")
check(should_crystallize("disk_low", {"clean_freed": 4}, []) is True, "four cleans can crystallize")
print(" [PASS] reflection crystallizes quality skills only")

root = _fresh_dir()
check(plan_companion_nudge(now=evening, base_dir=root) is None, "empty diary does not nudge")
for i in range(4):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=evening + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
nudge = plan_companion_nudge(now=evening + timedelta(days=3), base_dir=root)
check(nudge and nudge["issue_class"] == "wifi_weak", "enough evening wifi evidence nudges once")
check("tiết kiệm" in nudge["message"], "nudge suggests power-save, not a destructive action")
check("DNS" in nudge["message"], "nudge tells the user DNS is not changed automatically")
check(
    plan_companion_nudge(now=evening + timedelta(days=3, hours=1), base_dir=root) is None,
    "nudge respects cooldown",
)
burst = _fresh_dir()
for _ in range(6):
    record_app_event("wifi_weak", "Wi-Fi yếu buổi tối", now=evening, base_dir=burst)
check(
    plan_companion_nudge(now=evening, base_dir=burst) is None,
    "one coalesced wifi burst does not nag",
)
quiet = _fresh_dir()
for _ in range(4):
    record_app_event("wifi_weak", "Wi-Fi yếu buổi tối", now=evening, base_dir=quiet)

class _Quiet(_Cfg):
    pass

quiet_cfg = _Cfg(
    companion_enabled=True,
    companion_nudges_enabled=False,
    show_notifications=True,
)
check(plan_companion_nudge(now=evening, base_dir=quiet, config_manager=quiet_cfg) is None, "nudge toggle off")
off_cfg = _Cfg(companion_enabled=False, companion_nudges_enabled=True)
check(plan_companion_nudge(now=evening, base_dir=quiet, config_manager=off_cfg) is None, "companion off skips nudges")
mute_cfg = _Cfg(
    companion_enabled=True,
    companion_nudges_enabled=True,
    show_notifications=False,
    instant_screen_notifications_enabled=False,
)
check(plan_companion_nudge(now=evening, base_dir=quiet, config_manager=mute_cfg) is None, "notification mute skips nudges")
learned = recent_learning_text(base_dir=root, now=evening)
check("Wi-Fi" in learned, "card can show what was just learned")
check("Đang học" in explain_stage_progress(base_dir=root) or "ngày dùng" in explain_stage_progress(base_dir=root), "progress text explains the stage")
hints = derive_machine_hints(read_events(base_dir=root), now=evening, limit=3)
check(hints and len(hints) <= 3, "at most three machine hints")
print(" [PASS] calm nudges + learning feedback")

root = _fresh_dir()
for i in range(3):
    record_app_event(
        "high_ram",
        "RAM cao 91%",
        metrics={"ram_percent": 91},
        now=evening + timedelta(hours=4 * i),
        base_dir=root,
        coalesce=False,
    )
check(pending_skill_offer(base_dir=root), "repeated RAM still offers a skill")
decline_skill_offer(base_dir=root, now=evening)
check(pending_skill_offer(base_dir=root) is None, "decline clears the offer")
check(
    pending_offer_from_counts({"high_ram": 6}, base_dir=root, now=evening + timedelta(days=1)) is None,
    "declined skill is not offered again immediately",
)
print(" [PASS] declined skill offer cools down")


# ---------------------------------------------------------------------------
# Profile, optional goal, grounded retrieval, one insight
# ---------------------------------------------------------------------------

from core.companion_profile import (
    clear_habits,
    current_insight,
    dismiss_insight,
    goal_status,
    load_profile,
    refresh_profile,
    set_goal,
)
from core.companion import local_grounding_text

friday = datetime(2026, 9, 18, 19, 0, 0)
check(friday.weekday() == 4, "fixture Friday is Friday")
root = _fresh_dir()
for offset in (0, 7):
    record_app_event(
        "focus_mode",
        "Người dùng bật Trước thi / họp",
        now=friday + timedelta(days=offset),
        base_dir=root,
        coalesce=False,
        outcome="ok",
        tags=["focus"],
    )
focus_profile = load_profile(root)
focus_blob = " ".join(
    f"{item.get('label_vi')} {item.get('detail_vi')}" for item in focus_profile.get("habits") or []
)
check("thứ Sáu" in focus_blob, "profile remembers Friday exam focus")
print(" [PASS] Friday focus habit")

root = _fresh_dir()
evening = datetime(2026, 9, 20, 21, 0, 0)
noon = datetime(2026, 9, 20, 12, 0, 0)
for i in range(3):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=evening + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
for i in range(2):
    record_app_event(
        "thermal_warn",
        "Nhiệt cao",
        metrics={"thermal_c": 91},
        now=noon + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
for i in range(3):
    record_app_event(
        "clean_light",
        f"Dọn nhẹ {10 + i} MB",
        metrics={"junk_freed_mb": 10 + i},
        now=noon + timedelta(days=i, hours=1),
        base_dir=root,
        coalesce=False,
    )
record_app_event(
    "update_fail",
    "Không tải được bản cập nhật",
    now=evening + timedelta(hours=1),
    base_dir=root,
    coalesce=False,
)
for i in range(2):
    observe_suggestion(
        False,
        action_key="clean_light",
        base_dir=root,
        now=noon + timedelta(days=i, hours=3),
        coalesce=False,
    )
note_user_feedback(False, base_dir=root, now=evening + timedelta(days=3))
note_user_feedback(False, base_dir=root, now=evening + timedelta(days=3, minutes=5))

profile = load_profile(root)
blob = " ".join(
    f"{item.get('label_vi')} {item.get('detail_vi')}" for item in profile.get("habits") or []
)
check("buổi tối" in blob and "Wi-Fi" in blob, "profile remembers evening Wi-Fi")
check("Nhạy với nhiệt" in blob, "profile remembers thermal sensitivity")
check("bỏ qua" in blob, "profile remembers rejected clean suggestions")
check(profile.get("coaching") == "ask_more", "repeated unhelpful feedback asks more")
reloaded = load_profile(root)
check(reloaded.get("updated_at"), "profile is persisted")
check(len(reloaded.get("habits") or []) == len(profile.get("habits") or []), "reload keeps habits")

ctx_wifi = build_prompt_context("wifi chậm buổi tối", base_dir=root, now=evening + timedelta(days=4))
check("wifi_weak" in ctx_wifi, "wifi question retrieves wifi episodes")
check("thermal_warn" not in ctx_wifi, "wifi question leaves thermal episodes out")
check("clean_light" not in ctx_wifi and "update_fail" not in ctx_wifi, "wifi question leaves clean and update out")
check("Về máy này" in ctx_wifi and "buổi tối" in ctx_wifi, "wifi question includes the matching habit")
check("Gợi ý máy này" in ctx_wifi, "wifi context still has machine hints")
check(len(ctx_wifi) <= CONTEXT_CHAR_BUDGET, "grounded wifi context stays in budget")

ctx_heat = build_prompt_context("máy nóng", base_dir=root, now=evening + timedelta(days=4))
check("thermal_warn" in ctx_heat, "heat question retrieves thermal episodes")
check("wifi_weak" not in ctx_heat, "heat question leaves wifi episodes out")
check("Nhạy với nhiệt" in ctx_heat, "heat question includes the thermal habit")

ctx_clean = build_prompt_context("dọn rác ổ C", base_dir=root, now=evening + timedelta(days=4))
check("clean_light" in ctx_clean, "clean question retrieves clean episodes")
check("wifi_weak" not in ctx_clean and "thermal_warn" not in ctx_clean, "clean question stays on disk")

ctx_update = build_prompt_context("cập nhật bị lỗi", base_dir=root, now=evening + timedelta(days=4))
check("update_fail" in ctx_update, "update question retrieves the failed update")
check("wifi_weak" not in ctx_update and "thermal_warn" not in ctx_update, "update question stays on updates")
print(" [PASS] profile + topic retrieval")

goal_at = evening + timedelta(days=4)
goal = set_goal("ổn định Wi-Fi trước họp", base_dir=root, now=goal_at)
check(goal and goal.get("topic") == "wifi", "wifi goal infers wifi")
idle = goal_status(base_dir=root, now=goal_at)
check(idle and idle["related_count"] == 0, "episodes before the goal do not count as progress")
check("chưa có diễn biến" in idle["summary_vi"], "empty progress stays quiet")
check(not idle["next_action_vi"], "no next-action nag before any new episode")
record_app_event(
    "wifi_weak",
    "Wi-Fi yếu trước họp",
    now=goal_at + timedelta(hours=2),
    base_dir=root,
    coalesce=False,
)
record_app_event(
    "wifi_repaired",
    "Wi-Fi đã ổn định lại",
    now=goal_at + timedelta(hours=3),
    base_dir=root,
    coalesce=False,
    outcome="ok",
    tags=["wifi"],
)
progress = goal_status(base_dir=root, now=goal_at + timedelta(hours=4))
check(progress["open_count"] >= 1 and progress["improved_count"] >= 1, "goal tracks new weak and repaired episodes")
check("Mục tiêu" in progress["summary_vi"], "progress names the goal")
check("tiết kiệm" in progress["next_action_vi"], "next action is the safe wifi step")
ctx_goal = build_prompt_context("wifi họp", base_dir=root, now=goal_at + timedelta(hours=4))
check("Mục tiêu" in ctx_goal and "ổn định Wi-Fi" in ctx_goal, "copilot context includes goal status")
check(len(ctx_goal) <= CONTEXT_CHAR_BUDGET, "goal context stays in budget")

study = _fresh_dir()
study_goal = set_goal("máy mát khi học", base_dir=study, now=evening)
check(study_goal and study_goal.get("topic") == "thermal", "cool-while-studying goal is thermal")
check("focus" in (study_goal.get("topics") or []), "study goal also notices focus")
check(plan_companion_nudge(now=evening, base_dir=study) is None, "a goal alone does not toast")
set_goal("", base_dir=study)
check(goal_status(base_dir=study) is None, "clearing the goal stops coaching")
print(" [PASS] optional goal coaching")

kept_goal = set_goal("ổn định Wi-Fi trước họp", base_dir=root, now=goal_at)
check(kept_goal, "goal stored before habit clear")
clear_habits(base_dir=root, now=goal_at + timedelta(days=2))
after_habits = load_profile(root)
check(not after_habits.get("habits"), "habit clear removes the profile lines")
check((after_habits.get("goal") or {}).get("text"), "habit clear keeps the typed goal")
refresh_profile(base_dir=root, now=goal_at + timedelta(days=1))
check(not load_profile(root).get("habits"), "old episodes do not restore a cleared profile")
wiped = clear_local_memory(base_dir=root)
check(wiped.get("profile", 0) >= 1, "full clear removes the profile file")
check(goal_status(base_dir=root) is None, "full clear removes the goal")
print(" [PASS] profile browse/clear")

root = _fresh_dir()
for i in range(4):
    record_app_event(
        "clean_freed",
        "Dọn rác 40 MB",
        metrics={"junk_freed_mb": 40},
        now=noon + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
for i in range(3):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=evening + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
set_goal("ổn định Wi-Fi trước họp", base_dir=root, now=evening + timedelta(days=3))
reflected = maybe_run_reflection(
    _Cfg(),
    force=True,
    provider=TemplateReflectionProvider(),
    base_dir=root,
    now=evening + timedelta(days=3, hours=1),
)
check(reflected and reflected.get("skills") == ["wifi_weak"], "reflection saves the goal skill, not the unrelated clean")
check(len(load_skills(base_dir=root)) == 1, "at most the goal skill this pass")
note = reflected.get("note") or ""
check("buổi tối" in note or "Wi-Fi" in note, "sổ tay mentions the learned habit")
check("kết tinh" in note, "sổ tay still records the new skill")
check(load_profile(root).get("habits"), "reflection refreshed the profile")
grounded = local_grounding_text("wifi chậm", base_dir=root, now=evening + timedelta(days=3, hours=2))
check("Wi-Fi" in grounded or "buổi tối" in grounded, "offline grounding cites this machine")
check("Mục tiêu" in grounded, "offline grounding cites the goal when Gemini is absent")
print(" [PASS] reflection updates profile and prefers the goal skill")

root = _fresh_dir()
for i in range(3):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=evening + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
insight_now = evening + timedelta(days=3)
insight = current_insight(base_dir=root, now=insight_now)
check(insight and str(insight.get("text") or "").startswith("Hôm nay:"), "insight is a single Hôm nay line")
dismiss_insight(insight["id"], base_dir=root, now=insight_now)
check(current_insight(base_dir=root, now=insight_now) is None, "dismissing hides the strip for the rest of the day")
later = current_insight(base_dir=root, now=insight_now + timedelta(days=1))
check(later is None or later.get("id") != insight["id"], "the dismissed line does not come back")
check(
    current_insight(base_dir=root, now=evening + timedelta(days=3), enabled=False) is None,
    "companion off hides insight",
)
print(" [PASS] dismissible companion insight")


# ---------------------------------------------------------------------------
# Qt smoke: Settings card + memory dialog
# ---------------------------------------------------------------------------

from PyQt5.QtWidgets import QApplication
from ui.companion_card import CompanionCard, CompanionDialog

qt_app = QApplication.instance() or QApplication([])
root = _fresh_dir()
card = CompanionCard(config_manager=_Cfg(), compact=False)
check(card.btn_reflect.text() == REFLECT_BUTTON_VI, "card reflect button label")
check(hasattr(card, "btn_manage") and "bộ nhớ" in card.btn_manage.text(), "card has manage memory button")
check("&" not in card.btn_manage.text(), "manage button has no Qt mnemonic ampersand")
check(hasattr(card, "lbl_legend") and "Mới gặp" in card.lbl_legend.text(), "card shows stage legend")
check(hasattr(card, "lbl_reason") and "ngày dùng" in card.lbl_reason.text(), "card explains why the stage is what it is")
check(hasattr(card, "chk_nudges") and "thói quen" in card.chk_nudges.text(), "card can turn calm nudges off")
check(hasattr(card, "txt_goal") and "Wi-Fi" in card.txt_goal.placeholderText(), "card has one optional goal field")
check("tuỳ chọn" in card.lbl_goal.text(), "empty goal stays quiet")
check(card.insight_bar.isHidden(), "fresh card hides the insight strip")
check("Ollama" not in card.chk_reflect.text(), "companion checkbox does not mention Ollama")
check("vài ngày" in card.lbl_diary.text(), "card honest empty diary")
check("Pro" not in card.lbl_title.text(), "no Pro on companion card")

dlg = CompanionDialog(config_manager=_Cfg())
check(dlg.btn_reflect.text() == REFLECT_BUTTON_VI, "dialog reflect button")
check(hasattr(dlg, "list_diary") and hasattr(dlg, "list_skills"), "dialog lists diary and skills")
check(hasattr(dlg, "btn_clear_all") and "bộ nhớ" in dlg.btn_clear_all.text(), "dialog can clear all memory")
check(hasattr(dlg, "lbl_profile") and "hồ sơ" in dlg.lbl_profile.text().lower(), "dialog shows the habit profile")
check(hasattr(dlg, "btn_clear_profile"), "dialog can clear the habit profile")
check("vài ngày" in dlg.lbl_diary_empty.text(), "dialog empty diary copy")
check(dlg.list_diary.count() == 0, "new install diary list empty")
check(dlg.list_skills.count() == 0, "new install skills list empty")
dlg.close()

record_app_event(
    "wifi_weak",
    "Wi-Fi yếu buổi tối",
    now=datetime(2026, 9, 20, 21, 0, 0),
    base_dir=root,
)
card.refresh()
check("Wi-Fi" in card.lbl_learning.text(), "card shows what was just learned")
check("Đang học" in card.lbl_reason.text(), "card explains the move to Đang học")
for extra in range(2):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=datetime(2026, 9, 21, 21, 0, 0) + timedelta(days=extra),
        base_dir=root,
        coalesce=False,
    )
card.txt_goal.setText("ổn định Wi-Fi trước họp")
card._save_goal()
check("Mục tiêu" in card.lbl_goal.text() and "Wi-Fi" in card.lbl_goal.text(), "card shows the saved goal")
check(not card.insight_bar.isHidden(), "card shows one insight after real episodes")
check(card.insight_bar.lbl_insight.text().startswith("Hôm nay:"), "card insight is the Hôm nay line")
card.insight_bar._dismiss()
check(card.insight_bar.isHidden(), "Ẩn hides the insight on the card")
dlg = CompanionDialog(config_manager=_Cfg())
check(dlg.list_diary.count() >= 1, "dialog lists the new wifi episode")
check("Đang học" in dlg.lbl_legend.text() or "ngày dùng" in dlg.lbl_legend.text(), "dialog explains the stage")
dlg.close()
card.deleteLater()
print(" [PASS] companion card/dialog Qt smoke")

print(" [PASS] companion AI suite")
