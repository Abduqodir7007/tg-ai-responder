import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ai_services.claude_service import app as claude_module
from ai_services.claude_service.media import MediaExtract
from ai_services.gemini_service import app as gemini_module

TOKEN = "service-test-token"
HEADERS = {"X-Internal-Token": TOKEN}
IMAGE_B64 = base64.b64encode(b"\xff\xd8jpeg").decode()


class FakeAnthropic:
    def __init__(self, text="Salom!"):
        self.text = text
        self.calls = []
        self.api_keys = []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            usage=SimpleNamespace(input_tokens=11, output_tokens=5),
        )


class FakeGenai:
    def __init__(self, text="Salom!"):
        self.text = text
        self.calls = []
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return SimpleNamespace(
            text=self.text,
            usage_metadata=SimpleNamespace(prompt_token_count=21, candidates_token_count=6),
        )


@pytest.fixture(autouse=True)
def service_token(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", TOKEN)


def client_for(module, fake):
    keys = []

    def factory():
        def build(api_key):
            keys.append(api_key)
            return fake

        return build

    module.app.dependency_overrides[module.get_client_factory] = factory
    return TestClient(module.app), keys


@pytest.fixture
def claude():
    fake = FakeAnthropic()
    client, keys = client_for(claude_module, fake)
    yield client, fake, keys
    claude_module.app.dependency_overrides.clear()


@pytest.fixture
def gemini():
    fake = FakeGenai()
    client, keys = client_for(gemini_module, fake)
    yield client, fake, keys
    gemini_module.app.dependency_overrides.clear()


GENERATE_BODY = {
    "api_key": "user-key",
    "system": "persona",
    "messages": [
        {"role": "user", "content": [{"type": "text", "text": "salom"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "va alaykum"}]},
        {
            "role": "user",
            "content": [
                {"type": "image", "mime_type": "image/jpeg", "data_b64": IMAGE_B64},
                {"type": "text", "text": "bu nima?"},
            ],
        },
    ],
}

SUMMARY_BODY = {
    "api_key": "user-key",
    "existing_context": {"name": "Ali", "facts": {"city": "Tashkent"}},
    "messages": [{"id": 5, "role": "contact", "text": "Men Samarqandga ko'chdim"}],
    "mode": "update",
}


@pytest.mark.parametrize("module", [claude_module, gemini_module])
@pytest.mark.parametrize("path", ["/generate", "/summarize", "/describe-media"])
def test_endpoints_require_internal_token(module, path):
    response = TestClient(module.app).post(path, json={}, headers={"X-Internal-Token": "wrong"})
    assert response.status_code == 401


def test_claude_generate_passes_images_and_key(claude):
    client, fake, keys = claude

    response = client.post("/generate", json=GENERATE_BODY, headers=HEADERS)

    assert response.status_code == 200
    assert response.json() == {"text": "Salom!", "input_tokens": 11, "output_tokens": 5,
                               "model": "claude-sonnet-5-5"}
    assert keys == ["user-key"]
    call = fake.calls[0]
    assert call["system"] == "persona"
    assert [message["role"] for message in call["messages"]] == ["user", "assistant", "user"]
    image = call["messages"][2]["content"][0]
    assert image == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": IMAGE_B64}}


def test_claude_generate_honours_model_option(claude):
    client, fake, _ = claude

    client.post("/generate", json={**GENERATE_BODY, "model": "claude-opus-5-5"}, headers=HEADERS)

    assert fake.calls[0]["model"] == "claude-opus-5-5"


def test_claude_summarize_parses_fenced_json(claude):
    client, fake, _ = claude
    fake.text = '```json\n{"facts": {"city": "Samarkand"}, "open_tasks": ["visit"], "summary": "Moved"}\n```'

    response = client.post("/summarize", json=SUMMARY_BODY, headers=HEADERS)

    context = response.json()["context"]
    assert context["name"] == "Ali"
    assert context["facts"] == {"city": "Samarkand"}
    assert context["open_tasks"] == ["visit"]
    assert "Samarqandga" in fake.calls[0]["messages"][0]["content"][0]["text"]


def test_claude_voice_uses_whisper_without_model_call(claude, monkeypatch):
    client, fake, _ = claude
    monkeypatch.setattr(claude_module.media, "process_media",
                        lambda kind, mime, data: MediaExtract(transcript="ertaga kelaman"))

    response = client.post(
        "/describe-media",
        json={"api_key": "k", "media_type": "voice", "mime_type": "audio/ogg", "data_b64": IMAGE_B64},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["text"] == "Transcript: ertaga kelaman"
    assert fake.calls == []


def test_claude_video_uses_frames_and_transcript(claude, monkeypatch):
    client, fake, _ = claude
    fake.text = "A man waves at the camera."
    seen = {}

    def process(kind, mime, data):
        seen.update(kind=kind, mime=mime, data=data)
        return MediaExtract(transcript="salom", frames=[b"f1", b"f2"])

    monkeypatch.setattr(claude_module.media, "process_media", process)

    response = client.post(
        "/describe-media",
        json={"api_key": "k", "media_type": "video_note", "mime_type": "video/mp4", "data_b64": IMAGE_B64},
        headers=HEADERS,
    )

    body = response.json()
    assert seen == {"kind": "video_note", "mime": "video/mp4", "data": b"\xff\xd8jpeg"}
    assert body["text"] == "Transcript: salom\nVisual: A man waves at the camera."
    content = fake.calls[0]["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "image", "text"]


def test_gemini_generate_maps_roles_and_media(gemini):
    client, fake, keys = gemini

    response = client.post("/generate", json={**GENERATE_BODY, "max_tokens": 300}, headers=HEADERS)

    assert response.status_code == 200
    assert response.json()["input_tokens"] == 21
    assert keys == ["user-key"]
    call = fake.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert [content.role for content in call["contents"]] == ["user", "model", "user"]
    image_part = call["contents"][2].parts[0]
    assert image_part.inline_data.data == b"\xff\xd8jpeg"
    assert image_part.inline_data.mime_type == "image/jpeg"
    assert call["config"].system_instruction == "persona"
    assert call["config"].max_output_tokens == 300


def test_gemini_summarize_requests_json(gemini):
    client, fake, _ = gemini
    fake.text = '{"relationship": "colleague", "topics": ["work"]}'

    response = client.post("/summarize", json=SUMMARY_BODY, headers=HEADERS)

    context = response.json()["context"]
    assert context["relationship"] == "colleague"
    assert context["facts"] == {"city": "Tashkent"}
    assert fake.calls[0]["config"].response_mime_type == "application/json"


def test_gemini_describe_media_is_native(gemini):
    client, fake, _ = gemini
    fake.text = '{"transcript": "ertaga uchrashamiz", "description": "voice message"}'
    audio = base64.b64encode(b"OggS-audio").decode()

    response = client.post(
        "/describe-media",
        json={"api_key": "k", "media_type": "voice", "mime_type": "audio/ogg", "data_b64": audio},
        headers=HEADERS,
    )

    body = response.json()
    assert body["transcript"] == "ertaga uchrashamiz"
    assert body["text"].startswith("Transcript: ertaga uchrashamiz")
    media_part = fake.calls[0]["contents"][0]
    assert media_part.inline_data.data == b"OggS-audio"
    assert media_part.inline_data.mime_type == "audio/ogg"
