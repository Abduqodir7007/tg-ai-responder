import httpx
import pytest

from core.ai_client import AIClient, AIServiceError


def make_client(handler, settings):
    settings.AI_RETRY_ATTEMPTS = 2
    settings.AI_RETRY_DELAY_SECONDS = 0
    settings.AI_FALLBACK_MODELS = {"gemini": ["backup-model"]}
    return AIClient("gemini", "key", "main-model", "http://gemini", "token", transport=httpx.MockTransport(handler))


def test_overloaded_model_falls_back_to_next(settings):
    seen = []

    def handler(request):
        model = __import__("json").loads(request.content)["model"]
        seen.append(model)
        if model == "main-model":
            return httpx.Response(502, text='{"detail":"Gemini error 503: high demand"}')
        return httpx.Response(200, json={"text": "ok", "model": model})

    result = make_client(handler, settings).generate("s", [{"role": "user", "content": []}])
    assert result["text"] == "ok"
    assert seen == ["main-model", "main-model", "backup-model"]


def test_non_overload_error_is_not_retried(settings):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="bad request")

    with pytest.raises(AIServiceError):
        make_client(handler, settings).generate("s", [{"role": "user", "content": []}])
    assert len(calls) == 1
