from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from core.models import Account, Chat, GlobalSettings, MessageLog
from core.policy import owner_replied_since, reply_block_reason
from core.tasks import handle_incoming, register_new_message, summarize_chat


@dataclass
class ChatInfo:
    chat_id: int
    chat_type: str = Chat.ChatType.PRIVATE
    title: str = ""
    username: str = ""
    is_bot: bool = False


@dataclass
class EventInfo:
    chat: ChatInfo
    message_id: int
    outgoing: bool
    sender_id: int | None = None
    text: str = ""
    media_type: str = MessageLog.MediaType.TEXT
    media_path: str = ""
    media_mime: str = ""
    date: datetime | None = None
    from_ai: bool = False
    extra: dict = field(default_factory=dict)


def upsert_chat(account: Account, info: ChatInfo) -> Chat:
    chat, created = Chat.objects.get_or_create(
        account=account,
        telegram_chat_id=info.chat_id,
        defaults={
            "chat_type": info.chat_type,
            "title": info.title[:255],
            "username": info.username[:64],
            "is_bot": info.is_bot,
            "auto_reply_enabled": info.chat_type == Chat.ChatType.PRIVATE,
        },
    )
    if not created:
        changed = []
        for attr, value in (("title", info.title[:255]), ("username", info.username[:64])):
            if value and getattr(chat, attr) != value:
                setattr(chat, attr, value)
                changed.append(attr)
        if changed:
            chat.save(update_fields=changed)
    return chat


def is_ignored_chat(account: Account, chat: Chat) -> bool:
    if chat.chat_type == Chat.ChatType.PRIVATE:
        return False
    return not (account.allow_groups and chat.auto_reply_enabled)


def process_event(account_id: int, info: EventInfo) -> str:
    account = Account.objects.get(pk=account_id)
    gs = GlobalSettings.load()
    chat = upsert_chat(account, info.chat)

    if is_ignored_chat(account, chat):
        return "ignored_chat_type"

    if info.outgoing:
        if info.from_ai:
            return "own_ai_message"
        MessageLog.objects.get_or_create(
            chat=chat,
            telegram_msg_id=info.message_id,
            defaults={
                "account": account,
                "direction": MessageLog.Direction.OUT,
                "source": MessageLog.Source.OWNER,
                "status": MessageLog.Status.SENT,
                "text": info.text,
                "media_type": info.media_type,
                "media_path": info.media_path,
                "media_mime": info.media_mime,
                "sent_at": info.date or timezone.now(),
            },
        )
        register_new_message(chat, gs)
        return "owner_message"

    if account.telegram_user_id and info.sender_id == account.telegram_user_id:
        return "own_message"

    log, created = MessageLog.objects.get_or_create(
        chat=chat,
        telegram_msg_id=info.message_id,
        defaults={
            "account": account,
            "direction": MessageLog.Direction.IN,
            "source": MessageLog.Source.TELEGRAM,
            "text": info.text,
            "media_type": info.media_type,
            "media_path": info.media_path,
            "media_mime": info.media_mime,
        },
    )
    if not created:
        return "duplicate"
    register_new_message(chat, gs)

    reason = reply_block_reason(account, chat, gs)
    if reason:
        log.status = MessageLog.Status.SKIPPED
        log.error = reason
        log.save(update_fields=["status", "error"])
        return reason

    log.status = MessageLog.Status.QUEUED
    log.save(update_fields=["status"])
    handle_incoming.apply_async(args=[log.pk], countdown=gs.burst_window_seconds)
    return "queued"


def can_send(log_id: int) -> str | None:
    log = MessageLog.objects.select_related("chat", "account", "reply_to").filter(pk=log_id).first()
    if log is None or log.status != MessageLog.Status.PENDING_SEND:
        return "not_pending"
    gs = GlobalSettings.load()
    reason = reply_block_reason(log.account, log.chat, gs)
    if reason:
        mark_skipped(log_id, reason)
        return reason
    since = log.reply_to.created_at if log.reply_to else log.created_at
    if owner_replied_since(log.chat, since):
        mark_skipped(log_id, "owner_replied")
        return "owner_replied"
    return None


def mark_skipped(log_id: int, reason: str) -> None:
    MessageLog.objects.filter(pk=log_id).update(status=MessageLog.Status.SKIPPED, error=reason)


def mark_sent(log_id: int, telegram_msg_id: int) -> None:
    MessageLog.objects.filter(pk=log_id).update(
        status=MessageLog.Status.SENT,
        telegram_msg_id=telegram_msg_id,
        sent_at=timezone.now(),
    )


def mark_failed(log_id: int, error: str) -> None:
    MessageLog.objects.filter(pk=log_id).update(status=MessageLog.Status.FAILED, error=error[:2000])


def store_history(account_id: int, chat_info: ChatInfo, messages: list[EventInfo]) -> Chat:
    account = Account.objects.get(pk=account_id)
    chat = upsert_chat(account, chat_info)
    existing = set(
        MessageLog.objects.filter(chat=chat, telegram_msg_id__isnull=False).values_list("telegram_msg_id", flat=True)
    )
    rows = [
        MessageLog(
            account=account,
            chat=chat,
            telegram_msg_id=item.message_id,
            direction=MessageLog.Direction.OUT if item.outgoing else MessageLog.Direction.IN,
            source=MessageLog.Source.BOOTSTRAP,
            status=MessageLog.Status.SENT if item.outgoing else MessageLog.Status.RECEIVED,
            text=item.text,
            media_type=item.media_type,
            created_at=item.date or timezone.now(),
        )
        for item in messages
        if item.message_id not in existing
    ]
    MessageLog.objects.bulk_create(rows, ignore_conflicts=True)
    return chat


def finish_history(chat_id: int) -> None:
    summarize_chat.delay(chat_id, "bootstrap")


def set_bootstrap_status(account_id: int, status: str) -> None:
    updates = {"bootstrap_status": status}
    if status == Account.BootstrapStatus.DONE:
        updates["bootstrapped_at"] = timezone.now()
    Account.objects.filter(pk=account_id).update(**updates)


def connected_accounts() -> list[dict]:
    return [
        {
            "id": account.pk,
            "api_id": account.api_id,
            "api_hash": account.get_api_hash(),
            "session": account.get_session(),
            "updated_at": account.updated_at,
        }
        for account in Account.objects.filter(status=Account.Status.CONNECTED).exclude(session_encrypted="")
    ]


def set_account_error(account_id: int, error: str) -> None:
    Account.objects.filter(pk=account_id).update(status=Account.Status.ERROR, last_error=error[:2000])


def set_account_identity(account_id: int, user_id: int, username: str) -> None:
    Account.objects.filter(pk=account_id).update(telegram_user_id=user_id, telegram_username=username or "")
