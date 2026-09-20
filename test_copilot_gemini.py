"""
Unit tests for Gemini-only Copilot routing + extra_context companion injection.

All network I/O is mocked — CI must not need a local LLM daemon.
"""
import io
import json
import os
import sys
import types
import urllib.error
from unittest.mock import patch

if sys.platform != "win32":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if "winreg" not in sys.modules:
        winreg = types.ModuleType("winreg")
        winreg.HKEY_CURRENT_USER = 1
        winreg.HKEY_LOCAL_MACHINE = 2
        winreg.KEY_READ = 0
        winreg.KEY_WRITE = 0
        winreg.KEY_SET_VALUE = 0
        winreg.KEY_ALL_ACCESS = 0
        winreg.REG_DWORD = 4
        winreg.REG_SZ = 1

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

from app_meta import APP_NAME
from config_manager import (
    DEFAULT_CONFIG,
    RETIRED_COPILOT_KEYS,
    canonicalize_copilot_provider,
)
from core import ai_copilot as copilot_mod
from core.ai_copilot import (
    AICopilotEngine,
    CloudAIBrain,
    GEMINI_NEEDS_NETWORK_MSG,
    TelemetryCollector,
    resolve_copilot_provider,
)

_TELEMETRY = {
    "ram": {"percent": 70.0, "used_gb": 5.0, "total_gb": 8.0},
    "cpu": {"percent": 20.0, "count": 4},
    "disk": {"free_gb": 40.0, "total_gb": 256.0},
}

_RAW_503 = (
    '{"error":{"code":503,"message":"This model is currently experiencing high demand. '
    'Please try again later or switch to another model.","status":"UNAVAILABLE"}}'
)


class _MemCfg:
    def __init__(self, **store):
        self.store = dict(store)

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value):
        self.store[key] = value


def _req_url(req):
    if hasattr(req, "get_full_url"):
        return req.get_full_url()
    return getattr(req, "full_url", str(req))


def _http_error(url, code, body):
    return urllib.error.HTTPError(url, code, "error", hdrs=None, fp=io.BytesIO(body.encode("utf-8")))


class _OkResp:
    status = 200

    def __init__(self, text):
        self._payload = json.dumps({
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]
        }).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_no_live_ollama_provider_path():
    assert not hasattr(copilot_mod, "OllamaAIBrain")
    src = open(copilot_mod.__file__, encoding="utf-8").read()
    assert "11434" not in src
    assert "/api/tags" not in src
    assert "ollama.com" not in src
    assert "ollama pull" not in src
    assert "local_ollama" not in src
    welcome = AICopilotEngine().chat_history[0].content
    assert "Ollama" not in welcome
    assert "Gemini" in welcome
    assert APP_NAME in welcome
    assert "Pro" not in welcome


def test_config_strips_retired_ollama_keys():
    import json
    import os
    import tempfile
    from config_manager import ConfigManager

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "ai_copilot_provider": "ollama",
                "ai_copilot_ollama_base_url": "http://127.0.0.1:11434",
                "ai_copilot_ollama_model": "qwen2.5:3b",
            }, handle)
        cfg = ConfigManager(config_path=path)
        assert cfg.get("ai_copilot_provider") == "auto"
        assert "ai_copilot_ollama_base_url" not in cfg.config
        assert "ai_copilot_ollama_model" not in cfg.config
        with open(path, "r", encoding="utf-8") as handle:
            disk = json.load(handle)
        assert disk.get("ai_copilot_provider") == "auto"
        assert "ai_copilot_ollama_base_url" not in disk
        assert "ai_copilot_ollama_model" not in disk
        cfg.set("ai_copilot_ollama_base_url", "http://127.0.0.1:11434")
        assert "ai_copilot_ollama_base_url" not in cfg.config
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_canonicalize_helpers():
    assert canonicalize_copilot_provider("Tự động") == "auto"
    assert canonicalize_copilot_provider("gemini") == "gemini"
    assert canonicalize_copilot_provider("local") == "auto"
    assert canonicalize_copilot_provider("ollama") == "auto"
    assert canonicalize_copilot_provider("offline") == "auto"
    assert canonicalize_copilot_provider("nope") == "auto"
    assert DEFAULT_CONFIG.get("ai_copilot_provider") == "auto"
    for key in RETIRED_COPILOT_KEYS:
        assert key not in DEFAULT_CONFIG


def test_resolve_provider_legacy_cloud_checkbox():
    class _Legacy:
        def get(self, k, default=None):
            if k == "ai_copilot_cloud_enabled":
                return True
            return default

    assert resolve_copilot_provider(_Legacy()) == "gemini"
    assert resolve_copilot_provider(_MemCfg(ai_copilot_provider="ollama")) == "auto"
    assert resolve_copilot_provider(None) == "auto"


def test_provider_auto_uses_gemini_when_key_works():
    cfg = _MemCfg(
        ai_copilot_provider="auto",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
    )
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value="Trả lời Gemini về RAM.") as gem:
            msg = engine.ask("Máy ngốn RAM")
    assert msg.source == "cloud_gemini"
    assert "Gemini" in msg.content
    assert gem.called


def test_provider_auto_honest_when_gemini_unreachable():
    cfg = _MemCfg(
        ai_copilot_provider="auto",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
    )
    engine = AICopilotEngine(config_manager=cfg)
    CloudAIBrain.last_error = "Lỗi mạng: Connection refused"
    CloudAIBrain.last_error_short = "Lỗi mạng khi gọi Cloud Gemini."
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value=None) as gem:
            msg = engine.ask("Máy ngốn RAM")
    assert gem.called
    assert msg.source == "offline_expert"
    assert "cần mạng" in msg.content.lower() or "API key" in msg.content
    assert GEMINI_NEEDS_NETWORK_MSG.split("—")[0].strip() in msg.content or "Gemini" in msg.content
    assert "Ollama" not in msg.content
    assert "ollama.com" not in msg.content


def test_provider_auto_honest_when_no_gemini_key():
    cfg = _MemCfg(ai_copilot_provider="auto")
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value="should-not-run") as gem:
            msg = engine.ask("Máy ngốn RAM")
    assert not gem.called
    assert msg.source == "offline_expert"
    assert "API key" in msg.content
    assert "cần mạng" in msg.content.lower()
    assert "Ollama" not in msg.content


def test_legacy_ollama_provider_becomes_gemini_auto():
    cfg = _MemCfg(
        ai_copilot_provider="ollama",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
    )
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value="Gemini sau khi đổi nhà cung cấp.") as gem:
            msg = engine.ask("Máy ngốn RAM")
    assert resolve_copilot_provider(cfg) == "auto"
    assert gem.called
    assert msg.source == "cloud_gemini"


def test_auto_gemini_503_then_offline_expert():
    """Gemini walks 404/429/503 models first; if all fail, Auto uses Offline Expert — not a local LLM."""
    cfg = _MemCfg(
        ai_copilot_provider="auto",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
    )
    engine = AICopilotEngine(config_manager=cfg)
    urls = []

    def urlopen(req, timeout=None):
        url = _req_url(req)
        urls.append(url)
        raise _http_error(url, 503, _RAW_503)

    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch("urllib.request.urlopen", side_effect=urlopen):
            msg = engine.ask("Máy ngốn RAM")
    assert urls
    assert all("generativelanguage.googleapis.com" in u for u in urls)
    assert msg.source == "offline_expert"
    assert "Ollama" not in msg.content
    assert "cần mạng" in msg.content.lower() or "Gemini" in msg.content


def test_system_instruction_uses_app_name():
    from core.ai_copilot import copilot_system_instruction
    text = copilot_system_instruction(_TELEMETRY)
    assert APP_NAME in text
    assert "Pro" not in text


def test_extra_prompt_context_extension_point():
    from core.ai_copilot import (
        collect_extra_prompt_context,
        copilot_system_instruction,
        normalize_extra_prompt_context,
    )
    assert normalize_extra_prompt_context(None) == []
    assert normalize_extra_prompt_context(["", "  "]) == []
    assert normalize_extra_prompt_context("Giai đoạn: mầm") == ["Giai đoạn: mầm"]
    assert normalize_extra_prompt_context(["Nhật ký: đã dọn rác", "", "Kỹ năng: RAM"]) == [
        "Nhật ký: đã dọn rác",
        "Kỹ năng: RAM",
    ]
    base = copilot_system_instruction(_TELEMETRY)
    with_notes = copilot_system_instruction(
        _TELEMETRY,
        extra_context=["Giai đoạn: chồi", "Ghi chú: user thích tối ưu game"],
    )
    assert with_notes.startswith(base)
    assert "Giai đoạn: chồi" in with_notes
    assert "Ghi chú: user thích tối ưu game" in with_notes

    def provider(*, user_prompt, telemetry, health_report):
        assert user_prompt == "ping"
        assert telemetry["ram"]["percent"] == 70.0
        assert health_report is None
        return ["Companion: reflection notes"]

    merged = collect_extra_prompt_context(
        ["one-shot"],
        provider,
        user_prompt="ping",
        telemetry=_TELEMETRY,
    )
    assert merged == ["one-shot", "Companion: reflection notes"]

    def boom(**_k):
        raise RuntimeError("companion down")

    assert collect_extra_prompt_context(provider=boom, user_prompt="x") == []


def test_engine_extra_context_provider_reaches_gemini_payload():
    bodies = []

    def provider(*, user_prompt, telemetry, health_report):
        return [f"Diary:{user_prompt}", "Stage:seedling"]

    def urlopen(req, timeout=None):
        bodies.append(req.data.decode("utf-8"))
        return _OkResp("OK extra")

    cfg = _MemCfg(
        ai_copilot_provider="gemini",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
    )
    engine = AICopilotEngine(config_manager=cfg, extra_context_provider=provider)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch("urllib.request.urlopen", side_effect=urlopen):
            msg = engine.ask("Tối ưu RAM", extra_context=["Skill:ram"])
    assert msg.source == "cloud_gemini"
    assert bodies
    payload = json.loads(bodies[0])
    text = payload["contents"][0]["parts"][0]["text"]
    assert "Diary:Tối ưu RAM" in text
    assert "Stage:seedling" in text
    assert "Skill:ram" in text
    assert APP_NAME in text


if __name__ == "__main__":
    tests = [
        test_no_live_ollama_provider_path,
        test_config_strips_retired_ollama_keys,
        test_canonicalize_helpers,
        test_resolve_provider_legacy_cloud_checkbox,
        test_provider_auto_uses_gemini_when_key_works,
        test_provider_auto_honest_when_gemini_unreachable,
        test_provider_auto_honest_when_no_gemini_key,
        test_legacy_ollama_provider_becomes_gemini_auto,
        test_auto_gemini_503_then_offline_expert,
        test_system_instruction_uses_app_name,
        test_extra_prompt_context_extension_point,
        test_engine_extra_context_provider_reaches_gemini_payload,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] gemini copilot routing + extra_context suite")
