"""
Evening / on-demand reflection → short Vietnamese "sổ tay" note.

Uses a thin LLM provider hook: prefer local Ollama when configured, else the
existing Gemini path, else an honest metrics-only template (no fake wisdom).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Protocol

from config_manager import DEFAULT_GEMINI_MODEL, companion_dir

NOTE_FILENAME = "so_tay.txt"
META_FILENAME = "so_tay.json"
MAX_NOTE_LEN = 900


class CompanionLLMProvider(Protocol):
    """Thin hook so Gemini or a future Ollama hybrid can write the sổ tay."""

    name: str

    def generate(self, prompt: str, timeout: float = 8.0) -> Optional[str]:
        ...


class TemplateReflectionProvider:
    """Offline, honest summary from counts only — never pretends to 'understand'."""

    name = "template"

    def generate(self, prompt: str, timeout: float = 8.0) -> Optional[str]:
        return None


class GeminiReflectionProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str = DEFAULT_GEMINI_MODEL, persist_model=None):
        self.api_key = str(api_key or "").strip()
        self.model = model
        self.persist_model = persist_model

    def generate(self, prompt: str, timeout: float = 8.0) -> Optional[str]:
        if not self.api_key:
            return None
        try:
            from core.ai_copilot import CloudAIBrain
            return CloudAIBrain.query_gemini(
                api_key=self.api_key,
                user_prompt=prompt,
                telemetry={},
                model=self.model or DEFAULT_GEMINI_MODEL,
                persist_model=self.persist_model,
                extra_context=(
                    "Bạn viết một đoạn sổ tay ngắn (tiếng Việt, tối đa 8 câu) từ nhật ký máy. "
                    "Không bịa kỷ niệm. Không nhận là AGI. Không đưa lệnh phá hủy."
                ),
                timeout=timeout,
            )
        except Exception:
            return None


class OllamaReflectionProvider:
    """Local HTTP hook (Ollama /api/generate). Parallel hybrid branch can replace this."""

    name = "ollama"

    def __init__(self, host: str = "http://127.0.0.1:11434", model: str = "llama3.2"):
        self.host = str(host or "http://127.0.0.1:11434").rstrip("/")
        self.model = str(model or "llama3.2").strip() or "llama3.2"

    def generate(self, prompt: str, timeout: float = 8.0) -> Optional[str]:
        url = f"{self.host}/api/generate"
        payload = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            text = ""
            if isinstance(data, dict):
                text = str(data.get("response") or data.get("text") or "").strip()
            return text or None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            return None
        except Exception:
            return None


def resolve_llm_provider(config_manager: Optional[Any] = None) -> CompanionLLMProvider:
    """Prefer local Ollama when configured; else Gemini; else template."""
    get = config_manager.get if config_manager is not None and hasattr(config_manager, "get") else lambda k, d=None: d
    provider = str(get("ai_copilot_provider", "auto") or "auto").strip().lower()
    ollama_host = str(
        get("ai_copilot_ollama_base_url", "")
        or get("ai_copilot_ollama_host", "")
        or "http://127.0.0.1:11434"
    ).rstrip("/")
    ollama_model = str(get("ai_copilot_ollama_model", "") or "qwen2.5:3b")
    prefer_ollama = provider == "ollama" or bool(get("ai_copilot_ollama_enabled", False))
    if prefer_ollama:
        return OllamaReflectionProvider(host=ollama_host or "http://127.0.0.1:11434", model=ollama_model)
    key = str(get("ai_copilot_gemini_api_key", "") or "").strip()
    gemini_wanted = provider == "gemini" or bool(get("ai_copilot_cloud_enabled", False)) or (
        provider == "auto" and bool(key)
    )
    if gemini_wanted and key:
        model = str(get("ai_copilot_gemini_model", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL)
        persist_cb = None
        if hasattr(config_manager, "set"):
            cm = config_manager

            def _persist(working: str, _cm=cm) -> None:
                from config_manager import canonicalize_gemini_model
                fixed = canonicalize_gemini_model(working)
                current = str(_cm.get("ai_copilot_gemini_model", "")).strip()
                if fixed and fixed != current:
                    _cm.set("ai_copilot_gemini_model", fixed)

            persist_cb = _persist
        return GeminiReflectionProvider(api_key=key, model=model, persist_model=persist_cb)
    return TemplateReflectionProvider()


def note_path(base_dir: Optional[str] = None) -> str:
    return os.path.join(base_dir or companion_dir(), NOTE_FILENAME)


def meta_path(base_dir: Optional[str] = None) -> str:
    return os.path.join(base_dir or companion_dir(), META_FILENAME)


def load_reflection(base_dir: Optional[str] = None) -> str:
    path = note_path(base_dir)
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception:
        return ""


def load_reflection_meta(base_dir: Optional[str] = None) -> Dict[str, Any]:
    path = meta_path(base_dir)
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def clear_reflection(base_dir: Optional[str] = None) -> bool:
    removed = False
    for path in (note_path(base_dir), meta_path(base_dir)):
        try:
            if path and os.path.exists(path):
                os.remove(path)
                removed = True
        except Exception:
            continue
    return removed


def save_reflection(
    note: str,
    *,
    source: str,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    text = _clip_note(note)
    root = base_dir or companion_dir()
    os.makedirs(root, exist_ok=True)
    with open(note_path(base_dir), "w", encoding="utf-8") as handle:
        handle.write(text)
    stamp = (now or datetime.now()).replace(microsecond=0).isoformat(timespec="seconds")
    meta = {
        "updated_at": stamp,
        "source": str(source or "template")[:32],
        "chars": len(text),
    }
    tmp = meta_path(base_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, meta_path(base_dir))
    return text


def _clip_note(note: str) -> str:
    text = str(note or "").strip()
    text = text.replace("\x00", "")
    if len(text) > MAX_NOTE_LEN:
        text = text[: MAX_NOTE_LEN - 1].rstrip() + "…"
    return text


def template_reflection(
    *,
    digest: str,
    kind_counts: Optional[Dict[str, int]] = None,
    active_days: int = 0,
    stage_label: str = "",
    now: Optional[datetime] = None,
) -> str:
    """Honest metrics-only sổ tay. No invented personality or 'wisdom'."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    counts = kind_counts or {}
    total = sum(int(v) for v in counts.values()) if counts else 0
    lines = [
        f"Sổ tay {stamp} (chỉ số liệu — không dùng mô hình ngôn ngữ).",
        f"Giai đoạn: {stage_label or 'chưa xác định'}. Ngày dùng máy đã ghi: {int(active_days)}.",
        f"Sự kiện nhật ký gần đây: {total}.",
    ]
    labels = {
        "high_ram": "RAM cao",
        "ram_optimized": "thu hồi RAM",
        "wifi_weak": "Wi-Fi yếu",
        "wifi_repaired": "đã sửa Wi-Fi",
        "ping_high": "ping cao",
        "focus_mode": "Trước thi / họp",
        "clean_freed": "dọn rác",
        "clean_light": "dọn nhẹ",
        "thermal_warn": "cảnh báo nhiệt",
        "session_day": "phiên dùng app",
    }
    bits = []
    for kind, label in labels.items():
        n = int(counts.get(kind) or 0)
        if n:
            bits.append(f"{label} {n} lần")
    if bits:
        lines.append("Chi tiết: " + "; ".join(bits) + ".")
    digest_text = (digest or "").strip()
    if digest_text and "còn trống" not in digest_text:
        lines.append("Tóm tắt nhật ký:")
        lines.append(digest_text)
    else:
        lines.append("Chưa đủ nhật ký để tóm tắt thói quen máy này.")
    lines.append("Đây không phải AGI; chỉ là ghi chép local trên máy này.")
    return "\n".join(lines)


def build_reflection_prompt(
    *,
    digest: str,
    stage_label: str,
    skills_text: str,
    kind_counts: Optional[Dict[str, int]] = None,
) -> str:
    counts = kind_counts or {}
    count_line = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()) if v) or "không có"
    return (
        "Viết sổ tay ngắn bằng tiếng Việt cho trợ lý máy tính local "
        "(không nhận là AGI, không bịa sự kiện).\n"
        f"Giai đoạn đồng hành: {stage_label}\n"
        f"Đếm sự kiện: {count_line}\n"
        f"Nhật ký:\n{digest or '(trống)'}\n"
        f"Kỹ năng đã lưu:\n{skills_text or '(chưa có)'}\n"
        "Tối đa 8 câu. Nếu nhật ký trống, nói thẳng là chưa có dữ liệu."
    )


def run_reflection(
    *,
    digest: str,
    kind_counts: Optional[Dict[str, int]] = None,
    active_days: int = 0,
    stage_label: str = "",
    skills_text: str = "",
    provider: Optional[CompanionLLMProvider] = None,
    base_dir: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, str]:
    """Write sổ tay. LLM is optional; always falls back to the metrics template."""
    fallback = template_reflection(
        digest=digest,
        kind_counts=kind_counts,
        active_days=active_days,
        stage_label=stage_label,
        now=now,
    )
    used = "template"
    note = fallback
    llm = provider or TemplateReflectionProvider()
    if getattr(llm, "name", "") != "template":
        prompt = build_reflection_prompt(
            digest=digest,
            stage_label=stage_label,
            skills_text=skills_text,
            kind_counts=kind_counts,
        )
        try:
            generated = llm.generate(prompt)
        except Exception:
            generated = None
        text = _clip_note(generated or "")
        if text:
            note = text
            used = str(getattr(llm, "name", "llm") or "llm")
    saved = save_reflection(note, source=used, base_dir=base_dir, now=now)
    return {"note": saved, "source": used}
