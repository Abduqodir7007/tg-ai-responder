import base64
import time

import httpx
from django.conf import settings

from .models import GlobalSettings, ProviderConfig


class ProviderNotConfigured(Exception):
    pass


class AIServiceError(Exception):
    pass


def resolve_provider(account, gs: GlobalSettings | None = None) -> str:
    if account is not None and account.provider:
        return account.provider
    return (gs or GlobalSettings.load()).default_provider


OVERLOAD_MARKERS = ("503", "429", "high demand", "overloaded", "unavailable", "resource_exhausted")


def is_overloaded(response: httpx.Response) -> bool:
    if response.status_code in (429, 503, 529):
        return True
    text = response.text.lower()
    return response.status_code == 502 and any(marker in text for marker in OVERLOAD_MARKERS)


class AIClient:
    def __init__(self, provider, api_key, model, base_url, token, timeout=None, transport=None):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout or settings.AI_SERVICE_TIMEOUT
        self.transport = transport

    @classmethod
    def for_account(cls, account, gs: GlobalSettings | None = None, transport=None) -> "AIClient":
        provider = resolve_provider(account, gs)
        config = ProviderConfig.objects.filter(provider=provider, enabled=True).first()
        if config is None or not config.api_key_encrypted:
            raise ProviderNotConfigured(f"Provider '{provider}' has no enabled API key")
        model = config.effective_model
        if account is not None and account.provider == provider and account.model_override:
            model = account.model_override
        return cls(
            provider=provider,
            api_key=config.get_api_key(),
            model=model,
            base_url=settings.AI_SERVICE_URLS[provider],
            token=settings.INTERNAL_SERVICE_TOKEN,
            transport=transport,
        )

    def _models(self) -> list[str]:
        fallbacks = settings.AI_FALLBACK_MODELS.get(self.provider, [])
        return [self.model] + [m for m in fallbacks if m != self.model]

    def _post_once(self, path: str, payload: dict, model: str) -> httpx.Response:
        body = {**payload, "api_key": self.api_key, "model": model}
        headers = {"X-Internal-Token": self.token}
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
                return client.post(path, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise AIServiceError(f"{self.provider} service unreachable: {exc}") from exc

    def _post(self, path: str, payload: dict) -> dict:
        last_error = ""
        for model in self._models():
            for attempt in range(settings.AI_RETRY_ATTEMPTS):
                response = self._post_once(path, payload, model)
                if response.status_code < 400:
                    return response.json()
                last_error = f"{self.provider} service error {response.status_code}: {response.text[:500]}"
                if not is_overloaded(response):
                    raise AIServiceError(last_error)
                if attempt + 1 < settings.AI_RETRY_ATTEMPTS:
                    time.sleep(settings.AI_RETRY_DELAY_SECONDS * (attempt + 1))
        raise AIServiceError(last_error)

    def generate(self, system: str, messages: list[dict], max_tokens: int = 800) -> dict:
        return self._post("/generate", {"system": system, "messages": messages, "max_tokens": max_tokens})

    def summarize(self, existing: dict, messages: list[dict], mode: str = "update") -> dict:
        return self._post("/summarize", {"existing_context": existing, "messages": messages, "mode": mode})

    def describe_media(self, media_type: str, mime_type: str, data: bytes) -> dict:
        return self._post(
            "/describe-media",
            {
                "media_type": media_type,
                "mime_type": mime_type,
                "data_b64": base64.b64encode(data).decode(),
            },
        )
