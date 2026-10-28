import asyncio

from django.db import transaction
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from .models import Account


class LoginError(Exception):
    pass


def default_client_factory(session: str, api_id: int, api_hash: str):
    return TelegramClient(StringSession(session), api_id, api_hash)


client_factory = default_client_factory


def make_client(account: Account, session: str = ""):
    return client_factory(session, account.api_id, account.get_api_hash())


def run(coro):
    return asyncio.run(coro)


def finalize(account: Account, me, session: str) -> Account:
    from .tasks import start_bootstrap

    account.set_session(session)
    account.telegram_user_id = me.id
    account.telegram_username = getattr(me, "username", None) or ""
    account.phone_code_hash = ""
    account.status = Account.Status.CONNECTED
    account.last_error = ""
    account.save()
    if account.bootstrap_status != Account.BootstrapStatus.DONE:
        transaction.on_commit(lambda: start_bootstrap.delay(account.pk))
    return account


def fail(account: Account, exc: Exception) -> None:
    account.last_error = str(exc)
    account.save(update_fields=["last_error", "updated_at"])
    raise LoginError(str(exc)) from exc


def send_code(account: Account) -> Account:
    if not account.phone:
        raise LoginError("Phone number is required")

    async def flow():
        client = make_client(account)
        await client.connect()
        try:
            sent = await client.send_code_request(account.phone)
            return sent.phone_code_hash, client.session.save()
        finally:
            await client.disconnect()

    try:
        code_hash, session = run(flow())
    except Exception as exc:
        fail(account, exc)
    account.phone_code_hash = code_hash
    account.set_session(session)
    account.status = Account.Status.CODE_SENT
    account.last_error = ""
    account.save()
    return account


def submit_code(account: Account, code: str) -> Account:
    async def flow():
        client = make_client(account, account.get_session())
        await client.connect()
        try:
            try:
                me = await client.sign_in(phone=account.phone, code=code.strip(), phone_code_hash=account.phone_code_hash)
            except SessionPasswordNeededError:
                return None, client.session.save()
            return me, client.session.save()
        finally:
            await client.disconnect()

    try:
        me, session = run(flow())
    except Exception as exc:
        fail(account, exc)
    if me is None:
        account.set_session(session)
        account.status = Account.Status.PASSWORD_NEEDED
        account.last_error = ""
        account.save()
        return account
    return finalize(account, me, session)


def submit_password(account: Account, password: str) -> Account:
    async def flow():
        client = make_client(account, account.get_session())
        await client.connect()
        try:
            me = await client.sign_in(password=password)
            return me, client.session.save()
        finally:
            await client.disconnect()

    try:
        me, session = run(flow())
    except Exception as exc:
        fail(account, exc)
    return finalize(account, me, session)
