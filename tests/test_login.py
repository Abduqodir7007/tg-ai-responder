from types import SimpleNamespace

import pytest
from telethon.errors import SessionPasswordNeededError

from core import telegram_login
from core.models import Account


class FakeTelethonClient:
    instances = []
    password_required = True

    def __init__(self, session, api_id, api_hash):
        index = len(FakeTelethonClient.instances)
        self.session = SimpleNamespace(save=lambda: f"session-{index}")
        self.started_with = session
        self.api_id = api_id
        self.api_hash = api_hash
        FakeTelethonClient.instances.append(self)

    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def send_code_request(self, phone):
        return SimpleNamespace(phone_code_hash="hash-123")

    async def sign_in(self, phone=None, code=None, phone_code_hash=None, password=None):
        if password is None and self.password_required:
            raise SessionPasswordNeededError(request=None)
        return SimpleNamespace(id=4242, username="owner")


@pytest.fixture
def fake_telethon(monkeypatch):
    FakeTelethonClient.instances = []
    monkeypatch.setattr(telegram_login, "client_factory", FakeTelethonClient)
    return FakeTelethonClient


@pytest.fixture
def new_account(db):
    account = Account(name="New", phone="+998901112233", api_id=111)
    account.set_api_hash("abcdefabcdefabcdefabcdefabcdef12")
    account.save()
    return account


def test_phone_code_password_flow(new_account, fake_telethon, celery_calls, django_capture_on_commit_callbacks):
    telegram_login.send_code(new_account)
    assert new_account.status == Account.Status.CODE_SENT
    assert new_account.phone_code_hash == "hash-123"
    assert fake_telethon.instances[0].api_hash == "abcdefabcdefabcdefabcdefabcdef12"

    telegram_login.submit_code(new_account, "12345")
    assert new_account.status == Account.Status.PASSWORD_NEEDED
    assert fake_telethon.instances[1].started_with == "session-0"

    with django_capture_on_commit_callbacks(execute=True):
        telegram_login.submit_password(new_account, "secret")

    new_account.refresh_from_db()
    assert new_account.status == Account.Status.CONNECTED
    assert new_account.telegram_user_id == 4242
    assert new_account.get_session() == "session-2"
    assert "session-2" not in new_account.session_encrypted
    assert celery_calls["start_bootstrap"] == [{"args": (new_account.pk,), "kwargs": {}}]
