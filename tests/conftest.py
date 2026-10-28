import copy
import sys
from collections import defaultdict
from datetime import timedelta

import django
import pytest
from django.template.context import BaseContext
from django.utils import timezone

from core import bus
from core.ai_client import AIClient
from core.models import Account, Chat, GlobalSettings, MessageLog, ProviderConfig
from core.tasks import handle_incoming, rebootstrap_chat, start_bootstrap, summarize_chat


def _context_copy(self):
    duplicate = object.__new__(self.__class__)
    duplicate.__dict__ = copy.copy(self.__dict__)
    duplicate.dicts = self.dicts[:]
    return duplicate


if sys.version_info >= (3, 14) and django.VERSION < (5, 2):
    BaseContext.__copy__ = _context_copy


class FakeAIClient:
    provider = "claude"

    def __init__(self):
        self.generate_calls = []
        self.summarize_calls = []
        self.describe_calls = []
        self.reply_text = "Salom! Hozir band edim, keyinroq yozaman."
        self.summary_context = {
            "name": "Ali",
            "relationship": "friend",
            "language": "uz",
            "summary": "Ali is planning a trip.",
            "facts": {"city": "Samarkand"},
            "open_tasks": ["send photos"],
        }
        self.describe_result = {"text": "Transcript: ertaga uchrashamizmi?", "input_tokens": 7, "output_tokens": 4}
        self.describe_error = None

    def generate(self, system, messages, max_tokens=800):
        self.generate_calls.append({"system": system, "messages": messages, "max_tokens": max_tokens})
        return {"text": self.reply_text, "input_tokens": 120, "output_tokens": 12}

    def summarize(self, existing, messages, mode="update"):
        self.summarize_calls.append({"existing": existing, "messages": messages, "mode": mode})
        return {"context": self.summary_context}

    def describe_media(self, media_type, mime_type, data):
        self.describe_calls.append({"media_type": media_type, "mime_type": mime_type, "data": data})
        if self.describe_error:
            raise self.describe_error
        return self.describe_result


@pytest.fixture(autouse=True)
def bus_commands(monkeypatch):
    commands = []
    monkeypatch.setattr(bus, "push", commands.append)
    return commands


@pytest.fixture(autouse=True)
def celery_calls(monkeypatch):
    calls = defaultdict(list)

    def recorder(name):
        def delay(*args, **kwargs):
            calls[name].append({"args": args, "kwargs": kwargs})

        return delay

    for task in (summarize_chat, start_bootstrap, rebootstrap_chat):
        monkeypatch.setattr(task, "delay", recorder(task.name.rsplit(".", 1)[-1]))
    monkeypatch.setattr(handle_incoming, "apply_async", recorder("handle_incoming"))
    return calls


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.MEDIA_ROOT.mkdir()
    return settings.MEDIA_ROOT


@pytest.fixture
def gs(db):
    settings = GlobalSettings.load()
    settings.burst_window_seconds = 20
    settings.min_seconds_between_replies = 0
    settings.save()
    return settings


@pytest.fixture
def providers(db):
    claude = ProviderConfig(provider="claude")
    claude.set_api_key("sk-ant-test-claude-key")
    claude.save()
    gemini = ProviderConfig(provider="gemini", model="gemini-test-model")
    gemini.set_api_key("gemini-test-key-123")
    gemini.save()
    return {"claude": claude, "gemini": gemini}


@pytest.fixture
def account(db):
    obj = Account(
        name="Owner",
        phone="+998900000000",
        api_id=12345,
        status=Account.Status.CONNECTED,
        auto_reply_enabled=True,
        telegram_user_id=1000,
        persona_prompt="I am Jasur, a software engineer. Keep replies short.",
    )
    obj.set_api_hash("0123456789abcdef0123456789abcdef")
    obj.set_session("fake-session-string")
    obj.save()
    return obj


@pytest.fixture
def chat(account):
    return Chat.objects.create(account=account, telegram_chat_id=555, title="Ali", chat_type=Chat.ChatType.PRIVATE)


@pytest.fixture
def fake_ai(monkeypatch):
    client = FakeAIClient()
    monkeypatch.setattr(AIClient, "for_account", classmethod(lambda cls, account, gs=None, transport=None: client))
    return client


@pytest.fixture
def make_log():
    def factory(chat, msg_id, text="", direction=MessageLog.Direction.IN, minutes_ago=0, **extra):
        defaults = {
            "source": MessageLog.Source.TELEGRAM if direction == MessageLog.Direction.IN else MessageLog.Source.OWNER,
            "status": MessageLog.Status.RECEIVED if direction == MessageLog.Direction.IN else MessageLog.Status.SENT,
        }
        defaults.update(extra)
        return MessageLog.objects.create(
            account=chat.account,
            chat=chat,
            telegram_msg_id=msg_id,
            direction=direction,
            text=text,
            created_at=timezone.now() - timedelta(minutes=minutes_ago),
            **defaults,
        )

    return factory
