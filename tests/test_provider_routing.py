import json

import httpx
import pytest

from core.ai_client import AIClient, AIServiceError, ProviderNotConfigured, resolve_provider
from core.models import GlobalSettings, ProviderConfig


@pytest.fixture
def service_urls(settings):
    settings.AI_SERVICE_URLS = {"claude": "http://claude-service:8000", "gemini": "http://gemini-service:8000"}
    settings.INTERNAL_SERVICE_TOKEN = "internal-test-token"
    settings.DEFAULT_MODELS = {"claude": "claude-sonnet-5-5", "gemini": "gemini-3.6-flash"}


def capture_transport(captured, status=200):
    def handler(request):
        captured.append(request)
        return httpx.Response(status, json={"text": "ok", "input_tokens": 1, "output_tokens": 1})

    return httpx.MockTransport(handler)


def test_global_default_provider_is_used(gs, account, providers, service_urls):
    captured = []
    client = AIClient.for_account(account, gs, transport=capture_transport(captured))
    client.generate(system="s", messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}])

    request = captured[0]
    body = json.loads(request.content)
    assert client.provider == "claude"
    assert str(request.url) == "http://claude-service:8000/generate"
    assert request.headers["X-Internal-Token"] == "internal-test-token"
    assert body["api_key"] == "sk-ant-test-claude-key"
    assert body["model"] == "claude-sonnet-5-5"


def test_account_override_routes_to_gemini(gs, account, providers, service_urls):
    account.provider = "gemini"
    account.model_override = "gemini-pro-custom"
    account.save()
    captured = []
    client = AIClient.for_account(account, gs, transport=capture_transport(captured))
    client.summarize(existing={}, messages=[{"role": "contact", "text": "hi"}])

    body = json.loads(captured[0].content)
    assert str(captured[0].url) == "http://gemini-service:8000/summarize"
    assert body["api_key"] == "gemini-test-key-123"
    assert body["model"] == "gemini-pro-custom"


def test_global_switch_changes_provider(gs, account, providers, service_urls):
    GlobalSettings.objects.update(default_provider="gemini")
    gs.refresh_from_db()

    assert resolve_provider(account, gs) == "gemini"
    assert AIClient.for_account(account, gs).model == "gemini-test-model"


def test_disabled_provider_is_rejected(gs, account, providers, service_urls):
    ProviderConfig.objects.filter(provider="claude").update(enabled=False)

    with pytest.raises(ProviderNotConfigured):
        AIClient.for_account(account, gs)


def test_service_error_is_raised(gs, account, providers, service_urls):
    client = AIClient.for_account(account, gs, transport=capture_transport([], status=502))

    with pytest.raises(AIServiceError):
        client.describe_media("voice", "audio/ogg", b"bytes")


def test_keys_are_encrypted_at_rest_and_masked(providers):
    config = ProviderConfig.objects.get(provider="claude")

    assert "sk-ant-test-claude-key" not in config.api_key_encrypted
    assert config.get_api_key() == "sk-ant-test-claude-key"
    assert config.masked_api_key == "sk-a********-key"
