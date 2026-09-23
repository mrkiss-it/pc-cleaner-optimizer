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
check(n_cleared >= 1, "clear diary removes remaining rows")
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
wifi_rows = [row for row in rows if row.get("kind") == "wifi_weak"]
check(len(wifi_rows) == 1, "noisy wifi episodes coalesce to one row")
check(wifi_rows[0].get("outcome") == "warn", "wifi episode has outcome")
check("wifi" in (wifi_rows[0].get("tags") or []), "wifi episode is tagged")
check("evening" in (wifi_rows[0].get("tags") or []), "evening band tagged")
check(event_weight(wifi_rows[0]) == 5, "coalesced episode keeps repeat count")
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
# Chat memory, insight actions, stage voice, weekly digest
# ---------------------------------------------------------------------------

from core.companion_diary import event_weight
from core.companion_moment import (
    INSIGHT_ACTION_ALLOWLIST,
    action_cap_for_stage,
    is_allowed_insight_action,
    learn_from_chat,
    local_weekly_summary,
    maybe_weekly_digest,
    relevant_chat_topics,
    resolve_insight_action,
    stage_voice,
    weekly_digest_due,
)
from core.companion_reflection import load_reflection

root = _fresh_dir()
chat_now = datetime(2026, 9, 22, 10, 0, 0)
marker = "KHONG_LUU_PHAN_TRA_LOI_DAI_12345"
secret = "AIzaSyTHISISASECRETKEY123456"
skipped = learn_from_chat("xin chào", "Chào bạn, mình giúp được gì hôm nay?", now=chat_now, base_dir=root)
check(skipped is None, "greeting is not a diary episode")
skipped = learn_from_chat("wifi", "ok", now=chat_now, base_dir=root)
check(skipped is None, "tiny answer is not a full turn")
skipped = learn_from_chat(
    "Wifi chậm buổi tối",
    "Mình sẽ nói ngắn về Wi-Fi.",
    now=chat_now,
    base_dir=root,
    config_manager=_Cfg(companion_enabled=False),
)
check(skipped is None, "companion off does not learn from chat")
first = learn_from_chat(
    f"Wifi chậm, key {secret} đừng lưu",
    "Có thể do tiết kiệm điện của adapter. " + marker,
    now=chat_now,
    base_dir=root,
)
check(first and first.get("kind") == "chat_note", "wifi question becomes a chat episode")
check(secret not in json.dumps(first, ensure_ascii=False), "episode summary redacts the API key")
check(marker not in json.dumps(first, ensure_ascii=False), "episode does not store the assistant reply")
check("Wi-Fi" in (first.get("summary") or ""), "episode names the topic, not a chat dump")
again = learn_from_chat(
    "Wifi vẫn chậm",
    "Tắt tiết kiệm điện Wi-Fi trên thẻ ổn định rồi xem lại.",
    now=chat_now + timedelta(minutes=5),
    base_dir=root,
)
chat_rows = [row for row in read_events(base_dir=root) if row.get("kind") == "chat_note"]
check(len(chat_rows) == 1, "same topic inside 30 minutes coalesces")
check(event_weight(chat_rows[0]) >= 2, "coalesced chat line counts both turns")
later = learn_from_chat(
    "Wifi chậm lại rồi",
    "Mình vẫn chỉ nói về Wi-Fi, không đổi DNS.",
    now=chat_now + timedelta(hours=2),
    base_dir=root,
)
check(later and later.get("ts") != first.get("ts"), "a later question is a new episode")
asked = load_profile(root)
ask_blob = " ".join(
    f"{item.get('label_vi')} {item.get('detail_vi')}" for item in asked.get("habits") or []
)
check("hỏi" in ask_blob and "Wi-Fi" in ask_blob, "repeated questions update the habit profile")
note_user_feedback(True, base_dir=root, now=chat_now + timedelta(minutes=10))
feedback_rows = [
    row for row in read_events(base_dir=root)
    if row.get("kind") == "chat_note" and "hữu ích" in str(row.get("summary") or "")
]
check(feedback_rows, "explicit feedback on the last topic is remembered")
check(secret not in open(os.path.join(root, "diary.jsonl"), encoding="utf-8").read(), "diary file has no API key")
set_goal("ổn định Wi-Fi trước họp", base_dir=root, now=chat_now)
goal_turn = learn_from_chat(
    "nhắc mục tiêu của tôi",
    "Mục tiêu hiện tại là ổn định Wi-Fi trước họp.",
    now=chat_now + timedelta(hours=3),
    base_dir=root,
)
check(goal_turn and "wifi" in (goal_turn.get("tags") or []), "active goal is a chat topic")
ctx_chat = build_prompt_context("wifi chậm", base_dir=root, now=chat_now + timedelta(hours=4))
check("Bạn hỏi về" in ctx_chat, "later copilot context can see yesterday's question")
check(marker not in ctx_chat and secret not in ctx_chat, "context stays free of dumps and keys")
check(relevant_chat_topics("máy nóng", base_dir=root) == ["thermal"], "thermal questions are in scope")
check(relevant_chat_topics("dọn rác ổ C", base_dir=root) == ["disk"], "cleanup questions are in scope")
check("focus" in relevant_chat_topics("bật trước thi", base_dir=root), "exam focus questions are in scope")
check(relevant_chat_topics("có bản cập nhật không", base_dir=root) == ["update"], "update questions are in scope")
check(relevant_chat_topics("xin chào bạn", base_dir=root) == [], "small talk is out of scope")
wired = _fresh_dir()
from core.ai_copilot import AICopilotEngine
engine = AICopilotEngine(config_manager=_Cfg(ai_copilot_provider="auto", companion_enabled=True))
engine.ask("Wifi nhà mình chậm buổi tối")
wired_rows = [row for row in read_events(base_dir=wired) if row.get("kind") == "chat_note"]
check(wired_rows, "Copilot ask() writes the chat episode")
check(marker not in json.dumps(wired_rows, ensure_ascii=False), "ask() does not dump the reply into the diary")
print(" [PASS] chat turns update diary and habit profile")

blocked = {
    "clean_disk", "clean_junk", "winsxs_cleanup",
    "auto_optimize_all", "switch_dns", "registry_clean",
}
for key in blocked:
    check(not is_allowed_insight_action(key), f"{key} is not an insight action")
for topic in ("wifi", "thermal", "disk", "focus", "update", "ram", ""):
    for stage_n in range(4):
        for propose in (True, False):
            action = resolve_insight_action(topic, stage=stage_n, may_propose=propose, coaching="steady")
            if not action:
                continue
            check(action["key"] in INSIGHT_ACTION_ALLOWLIST, "resolved action stays on the allowlist")
            check(action["key"] not in blocked, "resolved action is not destructive")
            check(action["label_vi"] and "Pro" not in action["label_vi"], "action label is Vietnamese")
shy = resolve_insight_action("wifi", stage=0, may_propose=True)
check(shy and shy["key"] == "open_companion_memory", "stage 0 offers memory, not a system change")
guide = resolve_insight_action("wifi", stage=1, may_propose=False)
check(guide and guide["key"] == "open_wifi_stability", "wifi insight opens existing guidance")
check("Wi-Fi" in guide["label_vi"], "wifi button label is Vietnamese")
power = resolve_insight_action("wifi", stage=2, may_propose=True)
check(power and power["key"] == "disable_wifi_power_save", "mature wifi insight uses the existing power-save flow")
check("tiết kiệm" in power["label_vi"], "power-save button label is Vietnamese")
power_shy = resolve_insight_action("wifi", stage=3, may_propose=True, coaching="ask_more")
check(power_shy and power_shy["key"] == "open_wifi_stability", "ask-more coaching does not change Wi-Fi power")
thermal = resolve_insight_action("thermal", stage=1, may_propose=False)
check(thermal and thermal["key"] == "open_thermal_card", "thermal insight opens the thermal card")
focus_early = resolve_insight_action("focus", stage=1, may_propose=True)
check(focus_early and focus_early["key"] == "open_companion_memory", "exam focus waits until stage 2")
focus_go = resolve_insight_action("focus", stage=2, may_propose=True)
check(focus_go and focus_go["key"] == "enable_exam_focus", "stage 2 may start Trước thi / họp")
focus_no = resolve_insight_action("focus", stage=3, may_propose=False)
check(focus_no and focus_no["key"] != "enable_exam_focus", "exam focus respects the propose switch")
focus_ask = resolve_insight_action("focus", stage=3, may_propose=True, coaching="ask_more")
check(focus_ask and focus_ask["key"] == "open_companion_memory", "unhelpful coaching does not start focus")
disk_act = resolve_insight_action("disk", stage=3, may_propose=True)
check(disk_act and disk_act["key"] == "open_companion_memory", "cleanup insight does not one-tap delete")
check(resolve_insight_action("nope", stage=3) is None, "unknown topic has no button")
print(" [PASS] insight action allowlist")

voice0 = stage_voice(0)
voice3 = stage_voice(3)
check(voice0["boldness"] == "shy" and "hỏi" in voice0["tone_vi"], "stage 0 voice stays shy")
check(voice3["boldness"] == "specific" and "nhật ký" in voice3["tone_vi"], "stage 3 voice cites this machine")
check(action_cap_for_stage(0) == 0 and action_cap_for_stage(2) == 1 and action_cap_for_stage(3) == 2, "suggestion cap grows with stage")
check(action_cap_for_stage(3, coaching="ask_more") == 0, "ask-more coaching stops bold suggestions")
fresh_voice = _fresh_dir()
ctx_shy = build_prompt_context("xin chào", base_dir=fresh_voice)
check("hỏi" in ctx_shy.lower() or "Chưa đề xuất" in ctx_shy, "stage 0 prompt uses the shy voice")
dates = [(datetime(2026, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(21)]
from core.companion_maturity import save_state
save_state({"active_dates": dates, "first_seen": "2026-01-01T08:00:00"}, base_dir=fresh_voice)
ctx_sure = build_prompt_context("wifi", base_dir=fresh_voice)
check("nhật ký máy này" in ctx_sure or "cụ thể" in ctx_sure, "stage 3 prompt is specific")
check(voice0["tone_vi"] != voice3["tone_vi"], "stage voices are not the same line")
print(" [PASS] stage-aware voice")

root = _fresh_dir()
empty_week = maybe_weekly_digest(force=True, base_dir=root, now=chat_now, config_manager=_Cfg())
check(empty_week and empty_week.get("source") == "empty", "empty week does not invent a sổ tay")
check(not os.path.exists(os.path.join(root, "so_tay.txt")), "empty digest does not write sổ tay")
check(weekly_digest_due(now=chat_now, base_dir=root), "empty digest does not consume the weekly slot")
record_app_event(
    "wifi_weak",
    "Wi-Fi yếu buổi tối",
    now=chat_now - timedelta(days=1),
    base_dir=root,
    coalesce=False,
)
learn_from_chat(
    "Wifi chậm trước họp",
    "Mình ghi nhận Wi-Fi, không đổi DNS.",
    now=chat_now - timedelta(hours=2),
    base_dir=root,
)
set_goal("ổn định Wi-Fi trước họp", base_dir=root, now=chat_now - timedelta(days=2))
local_note = local_weekly_summary(now=chat_now, base_dir=root, stage_label="Giai đoạn 1 · Đang học")
check("Tóm tắt tuần" in local_note and "Wi-Fi" in local_note, "local weekly note uses diary facts")
first_week = maybe_weekly_digest(force=False, now=chat_now, base_dir=root, config_manager=_Cfg())
check(first_week and first_week.get("source") == "template", "no Gemini key stays on the local summary")
check("Tóm tắt tuần" in (first_week.get("note") or ""), "weekly note lands in the sổ tay")
check(not weekly_digest_due(now=chat_now + timedelta(days=1), base_dir=root), "same ISO week is gated")
again_week = maybe_weekly_digest(force=False, now=chat_now + timedelta(days=1), base_dir=root, config_manager=_Cfg())
check(again_week is None, "automatic digest does not repeat this week")
forced = maybe_weekly_digest(force=True, now=chat_now + timedelta(days=1), base_dir=root, config_manager=_Cfg())
check(forced and forced.get("note"), "manual button can rewrite the same week")

class _Polish:
    name = "gemini"

    def generate(self, prompt, timeout=8.0):
        return f"Tuần này Wi-Fi vẫn là việc chính. {secret}"

polished = maybe_weekly_digest(
    force=True,
    now=chat_now + timedelta(days=1, hours=1),
    base_dir=root,
    config_manager=_Cfg(),
    provider=_Polish(),
)
check(polished and polished.get("source") == "gemini", "Gemini polish is optional when a provider is present")
check(secret not in (polished.get("note") or ""), "weekly polish redacts API keys")
check("Wi-Fi" in (polished.get("note") or ""), "polished note stays about this machine")
off = maybe_weekly_digest(
    force=True,
    now=chat_now,
    base_dir=root,
    config_manager=_Cfg(companion_enabled=False),
    provider=_Polish(),
)
check(off is None, "weekly digest respects companion_enabled")
next_week = maybe_weekly_digest(
    force=False,
    now=chat_now + timedelta(days=7),
    base_dir=root,
    config_manager=_Cfg(),
)
check(next_week and next_week.get("source") == "template", "next ISO week can write again")
reflected = maybe_run_reflection(
    _Cfg(),
    force=True,
    provider=TemplateReflectionProvider(),
    base_dir=root,
    now=chat_now + timedelta(days=7, hours=2),
)
kept = load_reflection(root)
check("Tóm tắt tuần" in kept, "evening sổ tay keeps the weekly section")
check(reflected and reflected.get("note"), "evening reflection still writes")
print(" [PASS] weekly digest gating")


# ---------------------------------------------------------------------------
# Skill button, mute, stage-up, morning check-in
# ---------------------------------------------------------------------------

from core.companion import dismiss_stage_celebration, pending_stage_celebration
from core.companion_maturity import save_state
from core.companion_profile import (
    active_muted_topics,
    clear_muted_topics,
    mute_topic,
    topic_asks_more,
    topic_is_muted,
    unmute_topic,
)
from core.companion_skills import bump_skill_hit
from core.companion_moment import (
    attach_insight_action,
    compose_daily_checkin,
    dismiss_daily_checkin,
    skill_for_insight,
    sync_daily_checkin,
)

root = _fresh_dir()
for i in range(6):
    day = datetime(2026, 9, 1) + timedelta(days=i)
    record_app_event(
        "high_ram",
        "RAM cao 90%",
        metrics={"ram_percent": 90},
        now=day.replace(hour=12),
        base_dir=root,
        coalesce=False,
    )
save_skill("high_ram", hit_count=4, base_dir=root)
# Six days plus a skill is stage 2, so the saved playbook may offer Thu hồi RAM.
dates = [(datetime(2026, 9, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6)]
state = load_state(root)
state["active_dates"] = dates
state["last_recorded_stage"] = current_stage(base_dir=root).stage
state["last_celebrated_stage"] = state["last_recorded_stage"]
save_state(state, base_dir=root)
ram_now = datetime(2026, 9, 10, 9, 0, 0)
insight = current_insight(base_dir=root, now=ram_now)
check(insight and insight.get("topic") == "ram", "ram habit is an insight topic")
attached = attach_insight_action(insight, base_dir=root, now=ram_now)
check(attached and attached.get("action_key") == "optimize_ram", "saved RAM skill becomes the insight button")
check(attached.get("skill_id") == "high_ram", "insight remembers which skill backed the button")
before = load_skills(root)[0].hit_count
check(bump_skill_hit(skill_id=attached["skill_id"], base_dir=root).hit_count == before + 1, "tap increments hit_count once")
check(bump_skill_hit(skill_id="missing", base_dir=root) is None, "unknown skill tap does not invent a skill")
early = resolve_insight_action("ram", stage=1, may_propose=True, prefer_key="optimize_ram")
check(early and early["key"] == "open_companion_memory", "RAM skill falls back to memory before stage 2")
blocked_key = resolve_insight_action("disk", stage=3, may_propose=True, prefer_key="clean_junk")
check(blocked_key and blocked_key["key"] == "open_companion_memory", "blocked skill action is not a button")
save_skill("disk_low", hit_count=4, base_dir=root)
disk_skill = resolve_insight_action("disk", stage=2, may_propose=True, prefer_key="clean_light")
check(disk_skill and disk_skill["key"] == "clean_light", "saved disk skill offers Dọn nhẹ")
check(is_allowed_insight_action("clean_light"), "light clean is allowlisted for a skill tap")
check(not is_allowed_insight_action("clean_junk"), "full junk clean stays off the insight allowlist")
check(not is_allowed_insight_action("winsxs_cleanup"), "WinSxS stays off the insight allowlist")
check(skill_for_insight("ram", base_dir=root).issue_class == "high_ram", "insight topic finds the RAM skill")
print(" [PASS] skill-backed insight action")

root = _fresh_dir()
evening = datetime(2026, 9, 20, 21, 0, 0)
for i in range(4):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=evening + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
insight_now = evening + timedelta(days=3)
shown = current_insight(base_dir=root, now=insight_now)
check(shown and shown.get("topic") == "wifi", "wifi insight is visible before mute")
would_nudge = plan_companion_nudge(now=insight_now, base_dir=root, config_manager=_Cfg(), commit=False)
check(would_nudge and would_nudge.get("issue_class") == "wifi_weak", "wifi evidence would nudge before a mute")
mute_topic("wifi", days=7, reason="user", base_dir=root, now=insight_now)
check(topic_is_muted("wifi", base_dir=root, now=insight_now), "mute lasts through the cooldown")
hidden = current_insight(base_dir=root, now=insight_now)
check(hidden is None or hidden.get("topic") != "wifi", "muted topic leaves the daily insight")
nudge = plan_companion_nudge(now=insight_now, base_dir=root, config_manager=_Cfg())
check(nudge is None or nudge.get("issue_class") != "wifi_weak", "muted topic is not a proactive nudge")
asked = build_prompt_context("wifi chậm", base_dir=root, now=insight_now)
check("Đừng chủ động nhắc" in asked and "Wi-Fi" in asked, "Copilot is told not to volunteer a muted topic")
check("wifi_weak" in asked or "Wi-Fi" in asked, "Copilot can still see the diary if the user asks")
check(not topic_is_muted("wifi", base_dir=root, now=insight_now + timedelta(days=8)), "mute expires after the cooldown")
back = current_insight(base_dir=root, now=insight_now + timedelta(days=8))
check(back and back.get("topic") == "wifi", "expired mute lets the wifi insight return")
unmute_topic("wifi", base_dir=root)
check(not active_muted_topics(base_dir=root, now=insight_now), "unmute clears the topic immediately")
learn_from_chat(
    "Wifi nhà mình chậm",
    "Mình ghi nhận Wi-Fi, không đổi DNS.",
    now=insight_now + timedelta(days=9),
    base_dir=root,
)
note_user_feedback(False, base_dir=root, now=insight_now + timedelta(days=9, minutes=5), topic="wifi")
check(topic_is_muted("wifi", base_dir=root, now=insight_now + timedelta(days=9, minutes=6)), "negative feedback soft-mutes the topic")
check(topic_asks_more("wifi", base_dir=root), "negative feedback asks more before proposing that topic")
shy_wifi = resolve_insight_action("wifi", stage=3, may_propose=True, coaching="ask_more")
check(shy_wifi and shy_wifi["key"] != "disable_wifi_power_save", "ask-more topic does not change Wi-Fi power")
note_user_feedback(True, base_dir=root, now=insight_now + timedelta(days=9, minutes=20), topic="wifi")
check(not topic_asks_more("wifi", base_dir=root), "helpful feedback clears topic ask-more")
check(not topic_is_muted("wifi", base_dir=root, now=insight_now + timedelta(days=9, minutes=21)), "helpful feedback lifts the soft mute")
mute_topic("wifi", days=7, reason="user", base_dir=root, now=insight_now + timedelta(days=10))
note_user_feedback(True, topic="wifi", base_dir=root, now=insight_now + timedelta(days=10, hours=2))
check(topic_is_muted("wifi", base_dir=root, now=insight_now + timedelta(days=10, hours=3)), "helpful feedback keeps an explicit mute")
check(clear_muted_topics(base_dir=root) >= 1, "memory screen can clear every mute")
check(not active_muted_topics(base_dir=root), "clear mute leaves none behind")
print(" [PASS] mute topic and feedback coaching")

root = _fresh_dir()
base_day = datetime(2026, 8, 1, 8, 0, 0)
for i in range(6):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=base_day + timedelta(days=i),
        base_dir=root,
        coalesce=False,
    )
state = load_state(root)
state["last_recorded_stage"] = 1
state["last_celebrated_stage"] = 1
state["pending_stage_up"] = None
save_state(state, base_dir=root)
before_stage = [row for row in read_events(base_dir=root) if row.get("kind") == "stage_up"]
record_app_event(
    "session_day",
    "Phiên dùng app trên máy này",
    now=base_day + timedelta(days=6),
    base_dir=root,
    coalesce=False,
)
stage_rows = [row for row in read_events(base_dir=root) if row.get("kind") == "stage_up"]
check(len(stage_rows) == len(before_stage) + 1, "crossing into Lớn dần writes one diary line")
latest = stage_rows[-1]
check("giai đoạn 2" in latest["summary"].lower() or "Lớn dần" in latest["summary"], "stage-up names the new stage")
check("ngày dùng" in latest["summary"], "stage-up cites why the stage rose")
pending = pending_stage_celebration(root, now=base_day + timedelta(days=6))
check(pending and pending.get("text", "").startswith("Mình vừa lên giai đoạn 2"), "stage-up banner explains the rise")
check("ngày" in pending.get("reason_vi", "") or "ngày" in pending.get("text", ""), "banner keeps the stage reason")
check(
    pending_stage_celebration(root, now=base_day + timedelta(days=7)) is None,
    "the banner does not repeat on a later day",
)
again = record_app_event(
    "wifi_weak",
    "Wi-Fi yếu",
    now=base_day + timedelta(days=6, hours=2),
    base_dir=root,
    coalesce=False,
)
stage_rows_again = [row for row in read_events(base_dir=root) if row.get("kind") == "stage_up"]
check(len(stage_rows_again) == len(stage_rows), "the same stage is not celebrated twice")
check(again and again.get("kind") == "wifi_weak", "later events still record normally")
dismiss_stage_celebration(root)
check(pending_stage_celebration(root) is None, "dismiss hides the stage banner")
record_app_event(
    "wifi_weak",
    "Wi-Fi yếu lần nữa",
    now=base_day + timedelta(days=6, hours=3),
    base_dir=root,
    coalesce=False,
)
check(pending_stage_celebration(root) is None, "dismissed stage does not return on the next open")
check(
    len([row for row in read_events(base_dir=root) if row.get("kind") == "stage_up"]) == len(stage_rows),
    "dismiss does not write another stage-up",
)
print(" [PASS] one-shot stage-up")

root = _fresh_dir()
quiet = compose_daily_checkin(now=datetime(2026, 9, 23, 8, 0, 0), base_dir=root, config_manager=_Cfg())
check(quiet is None, "a brand-new machine has no morning check-in")
yesterday = datetime(2026, 9, 22, 21, 0, 0)
record_app_event("wifi_weak", "Wi-Fi yếu buổi tối", now=yesterday, base_dir=root, coalesce=False)
record_app_event("thermal_warn", "Nhiệt cao", metrics={"thermal_c": 90}, now=yesterday.replace(hour=15), base_dir=root, coalesce=False)
morning = datetime(2026, 9, 23, 8, 0, 0)
first = sync_daily_checkin(now=morning, base_dir=root, config_manager=_Cfg())
check(first and "Hôm qua" in first.get("text", ""), "check-in is built from yesterday")
check("Wi-Fi" in first["text"] or "nhiệt" in first["text"], "check-in names yesterday's pattern")
check("Gemini" not in first["text"] and "Ollama" not in first["text"], "check-in does not call a model")
second = sync_daily_checkin(now=morning.replace(hour=18), base_dir=root, config_manager=_Cfg())
check(second and second.get("text") == first.get("text"), "the same day reuses one check-in")
dismiss_daily_checkin(base_dir=root, now=morning.replace(hour=19))
check(sync_daily_checkin(now=morning.replace(hour=20), base_dir=root, config_manager=_Cfg()) is None, "dismissed check-in stays hidden today")
next_morning = sync_daily_checkin(now=morning + timedelta(days=1), base_dir=root, config_manager=_Cfg())
check(next_morning is None or "Hôm qua" in (next_morning.get("text") or ""), "the next day may check in again")
goal_root = _fresh_dir()
set_goal("ổn định Wi-Fi trước họp", base_dir=goal_root, now=morning - timedelta(days=2))
for i in range(7):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=morning - timedelta(days=8 - i),
        base_dir=goal_root,
        coalesce=False,
    )
save_skill("wifi_weak", hit_count=3, base_dir=goal_root)
goal_line = compose_daily_checkin(now=morning, base_dir=goal_root, config_manager=_Cfg(companion_may_propose_actions=True))
check(goal_line and "Mục tiêu" in goal_line.get("text", "") or "mục tiêu" in goal_line.get("text", "").lower(), "check-in can remind an open goal")
check(goal_line.get("action_key") in INSIGHT_ACTION_ALLOWLIST, "check-in action stays allowlisted")
check(goal_line.get("action_key") not in ("clean_junk", "winsxs_cleanup", "switch_dns", "auto_optimize_all"), "check-in action is not destructive")
mute_topic("wifi", days=7, base_dir=goal_root, now=morning)
muted_line = compose_daily_checkin(now=morning + timedelta(days=1), base_dir=goal_root, config_manager=_Cfg())
check("Wi-Fi" not in (muted_line or {}).get("text", ""), "check-in does not name a muted topic")
check((muted_line or {}).get("topic") != "wifi", "check-in does not lead with a muted topic")
off = sync_daily_checkin(now=morning, base_dir=root, config_manager=_Cfg(companion_enabled=False))
check(off is None, "check-in respects companion_enabled")
print(" [PASS] morning check-in")


# ---------------------------------------------------------------------------
# Sticky corrections, trust, time windows, growth timeline
# ---------------------------------------------------------------------------

from core.companion_profile import (
    GROWTH_EMPTY_VI,
    WINDOW_PHRASE,
    active_time_windows,
    add_user_note,
    build_growth_timeline,
    clear_habits,
    delete_user_note,
    effective_coaching,
    list_user_notes,
    score_trust,
)
from core.companion_moment import action_cap_for_stage, stage_voice
from core.companion_skills import BLOCKED_ACTION_KEYS

root = _fresh_dir()
blank = add_user_note("   ", base_dir=root)
check(blank is None, "blank note is not stored")
secret = add_user_note(
    "sai rồi, Wi-Fi yếu vì kênh DFS, key AIzaSyTESTKEY1234567890",
    source="user",
    base_dir=root,
    now=datetime(2026, 9, 23, 9, 0, 0),
)
check(secret and secret.get("topic") == "wifi", "explicit note tags Wi-Fi")
check(secret.get("kind") == "correction", "a hardware fact is a correction")
check("AIza" not in secret.get("text", ""), "note redacts secrets")
check("DFS" in secret.get("text", ""), "note keeps the short fact")
style = add_user_note("gọi ngắn gọn", source="user", base_dir=root, now=datetime(2026, 9, 23, 9, 1, 0))
check(style and style.get("kind") == "preference" and not style.get("topic"), "style note has no fake topic")
avoid = add_user_note("đừng đề xuất dọn nặng", source="user", base_dir=root, now=datetime(2026, 9, 23, 9, 2, 0))
check(avoid and avoid.get("kind") == "preference" and avoid.get("topic") == "disk", "don't-clean note is a disk preference")
again = add_user_note(secret.get("text") or "", source="user", base_dir=root, now=datetime(2026, 9, 23, 9, 3, 0))
check(again and again.get("id") == secret.get("id"), "the same fact updates instead of duplicating")
check(len(list_user_notes(base_dir=root)) == 3, "three distinct notes stay under the cap")

for i in range(22):
    add_user_note(f"ghi chú riêng số {i:02d} cho máy này", base_dir=root, now=datetime(2026, 9, 23, 10, 0, 0) + timedelta(minutes=i))
check(len(list_user_notes(base_dir=root)) == 20, "notes cap at 20")
blob = " ".join(item.get("text") or "" for item in list_user_notes(base_dir=root))
check("số 00" not in blob and "số 21" in blob, "the cap drops the oldest note")
dropped = delete_user_note(list_user_notes(base_dir=root)[-1]["id"], base_dir=root)
check(dropped and len(list_user_notes(base_dir=root)) == 19, "memory screen can delete one note")

chat_root = _fresh_dir()
reply = "Đây là câu trả lời dài của Copilot, không được lưu nguyên transcript. " + ("x" * 80)
learned = learn_from_chat(
    "sai rồi, Wi-Fi yếu vì kênh DFS",
    reply,
    now=datetime(2026, 9, 23, 11, 0, 0),
    base_dir=chat_root,
)
check(learned and learned.get("kind") == "chat_note", "a correction can still be a short chat note")
stored = list_user_notes(base_dir=chat_root)
check(len(stored) == 1, "chat correction stores one line")
check("transcript" not in stored[0]["text"] and "xxxx" not in stored[0]["text"], "assistant reply is not stored")
check(stored[0]["source"] == "chat" and "DFS" in stored[0]["text"], "chat line is sanitized and tagged")
check(stored[0]["text"].count(" ") < 40, "stored correction is one short line")
quiet_chat = learn_from_chat(
    "Wifi nhà mình chậm",
    "Mình xem nhật ký Wi-Fi giúp bạn.",
    now=datetime(2026, 9, 23, 11, 5, 0),
    base_dir=chat_root,
)
check(quiet_chat and len(list_user_notes(base_dir=chat_root)) == 1, "a normal question is not a correction")

ctx_fact = build_prompt_context("wifi chậm", base_dir=chat_root, now=datetime(2026, 9, 23, 11, 6, 0))
check("DFS" in ctx_fact and "Lời bạn đã dạy" in ctx_fact, "Copilot context quotes the matching correction")
check("transcript" not in ctx_fact, "context does not include the assistant reply")
ctx_heat = build_prompt_context("máy nóng", base_dir=chat_root, now=datetime(2026, 9, 23, 11, 6, 0))
check("DFS" not in ctx_heat and "kênh" not in ctx_heat, "a heat question does not invent the Wi-Fi cause")
ground_fact = local_grounding_text("wifi chậm", base_dir=chat_root, now=datetime(2026, 9, 23, 11, 6, 0))
check("DFS" in ground_fact, "offline grounding quotes the stored Wi-Fi fact")
for i in range(2):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu",
        now=datetime(2026, 9, 20 + i, 21, 0, 0),
        base_dir=chat_root,
        coalesce=False,
    )
seen = current_insight(base_dir=chat_root, now=datetime(2026, 9, 23, 8, 0, 0))
check(seen and seen.get("topic") == "wifi" and "DFS" in seen.get("text", ""), "morning insight quotes the Wi-Fi correction")
check_in_fact = compose_daily_checkin(
    now=datetime(2026, 9, 23, 8, 0, 0),
    base_dir=chat_root,
    config_manager=_Cfg(),
)
check(check_in_fact and "DFS" in check_in_fact.get("text", ""), "check-in quotes the matching correction")
kept = add_user_note("gọi ngắn gọn", base_dir=chat_root, now=datetime(2026, 9, 23, 12, 0, 0))
clear_habits(base_dir=chat_root, now=datetime(2026, 9, 23, 12, 1, 0))
after_clear = list_user_notes(base_dir=chat_root)
check(any("DFS" in item.get("text", "") for item in after_clear), "clearing habits keeps taught notes")
check(kept and any(item.get("id") == kept.get("id") for item in after_clear), "style note stays with the goal")
print(" [PASS] sticky corrections")

trust_root = _fresh_dir()
for i in range(3):
    observe_suggestion(
        False,
        action_key="clean_light",
        base_dir=trust_root,
        now=datetime(2026, 9, 10 + i, 18, 0, 0),
        coalesce=False,
    )
low = score_trust(base_dir=trust_root)
check(low["level"] == "low" and low["rejected"] >= 2, "three rejects is low trust")
check(effective_coaching(base_dir=trust_root) == "ask_more", "low trust asks more without editing the coaching flag")
check(load_profile(trust_root).get("coaching") == "steady", "global coaching flag stays steady")
check(action_cap_for_stage(3, trust="low") == 0, "low trust hides action buttons")
check(stage_voice(3, trust="low")["boldness"] == "ask", "low trust uses the ask voice")
shy_focus = resolve_insight_action("focus", stage=3, may_propose=True, coaching=effective_coaching(base_dir=trust_root))
check(shy_focus and shy_focus["key"] != "enable_exam_focus", "low trust does not start focus mode")
soft = compose_daily_checkin(now=datetime(2026, 9, 23, 8, 0, 0), base_dir=trust_root, config_manager=_Cfg())
check(soft is None or "hỏi thêm" in soft.get("text", "") or not soft.get("action_key"), "low trust check-in stays soft")

high_root = _fresh_dir()
for i in range(3):
    observe_suggestion(
        True,
        action_key="optimize_ram",
        base_dir=high_root,
        now=datetime(2026, 9, 10 + i, 18, 0, 0),
        coalesce=False,
    )
high = score_trust(base_dir=high_root)
check(high["level"] == "high" and high["accepted"] >= 2, "repeated accepts build high trust")
check(effective_coaching(base_dir=high_root) == "steady", "high trust does not force ask-more")
check(action_cap_for_stage(2, trust="high", may_propose=True) == 1, "high trust at stage 2 may propose one action")
check(action_cap_for_stage(1, trust="high", may_propose=True) == 0, "high trust does not skip the stage gate")
check(action_cap_for_stage(3, trust="high", may_propose=False) == 0, "high trust still honors the propose switch")
blocked = resolve_insight_action("disk", stage=3, may_propose=True, coaching="steady", prefer_key="clean_junk")
check(blocked and blocked["key"] not in BLOCKED_ACTION_KEYS, "trust never offers a blocked action")
mute_topic("wifi", days=7, reason="user", base_dir=high_root, now=datetime(2026, 9, 20, 8, 0, 0))
check(
    effective_coaching(base_dir=high_root, topic="wifi", now=datetime(2026, 9, 20, 9, 0, 0)) == "ask_more",
    "a mute still wins when trust is high",
)
note_user_feedback(False, base_dir=high_root, now=datetime(2026, 9, 20, 9, 5, 0), topic="thermal")
check(topic_is_muted("thermal", base_dir=high_root, now=datetime(2026, 9, 20, 9, 6, 0)), "unhelpful feedback still soft-mutes")
check(
    effective_coaching(base_dir=high_root, topic="thermal", now=datetime(2026, 9, 20, 9, 6, 0)) == "ask_more",
    "soft mute is not cleared by older accepts",
)
print(" [PASS] trust adjusts boldness")

window_root = _fresh_dir()
for i in range(3):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=datetime(2026, 9, 20 + i, 20, 30, 0),
        base_dir=window_root,
        coalesce=False,
    )
record_app_event(
    "wifi_weak",
    "Wi-Fi yếu buổi tối",
    now=datetime(2026, 9, 23, 19, 0, 0),
    base_dir=window_root,
    coalesce=False,
)
for i in range(2):
    record_app_event(
        "high_ram",
        "RAM cao 88%",
        metrics={"ram_percent": 88},
        now=datetime(2026, 9, 20 + i, 16, 0, 0),
        base_dir=window_root,
        coalesce=False,
    )
evening = datetime(2026, 9, 23, 20, 0, 0)
afternoon = datetime(2026, 9, 23, 16, 0, 0)
morning_quiet = datetime(2026, 9, 23, 8, 0, 0)
windows = active_time_windows(read_events(base_dir=window_root), now=evening, profile=load_profile(window_root))
check(any(item.get("topic") == "wifi" for item in windows), "evening Wi-Fi is a recurring window")
check(all(item.get("topic") != "ram" for item in windows), "afternoon RAM is not an evening window")
wifi_line = current_insight(base_dir=window_root, now=evening)
check(wifi_line and WINDOW_PHRASE in wifi_line.get("text", "") and wifi_line.get("topic") == "wifi", "evening insight names this hour")
ram_line = current_insight(base_dir=window_root, now=afternoon)
check(ram_line and ram_line.get("topic") == "ram" and WINDOW_PHRASE in ram_line.get("text", ""), "afternoon insight names the RAM window")
morning_line = current_insight(base_dir=window_root, now=morning_quiet)
check(WINDOW_PHRASE not in (morning_line or {}).get("text", ""), "morning does not claim the evening window")
nudge = plan_companion_nudge(now=evening, base_dir=window_root, config_manager=_Cfg(), commit=False)
check(nudge and nudge.get("issue_class") == "wifi_weak", "window nudge reuses the calm wifi tip")
check(WINDOW_PHRASE in nudge.get("message", ""), "nudge mentions the usual hour")
check("tiết kiệm" in nudge["message"] or "DNS" in nudge["message"], "window nudge stays the safe wifi tip")
mute_topic("wifi", days=7, base_dir=window_root, now=evening)
muted_hour = current_insight(base_dir=window_root, now=evening)
check(muted_hour is None or muted_hour.get("topic") != "wifi", "muted topic is not a time-of-day insight")
muted_nudge = plan_companion_nudge(now=evening + timedelta(hours=1), base_dir=window_root, config_manager=_Cfg(), commit=False)
check(muted_nudge is None or muted_nudge.get("issue_class") != "wifi_weak", "muted topic is not a time-of-day toast")
print(" [PASS] time-of-day habit hints")

growth_root = _fresh_dir()
check(build_growth_timeline(base_dir=growth_root) == [], "empty disk has no growth rows")
check("mốc" in GROWTH_EMPTY_VI, "empty growth copy is humble")
add_user_note("Wi-Fi yếu vì kênh DFS", base_dir=growth_root, now=datetime(2026, 9, 18, 9, 0, 0))
save_skill("wifi_weak", hit_count=3, base_dir=growth_root)
record_app_event(
    "stage_up",
    "Mình vừa lên giai đoạn 2 · Lớn dần. Lớn dần vì 7 ngày dùng.",
    metrics={"stage": 2},
    now=datetime(2026, 9, 19, 8, 0, 0),
    base_dir=growth_root,
    coalesce=False,
)
record_app_event(
    "skill_saved",
    "Đã kết tinh kỹ năng: Wi-Fi yếu / ping lỗi trên máy này",
    now=datetime(2026, 9, 19, 8, 5, 0),
    base_dir=growth_root,
    coalesce=False,
)
record_app_event(
    "reflection",
    "Đã ghi tóm tắt tuần",
    now=datetime(2026, 9, 21, 20, 0, 0),
    base_dir=growth_root,
    coalesce=False,
)
timeline = build_growth_timeline(base_dir=growth_root)
texts = " ".join(item.get("text") or "" for item in timeline)
check("giai đoạn 2" in texts or "Lớn dần" in texts, "timeline lists the stage-up")
check("kỹ năng" in texts.lower(), "timeline lists a saved skill")
check("DFS" in texts, "timeline lists the correction")
check("tuần" in texts.lower(), "timeline lists the weekly marker")
check(timeline[0]["ts"] <= timeline[-1]["ts"], "timeline is chronological")
print(" [PASS] growth timeline")


# ---------------------------------------------------------------------------
# Quiet hours, follow-up, outcome learning, end-of-day wrap
# ---------------------------------------------------------------------------

from core.companion_moment import (
    answer_action_followup,
    attach_insight_action,
    compose_eod_wrap,
    dismiss_action_followup,
    dismiss_eod_wrap,
    due_action_followup,
    note_mute_after_action,
    schedule_action_followup,
    sync_eod_wrap,
)
from core.companion import observe_ram_optimized
from core.companion_profile import (
    add_user_note,
    effective_coaching,
    in_quiet_hours,
    quiet_hours_settings,
    score_trust,
    set_quiet_hours,
    topic_asks_more,
    topic_is_muted,
)
from core.companion_skills import bump_skill_hit as _bump_skill_hit

root = _fresh_dir()
check(quiet_hours_settings(base_dir=root)["enabled"] is False, "quiet hours default off")
check(quiet_hours_settings(base_dir=root)["start"] == "23:00", "suggested quiet start is 23:00")
check(quiet_hours_settings(base_dir=root)["end"] == "07:00", "suggested quiet end is 07:00")
check(not in_quiet_hours(datetime(2026, 9, 23, 2, 0), base_dir=root), "off window is not quiet")
set_quiet_hours(True, base_dir=root)
check(in_quiet_hours(datetime(2026, 9, 23, 23, 0), base_dir=root), "23:00 starts quiet hours")
check(in_quiet_hours(datetime(2026, 9, 23, 2, 15), base_dir=root), "after midnight is still quiet")
check(in_quiet_hours(datetime(2026, 9, 23, 6, 59), base_dir=root), "06:59 is still quiet")
check(not in_quiet_hours(datetime(2026, 9, 23, 7, 0), base_dir=root), "07:00 leaves quiet hours")
check(not in_quiet_hours(datetime(2026, 9, 23, 22, 59), base_dir=root), "22:59 is before the window")
check(not in_quiet_hours(datetime(2026, 9, 23, 12, 0), base_dir=root), "midday is not quiet")
set_quiet_hours(False, base_dir=root)
check(not in_quiet_hours(datetime(2026, 9, 23, 2, 0), base_dir=root), "turning quiet hours off restores the day")

quiet_nudge = _fresh_dir()
for i in range(4):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=datetime(2026, 9, 20, 21, 10, 0) + timedelta(days=i),
        base_dir=quiet_nudge,
        coalesce=False,
    )
night = datetime(2026, 9, 23, 23, 30, 0)
daytime = datetime(2026, 9, 23, 21, 10, 0)
set_quiet_hours(True, base_dir=quiet_nudge)
check(
    plan_companion_nudge(now=night, base_dir=quiet_nudge, config_manager=_Cfg(), commit=False) is None,
    "quiet hours suppress the calm companion toast",
)
still = plan_companion_nudge(now=daytime, base_dir=quiet_nudge, config_manager=_Cfg(), commit=False)
check(still and still.get("issue_class") == "wifi_weak", "the same tip still exists outside quiet hours")

night_root = _fresh_dir()
record_app_event(
    "wifi_weak",
    "Wi-Fi yếu buổi tối",
    now=datetime(2026, 9, 22, 21, 0, 0),
    base_dir=night_root,
    coalesce=False,
)
set_quiet_hours(True, base_dir=night_root)
night_open = datetime(2026, 9, 23, 1, 30, 0)
check(
    sync_daily_checkin(now=night_open, base_dir=night_root, config_manager=_Cfg()) is None,
    "quiet hours do not compose a morning check-in",
)
check(load_state(night_root).get("last_checkin_date") != "2026-09-23", "a night open does not consume the check-in")
morning_after = sync_daily_checkin(
    now=datetime(2026, 9, 23, 8, 0, 0),
    base_dir=night_root,
    config_manager=_Cfg(),
)
check(morning_after and "Hôm qua" in morning_after.get("text", ""), "morning check-in still runs after quiet hours")

soft = {"id": "habit:wifi", "text": "Hôm nay: Wi-Fi yếu buổi tối trên máy này.", "topic": "wifi"}
quiet_insight = _fresh_dir()
set_quiet_hours(True, base_dir=quiet_insight)
stripped = attach_insight_action(
    soft,
    config_manager=_Cfg(),
    base_dir=quiet_insight,
    now=datetime(2026, 9, 23, 23, 40, 0),
)
check(stripped and stripped.get("text"), "quiet hours still keep the insight line")
check("action_key" not in (stripped or {}), "quiet hours drop propose buttons")
check((stripped or {}).get("quiet") is True, "the insight is marked softer")
set_quiet_hours(True, allow_actions=True, base_dir=quiet_insight)
kept = attach_insight_action(
    soft,
    config_manager=_Cfg(),
    base_dir=quiet_insight,
    now=datetime(2026, 9, 23, 23, 40, 0),
)
check(kept and kept.get("action_key"), "opt-in keeps the propose button during quiet hours")
check(kept.get("action_key") not in BLOCKED_ACTION_KEYS, "quiet-hours opt-in stays on the allowlist")

follow = _fresh_dir()
save_skill("wifi_weak", hit_count=4, base_dir=follow)
skill_id = load_skills(follow)[0].id
asked_at = datetime(2026, 9, 23, 15, 0, 0)
for blocked_key in ("winsxs_cleanup", "clean_junk", "switch_dns", "auto_optimize_all", "open_companion_memory"):
    check(
        schedule_action_followup(blocked_key, now=asked_at, base_dir=follow, config_manager=_Cfg()) is None,
        f"{blocked_key} does not schedule a follow-up",
    )
first_ask = schedule_action_followup(
    "repair_network_now",
    skill_id=skill_id,
    now=asked_at,
    base_dir=follow,
    config_manager=_Cfg(),
)
check(first_ask and "Wi-Fi" in first_ask.get("question_vi", ""), "follow-up asks about Wi-Fi in Vietnamese")
check("Gemini" not in first_ask["question_vi"] and "Ollama" not in first_ask["question_vi"], "follow-up needs no model")
check(
    schedule_action_followup("optimize_ram", now=asked_at, base_dir=follow, config_manager=_Cfg()) is None,
    "only one follow-up can be pending",
)
check(
    due_action_followup(now=asked_at + timedelta(minutes=20), base_dir=follow, config_manager=_Cfg()) is None,
    "follow-up waits out its delay",
)
set_quiet_hours(True, base_dir=follow)
check(
    due_action_followup(now=datetime(2026, 9, 23, 23, 30), base_dir=follow, config_manager=_Cfg()) is None,
    "quiet hours hide the follow-up without deleting it",
)
check(load_state(follow).get("pending_followup"), "the hidden follow-up is still pending")
set_quiet_hours(False, base_dir=follow)
due = due_action_followup(now=datetime(2026, 9, 23, 23, 40), base_dir=follow, config_manager=_Cfg())
check(due and due.get("question_vi") == first_ask.get("question_vi"), "the follow-up returns on the next open")
dismiss_action_followup(base_dir=follow)
check(due_action_followup(now=asked_at + timedelta(hours=3), base_dir=follow, config_manager=_Cfg()) is None, "dismiss clears the question")
check(
    not any(row.get("kind") == "user_feedback" for row in read_events(base_dir=follow)),
    "dismiss does not write a diary verdict",
)

again = schedule_action_followup(
    "repair_network_now",
    skill_id=skill_id,
    now=asked_at,
    base_dir=follow,
    config_manager=_Cfg(),
)
check(again, "a new follow-up can be scheduled after dismiss")
before_trust = score_trust(base_dir=follow, now=asked_at)
answer_action_followup(True, now=asked_at + timedelta(hours=2), base_dir=follow, config_manager=_Cfg())
after_yes = score_trust(base_dir=follow, now=asked_at + timedelta(hours=2))
check(after_yes["accepted"] == before_trust["accepted"] + 1, "Có ích feeds trust")
check(load_skills(follow)[0].hit_count == 5, "Có ích bumps skill quality")
check(
    any(row.get("kind") == "user_feedback" and row.get("outcome") == "accepted" for row in read_events(base_dir=follow)),
    "Có ích is a diary line",
)

no_help = _fresh_dir()
save_skill("high_ram", hit_count=3, base_dir=no_help)
ram_id = load_skills(no_help)[0].id
schedule_action_followup("optimize_ram", skill_id=ram_id, now=asked_at, base_dir=no_help, config_manager=_Cfg())
answer_action_followup(False, now=asked_at + timedelta(hours=1), base_dir=no_help, config_manager=_Cfg())
check(load_skills(no_help)[0].hit_count == 2, "Chưa lowers skill quality")
check(topic_is_muted("ram", now=asked_at + timedelta(hours=1), base_dir=no_help), "Chưa soft-mutes that topic")
check(
    effective_coaching(topic="ram", base_dir=no_help, now=asked_at + timedelta(hours=1)) == "ask_more",
    "Chưa weakens propose boldness for that topic",
)
check(score_trust(base_dir=no_help, now=asked_at + timedelta(hours=1))["rejected"] >= 1, "Chưa feeds a trust reject")
check(_bump_skill_hit(skill_id=ram_id, delta=-5, base_dir=no_help).hit_count == 0, "skill quality does not go negative")

learned = _fresh_dir()
save_skill("wifi_weak", hit_count=3, base_dir=learned)
learned_id = load_skills(learned)[0].id
when = datetime(2026, 9, 23, 16, 0, 0)
schedule_action_followup("repair_network_now", skill_id=learned_id, now=when, base_dir=learned, config_manager=_Cfg())
observe_wifi_repaired(False, base_dir=learned, now=when + timedelta(minutes=2))
check(load_skills(learned)[0].hit_count == 3, "a failed repair does not strengthen the skill")
observe_wifi_repaired(True, base_dir=learned, now=when - timedelta(minutes=5))
check(load_skills(learned)[0].hit_count == 3, "an older repair is not credited to this action")
observe_wifi_repaired(True, base_dir=learned, now=when + timedelta(minutes=8))
check(load_skills(learned)[0].hit_count == 4, "wifi_repaired after the action strengthens the skill")
check(
    score_trust(base_dir=learned, now=when + timedelta(minutes=8))["accepted"] >= 1,
    "a real recovery strengthens trust slightly",
)
observe_wifi_repaired(True, base_dir=learned, now=when + timedelta(minutes=12), coalesce=False)
check(load_skills(learned)[0].hit_count == 4, "the same recovery is credited once")

ram_learn = _fresh_dir()
save_skill("high_ram", hit_count=2, base_dir=ram_learn)
schedule_action_followup(
    "optimize_ram",
    skill_id=load_skills(ram_learn)[0].id,
    now=when,
    base_dir=ram_learn,
    config_manager=_Cfg(),
)
observe_ram_optimized(120, base_dir=ram_learn, now=when + timedelta(minutes=3))
check(load_skills(ram_learn)[0].hit_count == 3, "ram_optimized after optimize_ram strengthens that skill")

muted_after = _fresh_dir()
save_skill("wifi_weak", hit_count=4, base_dir=muted_after)
schedule_action_followup(
    "repair_network_now",
    skill_id=load_skills(muted_after)[0].id,
    now=when,
    base_dir=muted_after,
    config_manager=_Cfg(),
)
mute_topic("wifi", days=7, base_dir=muted_after, now=when + timedelta(minutes=1))
check(note_mute_after_action("wifi", base_dir=muted_after, now=when + timedelta(minutes=1)), "mute after an action is noticed")
check(load_skills(muted_after)[0].hit_count == 3, "muting the topic after an action lowers skill quality")
check(load_state(muted_after).get("pending_followup") is None, "mute retires the open follow-up")
check(
    effective_coaching(topic="wifi", base_dir=muted_after, now=when + timedelta(minutes=2)) == "ask_more",
    "mute keeps propose boldness down",
)
check(not note_mute_after_action("thermal", base_dir=muted_after), "an unrelated mute does not penalize the wifi skill")

bare = _fresh_dir()
observe_wifi_repaired(True, base_dir=bare, now=when)
check(
    not any(row.get("tags") and "outcome" in row.get("tags") for row in read_events(base_dir=bare)),
    "recovery without a companion action does not invent trust",
)

eod = _fresh_dir()
afternoon = datetime(2026, 9, 23, 17, 0, 0)
evening_open = datetime(2026, 9, 23, 19, 10, 0)
check(sync_eod_wrap(now=evening_open, base_dir=eod, config_manager=_Cfg()) is None, "an empty evening stays quiet")
check(not load_state(eod).get("last_eod_date"), "an empty day does not consume the wrap")
record_app_event("wifi_weak", "Wi-Fi yếu", now=datetime(2026, 9, 23, 11, 0, 0), base_dir=eod, coalesce=False)
record_app_event("wifi_repaired", "Wi-Fi đã ổn định lại", now=datetime(2026, 9, 23, 11, 20, 0), base_dir=eod, coalesce=False, outcome="ok")
check(compose_eod_wrap(now=afternoon, base_dir=eod, config_manager=_Cfg()) is None, "before 18:00 there is no wrap")
set_goal("ổn định Wi-Fi trước họp", base_dir=eod, now=datetime(2026, 9, 23, 9, 0, 0))
add_user_note("Wi-Fi yếu vì kênh DFS", base_dir=eod, now=datetime(2026, 9, 23, 9, 5, 0))
set_quiet_hours(True, start="18:00", end="23:00", base_dir=eod)
check(sync_eod_wrap(now=evening_open, base_dir=eod, config_manager=_Cfg()) is None, "quiet hours skip the evening wrap")
check(not load_state(eod).get("last_eod_date"), "skipping for quiet hours does not consume the day")
set_quiet_hours(False, base_dir=eod)
wrap = sync_eod_wrap(now=evening_open, base_dir=eod, config_manager=_Cfg())
check(wrap and wrap.get("text", "").startswith("Cuối ngày:"), "evening wrap is a short local line")
check("Wi-Fi" in wrap["text"], "the wrap uses today's diary")
check("Mục tiêu" in wrap["text"], "the wrap keeps the goal")
check("DFS" in wrap["text"], "the wrap includes one matching correction")
check("Gemini" not in wrap["text"] and "Ollama" not in wrap["text"], "the wrap does not call a model")
again_wrap = sync_eod_wrap(now=evening_open.replace(hour=21), base_dir=eod, config_manager=_Cfg())
check(again_wrap and again_wrap.get("text") == wrap.get("text"), "one wrap per evening")
dismiss_eod_wrap(base_dir=eod, now=evening_open.replace(hour=21, minute=30))
check(sync_eod_wrap(now=evening_open.replace(hour=22), base_dir=eod, config_manager=_Cfg()) is None, "dismiss hides the wrap")
print(" [PASS] quiet hours, follow-up, outcomes, end-of-day wrap")


# ---------------------------------------------------------------------------
# Focus session, goal conflict, stress, memory backup
# ---------------------------------------------------------------------------

from core.companion import (
    export_companion_memory,
    import_companion_memory,
    observe_focus_disabled,
    observe_focus_enabled,
)
from core.companion_moment import (
    compose_daily_checkin,
    dismiss_goal_conflict,
    due_action_followup,
    machine_stress_active,
    note_focus_ended,
    note_focus_started,
    quiet_covers_reminder_band,
    sync_focus_session,
    sync_goal_conflict,
)
from core.companion_profile import mute_topic, set_goal, set_quiet_hours, unmute_topic
from core.companion_reflection import load_reflection, save_reflection
from core.exam_focus import ExamMeetingFocus
from core.companion_diary import read_events
from core.companion_maturity import load_state, save_state
from core.companion_skills import BLOCKED_ACTION_KEYS, load_skills

ExamMeetingFocus.reset_for_tests()
focus_root = _fresh_dir()
started = datetime(2026, 9, 23, 9, 0, 0)
check(observe_focus_enabled({"already_active": True}, base_dir=focus_root, now=started) is None, "already-on focus does not write another start")
check(ExamMeetingFocus.is_active() is False, "observing focus does not turn the mode on")
started_row = observe_focus_enabled({"freed_junk_mb": 12}, base_dir=focus_root, now=started, config_manager=_Cfg())
check(started_row and started_row.get("kind") == "focus_mode", "enabling focus writes a diary episode")
check("bật" in started_row.get("summary", "").lower() or "Trước thi" in started_row.get("summary", ""), "start episode names Trước thi / họp")
check("start" in (started_row.get("tags") or []), "start episode is tagged")
check(load_state(focus_root).get("focus_session", {}).get("active") is True, "the companion notices the open session")
check(observe_focus_disabled({"already_inactive": True}, base_dir=focus_root, now=started) is None, "already-off focus does not write an end")
nudge_root = _fresh_dir()
for i in range(4):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=datetime(2026, 9, 20, 21, 0, 0) + timedelta(days=i),
        base_dir=nudge_root,
        coalesce=False,
    )
open_nudge = plan_companion_nudge(
    now=datetime(2026, 9, 24, 21, 0, 0),
    base_dir=nudge_root,
    config_manager=_Cfg(),
    commit=False,
)
check(open_nudge and open_nudge.get("issue_class") == "wifi_weak", "without focus, a repeated Wi-Fi pattern can nudge")
ExamMeetingFocus._is_active = True
try:
    check(stage_voice(3, focus_active=True)["boldness"] == "ask", "an open session uses a softer voice")
    check(action_cap_for_stage(3, focus_active=True) == 0, "an open session does not pile propose buttons")
    check(
        plan_companion_nudge(
            now=datetime(2026, 9, 24, 21, 0, 0),
            base_dir=nudge_root,
            config_manager=_Cfg(),
            commit=False,
        ) is None,
        "an open session skips non-focus nudges",
    )
    wifi_line = attach_insight_action(
        {"id": "habit:wifi", "text": "Hôm nay: Wi-Fi yếu.", "topic": "wifi"},
        config_manager=_Cfg(companion_may_propose_actions=True),
        base_dir=focus_root,
        now=started,
    )
    check(not (wifi_line or {}).get("action_key"), "focus session keeps non-focus actions off the strip")
finally:
    ExamMeetingFocus.reset_for_tests()
ended = observe_focus_disabled({}, base_dir=focus_root, now=datetime(2026, 9, 23, 11, 0, 0), config_manager=_Cfg())
check(ended and ended.get("kind") == "focus_end", "turning focus off writes its own episode")
check("tắt" in (ended.get("summary") or "").lower(), "end episode says the session stopped")
check(load_state(focus_root).get("focus_session", {}).get("active") is False, "the session is closed in memory")
asked = due_action_followup(now=datetime(2026, 9, 23, 11, 5, 0), base_dir=focus_root, config_manager=_Cfg())
check(asked and "Trước thi" in asked.get("question_vi", ""), "ending focus asks whether the session helped")
check(note_focus_ended(now=datetime(2026, 9, 23, 11, 6, 0), base_dir=focus_root, config_manager=_Cfg()) is None, "the same session is not asked twice")
set_quiet_hours(True, base_dir=focus_root)
check(
    due_action_followup(now=datetime(2026, 9, 23, 23, 30, 0), base_dir=focus_root, config_manager=_Cfg()) is None,
    "quiet hours hide the focus follow-up",
)
check(load_state(focus_root).get("pending_followup"), "quiet hours keep the focus question")
set_quiet_hours(False, base_dir=focus_root)
mute_topic("focus", days=7, base_dir=focus_root, now=datetime(2026, 9, 23, 11, 10, 0))
check(
    due_action_followup(now=datetime(2026, 9, 23, 12, 0, 0), base_dir=focus_root, config_manager=_Cfg()) is None,
    "a muted focus topic hides the follow-up",
)
unmute_topic("focus", base_dir=focus_root)
helpful = answer_action_followup(True, now=datetime(2026, 9, 23, 12, 5, 0), base_dir=focus_root, config_manager=_Cfg())
check(helpful and helpful.get("helpful") is True, "Có ích answers the focus question")
check(load_state(focus_root).get("positive_feedback", 0) >= 1, "Có ích feeds trust")
check(load_state(focus_root).get("pending_followup") is None, "answering clears the focus question")

reopen = _fresh_dir()
note_focus_started(now=datetime(2026, 9, 23, 8, 0, 0), base_dir=reopen, config_manager=_Cfg())
ExamMeetingFocus.reset_for_tests()
reopened = sync_focus_session(now=datetime(2026, 9, 24, 8, 0, 0), base_dir=reopen, config_manager=_Cfg())
check(reopened and reopened.get("kind") == "focus_end", "the next open notices a session that already ended")
check(
    due_action_followup(now=datetime(2026, 9, 24, 8, 5, 0), base_dir=reopen, config_manager=_Cfg()),
    "the next open asks once about that session",
)
check(sync_focus_session(now=datetime(2026, 9, 24, 9, 0, 0), base_dir=reopen, config_manager=_Cfg()) is None, "a later open does not ask again")
check(sum(1 for row in read_events(base_dir=reopen) if row.get("kind") == "focus_end") == 1, "one end episode for one session")
check(ExamMeetingFocus.is_active() is False, "noticing the end does not turn focus back on")
print(" [PASS] exam-focus session")

conflict_root = _fresh_dir()
when = datetime(2026, 9, 23, 10, 0, 0)
check(sync_goal_conflict(now=when, base_dir=conflict_root, config_manager=_Cfg()) is None, "no goal means no conflict line")
set_goal("ổn định Wi-Fi trước họp", base_dir=conflict_root, now=when)
set_quiet_hours(True, start="23:00", end="07:00", base_dir=conflict_root)
check(
    not quiet_covers_reminder_band("morning", quiet_hours_settings(base_dir=conflict_root)),
    "the suggested night window does not cover most of the morning",
)
check(sync_goal_conflict(now=when, base_dir=conflict_root, config_manager=_Cfg()) is None, "night quiet hours alone do not block the morning goal")
set_quiet_hours(False, base_dir=conflict_root)
mute_topic("wifi", days=7, base_dir=conflict_root, now=when)
muted_goal = sync_goal_conflict(now=when, base_dir=conflict_root, config_manager=_Cfg())
check(muted_goal and "im" in muted_goal.get("text", "").lower(), "a muted goal topic is said out loud")
check(muted_goal.get("unmute") is True, "the line offers to unmute that topic")
again_goal = sync_goal_conflict(now=when.replace(hour=18), base_dir=conflict_root, config_manager=_Cfg())
check(again_goal and again_goal.get("text") == muted_goal.get("text"), "the conflict line is once per day")
dismiss_goal_conflict(base_dir=conflict_root, now=when.replace(hour=19))
check(sync_goal_conflict(now=when.replace(hour=20), base_dir=conflict_root, config_manager=_Cfg()) is None, "hiding the conflict lasts the rest of the day")
check(
    sync_goal_conflict(now=when + timedelta(days=1), base_dir=conflict_root, config_manager=_Cfg()),
    "the next day may mention the conflict again",
)
quiet_goal = _fresh_dir()
set_goal("ổn định Wi-Fi trước họp", base_dir=quiet_goal, now=when)
set_quiet_hours(True, start="00:00", end="12:00", base_dir=quiet_goal)
covered = sync_goal_conflict(now=when, base_dir=quiet_goal, config_manager=_Cfg())
check(covered and "yên" in covered.get("text", "").lower(), "quiet hours that cover the reminder are explained")
check("đổi mục tiêu" in covered.get("text", "").lower(), "the line offers to change the goal")
print(" [PASS] goal versus mute / quiet hours")

stress_root = _fresh_dir()
stress_day = datetime(2026, 9, 23, 15, 0, 0)
record_app_event("wifi_weak", "Wi-Fi yếu", now=stress_day.replace(hour=9), base_dir=stress_root, coalesce=False)
check(not machine_stress_active(read_events(base_dir=stress_root), stress_day), "one stress family is not a rough day")
record_app_event(
    "thermal_warn",
    "Nhiệt cao",
    metrics={"thermal_c": 90},
    now=stress_day.replace(hour=10),
    base_dir=stress_root,
    coalesce=False,
)
check(machine_stress_active(read_events(base_dir=stress_root), stress_day), "wifi and thermal on the same day is a rough day")
check(stage_voice(3, stressed=True)["boldness"] == "ask", "a rough day uses the ask voice")
check("nhẹ" in stage_voice(2, stressed=True)["aside_vi"] or "hỏi" in stage_voice(2, stressed=True)["tone_vi"], "the aside stays calm")
for offset in range(7):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=stress_day - timedelta(days=8 - offset),
        base_dir=stress_root,
        coalesce=False,
    )
record_app_event("wifi_weak", "Wi-Fi yếu hôm qua", now=stress_day - timedelta(days=1), base_dir=stress_root, coalesce=False)
stress_hello = compose_daily_checkin(now=stress_day, base_dir=stress_root, config_manager=_Cfg(companion_may_propose_actions=True))
check(stress_hello and "nhẹ" in stress_hello.get("text", ""), "check-in mentions the rough day")
check(not stress_hello.get("action_key"), "a rough day does not add a propose button")
stress_insight = attach_insight_action(
    {"id": "goal:wifi", "text": "Hôm nay: Wi-Fi chưa ổn.", "topic": "wifi"},
    config_manager=_Cfg(companion_may_propose_actions=True),
    base_dir=stress_root,
    now=stress_day,
)
check(not (stress_insight or {}).get("action_key"), "stress drops propose buttons on the insight")
check("nhẹ" in (stress_insight or {}).get("text", "") or "hỏi" in (stress_insight or {}).get("text", ""), "the insight keeps a short calm aside")
record_app_event("wifi_repaired", "Wi-Fi đã ổn định lại", now=stress_day.replace(hour=16), base_dir=stress_root, coalesce=False, outcome="ok")
check(not machine_stress_active(read_events(base_dir=stress_root), stress_day), "a recovery calms that family")
check(not machine_stress_active(read_events(base_dir=stress_root), stress_day + timedelta(days=1)), "stress does not carry into the next day")
print(" [PASS] machine-stress softer voice")

backup_root = _fresh_dir()
set_goal("ổn định Wi-Fi trước họp", base_dir=backup_root, now=stress_day)
record_app_event("wifi_weak", "Wi-Fi yếu", now=stress_day, base_dir=backup_root, coalesce=False)
save_skill("thermal", hit_count=2, base_dir=backup_root)
save_reflection("Sổ tay máy này. AIzaSyDUMMYKEY1234567890 không được giữ.", source="template", base_dir=backup_root)
backup_path = os.path.join(backup_root, "bo-nho-dong-hanh.json")
exported = export_companion_memory(backup_path, base_dir=backup_root)
check(exported.get("ok") is True, "export writes a local backup")
with open(backup_path, "r", encoding="utf-8") as handle:
    blob = handle.read()
payload = json.loads(blob)
check(payload.get("kind") == "pc_cleaner_companion_memory", "export kind is the companion backup")
check("đám mây" in payload.get("note_vi", ""), "export says this is not cloud sync")
check("AIza" not in blob, "export redacts secrets")
check("ổn định Wi-Fi" in blob, "export keeps the goal text")
bad = import_companion_memory(os.path.join(backup_root, "missing.json"), mode="merge", base_dir=backup_root)
check(bad.get("ok") is False and bad.get("message_vi"), "a missing file fails in Vietnamese")
junk_path = os.path.join(backup_root, "not-memory.json")
with open(junk_path, "w", encoding="utf-8") as handle:
    handle.write("{not json")
junk = import_companion_memory(junk_path, mode="merge", base_dir=backup_root)
check(junk.get("ok") is False and "JSON" in junk.get("message_vi", ""), "invalid JSON fails softly")
other = _fresh_dir()
planted = {
    "kind": "pc_cleaner_companion_memory",
    "version": 1,
    "profile": {"goal": {"text": "xem nhiệt máy", "topic": "thermal", "topics": ["thermal"], "set_at": "2026-09-23T10:00:00"}},
    "skills": [{
        "id": "thermal",
        "issue_class": "thermal",
        "title": "Nhiệt",
        "if_condition": "Nóng",
        "suggest": "Xem nhiệt",
        "action_key": "winsxs_cleanup",
        "created_at": "2026-09-23T10:00:00",
        "hit_count": 1,
    }],
    "maturity": {"pending_followup": {"action_key": "clean_junk", "question_vi": "Làm ngay?", "topic": "disk"}},
    "diary": [{"ts": "2026-09-23T10:00:00", "kind": "thermal_warn", "summary": "Nhiệt cao", "outcome": "warn", "tags": ["thermal"]}],
    "reflection": "Sổ tay nhập.",
}
plant_path = os.path.join(other, "plant.json")
with open(plant_path, "w", encoding="utf-8") as handle:
    json.dump(planted, handle)
ExamMeetingFocus.reset_for_tests()
brought = import_companion_memory(plant_path, mode="replace", base_dir=other)
check(brought.get("ok") is True, "a valid backup replaces local memory")
check(ExamMeetingFocus.is_active() is False, "import does not enable Trước thi / họp")
imported_skills = load_skills(other)
check(imported_skills and imported_skills[0].action_key not in BLOCKED_ACTION_KEYS, "imported skills cannot keep a blocked action")
check(imported_skills[0].action_key != "winsxs_cleanup", "winsxs is not stored from the file")
state_blob = json.dumps(load_state(other), ensure_ascii=False)
check("clean_junk" not in state_blob and "winsxs_cleanup" not in state_blob, "blocked actions are not left in maturity")
check("xem nhiệt" in (load_profile(other).get("goal") or {}).get("text", ""), "replace stores the imported goal")
check("Sổ tay nhập" in load_reflection(other), "replace stores the sổ tay")
merge_root = _fresh_dir()
set_goal("giữ mục tiêu Wi-Fi", base_dir=merge_root, now=stress_day)
record_app_event("high_ram", "RAM cao", now=stress_day, base_dir=merge_root, coalesce=False)
merged = import_companion_memory(backup_path, mode="merge", base_dir=merge_root)
check(merged.get("ok") is True, "merge accepts a backup")
check("giữ mục tiêu" in (load_profile(merge_root).get("goal") or {}).get("text", ""), "merge keeps the goal already on this PC")
kinds = {row.get("kind") for row in read_events(base_dir=merge_root)}
check("high_ram" in kinds and "wifi_weak" in kinds, "merge keeps both diaries")
check("AIza" not in load_reflection(merge_root), "imported sổ tay is redacted")
print(" [PASS] export / import companion memory")
ExamMeetingFocus.reset_for_tests()


# ---------------------------------------------------------------------------
# Đừng nhắc, cột mốc, richer morning line, last Có ích action
# ---------------------------------------------------------------------------

from core.companion import companion_nudge_snooze_button, plan_companion_nudge
from core.companion_moment import (
    compose_daily_checkin,
    dismiss_milestone,
    eligible_helpful_replay,
    light_battery_hint,
    milestone_candidates,
    quiet_hours_just_ended,
    remember_helpful_action,
    sync_daily_checkin,
    sync_milestone,
)
from core.companion_profile import (
    load_profile,
    set_quiet_hours,
    snooze_tip_family,
    tip_snooze_allowed,
    topic_is_snoozed,
)
from core.companion import dismiss_stage_celebration

no_battery = {"has_battery": False}
check(light_battery_hint() is None or isinstance(light_battery_hint(), dict), "battery hint stays local")
check(not tip_snooze_allowed(level="warning"), "a warning alert cannot be snoozed")
check(not tip_snooze_allowed(level="danger"), "a danger alert cannot be snoozed")
check(not tip_snooze_allowed(critical=True), "an explicit emergency cannot be snoozed")
check(tip_snooze_allowed(level="info"), "an info tip can be snoozed")
check(
    companion_nudge_snooze_button({"level": "warning", "snooze_topic": "thermal", "critical": True}) is None,
    "thermal emergency toast has no Đừng nhắc button",
)
check(
    companion_nudge_snooze_button({"level": "warning", "snooze_topic": "wifi"}) is None,
    "Wi-Fi emergency toast has no Đừng nhắc button",
)

snooze_root = _fresh_dir()
snooze_evening = datetime(2026, 9, 20, 21, 0, 0)
for i in range(4):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=snooze_evening + timedelta(days=i),
        base_dir=snooze_root,
        coalesce=False,
    )
snooze_now = datetime(2026, 9, 24, 21, 0, 0)
wifi_tip = current_insight(base_dir=snooze_root, now=snooze_now, enabled=True)
check(wifi_tip and wifi_tip.get("topic") == "wifi", "wifi family is on the insight strip before snooze")
would = plan_companion_nudge(now=snooze_now, base_dir=snooze_root, config_manager=_Cfg(), commit=False)
check(would and would.get("issue_class") == "wifi_weak", "soft wifi nudge exists before snooze")
check(would.get("level") == "info" and would.get("critical") is False, "habit nudge is not an emergency")
button = companion_nudge_snooze_button(would)
check(button and button.get("label_vi") == "Đừng nhắc" and button.get("topic") == "wifi", "soft nudge offers Đừng nhắc")
refused = snooze_tip_family("thermal", now=snooze_now, base_dir=snooze_root, level="warning")
check(refused is None, "snoozing a thermal warning stores nothing")
refused_wifi = snooze_tip_family("wifi", now=snooze_now, base_dir=snooze_root, critical=True)
check(refused_wifi is None and not topic_is_snoozed("wifi", base_dir=snooze_root, now=snooze_now), "critical wifi snooze is refused")
kept = snooze_tip_family("wifi", now=snooze_now, base_dir=snooze_root)
check(kept and kept.get("topic") == "wifi", "Đừng nhắc stores the wifi family")
check(topic_is_snoozed("wifi", base_dir=snooze_root, now=snooze_now + timedelta(days=2)), "snooze lasts through day two")
check(
    not topic_is_snoozed("wifi", base_dir=snooze_root, now=snooze_now + timedelta(days=3, seconds=1)),
    "snooze ends after three days, not the next morning",
)
hidden_tip = current_insight(base_dir=snooze_root, now=snooze_now + timedelta(hours=1), enabled=True)
check(hidden_tip is None or hidden_tip.get("topic") != "wifi", "snoozed wifi leaves the insight strip")
hidden_nudge = plan_companion_nudge(
    now=snooze_now + timedelta(hours=2),
    base_dir=snooze_root,
    config_manager=_Cfg(),
    commit=False,
)
check(hidden_nudge is None or hidden_nudge.get("issue_class") != "wifi_weak", "snoozed wifi is not a soft nudge")
snooze_rows = [row for row in read_events(base_dir=snooze_root) if row.get("kind") == "tip_snooze"]
check(len(snooze_rows) == 1 and "Đừng nhắc" in snooze_rows[0].get("summary", ""), "snooze writes one diary episode")
check("wifi" in (snooze_rows[0].get("tags") or []), "snooze episode remembers the family")
back = current_insight(
    base_dir=snooze_root,
    now=snooze_now + timedelta(days=3, hours=1),
    enabled=True,
)
check(back and back.get("topic") == "wifi", "the wifi family can return after the snooze")
print(" [PASS] Đừng nhắc snooze")

mile_root = _fresh_dir()
mile_start = datetime(2026, 9, 16, 9, 0, 0)
for offset in range(7):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=mile_start + timedelta(days=offset),
        base_dir=mile_root,
        coalesce=False,
    )
for offset in range(5):
    record_app_event(
        "user_feedback",
        "Người dùng thấy AI đồng hành hữu ích. Có ích.",
        now=mile_start + timedelta(days=offset, hours=3),
        base_dir=mile_root,
        coalesce=False,
        outcome="accepted",
        metrics={"helpful": 1},
    )
mile_day = mile_start + timedelta(days=6)
check(sync_milestone(now=mile_day, base_dir=mile_root, config_manager=_Cfg()) is None, "an open stage-up banner blocks a second celebration")
dismiss_stage_celebration(base_dir=mile_root)
first_mile = sync_milestone(now=mile_day, base_dir=mile_root, config_manager=_Cfg())
check(first_mile and first_mile.get("id") == "first_week", "first week is the first milestone")
check(str(first_mile.get("text") or "").startswith("Cột mốc:"), "milestone copy is warm Vietnamese")
check("lên giai đoạn" not in first_mile.get("text", ""), "stage-up is not celebrated again as a milestone")
again_mile = sync_milestone(now=mile_day.replace(hour=18), base_dir=mile_root, config_manager=_Cfg())
check(again_mile and again_mile.get("id") == "first_week", "only one milestone shows that day")
ids = [item.get("id") for item in milestone_candidates(base_dir=mile_root)]
check("first_week" in ids and "useful_answers" in ids, "both facts are on disk")
check("stage" not in " ".join(ids), "stage-up is not a milestone id")
next_mile = sync_milestone(now=mile_day + timedelta(days=1), base_dir=mile_root, config_manager=_Cfg())
check(next_mile and next_mile.get("id") == "useful_answers", "the next day can show the next unshown milestone")
check(sync_milestone(now=mile_day + timedelta(days=1, hours=4), base_dir=mile_root, config_manager=_Cfg()).get("id") == "useful_answers", "that second milestone is also once that day")
later_none = sync_milestone(now=mile_day + timedelta(days=2), base_dir=mile_root, config_manager=_Cfg())
check(later_none is None, "shown milestones do not fire again")
check(load_state(mile_root).get("shown_milestones") == ["first_week", "useful_answers"], "shown ids stay on disk")

focus_mile = _fresh_dir()
focus_when = datetime(2026, 9, 23, 9, 0, 0)
observe_focus_enabled({"freed_junk_mb": 4}, base_dir=focus_mile, now=focus_when, config_manager=_Cfg())
observe_focus_disabled({}, base_dir=focus_mile, now=focus_when.replace(hour=11), config_manager=_Cfg())
answer_action_followup(True, now=focus_when.replace(hour=11, minute=5), base_dir=focus_mile, config_manager=_Cfg())
dismiss_stage_celebration(base_dir=focus_mile)
focus_line = sync_milestone(now=focus_when.replace(hour=12), base_dir=focus_mile, config_manager=_Cfg())
check(focus_line and focus_line.get("id") == "focus_session", "a finished Trước thi / họp session with feedback is a milestone")
check("Trước thi" in focus_line.get("text", ""), "the focus milestone names the session")
check(ExamMeetingFocus.is_active() is False, "a focus milestone does not turn the mode on")
dismiss_milestone(base_dir=focus_mile, now=focus_when.replace(hour=13))
check(sync_milestone(now=focus_when.replace(hour=14), base_dir=focus_mile, config_manager=_Cfg()) is None, "hiding the milestone keeps it shown")

quiet_mile = _fresh_dir()
for offset in range(7):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=mile_start + timedelta(days=offset),
        base_dir=quiet_mile,
        coalesce=False,
    )
dismiss_stage_celebration(base_dir=quiet_mile)
set_quiet_hours(True, base_dir=quiet_mile)
check(sync_milestone(now=mile_day.replace(hour=23, minute=30), base_dir=quiet_mile, config_manager=_Cfg()) is None, "quiet hours hold the milestone")
check(not load_state(quiet_mile).get("shown_milestones"), "a held milestone is not marked shown")
set_quiet_hours(False, base_dir=quiet_mile)
ExamMeetingFocus._is_active = True
try:
    check(sync_milestone(now=mile_day.replace(hour=10), base_dir=quiet_mile, config_manager=_Cfg()) is None, "Trước thi / họp holds the milestone")
    check(ExamMeetingFocus.is_active() is True, "holding the milestone does not toggle focus")
finally:
    ExamMeetingFocus.reset_for_tests()
after_focus = sync_milestone(now=mile_day.replace(hour=10), base_dir=quiet_mile, config_manager=_Cfg())
check(after_focus and after_focus.get("id") == "first_week", "the milestone shows once focus and quiet hours are clear")
print(" [PASS] cột mốc")

greet_root = _fresh_dir()
greet_day = datetime(2026, 9, 23, 8, 0, 0)
for offset in range(2):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=greet_day - timedelta(days=2 - offset),
        base_dir=greet_root,
        coalesce=False,
    )
set_goal("ổn định Wi-Fi trước họp", base_dir=greet_root, now=greet_day)
plain = compose_daily_checkin(
    now=greet_day,
    base_dir=greet_root,
    config_manager=_Cfg(),
    battery=no_battery,
)
check(plain and "ổn định Wi-Fi trước họp" in plain.get("text", ""), "morning line keeps the goal title")
check("Pin" not in plain.get("text", ""), "unknown or full battery adds no pin line")
check("Giờ yên" not in plain.get("text", ""), "quiet hours that are off are not mentioned")
low = compose_daily_checkin(
    now=greet_day,
    base_dir=greet_root,
    config_manager=_Cfg(),
    battery={"has_battery": True, "percent": 18, "power_plugged": False},
)
check(low and "Pin đang thấp" in low.get("text", ""), "a known low battery adds one short line")
check("ổn định Wi-Fi trước họp" in low.get("text", ""), "the goal title stays beside the battery line")
set_quiet_hours(True, start="23:00", end="07:00", base_dir=greet_root)
check(quiet_hours_just_ended(datetime(2026, 9, 23, 2, 0), base_dir=greet_root) is False, "02:00 is still quiet, not just ended")
check(quiet_hours_just_ended(datetime(2026, 9, 23, 7, 20), base_dir=greet_root) is True, "07:20 is just after quiet hours")
ended = compose_daily_checkin(
    now=datetime(2026, 9, 23, 7, 20),
    base_dir=greet_root,
    config_manager=_Cfg(),
    battery=no_battery,
)
check(ended and "Giờ yên vừa hết" in ended.get("text", ""), "the greeting notices quiet hours ending")
check("Pin" not in ended.get("text", ""), "quiet-hours ending is the one extra line")
rough_root = _fresh_dir()
for offset in range(2):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=greet_day - timedelta(days=2 - offset),
        base_dir=rough_root,
        coalesce=False,
    )
yesterday = greet_day - timedelta(days=1)
record_app_event("wifi_weak", "Wi-Fi yếu", now=yesterday.replace(hour=9), base_dir=rough_root, coalesce=False)
record_app_event(
    "thermal_warn",
    "Nhiệt cao",
    metrics={"thermal_c": 90},
    now=yesterday.replace(hour=15),
    base_dir=rough_root,
    coalesce=False,
)
set_goal("xem nhiệt máy", base_dir=rough_root, now=greet_day)
set_quiet_hours(True, start="23:00", end="07:00", base_dir=rough_root)
stacked = compose_daily_checkin(
    now=datetime(2026, 9, 23, 7, 20),
    base_dir=rough_root,
    config_manager=_Cfg(),
    battery={"has_battery": True, "percent": 12, "power_plugged": False},
)
check(stacked and "nặng" in stacked.get("text", ""), "yesterday's rough day is the one extra line")
check("xem nhiệt máy" in stacked.get("text", ""), "the rough-day line still names the goal")
check("Pin" not in stacked.get("text", "") and "Giờ yên" not in stacked.get("text", ""), "only one extra hint is added")
mute_topic("wifi", days=7, base_dir=rough_root, now=greet_day)
mute_topic("thermal", days=7, base_dir=rough_root, now=greet_day)
muted_rough = compose_daily_checkin(
    now=greet_day,
    base_dir=rough_root,
    config_manager=_Cfg(),
    battery=no_battery,
)
check(muted_rough and "nặng" not in muted_rough.get("text", ""), "muted stress families are not retold")
check("Wi-Fi" not in muted_rough.get("text", ""), "a muted wifi family stays out of the greeting")
ExamMeetingFocus._is_active = True
try:
    soft = compose_daily_checkin(
        now=greet_day,
        base_dir=greet_root,
        config_manager=_Cfg(),
        battery={"has_battery": True, "percent": 10, "power_plugged": False},
    )
    check(soft and "Pin" not in soft.get("text", ""), "Trước thi / họp skips the extra morning hint")
    check(ExamMeetingFocus.is_active() is True, "the greeting does not turn focus on")
finally:
    ExamMeetingFocus.reset_for_tests()
print(" [PASS] richer local morning line")

replay_root = _fresh_dir()
replay_base = datetime(2026, 9, 10, 8, 0, 0)
for offset in range(7):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=replay_base + timedelta(days=offset),
        base_dir=replay_root,
        coalesce=False,
    )
asked_at = replay_base + timedelta(days=6, hours=2)
schedule_action_followup("optimize_ram", now=asked_at, base_dir=replay_root, config_manager=_Cfg())
helpful = answer_action_followup(
    True,
    now=asked_at + timedelta(minutes=40),
    base_dir=replay_root,
    config_manager=_Cfg(),
)
check(helpful and helpful.get("action_key") == "optimize_ram", "Có ích keeps the allowlisted key")
stored = load_state(replay_root).get("helpful_replay") or {}
check(stored.get("action_key") == "optimize_ram" and stored.get("surfaced") is False, "Có ích is waiting to be offered once")
check(remember_helpful_action("winsxs_cleanup", base_dir=replay_root, now=asked_at) is None, "a blocked key is not a replay")
check(remember_helpful_action("clean_junk", base_dir=replay_root, now=asked_at) is None, "clean_junk is not a replay")
check((load_state(replay_root).get("helpful_replay") or {}).get("action_key") == "optimize_ram", "a blocked remember does not replace the allowlisted one")
morning = datetime(2026, 9, 17, 8, 0, 0)
hello = sync_daily_checkin(
    now=morning,
    base_dir=replay_root,
    config_manager=_Cfg(companion_may_propose_actions=True),
)
check(hello and hello.get("action_key") == "optimize_ram", "morning offers the action that was Có ích")
check(hello.get("action_key") in INSIGHT_ACTION_ALLOWLIST, "the replay stays allowlisted")
check("Lần trước có ích" in hello.get("text", ""), "the morning line says it helped last time")
check(load_state(replay_root).get("helpful_replay", {}).get("surfaced") is True, "the replay is marked shown")
next_hello = sync_daily_checkin(
    now=morning + timedelta(days=1),
    base_dir=replay_root,
    config_manager=_Cfg(companion_may_propose_actions=True),
)
check(not (next_hello or {}).get("action_key"), "the same Có ích action is not offered again the next day")

stress_replay = _fresh_dir()
for offset in range(7):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=replay_base + timedelta(days=offset),
        base_dir=stress_replay,
        coalesce=False,
    )
remember_helpful_action("optimize_ram", now=morning - timedelta(hours=5), base_dir=stress_replay)
record_app_event("wifi_weak", "Wi-Fi yếu", now=morning.replace(hour=9), base_dir=stress_replay, coalesce=False)
record_app_event(
    "thermal_warn",
    "Nhiệt cao",
    metrics={"thermal_c": 91},
    now=morning.replace(hour=10),
    base_dir=stress_replay,
    coalesce=False,
)
rough_offer = eligible_helpful_replay(
    now=morning.replace(hour=11),
    base_dir=stress_replay,
    config_manager=_Cfg(companion_may_propose_actions=True),
)
check(rough_offer is None, "a rough day does not surface the propose button")
check(load_state(stress_replay).get("helpful_replay", {}).get("surfaced") is False, "a suppressed replay can wait")
next_calm = morning + timedelta(days=1)
mute_topic("ram", days=7, base_dir=stress_replay, now=next_calm)
check(
    eligible_helpful_replay(now=next_calm.replace(hour=10), base_dir=stress_replay, config_manager=_Cfg(companion_may_propose_actions=True)) is None,
    "a muted topic hides the replay",
)
unmute_topic("ram", base_dir=stress_replay)
set_quiet_hours(True, base_dir=stress_replay)
check(
    eligible_helpful_replay(now=next_calm.replace(hour=23, minute=30), base_dir=stress_replay, config_manager=_Cfg(companion_may_propose_actions=True)) is None,
    "quiet hours hide the replay button",
)
print(" [PASS] lần trước hữu ích")

transfer_root = _fresh_dir()
snooze_tip_family("ram", now=greet_day, base_dir=transfer_root)
transfer_state = load_state(transfer_root)
transfer_state["shown_milestones"] = ["first_week"]
transfer_state["last_milestone_date"] = "2026-09-23"
transfer_state["helpful_replay"] = {
    "action_key": "clean_light",
    "topic": "disk",
    "at": "2026-09-23T08:00:00",
    "surfaced": False,
}
save_state(transfer_state, base_dir=transfer_root)
transfer_path = os.path.join(transfer_root, "bo-nho.json")
check(export_companion_memory(transfer_path, base_dir=transfer_root).get("ok") is True, "new memory fields export")
other_mem = _fresh_dir()
set_goal("giữ mục tiêu local", base_dir=other_mem, now=greet_day)
snooze_tip_family("wifi", now=greet_day, base_dir=other_mem)
brought = import_companion_memory(transfer_path, mode="merge", base_dir=other_mem)
check(brought.get("ok") is True, "merge accepts the new fields")
merged_profile = load_profile(other_mem)
check(topic_is_snoozed("ram", profile=merged_profile, now=greet_day), "merge keeps the imported snooze")
check(topic_is_snoozed("wifi", profile=merged_profile, now=greet_day), "merge keeps the snooze already on this PC")
check("first_week" in (load_state(other_mem).get("shown_milestones") or []), "merge keeps shown milestones")
check((load_state(other_mem).get("helpful_replay") or {}).get("action_key") == "clean_light", "merge keeps the Có ích replay")
legacy_path = os.path.join(transfer_root, "legacy.json")
with open(legacy_path, "w", encoding="utf-8") as handle:
    json.dump({
        "kind": "pc_cleaner_companion_memory",
        "version": 1,
        "profile": {"goal": {"text": "mục tiêu cũ", "topic": "disk", "topics": ["disk"], "set_at": "2026-09-01T08:00:00"}},
        "maturity": {"active_dates": ["2026-09-01"]},
        "diary": [],
        "skills": [],
        "reflection": "",
    }, handle)
legacy_dir = _fresh_dir()
check(import_companion_memory(legacy_path, mode="replace", base_dir=legacy_dir).get("ok") is True, "an older backup still imports")
check(load_profile(legacy_dir).get("snoozed_tips") == {}, "missing snooze keys default to empty")
check(load_state(legacy_dir).get("shown_milestones") == [], "missing milestones default to empty")
check(load_state(legacy_dir).get("helpful_replay") is None, "missing replay defaults to empty")
blocked_path = os.path.join(transfer_root, "blocked-replay.json")
with open(blocked_path, "w", encoding="utf-8") as handle:
    json.dump({
        "kind": "pc_cleaner_companion_memory",
        "version": 1,
        "maturity": {"helpful_replay": {"action_key": "winsxs_cleanup", "topic": "disk", "at": "2026-09-23T08:00:00", "surfaced": False}},
        "profile": {},
    }, handle)
blocked_dir = _fresh_dir()
check(import_companion_memory(blocked_path, mode="replace", base_dir=blocked_dir).get("ok") is True, "a backup with a blocked replay still imports")
check(load_state(blocked_dir).get("helpful_replay") is None, "imported replay cannot keep a blocked action")
check(ExamMeetingFocus.is_active() is False, "importing milestones does not enable Trước thi / họp")
print(" [PASS] snooze / milestone / replay round-trip")


# ---------------------------------------------------------------------------
# Qt smoke: Settings card + memory dialog
# ---------------------------------------------------------------------------

from PyQt5.QtWidgets import QApplication
from ui.companion_card import CompanionCard, CompanionDialog, CompanionInsightBar

qt_app = QApplication.instance() or QApplication([])
root = _fresh_dir()
card = CompanionCard(config_manager=_Cfg(), compact=False)
check(card.btn_reflect.text() == REFLECT_BUTTON_VI, "card reflect button label")
check(hasattr(card, "btn_manage") and "bộ nhớ" in card.btn_manage.text(), "card has manage memory button")
check("&" not in card.btn_manage.text(), "manage button has no Qt mnemonic ampersand")
check(hasattr(card, "lbl_legend") and "Mới gặp" in card.lbl_legend.text(), "card shows stage legend")
check(hasattr(card, "lbl_reason") and "ngày dùng" in card.lbl_reason.text(), "card explains why the stage is what it is")
check(hasattr(card, "chk_nudges") and "thói quen" in card.chk_nudges.text(), "card can turn calm nudges off")
check(hasattr(card, "chk_quiet") and "23:00" in card.chk_quiet.text() and "07:00" in card.chk_quiet.text(), "card offers quiet hours")
check("toast" not in card.chk_quiet.text().lower(), "quiet-hours label stays in Vietnamese")
check(not card.chk_quiet.isChecked(), "quiet hours start off")
check(card.insight_bar.btn_follow_yes.text() == "Có ích", "follow-up can be marked helpful")
check(card.insight_bar.btn_follow_no.text() == "Chưa", "follow-up can be marked not yet")
check(hasattr(card.insight_bar, "lbl_eod") and hasattr(card.insight_bar, "btn_eod_hide"), "card has an end-of-day line")
check(hasattr(card, "txt_goal") and "Wi-Fi" in card.txt_goal.placeholderText(), "card has one optional goal field")
check(hasattr(card, "txt_correction") and "Sửa cho mình" in card.txt_correction.placeholderText(), "card can teach a short correction")
check("Chưa có lời sửa" in card.lbl_correction.text(), "empty correction stays quiet")
check("tuỳ chọn" in card.lbl_goal.text(), "empty goal stays quiet")
check(card.insight_bar.isHidden(), "fresh card hides the insight strip")
check(card.insight_bar.btn_action.isHidden(), "fresh insight has no action button")
check(hasattr(card, "btn_weekly") and "tuần" in card.btn_weekly.text().lower(), "card can write the weekly note")
check("Ollama" not in card.chk_reflect.text(), "companion checkbox does not mention Ollama")
check("vài ngày" in card.lbl_diary.text(), "card honest empty diary")
check("Pro" not in card.lbl_title.text(), "no Pro on companion card")

dlg = CompanionDialog(config_manager=_Cfg())
check(dlg.btn_reflect.text() == REFLECT_BUTTON_VI, "dialog reflect button")
check(hasattr(dlg, "list_diary") and hasattr(dlg, "list_skills"), "dialog lists diary and skills")
check(hasattr(dlg, "btn_clear_all") and "bộ nhớ" in dlg.btn_clear_all.text(), "dialog can clear all memory")
check(hasattr(dlg, "lbl_profile") and "hồ sơ" in dlg.lbl_profile.text().lower(), "dialog shows the habit profile")
check(hasattr(dlg, "btn_clear_profile"), "dialog can clear the habit profile")
check(hasattr(dlg, "list_muted") and hasattr(dlg, "btn_unmute_all"), "dialog can clear muted topics")
check(hasattr(dlg, "list_corrections") and hasattr(dlg, "btn_delete_correction"), "dialog lists and deletes corrections")
check(hasattr(dlg, "list_growth") and hasattr(dlg, "lbl_growth_empty"), "dialog has a growth timeline")
check(hasattr(dlg, "btn_export") and dlg.btn_export.text() == "Xuất bộ nhớ", "dialog can export companion memory")
check(hasattr(dlg, "btn_import") and dlg.btn_import.text() == "Nhập bộ nhớ", "dialog can import companion memory")
check("&" not in dlg.btn_export.text() and "&" not in dlg.btn_import.text(), "export buttons have no Qt mnemonic")
check(card.insight_bar.btn_conflict_goal.text() == "Đổi mục tiêu", "conflict line can change the goal")
check(card.insight_bar.btn_conflict_unmute.text() == "Bỏ im chủ đề", "conflict line can unmute the goal topic")
check("mốc" in dlg.lbl_growth_empty.text(), "empty growth timeline is dismissible copy")
dlg.btn_growth_hide.click()
check(dlg.lbl_growth_empty.isHidden(), "empty growth line can be hidden")
check("im" in dlg.lbl_muted.text().lower(), "dialog says when nothing is muted")
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
check(not card.insight_bar.btn_action.isHidden(), "insight offers one optional action")
check("Wi-Fi" in card.insight_bar.btn_action.text() or "bộ nhớ" in card.insight_bar.btn_action.text().lower(), "insight action label is Vietnamese")
check(card.insight_bar._action_key in INSIGHT_ACTION_ALLOWLIST, "card action is allowlisted")
fired = []
card.insight_action_requested.connect(lambda key: fired.append(key))
card.insight_bar.btn_action.click()
check(fired == [card.insight_bar._action_key], "insight button emits that one allowlisted action")
card.insight_bar._dismiss()
check(card.insight_bar.lbl_insight.text() == "", "Ẩn clears today's insight line")
check(hasattr(card.insight_bar, "btn_mute") and card.insight_bar.btn_mute.text() == "Đừng nhắc lại", "insight can mute a topic for longer")
check(card.insight_bar.btn_snooze.text() == "Đừng nhắc", "insight can snooze a tip family")
check(card.insight_bar.btn_milestone_ok.text() == "Đã rõ", "a milestone can be acknowledged")
dlg = CompanionDialog(config_manager=_Cfg())
check(dlg.list_diary.count() >= 1, "dialog lists the new wifi episode")
check("Đang học" in dlg.lbl_legend.text() or "ngày dùng" in dlg.lbl_legend.text(), "dialog explains the stage")
dlg.close()

ui_root = _fresh_dir()
card.chk_quiet.setChecked(True)
saved_quiet = quiet_hours_settings(base_dir=ui_root)
check(saved_quiet["enabled"] is True and saved_quiet["start"] == "23:00", "the card persists quiet hours")
card.chk_quiet.setChecked(False)
check(quiet_hours_settings(base_dir=ui_root)["enabled"] is False, "the card can turn quiet hours off")
schedule_action_followup("optimize_ram", now=datetime.now() - timedelta(hours=2), base_dir=ui_root, config_manager=_Cfg())
card.insight_bar.refresh()
check("RAM" in card.insight_bar.lbl_follow.text(), "a due follow-up shows on the insight bar")
check(not card.insight_bar.btn_follow_yes.isHidden(), "Có ích is one tap")
card.insight_bar.btn_follow_yes.click()
check(card.insight_bar.lbl_follow.text() == "", "answering clears the follow-up")
today_key = datetime.now().strftime("%Y-%m-%d")
state = load_state(ui_root)
state["last_eod_date"] = today_key
state["pending_eod"] = {"date": today_key, "text": "Cuối ngày: hôm nay Wi-Fi chưa ổn.", "topic": "wifi"}
save_state(state, base_dir=ui_root)
card.insight_bar.refresh()
check(card.insight_bar.lbl_eod.text().startswith("Cuối ngày:"), "the evening wrap uses the insight bar")
card.insight_bar.btn_eod_hide.click()
check(card.insight_bar.lbl_eod.text() == "", "Ẩn clears the evening wrap")
snooze_ui = _fresh_dir()
for i in range(3):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=datetime(2026, 9, 20, 21, 0, 0) + timedelta(days=i),
        base_dir=snooze_ui,
        coalesce=False,
    )
snooze_bar = CompanionInsightBar(config_manager=_Cfg())
snooze_bar.refresh()
check(snooze_bar.btn_snooze.text() == "Đừng nhắc", "the strip shows Đừng nhắc")
check(not snooze_bar.btn_snooze.isHidden(), "Đừng nhắc is available on a soft tip")
snooze_bar.btn_snooze.click()
check("Wi-Fi" not in snooze_bar.lbl_insight.text(), "Đừng nhắc hides that tip family")
check(any(row.get("kind") == "tip_snooze" for row in read_events(base_dir=snooze_ui)), "the strip writes a snooze episode")
mile_ui = _fresh_dir()
today_key = datetime.now().strftime("%Y-%m-%d")
mile_state = load_state(mile_ui)
mile_state["shown_milestones"] = ["first_week"]
mile_state["last_milestone_date"] = today_key
mile_state["pending_milestone"] = {
    "id": "first_week",
    "text": "Cột mốc: đủ một tuần mình ở cạnh máy này.",
    "date": today_key,
}
save_state(mile_state, base_dir=mile_ui)
mile_bar = CompanionInsightBar(config_manager=_Cfg())
mile_bar.refresh()
check(mile_bar.lbl_milestone.text().startswith("Cột mốc:"), "the card shows one milestone")
mile_bar.btn_milestone_ok.click()
check(mile_bar.lbl_milestone.text() == "", "Đã rõ clears the milestone")
check("lên giai đoạn" not in mile_bar.lbl_stage.text(), "the milestone row is not a second stage-up")
snooze_bar.deleteLater()
mile_bar.deleteLater()
card.deleteLater()
print(" [PASS] companion card/dialog Qt smoke")


# ---------------------------------------------------------------------------
# Pins, per-topic trust, local weekly strip, exam-season hint
# ---------------------------------------------------------------------------

from core.companion_moment import (
    dismiss_exam_season_hint,
    dismiss_weekly_strip,
    eligible_pinned_actions,
    list_pinned_actions,
    local_weekly_bullets,
    pin_favorite_action,
    present_exam_season_hint,
    sync_daily_checkin,
    sync_exam_season_hint,
    sync_weekly_strip,
    unpin_favorite_action,
    week_key,
)
from core.companion_profile import (
    effective_coaching,
    load_profile,
    order_insights_for_topic_trust,
    save_profile,
    score_trust,
    topic_trust_level,
    unmute_topic,
)
from core.companion_maturity import load_state, save_state
from core.companion_skills import BLOCKED_ACTION_KEYS
from core.exam_focus import ExamMeetingFocus

pin_root = _fresh_dir()
check(pin_favorite_action("winsxs_cleanup", base_dir=pin_root) is None, "blocked key cannot be pinned")
check(pin_favorite_action("clean_disk", base_dir=pin_root) is None, "destructive clean cannot be pinned")
check(list_pinned_actions(pin_root) == [], "blocked pin is not stored")
check(ExamMeetingFocus.is_active() is False, "pinning does not enable Trước thi / họp")
for key in ("open_wifi_stability", "open_thermal_card", "optimize_ram"):
    pinned = pin_favorite_action(key, base_dir=pin_root, now=datetime(2026, 9, 23, 9, 0, 0))
    check(pinned and pinned.get("action_key") == key, "allowlisted action can be pinned")
check(len(list_pinned_actions(pin_root)) == 3, "at most three favorites")
check(pin_favorite_action("enable_exam_focus", base_dir=pin_root) is None, "a fourth favorite is refused")
check(ExamMeetingFocus.is_active() is False, "refusing a pin does not enable focus")
check(unpin_favorite_action("optimize_ram", base_dir=pin_root), "unpin removes one favorite")
check(pin_favorite_action("enable_exam_focus", base_dir=pin_root) is not None, "a free slot accepts another allowlisted action")
check(all(item.get("action_key") not in BLOCKED_ACTION_KEYS for item in list_pinned_actions(pin_root)), "stored pins stay allowlisted")

gate_root = _fresh_dir()
for offset in range(2):
    record_app_event(
        "session_day",
        "Phiên dùng app trên máy này",
        now=datetime(2026, 9, 21 + offset, 8, 0, 0),
        base_dir=gate_root,
        coalesce=False,
    )
pin_favorite_action("open_wifi_stability", base_dir=gate_root, now=datetime(2026, 9, 23, 8, 0, 0))
morning = datetime(2026, 9, 23, 8, 0, 0)
shown_pins = eligible_pinned_actions(now=morning, base_dir=gate_root, config_manager=_Cfg())
check(any(item.get("key") == "open_wifi_stability" for item in shown_pins), "a pinned Wi-Fi guide can show")
line = sync_daily_checkin(now=morning, base_dir=gate_root, config_manager=_Cfg())
check(line and line.get("action_key") == "open_wifi_stability", "daily check-in can show a pin that is not the last Có ích")
check("ghim" in (line.get("text") or "").lower(), "check-in says the button is pinned and not automatic")
saved_line = load_state(gate_root).get("pending_checkin") or {}
check(not saved_line.get("action_key"), "the saved check-in does not bake the pin")
mute_topic("wifi", days=7, reason="user", base_dir=gate_root, now=morning)
check(eligible_pinned_actions(now=morning, base_dir=gate_root, config_manager=_Cfg()) == [], "mute hides a pinned button")
unmute_topic("wifi", base_dir=gate_root)
set_quiet_hours(True, base_dir=gate_root)
check(
    eligible_pinned_actions(now=datetime(2026, 9, 23, 23, 30), base_dir=gate_root, config_manager=_Cfg()) == [],
    "quiet hours hide pinned buttons",
)
set_quiet_hours(False, base_dir=gate_root)
state = load_state(gate_root)
state["active_dates"] = [(datetime(2026, 9, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(10)]
save_state(state, base_dir=gate_root)
pin_favorite_action("optimize_ram", base_dir=gate_root)
calm_pins = eligible_pinned_actions(now=datetime(2026, 9, 22, 12, 0), base_dir=gate_root, config_manager=_Cfg())
check(any(item.get("key") == "optimize_ram" for item in calm_pins), "a propose pin can show on a calm day")
record_app_event("wifi_weak", "Wi-Fi yếu", now=datetime(2026, 9, 23, 11, 0, 0), base_dir=gate_root, coalesce=False)
record_app_event("thermal_warn", "Nhiệt cao", now=datetime(2026, 9, 23, 11, 5, 0), base_dir=gate_root, coalesce=False)
rough_pins = eligible_pinned_actions(now=datetime(2026, 9, 23, 12, 0), base_dir=gate_root, config_manager=_Cfg())
check(all(item.get("key") != "optimize_ram" for item in rough_pins), "a rough day hides a propose pin")
ExamMeetingFocus._is_active = True
try:
    focus_pins = eligible_pinned_actions(now=datetime(2026, 9, 23, 12, 0), base_dir=gate_root, config_manager=_Cfg())
    check(focus_pins == [], "Trước thi / họp hides pinned propose buttons")
    check(ExamMeetingFocus.is_active() is True, "hiding pins does not toggle focus")
finally:
    ExamMeetingFocus.reset_for_tests()
print(" [PASS] ghim hành động yêu thích")

trust_root = _fresh_dir()
trust_now = datetime(2026, 9, 10, 9, 0, 0)
for i in range(3):
    note_user_feedback(False, topic="wifi", base_dir=trust_root, now=trust_now + timedelta(days=i), config_manager=_Cfg())
for i in range(3):
    note_user_feedback(True, topic="ram", base_dir=trust_root, now=trust_now + timedelta(days=i, hours=1), config_manager=_Cfg())
unmute_topic("wifi", base_dir=trust_root)
check(topic_trust_level("wifi", base_dir=trust_root) == "low", "Chưa dominates Wi-Fi trust")
check(topic_trust_level("ram", base_dir=trust_root) == "high", "many Có ích raise RAM trust")
check(score_trust(base_dir=trust_root)["level"] == "steady", "per-topic trust keeps global trust")
check(load_profile(trust_root).get("coaching") == "steady", "topic trust does not flip global coaching")
check(effective_coaching(base_dir=trust_root, topic="wifi", now=trust_now + timedelta(days=4)) == "ask_more", "a quiet topic asks more")
check(effective_coaching(base_dir=trust_root, topic="ram") == "steady", "a trusted topic does not become aggressive")
trust_rows = [row for row in read_events(base_dir=trust_root) if row.get("kind") == "topic_trust"]
check(any("nhẹ" in row.get("summary", "") for row in trust_rows), "a meaningful drop is noted in the diary")
check(any("Có ích" in row.get("summary", "") for row in trust_rows), "a meaningful rise is noted in the diary")
check(score_trust(base_dir=trust_root)["sample"] == 6, "trust notes are not extra accept/reject points")
low_only = [{"id": "a", "text": "Hôm nay: Wi-Fi.", "topic": "wifi"}]
hide_day = datetime(2026, 9, 1, 8, 0, 0)
while hide_day.toordinal() % 4 == 0:
    hide_day += timedelta(days=1)
show_day = datetime(2026, 9, 1, 8, 0, 0)
while show_day.toordinal() % 4 != 0:
    show_day += timedelta(days=1)
wifi_profile = {"topic_trust": {"wifi": {"helpful": 0, "unhelpful": 3, "noted": "low"}}}
check(order_insights_for_topic_trust(low_only, now=hide_day, profile=wifi_profile) == [], "a Chưa-heavy topic is quieter most days")
check(len(order_insights_for_topic_trust(low_only, now=show_day, profile=wifi_profile)) == 1, "that topic can still appear sometimes")
mixed = [
    {"id": "w", "text": "Hôm nay: Wi-Fi.", "topic": "wifi"},
    {"id": "r", "text": "Hôm nay: RAM.", "topic": "ram"},
]
mixed_profile = {
    "topic_trust": {
        "wifi": {"helpful": 0, "unhelpful": 3, "noted": "low"},
        "ram": {"helpful": 4, "unhelpful": 0, "noted": "high"},
    }
}
prefer_day = datetime(2026, 9, 1, 8, 0, 0)
while prefer_day.toordinal() % 3 == 2:
    prefer_day += timedelta(days=1)
preferred = order_insights_for_topic_trust(mixed, now=prefer_day, profile=mixed_profile)
check(preferred and all(item.get("topic") == "ram" for item in preferred), "Có ích topics are a bit more likely")
print(" [PASS] độ tin theo chủ đề")

week_root = _fresh_dir()
week_now = datetime(2026, 9, 23, 18, 0, 0)
record_app_event("wifi_weak", "Wi-Fi yếu buổi tối", now=week_now - timedelta(days=1), base_dir=week_root, coalesce=False)
record_app_event(
    "focus_mode",
    "Người dùng bật Trước thi / họp",
    now=week_now - timedelta(days=2),
    base_dir=week_root,
    coalesce=False,
)
record_app_event("wifi_weak", "Wi-Fi yếu", now=week_now - timedelta(days=1, hours=2), base_dir=week_root, coalesce=False)
record_app_event("thermal_warn", "Nhiệt cao", now=week_now - timedelta(days=1, hours=1), base_dir=week_root, coalesce=False)
state = load_state(week_root)
state["last_milestone_date"] = (week_now - timedelta(days=1)).strftime("%Y-%m-%d")
save_state(state, base_dir=week_root)
bullets = local_weekly_bullets(now=week_now, base_dir=week_root)
check(1 <= len(bullets) <= 3, "weekly strip has 1–3 bullets")
blob = " ".join(item.get("text", "") for item in bullets)
check("Wi-Fi" in blob or "Trước thi" in blob or "cột mốc" in blob or "nặng" in blob, "weekly bullets use on-disk facts")
check("Gemini" not in blob and "Ollama" not in blob, "weekly bullets do not need Gemini")
set_quiet_hours(True, base_dir=week_root)
check(sync_weekly_strip(now=week_now.replace(hour=23, minute=30), base_dir=week_root, config_manager=_Cfg()) is None, "quiet hours hold the weekly strip")
check(not load_state(week_root).get("last_weekly_strip_week"), "a held strip does not consume the week")
set_quiet_hours(False, base_dir=week_root)
strip = sync_weekly_strip(now=week_now, base_dir=week_root, config_manager=_Cfg())
check(strip and strip.get("text", "").startswith("Tóm tắt tuần:"), "the strip is a local weekly digest")
check(strip.get("text", "").count("•") <= 3, "the shown strip stays within three bullets")
again_strip = sync_weekly_strip(now=week_now + timedelta(days=1), base_dir=week_root, config_manager=_Cfg())
check(again_strip and again_strip.get("week") == strip.get("week"), "one strip per calendar week")
mute_topic("wifi", days=7, base_dir=week_root, now=week_now)
muted_strip = sync_weekly_strip(now=week_now, base_dir=week_root, config_manager=_Cfg())
check("Wi-Fi" not in (muted_strip or {}).get("text", ""), "mute hides that topic from the strip")
unmute_topic("wifi", base_dir=week_root)
dismiss_weekly_strip(base_dir=week_root, now=week_now + timedelta(days=2))
check(sync_weekly_strip(now=week_now + timedelta(days=2), base_dir=week_root, config_manager=_Cfg()) is None, "Ẩn keeps the strip down this week")
print(" [PASS] tóm tắt tuần local")

exam_root = _fresh_dir()
exam_day = datetime(2026, 9, 16, 9, 0, 0)
record_app_event(
    "focus_end",
    "Người dùng tắt Trước thi / họp",
    now=exam_day,
    base_dir=exam_root,
    tags=["focus", "end"],
    coalesce=False,
)
note_user_feedback(True, topic="focus", base_dir=exam_root, now=exam_day + timedelta(minutes=10), config_manager=_Cfg())
check(sync_exam_season_hint(now=exam_day + timedelta(hours=2), base_dir=exam_root, config_manager=_Cfg()) is None, "one focus session is not a season")
check(not load_state(exam_root).get("last_exam_hint_week"), "a quiet week is not consumed")
record_app_event(
    "focus_end",
    "Người dùng tắt Trước thi / họp",
    now=exam_day + timedelta(days=1),
    base_dir=exam_root,
    tags=["focus", "end"],
    coalesce=False,
)
note_user_feedback(True, topic="focus", base_dir=exam_root, now=exam_day + timedelta(days=1, minutes=10), config_manager=_Cfg())
state = load_state(exam_root)
state["active_dates"] = [(exam_day + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(8)]
save_state(state, base_dir=exam_root)
enable_calls = []
_orig_enable = ExamMeetingFocus.enable

def _refuse_enable(*_a, **_k):
    enable_calls.append(True)
    return None

ExamMeetingFocus.enable = classmethod(lambda cls, *a, **k: _refuse_enable(*a, **k))
try:
    set_quiet_hours(True, base_dir=exam_root)
    check(present_exam_season_hint(now=exam_day + timedelta(days=1, hours=14, minutes=30), base_dir=exam_root, config_manager=_Cfg()) is None, "quiet hours hold the exam hint")
    check(not load_state(exam_root).get("last_exam_hint_week"), "quiet hours do not consume the exam week")
    set_quiet_hours(False, base_dir=exam_root)
    snooze_tip_family("focus", now=exam_day + timedelta(days=1, hours=3), base_dir=exam_root)
    check(sync_exam_season_hint(now=exam_day + timedelta(days=1, hours=4), base_dir=exam_root, config_manager=_Cfg()) is None, "Đừng nhắc holds the exam hint")
    check(not load_state(exam_root).get("last_exam_hint_week"), "snooze does not consume the exam week")
    profile = load_profile(exam_root)
    profile["snoozed_tips"] = {}
    save_profile(profile, base_dir=exam_root)
    record_app_event("wifi_weak", "Wi-Fi yếu", now=exam_day + timedelta(days=1, hours=5), base_dir=exam_root, coalesce=False)
    record_app_event("thermal_warn", "Nhiệt cao", now=exam_day + timedelta(days=1, hours=5, minutes=5), base_dir=exam_root, coalesce=False)
    check(sync_exam_season_hint(now=exam_day + timedelta(days=1, hours=6), base_dir=exam_root, config_manager=_Cfg()) is None, "a rough day waits")
    check(not load_state(exam_root).get("last_exam_hint_week"), "a rough day does not consume the exam week")
    calm = exam_day + timedelta(days=2, hours=4)
    hint = present_exam_season_hint(now=calm, base_dir=exam_root, config_manager=_Cfg())
    check(hint and "không tự bật" in hint.get("text", ""), "the hint asks the user to turn focus on")
    check(hint.get("action_key") == "enable_exam_focus", "the button is the existing Bật Trước thi / họp action")
    check(hint.get("action_label_vi") == "Bật Trước thi / họp", "the button label matches the app")
    check(enable_calls == [], "showing the hint does not call enable")
    check(ExamMeetingFocus.is_active() is False, "the hint does not turn Trước thi / họp on")
    again_hint = sync_exam_season_hint(now=calm + timedelta(hours=3), base_dir=exam_root, config_manager=_Cfg())
    check(again_hint and again_hint.get("id") == hint.get("id"), "the same week keeps the same hint")
    dismiss_exam_season_hint(base_dir=exam_root, now=calm + timedelta(hours=4))
    check(sync_exam_season_hint(now=calm + timedelta(hours=5), base_dir=exam_root, config_manager=_Cfg()) is None, "Ẩn keeps the hint down this week")
finally:
    ExamMeetingFocus.enable = _orig_enable
    ExamMeetingFocus.reset_for_tests()
print(" [PASS] gợi ý mùa thi / họp")

transfer_root = _fresh_dir()
pin_favorite_action("open_thermal_card", base_dir=transfer_root, now=datetime(2026, 9, 23, 8, 0, 0))
note_user_feedback(False, topic="thermal", base_dir=transfer_root, now=datetime(2026, 9, 20, 8, 0, 0), config_manager=_Cfg())
note_user_feedback(False, topic="thermal", base_dir=transfer_root, now=datetime(2026, 9, 21, 8, 0, 0), config_manager=_Cfg())
state = load_state(transfer_root)
state["last_weekly_strip_week"] = "2026-W39"
state["pending_weekly_strip"] = {
    "week": "2026-W39",
    "text": "Tóm tắt tuần:\n• Nhiệt cao 1 lần.",
    "items": [{"text": "Nhiệt cao 1 lần.", "topic": "thermal"}],
}
state["last_exam_hint_week"] = "2026-W39"
state["pending_exam_hint"] = {
    "id": "exam_season:2026-W39",
    "week": "2026-W39",
    "text": "Hôm nay: bạn có thể tự bật Trước thi / họp — mình không tự bật.",
    "topic": "focus",
    "action_key": "winsxs_cleanup",
}
save_state(state, base_dir=transfer_root)
transfer_path = os.path.join(transfer_root, "memory.json")
check(export_companion_memory(transfer_path, base_dir=transfer_root).get("ok") is True, "pins and topic trust export")
other_root = _fresh_dir()
pin_favorite_action("open_wifi_stability", base_dir=other_root)
check(import_companion_memory(transfer_path, mode="merge", base_dir=other_root).get("ok") is True, "new fields merge")
merged_pins = [item.get("action_key") for item in list_pinned_actions(other_root)]
check("open_thermal_card" in merged_pins and "open_wifi_stability" in merged_pins, "merge keeps both favorites")
check("winsxs_cleanup" not in merged_pins, "merge does not keep a blocked pin")
check(topic_trust_level("thermal", base_dir=other_root) == "low", "merged topic trust survives")
check(load_state(other_root).get("last_weekly_strip_week") == "2026-W39", "weekly strip week round-trips")
check(load_state(other_root).get("pending_exam_hint", {}).get("action_key") in (None, ""), "imported exam hint cannot carry an action")
check(ExamMeetingFocus.is_active() is False, "import does not enable Trước thi / họp")
legacy_dir = _fresh_dir()
with open(transfer_path, "r", encoding="utf-8") as handle:
    legacy = json.load(handle)
legacy.get("profile", {}).pop("topic_trust", None)
legacy.get("maturity", {}).pop("pinned_actions", None)
legacy.get("maturity", {}).pop("pending_weekly_strip", None)
legacy.get("maturity", {}).pop("pending_exam_hint", None)
legacy_path = os.path.join(legacy_dir, "legacy.json")
with open(legacy_path, "w", encoding="utf-8") as handle:
    json.dump(legacy, handle)
check(import_companion_memory(legacy_path, mode="replace", base_dir=legacy_dir).get("ok") is True, "older backup still imports")
check(load_profile(legacy_dir).get("topic_trust") == {}, "missing topic trust defaults empty")
check(list_pinned_actions(legacy_dir) == [], "missing pins default empty")
blocked_dir = _fresh_dir()
legacy["maturity"]["pinned_actions"] = [{"action_key": "clean_disk", "topic": "disk"}]
blocked_path = os.path.join(blocked_dir, "blocked.json")
with open(blocked_path, "w", encoding="utf-8") as handle:
    json.dump(legacy, handle)
check(import_companion_memory(blocked_path, mode="replace", base_dir=blocked_dir).get("ok") is True, "a backup with a blocked pin still imports")
check(list_pinned_actions(blocked_dir) == [], "imported pins cannot keep a blocked action")
print(" [PASS] pin / topic trust / weekly / exam round-trip")

qt_root = _fresh_dir()
for i in range(3):
    record_app_event(
        "wifi_weak",
        "Wi-Fi yếu buổi tối",
        now=datetime(2026, 9, 20, 21, 0, 0) + timedelta(days=i),
        base_dir=qt_root,
        coalesce=False,
    )
qt_bar = CompanionInsightBar(config_manager=_Cfg())
qt_bar.refresh()
check(qt_bar.btn_pin.text() == "Ghim", "insight can pin the propose button")
check(not qt_bar.btn_pin.isHidden(), "Ghim sits next to the propose button")
fired_pins = []
qt_bar.action_requested.connect(lambda key: fired_pins.append(key))
qt_bar.btn_pin.click()
check(fired_pins == [], "Ghim does not run the action")
check(qt_bar.lbl_pins.text() == "Đã ghim", "the card lists pinned actions")
check(any(button.text() == "Bỏ ghim" and not button.isHidden() for button in qt_bar.pin_unpin_buttons), "unpin is on the card")
qt_bar.pin_unpin_buttons[0].click()
check(list_pinned_actions(qt_root) == [], "Bỏ ghim clears the favorite")
this_week = week_key()
week_state = load_state(qt_root)
week_state["last_weekly_strip_week"] = this_week
week_state["pending_weekly_strip"] = {
    "week": this_week,
    "text": "Tóm tắt tuần:\n• Wi-Fi yếu 1 lần.",
    "items": [{"text": "Wi-Fi yếu 1 lần.", "topic": "wifi"}],
}
save_state(week_state, base_dir=qt_root)
qt_bar.refresh()
check(qt_bar.lbl_week.text().startswith("Tóm tắt tuần:"), "the card shows the local weekly strip")
check(qt_bar.lbl_week.text().count("•") <= 3, "the card strip has at most three bullets")
qt_bar.btn_week_hide.click()
check(qt_bar.lbl_week.text() == "", "Ẩn clears the weekly strip")
exam_state = load_state(qt_root)
exam_state["active_dates"] = [(datetime(2026, 9, 1) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(10)]
exam_state["last_exam_hint_week"] = this_week
exam_state["pending_exam_hint"] = {
    "id": f"exam_season:{this_week}",
    "week": this_week,
    "text": "Hôm nay: bạn có thể tự bật Trước thi / họp — mình không tự bật.",
    "topic": "focus",
}
save_state(exam_state, base_dir=qt_root)
qt_bar.refresh()
check("không tự bật" in qt_bar.lbl_insight.text(), "the card shows the exam-season hint")
check(qt_bar.btn_action.text() == "Bật Trước thi / họp", "the card offers the existing focus button")
fired_exam = []
qt_bar.action_requested.connect(lambda key: fired_exam.append(key))
qt_bar.btn_action.click()
check(fired_exam == ["enable_exam_focus"], "the button emits the existing focus action")
check(ExamMeetingFocus.is_active() is False, "the card click does not enable focus by itself")
qt_bar.deleteLater()
print(" [PASS] pin / weekly / exam card")

# ---------------------------------------------------------------------------
# Mô hình học mỗi ngày — JSON snapshot, not an LLM weight file
# ---------------------------------------------------------------------------

from core.companion_learning import (
    learn_status_vi,
    load_daily_model,
    merge_learning_models,
    model_path,
    morning_learn_clause,
    prefer_learned_topics,
    prompt_learn_line,
    update_daily_model,
    weekly_learn_line,
)
from core.companion_skills import BLOCKED_ACTION_KEYS as _LEARN_BLOCKED

learn_root = _fresh_dir()
learn_day = datetime(2026, 9, 23, 8, 0, 0)
record_app_event(
    "wifi_weak",
    "Wi-Fi yếu buổi tối",
    now=datetime(2026, 9, 22, 21, 0, 0),
    base_dir=learn_root,
    coalesce=False,
)
for offset in range(3):
    note_user_feedback(
        True,
        base_dir=learn_root,
        now=learn_day - timedelta(days=1, minutes=30 - offset),
        topic="wifi",
    )
note_user_feedback(False, base_dir=learn_root, now=learn_day - timedelta(days=1, minutes=10), topic="ram")
note_user_feedback(False, base_dir=learn_root, now=learn_day - timedelta(days=1, minutes=8), topic="ram")
record_app_event(
    "focus_mode",
    "Người dùng bật Trước thi / họp",
    now=learn_day - timedelta(days=2),
    base_dir=learn_root,
    coalesce=False,
)
record_app_event(
    "focus_mode",
    "Người dùng bật Trước thi / họp",
    now=learn_day - timedelta(days=3),
    base_dir=learn_root,
    coalesce=False,
)
ExamMeetingFocus.reset_for_tests()
first_model = update_daily_model(now=learn_day, base_dir=learn_root)
check(os.path.isfile(model_path(learn_root)), "daily model is a JSON file on this PC")
check(first_model.get("date") == "2026-09-23", "the snapshot is stamped with the local day")
check(first_model.get("source") == "local", "the model is local memory, not a downloaded LLM")
check("trọng số" in first_model.get("note_vi", "") or "AGI" in first_model.get("note_vi", ""), "the file says it is not an LLM weight file")
check("Hôm nay học được" in first_model.get("summary_vi", ""), "the snapshot has a Vietnamese lesson")
check("Ollama" not in json.dumps(first_model, ensure_ascii=False), "the snapshot does not call Ollama")
wifi_score = (first_model.get("topic_scores") or {}).get("wifi") or {}
check(int(wifi_score.get("helpful") or 0) >= 3, "Có ích counts land in the topic score")
ram_score = (first_model.get("topic_scores") or {}).get("ram") or {}
check(int(ram_score.get("unhelpful") or 0) >= 2, "Chưa counts land in the topic score")
check(int(first_model.get("focus_sessions") or 0) >= 2, "focus sessions are a stat, not a switch")
check(ExamMeetingFocus.is_active() is False, "learning does not turn on Trước thi / họp")
check("Hôm qua mình học" in (morning_learn_clause(now=learn_day, base_dir=learn_root) or ""), "the morning line can say what was learned yesterday")
check("Hôm nay học được" in (weekly_learn_line(now=learn_day, base_dir=learn_root, muted=set()) or ""), "the weekly digest can use the daily lesson")
mute_topic("wifi", days=7, base_dir=learn_root, now=learn_day)
check(morning_learn_clause(now=learn_day, base_dir=learn_root, hidden={"wifi"}) == "", "a muted topic stays out of the morning lesson")
check(weekly_learn_line(now=learn_day, base_dir=learn_root, muted={"wifi"}) == "", "a muted topic stays out of the weekly lesson")
unmute_topic("wifi", base_dir=learn_root)
check(any(item.get("issue_class") == "wifi_weak" for item in first_model.get("skill_candidates") or []), "skill candidates come from the diary")
check(
    all(item.get("action_key") not in _LEARN_BLOCKED for item in first_model.get("skill_candidates") or []),
    "skill candidates do not carry blocked actions",
)
note_user_feedback(True, base_dir=learn_root, now=learn_day.replace(hour=9), topic="wifi")
second_model = update_daily_model(now=learn_day.replace(hour=21), base_dir=learn_root)
check(second_model.get("topic_scores") == first_model.get("topic_scores"), "a second run the same day does not add the new Có ích")
check(second_model.get("summary_vi") == first_model.get("summary_vi"), "the same day keeps the same lesson")
check(second_model.get("trust_deltas") == first_model.get("trust_deltas"), "trust deltas are not stacked the same day")
next_model = update_daily_model(now=learn_day + timedelta(days=1), base_dir=learn_root)
next_wifi = (next_model.get("topic_scores") or {}).get("wifi") or {}
check(next_model.get("date") == "2026-09-24", "the next morning writes a new day")
check(int(next_wifi.get("helpful") or 0) == int(wifi_score.get("helpful") or 0) + 1, "the next day counts the Có ích once")
wifi_delta = ((next_model.get("trust_deltas") or {}).get("wifi") or {}).get("delta")
check(wifi_delta == 1, "the trust delta is the change since yesterday, not the full total")
check("Ollama" not in prompt_learn_line(now=learn_day, base_dir=learn_root), "prompt context does not fetch a base model")
status = learn_status_vi(first_model, now=learn_day)
check("Hôm nay đã học từ máy này" in status and "không phải AGI" in status, "the status line is honest and local")
empty_status = learn_status_vi(update_daily_model(now=learn_day, base_dir=_fresh_dir()), now=learn_day)
check("chưa có gì mới" in empty_status and "không phải AGI" in empty_status, "an empty day does not pretend to have learned")
ordered = prefer_learned_topics(
    [
        {"id": "tip:wifi", "topic": "wifi", "text": "Wi-Fi"},
        {"id": "tip:ram", "topic": "ram", "text": "RAM"},
        {"id": "window:wifi", "topic": "wifi", "text": "Buổi tối"},
    ],
    base_dir=learn_root,
)
check(str(ordered[0].get("id")).startswith("window:"), "a time window still comes before the learned topic")
check(ordered[1].get("topic") == "wifi", "a topic with more Có ích is preferred after the window")
quiet_root = _fresh_dir()
record_app_event("wifi_weak", "Wi-Fi yếu", now=learn_day - timedelta(hours=12), base_dir=quiet_root, coalesce=False)
set_quiet_hours(True, base_dir=quiet_root)
check(sync_daily_checkin(now=learn_day.replace(hour=23, minute=30), base_dir=quiet_root, config_manager=_Cfg()) is None, "quiet hours still hide the morning line")
check(load_daily_model(quiet_root).get("date") == "2026-09-23", "the daily job still learns during quiet hours")
set_quiet_hours(False, base_dir=quiet_root)
spoken = sync_daily_checkin(now=learn_day.replace(hour=8), base_dir=quiet_root, config_manager=_Cfg())
check(spoken and "Hôm qua mình học" in spoken.get("text", ""), "the morning line shows yesterday's lesson")
check("Gemini" not in spoken.get("text", "") and "Ollama" not in spoken.get("text", ""), "the morning lesson is not an online model")
again_spoken = sync_daily_checkin(now=learn_day.replace(hour=11), base_dir=quiet_root, config_manager=_Cfg())
check(again_spoken and again_spoken.get("text") == spoken.get("text"), "the learned morning line is still once per day")
learn_path = os.path.join(learn_root, "hoc.json")
check(export_companion_memory(learn_path, base_dir=learn_root).get("ok") is True, "the daily model exports with memory")
with open(learn_path, "r", encoding="utf-8") as handle:
    exported_model = json.load(handle).get("learning_model") or {}
check(exported_model.get("date") == "2026-09-24", "export keeps the latest learning day")
other_learn = _fresh_dir()
update_daily_model(now=learn_day, base_dir=other_learn)
check(import_companion_memory(learn_path, mode="merge", base_dir=other_learn).get("ok") is True, "the daily model imports")
check(load_daily_model(other_learn).get("date") == "2026-09-24", "merge keeps the newer snapshot")
check(load_daily_model(other_learn).get("summary_vi") == next_model.get("summary_vi"), "merge does not add the two snapshots together")
older = dict(exported_model)
older["date"] = "2026-09-20"
older["summary_vi"] = "Hôm nay học được: bản cũ."
check(merge_learning_models(exported_model, older).get("date") == "2026-09-24", "an older file does not replace today's model")
kept_local = _fresh_dir()
update_daily_model(now=learn_day, base_dir=kept_local)
legacy_learn = {
    "kind": "pc_cleaner_companion_memory",
    "version": 1,
    "profile": {},
    "diary": [],
}
legacy_learn_path = os.path.join(kept_local, "legacy.json")
with open(legacy_learn_path, "w", encoding="utf-8") as handle:
    json.dump(legacy_learn, handle)
check(import_companion_memory(legacy_learn_path, mode="replace", base_dir=kept_local).get("ok") is True, "an older backup without the model still imports")
check(load_daily_model(kept_local).get("date") == "2026-09-23", "a missing model key leaves the local snapshot")
poison = dict(exported_model)
poison["skill_candidates"] = [{"issue_class": "winsxs", "action_key": "winsxs_cleanup", "weight": 9, "title_vi": "no"}]
poison_path = os.path.join(learn_root, "poison.json")
with open(poison_path, "w", encoding="utf-8") as handle:
    json.dump({
        "kind": "pc_cleaner_companion_memory",
        "version": 1,
        "learning_model": poison,
    }, handle)
poison_root = _fresh_dir()
check(import_companion_memory(poison_path, mode="replace", base_dir=poison_root).get("ok") is True, "a model file with a blocked key still imports")
imported_candidates = load_daily_model(poison_root).get("skill_candidates") or []
check(all("winsxs" not in json.dumps(item) for item in imported_candidates), "import drops a blocked skill candidate")
check(ExamMeetingFocus.is_active() is False, "importing the model does not enable Trước thi / họp")
learn_bar = CompanionInsightBar(config_manager=_Cfg())
os.environ["PCAUTOCLEANER_COMPANION_DIR"] = learn_root
learn_bar.refresh()
check("không phải AGI" in learn_bar.lbl_learned_today.text(), "the companion card shows the local learning line")
check("Ollama" not in learn_bar.lbl_learned_today.text(), "the learning line does not mention Ollama")
learn_bar.deleteLater()
print(" [PASS] mô hình học mỗi ngày")

print(" [PASS] companion AI suite")
