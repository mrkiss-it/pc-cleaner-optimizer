"""
Unit tests for Hybrid Copilot: Ollama HTTP path + provider selection.
All network I/O is mocked — CI must not need a real Ollama daemon.
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
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_MODEL,
    canonicalize_copilot_provider,
    canonicalize_ollama_base_url,
    canonicalize_ollama_model,
)
from core.ai_copilot import (
    AICopilotEngine,
    CloudAIBrain,
    OllamaAIBrain,
    TelemetryCollector,
    format_ollama_empty_library,
    format_ollama_no_model,
    format_ollama_not_running,
    parse_ollama_error_message,
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


def _reset_ollama():
    OllamaAIBrain.last_error = ""
    OllamaAIBrain.last_error_short = ""
    OllamaAIBrain.last_working_model = ""
    OllamaAIBrain._down_until = 0.0
    OllamaAIBrain._down_base = ""


def _req_url(req):
    if hasattr(req, "get_full_url"):
        return req.get_full_url()
    return getattr(req, "full_url", str(req))


def _http_error(url, code, body):
    return urllib.error.HTTPError(url, code, "error", hdrs=None, fp=io.BytesIO(body.encode("utf-8")))


class _JsonResp:
    status = 200

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _tags_resp(names):
    return _JsonResp({"models": [{"name": n} for n in names]})


def _chat_resp(text):
    return _JsonResp({"message": {"role": "assistant", "content": text}, "done": True})


class _GeminiOkResp:
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


class _MemCfg:
    def __init__(self, **store):
        self.store = dict(store)

    def get(self, key, default=None):
        return self.store.get(key, default)

    def set(self, key, value):
        self.store[key] = value


def test_canonicalize_helpers():
    assert canonicalize_copilot_provider("Tự động") == "auto"
    assert canonicalize_copilot_provider("gemini") == "gemini"
    assert canonicalize_copilot_provider("local") == "ollama"
    assert canonicalize_copilot_provider("nope") == "auto"
    assert canonicalize_ollama_base_url("") == DEFAULT_OLLAMA_BASE_URL
    assert canonicalize_ollama_base_url("http://127.0.0.1:11434/") == "http://127.0.0.1:11434"
    assert canonicalize_ollama_base_url("file:///etc/passwd") == DEFAULT_OLLAMA_BASE_URL
    assert canonicalize_ollama_model("ollama pull llama3.2:3b") == "llama3.2:3b"
    assert canonicalize_ollama_model("!!!") == DEFAULT_OLLAMA_MODEL
    assert DEFAULT_CONFIG.get("ai_copilot_provider") == "auto"
    assert DEFAULT_CONFIG.get("ai_copilot_ollama_base_url") == DEFAULT_OLLAMA_BASE_URL
    assert DEFAULT_CONFIG.get("ai_copilot_ollama_model") == DEFAULT_OLLAMA_MODEL


def test_resolve_provider_legacy_cloud_checkbox():
    class _Legacy:
        def get(self, k, default=None):
            if k == "ai_copilot_cloud_enabled":
                return True
            return default

    assert resolve_copilot_provider(_Legacy()) == "gemini"
    assert resolve_copilot_provider(_MemCfg(ai_copilot_provider="ollama")) == "ollama"
    assert resolve_copilot_provider(None) == "auto"


def test_honest_vietnamese_guidance_strings():
    msg = format_ollama_not_running("http://127.0.0.1:11434")
    assert "127.0.0.1:11434" in msg
    assert "https://ollama.com" in msg
    assert "ollama pull qwen2.5:3b" in msg
    assert "llama3.2:3b" in msg
    empty = format_ollama_empty_library()
    assert "chưa tải mô hình" in empty
    assert "ollama pull" in empty
    missing = format_ollama_no_model("qwen2.5:3b", ["llama3.2:3b"])
    assert "qwen2.5:3b" in missing
    assert "llama3.2:3b" in missing
    parsed = parse_ollama_error_message('{"error":"model \'foo\' not found"}')
    assert "not found" in parsed
    assert "{" not in parsed


def test_ollama_chat_success_mocked_http():
    _reset_ollama()
    urls = []

    def urlopen(req, timeout=None):
        url = _req_url(req)
        urls.append(url)
        if url.endswith("/api/tags"):
            return _tags_resp(["qwen2.5:3b", "llama3.2:3b"])
        if url.endswith("/api/chat"):
            body = req.data.decode("utf-8") if isinstance(req.data, (bytes, bytearray)) else ""
            assert "qwen2.5:3b" in body
            assert APP_NAME in body
            return _chat_resp("RAM đang cao, hãy thu hồi bộ nhớ standby.")
        raise AssertionError(f"unexpected url {url}")

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = OllamaAIBrain.query(
            user_prompt="Máy ngốn RAM",
            telemetry=_TELEMETRY,
            model="qwen2.5:3b",
        )
    assert reply and "RAM" in reply
    assert OllamaAIBrain.last_working_model == "qwen2.5:3b"
    assert not OllamaAIBrain.last_error
    assert any(u.endswith("/api/tags") for u in urls)
    assert any(u.endswith("/api/chat") for u in urls)
    assert all("11434" in u for u in urls)


def test_ollama_not_running_is_honest():
    _reset_ollama()

    def urlopen(req, timeout=None):
        raise urllib.error.URLError(OSError("Connection refused"))

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = OllamaAIBrain.query(user_prompt="hi", telemetry=_TELEMETRY)
    assert reply is None
    assert "Không kết nối được Ollama" in OllamaAIBrain.last_error
    assert "https://ollama.com" in OllamaAIBrain.last_error
    assert "ollama pull qwen2.5:3b" in OllamaAIBrain.last_error
    assert "{" not in OllamaAIBrain.last_error


def test_ollama_empty_library():
    _reset_ollama()

    def urlopen(req, timeout=None):
        url = _req_url(req)
        if url.endswith("/api/tags"):
            return _tags_resp([])
        raise AssertionError("must not chat when library is empty")

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = OllamaAIBrain.query(user_prompt="hi", telemetry=_TELEMETRY)
    assert reply is None
    assert "chưa tải mô hình" in OllamaAIBrain.last_error
    assert "ollama pull qwen2.5:3b" in OllamaAIBrain.last_error


def test_ollama_model_not_pulled():
    _reset_ollama()

    def urlopen(req, timeout=None):
        url = _req_url(req)
        if url.endswith("/api/tags"):
            return _tags_resp(["tinyllama:latest"])
        raise AssertionError("must not chat when configured model is missing")

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = OllamaAIBrain.query(
            user_prompt="hi",
            telemetry=_TELEMETRY,
            model="qwen2.5:3b",
        )
    assert reply is None
    assert "qwen2.5:3b" in OllamaAIBrain.last_error
    assert "tinyllama:latest" in OllamaAIBrain.last_error
    assert "ollama pull qwen2.5:3b" in OllamaAIBrain.last_error


def test_ollama_chat_404_pull_hint():
    _reset_ollama()

    def urlopen(req, timeout=None):
        url = _req_url(req)
        if url.endswith("/api/tags"):
            return _tags_resp(["qwen2.5:3b"])
        if url.endswith("/api/chat"):
            raise _http_error(url, 404, '{"error":"model \'qwen2.5:3b\' not found, try pulling it"}')
        raise AssertionError(url)

    with patch("urllib.request.urlopen", side_effect=urlopen):
        reply = OllamaAIBrain.query(user_prompt="hi", telemetry=_TELEMETRY, model="qwen2.5:3b")
    assert reply is None
    assert "ollama pull qwen2.5:3b" in OllamaAIBrain.last_error


def test_provider_auto_uses_gemini_when_key_works():
    _reset_ollama()
    cfg = _MemCfg(
        ai_copilot_provider="auto",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
    )
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value="Trả lời Gemini về RAM.") as gem:
            with patch.object(OllamaAIBrain, "query", return_value="Trả lời Ollama.") as oll:
                msg = engine.ask("Máy ngốn RAM")
    assert msg.source == "cloud_gemini"
    assert "Gemini" in msg.content
    assert gem.called
    assert not oll.called


def test_provider_auto_falls_back_to_ollama_when_gemini_unreachable():
    _reset_ollama()
    cfg = _MemCfg(
        ai_copilot_provider="auto",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
        ai_copilot_ollama_model="qwen2.5:3b",
    )
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value=None) as gem:
            CloudAIBrain.last_error = "Lỗi mạng khi gọi Cloud Gemini."
            with patch.object(OllamaAIBrain, "query", return_value="Câu trả lời Ollama offline.") as oll:
                msg = engine.ask("ping")
    assert gem.called
    assert oll.called
    assert msg.source == "local_ollama"
    assert "Ollama" in msg.content
    assert "Câu trả lời Ollama offline." in msg.content


def test_provider_auto_uses_ollama_when_no_gemini_key():
    _reset_ollama()
    cfg = _MemCfg(ai_copilot_provider="auto", ai_copilot_gemini_api_key="")
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value="should-not-run") as gem:
            with patch.object(OllamaAIBrain, "query", return_value="Local OK") as oll:
                msg = engine.ask("hi")
    assert not gem.called
    assert oll.called
    assert msg.source == "local_ollama"
    assert msg.content == "Local OK"


def test_provider_gemini_does_not_call_ollama():
    _reset_ollama()
    cfg = _MemCfg(
        ai_copilot_provider="gemini",
        ai_copilot_cloud_enabled=True,
        ai_copilot_gemini_api_key="AIzaSyTEST",
    )
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value=None):
            CloudAIBrain.last_error = "HTTP 401: API key not valid"
            with patch.object(OllamaAIBrain, "query", return_value="should-not-run") as oll:
                msg = engine.ask("Kham suc khoe")
    assert not oll.called
    assert "Cloud Gemini lỗi" in msg.content
    assert msg.source == "offline_expert"


def test_provider_ollama_does_not_call_gemini():
    _reset_ollama()
    cfg = _MemCfg(
        ai_copilot_provider="ollama",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_ollama_model="qwen2.5:3b",
    )
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(CloudAIBrain, "query_gemini", return_value="gemini") as gem:
            with patch.object(OllamaAIBrain, "query", return_value="ollama-only"):
                msg = engine.ask("hi")
    assert not gem.called
    assert msg.source == "local_ollama"
    assert msg.content == "ollama-only"


def test_provider_ollama_honest_when_daemon_down():
    _reset_ollama()
    cfg = _MemCfg(ai_copilot_provider="ollama")
    engine = AICopilotEngine(config_manager=cfg)
    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch.object(OllamaAIBrain, "query", return_value=None):
            OllamaAIBrain.last_error = format_ollama_not_running(DEFAULT_OLLAMA_BASE_URL)
            msg = engine.ask("Tại sao máy ngốn RAM?")
    assert "Không kết nối được Ollama" in msg.content
    assert "không bịa" in msg.content.lower() or "Không bịa" in msg.content or "không bịa" in msg.content
    assert "https://ollama.com" in msg.content
    assert "ollama pull" in msg.content
    assert msg.source == "offline_expert"


def test_auto_gemini_503_then_ollama_http():
    """Gemini walks 404/429/503 models first; if all fail, Auto uses Ollama."""
    _reset_ollama()
    urls = []
    cfg = _MemCfg(
        ai_copilot_provider="auto",
        ai_copilot_gemini_api_key="AIzaSyTEST",
        ai_copilot_gemini_model="gemini-flash-latest",
        ai_copilot_ollama_model="qwen2.5:3b",
    )
    engine = AICopilotEngine(config_manager=cfg)

    def urlopen(req, timeout=None):
        url = _req_url(req)
        urls.append(url)
        if "generativelanguage.googleapis.com" in url:
            raise _http_error(url, 503, _RAW_503)
        if url.endswith("/api/tags"):
            return _tags_resp(["qwen2.5:3b"])
        if url.endswith("/api/chat"):
            return _chat_resp("Ollama trả lời sau khi Gemini quá tải.")
        raise AssertionError(url)

    with patch.object(TelemetryCollector, "collect", return_value=_TELEMETRY):
        with patch("urllib.request.urlopen", side_effect=urlopen):
            msg = engine.ask("hi")
    assert any("gemini-flash-latest" in u for u in urls)
    assert any("gemini-3.1-flash-lite" in u for u in urls)
    assert any(u.endswith("/api/chat") for u in urls)
    assert msg.source == "local_ollama"
    assert "Ollama trả lời sau khi Gemini quá tải." in msg.content


def test_system_instruction_uses_app_name():
    from core.ai_copilot import copilot_system_instruction
    text = copilot_system_instruction(_TELEMETRY)
    assert APP_NAME in text
    assert "Pro" not in text


if __name__ == "__main__":
    tests = [
        test_canonicalize_helpers,
        test_resolve_provider_legacy_cloud_checkbox,
        test_honest_vietnamese_guidance_strings,
        test_ollama_chat_success_mocked_http,
        test_ollama_not_running_is_honest,
        test_ollama_empty_library,
        test_ollama_model_not_pulled,
        test_ollama_chat_404_pull_hint,
        test_provider_auto_uses_gemini_when_key_works,
        test_provider_auto_falls_back_to_ollama_when_gemini_unreachable,
        test_provider_auto_uses_ollama_when_no_gemini_key,
        test_provider_gemini_does_not_call_ollama,
        test_provider_ollama_does_not_call_gemini,
        test_provider_ollama_honest_when_daemon_down,
        test_auto_gemini_503_then_ollama_http,
        test_system_instruction_uses_app_name,
    ]
    for fn in tests:
        fn()
        print(f" [PASS] {fn.__name__}")
    print(" [PASS] ollama hybrid copilot suite")
