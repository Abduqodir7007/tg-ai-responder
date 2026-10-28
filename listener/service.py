import asyncio
import json
import logging
from pathlib import Path

import redis.asyncio as aioredis
from asgiref.sync import sync_to_async
from django.conf import settings
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from core import bus
from core.models import Account, Chat, MessageLog

from . import handlers
from .handlers import ChatInfo, EventInfo

logger = logging.getLogger(__name__)


def detect_media(message) -> str:
    if message.photo:
        return MessageLog.MediaType.PHOTO
    if message.video_note:
        return MessageLog.MediaType.VIDEO_NOTE
    if message.voice:
        return MessageLog.MediaType.VOICE
    if message.video or message.gif:
        return MessageLog.MediaType.VIDEO
    if message.audio:
        return MessageLog.MediaType.AUDIO
    if message.sticker:
        return MessageLog.MediaType.STICKER
    if message.document:
        return MessageLog.MediaType.DOCUMENT
    if message.media:
        return MessageLog.MediaType.OTHER
    return MessageLog.MediaType.TEXT


DOWNLOADABLE = {
    MessageLog.MediaType.PHOTO,
    MessageLog.MediaType.VIDEO,
    MessageLog.MediaType.VIDEO_NOTE,
    MessageLog.MediaType.VOICE,
    MessageLog.MediaType.AUDIO,
}


def chat_type_of(event_or_dialog) -> str:
    if getattr(event_or_dialog, "is_group", False):
        return Chat.ChatType.GROUP
    if getattr(event_or_dialog, "is_channel", False):
        return Chat.ChatType.CHANNEL
    return Chat.ChatType.PRIVATE


def chat_info_from_entity(chat_id: int, chat_type: str, entity) -> ChatInfo:
    title = getattr(entity, "title", None)
    if not title:
        names = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
        title = " ".join(name for name in names if name)
    return ChatInfo(
        chat_id=chat_id,
        chat_type=chat_type,
        title=title or "",
        username=getattr(entity, "username", None) or "",
        is_bot=bool(getattr(entity, "bot", False)),
    )


class AccountConnection:
    def __init__(self, account_id: int, client: TelegramClient, me):
        self.account_id = account_id
        self.client = client
        self.me = me
        self.pending_texts: set[tuple[int, str]] = set()
        self.sent_ids: set[int] = set()


class ListenerService:
    def __init__(self):
        self.connections: dict[int, AccountConnection] = {}
        self.fingerprints: dict[int, str] = {}
        self.redis = aioredis.from_url(settings.REDIS_URL, socket_timeout=30, health_check_interval=30)
        self.media_root = Path(settings.MEDIA_ROOT)

    async def run(self):
        await asyncio.gather(self.sync_accounts_forever(), self.consume_commands_forever())

    async def sync_accounts_forever(self):
        while True:
            try:
                await self.sync_accounts()
            except Exception:
                logger.exception("Account sync failed")
            await asyncio.sleep(settings.LISTENER_ACCOUNT_SYNC_SECONDS)

    async def sync_accounts(self):
        accounts = await sync_to_async(handlers.connected_accounts)()
        wanted = {item["id"]: item for item in accounts}
        for account_id in list(self.connections):
            fingerprint = wanted.get(account_id, {}).get("session")
            if account_id not in wanted or fingerprint != self.fingerprints.get(account_id):
                await self.stop_account(account_id)
        for account_id, item in wanted.items():
            if account_id not in self.connections:
                await self.start_account(item)

    async def start_account(self, item: dict):
        client = TelegramClient(StringSession(item["session"]), item["api_id"], item["api_hash"])
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                await sync_to_async(handlers.set_account_error)(item["id"], "Session is not authorized")
                return
            me = await client.get_me()
        except Exception as exc:
            logger.exception("Cannot start account %s", item["id"])
            await sync_to_async(handlers.set_account_error)(item["id"], str(exc))
            return
        await sync_to_async(handlers.set_account_identity)(item["id"], me.id, me.username)
        connection = AccountConnection(item["id"], client, me)

        async def on_message(event):
            await self.on_message(connection, event)

        client.add_event_handler(on_message, events.NewMessage())
        self.connections[item["id"]] = connection
        self.fingerprints[item["id"]] = item["session"]
        logger.info("Account %s connected as %s", item["id"], me.id)

    async def stop_account(self, account_id: int):
        connection = self.connections.pop(account_id, None)
        self.fingerprints.pop(account_id, None)
        if connection:
            await connection.client.disconnect()
            logger.info("Account %s disconnected", account_id)

    async def on_message(self, connection: AccountConnection, event):
        try:
            info = await self.build_event_info(connection, event)
            result = await sync_to_async(handlers.process_event)(connection.account_id, info)
            logger.debug("Account %s message %s: %s", connection.account_id, info.message_id, result)
        except Exception:
            logger.exception("Failed to process message for account %s", connection.account_id)

    async def build_event_info(self, connection: AccountConnection, event) -> EventInfo:
        message = event.message
        chat_type = chat_type_of(event)
        entity = await event.get_chat()
        chat = chat_info_from_entity(event.chat_id, chat_type, entity)
        text = message.message or ""
        from_ai = bool(message.out) and (
            message.id in connection.sent_ids or (event.chat_id, text) in connection.pending_texts
        )
        media_type = detect_media(message)
        media_path, media_mime = "", ""
        if media_type in DOWNLOADABLE and chat_type == Chat.ChatType.PRIVATE and not from_ai:
            media_path, media_mime = await self.download(connection.account_id, event.chat_id, message)
        return EventInfo(
            chat=chat,
            message_id=message.id,
            outgoing=bool(message.out),
            sender_id=message.sender_id,
            text=text,
            media_type=media_type,
            media_path=media_path,
            media_mime=media_mime,
            date=message.date,
            from_ai=from_ai,
        )

    async def download(self, account_id: int, chat_id: int, message) -> tuple[str, str]:
        file = message.file
        if file is not None and file.size and file.size > settings.MAX_MEDIA_BYTES:
            return "", ""
        relative = Path(str(account_id)) / str(chat_id) / f"{message.id}{(file.ext if file else '') or ''}"
        target = self.media_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            await message.download_media(file=str(target))
        except Exception:
            logger.exception("Media download failed for message %s", message.id)
            return "", ""
        return relative.as_posix(), (file.mime_type if file else "") or ""

    async def consume_commands_forever(self):
        while True:
            try:
                item = await self.redis.blpop([settings.TELEGRAM_OUTBOX_KEY], timeout=5)
            except Exception:
                logger.exception("Redis read failed")
                await asyncio.sleep(3)
                continue
            if not item:
                continue
            try:
                command = json.loads(item[1])
            except (TypeError, ValueError):
                logger.warning("Invalid command payload: %r", item[1])
                continue
            asyncio.create_task(self.dispatch(command))

    async def dispatch(self, command: dict):
        action = command.get("action")
        connection = self.connections.get(command.get("account_id"))
        if connection is None:
            logger.warning("No live connection for command %s", command)
            if action == bus.SEND_MESSAGE:
                await sync_to_async(handlers.mark_failed)(command["log_id"], "account_offline")
            return
        try:
            if action == bus.SEND_MESSAGE:
                await self.send_reply(connection, command)
            elif action == bus.BOOTSTRAP_DIALOGS:
                await self.bootstrap(connection, command)
            elif action == bus.FETCH_CHAT_HISTORY:
                await self.fetch_chat_history(connection, command)
        except Exception as exc:
            logger.exception("Command %s failed", action)
            if action == bus.SEND_MESSAGE:
                await sync_to_async(handlers.mark_failed)(command["log_id"], str(exc))
            if action == bus.BOOTSTRAP_DIALOGS:
                await sync_to_async(handlers.set_bootstrap_status)(
                    connection.account_id, Account.BootstrapStatus.FAILED
                )

    async def resolve(self, client: TelegramClient, chat_id: int):
        try:
            return await client.get_input_entity(chat_id)
        except ValueError:
            await client.get_dialogs()
            return await client.get_input_entity(chat_id)

    async def send_reply(self, connection: AccountConnection, command: dict):
        log_id = command["log_id"]
        if await sync_to_async(handlers.can_send)(log_id):
            return
        client = connection.client
        entity = await self.resolve(client, command["chat_id"])
        await client.send_read_acknowledge(entity)
        async with client.action(entity, "typing"):
            await asyncio.sleep(float(command.get("delay") or 0))
        if await sync_to_async(handlers.can_send)(log_id):
            return
        key = (command["chat_id"], command["text"])
        connection.pending_texts.add(key)
        try:
            message = await client.send_message(entity, command["text"])
            connection.sent_ids.add(message.id)
            await sync_to_async(handlers.mark_sent)(log_id, message.id)
        finally:
            asyncio.get_running_loop().call_later(60, connection.pending_texts.discard, key)

    async def collect_history(self, client: TelegramClient, entity, limit: int) -> list[EventInfo]:
        items = []
        async for message in client.iter_messages(entity, limit=limit):
            if message.action is not None:
                continue
            items.append(
                EventInfo(
                    chat=None,
                    message_id=message.id,
                    outgoing=bool(message.out),
                    sender_id=message.sender_id,
                    text=message.message or "",
                    media_type=detect_media(message),
                    date=message.date,
                )
            )
        return items

    async def bootstrap(self, connection: AccountConnection, command: dict):
        client = connection.client
        async for dialog in client.iter_dialogs(limit=command["dialog_limit"]):
            entity = dialog.entity
            if not dialog.is_user or getattr(entity, "bot", False) or getattr(entity, "is_self", False):
                continue
            await self.import_dialog(client, connection.account_id, dialog.id, entity, command["messages_per_dialog"])
            await asyncio.sleep(1)
        await sync_to_async(handlers.set_bootstrap_status)(connection.account_id, Account.BootstrapStatus.DONE)

    async def fetch_chat_history(self, connection: AccountConnection, command: dict):
        client = connection.client
        entity = await client.get_entity(await self.resolve(client, command["chat_id"]))
        await self.import_dialog(client, connection.account_id, command["chat_id"], entity, command["limit"])

    async def import_dialog(self, client, account_id: int, chat_id: int, entity, limit: int):
        while True:
            try:
                history = await self.collect_history(client, entity, limit)
                break
            except FloodWaitError as exc:
                await asyncio.sleep(exc.seconds + 1)
        chat_info = chat_info_from_entity(chat_id, Chat.ChatType.PRIVATE, entity)
        chat = await sync_to_async(handlers.store_history)(account_id, chat_info, history)
        await sync_to_async(handlers.finish_history)(chat.pk)
