from datetime import timedelta

from django.utils import timezone

from .models import Account, Chat, GlobalSettings, MessageLog


def reply_block_reason(account: Account, chat: Chat, gs: GlobalSettings) -> str | None:
    if gs.kill_switch:
        return "kill_switch"
    if account.status != Account.Status.CONNECTED:
        return "account_not_connected"
    if not account.auto_reply_enabled:
        return "account_paused"
    if chat.chat_type != Chat.ChatType.PRIVATE and not account.allow_groups:
        return "groups_disabled"
    if chat.is_bot:
        return "bot_chat"
    if not chat.auto_reply_enabled:
        return "chat_disabled"
    if account.chat_filter_mode == Account.FilterMode.WHITELIST and chat.list_status != Chat.ListStatus.WHITELISTED:
        return "not_whitelisted"
    if account.chat_filter_mode == Account.FilterMode.BLACKLIST and chat.list_status == Chat.ListStatus.BLACKLISTED:
        return "blacklisted"
    return None


def is_superseded(log: MessageLog) -> bool:
    return MessageLog.objects.filter(
        chat=log.chat,
        direction=MessageLog.Direction.IN,
        source=MessageLog.Source.TELEGRAM,
        pk__gt=log.pk,
    ).exists()


def owner_replied_since(chat: Chat, since) -> bool:
    return MessageLog.objects.filter(
        chat=chat,
        direction=MessageLog.Direction.OUT,
        source=MessageLog.Source.OWNER,
        created_at__gte=since,
    ).exists()


def rate_limit_reason(chat: Chat, gs: GlobalSettings) -> str | None:
    now = timezone.now()
    ai_replies = MessageLog.objects.filter(
        chat=chat,
        direction=MessageLog.Direction.OUT,
        source=MessageLog.Source.AI,
        status__in=[MessageLog.Status.SENT, MessageLog.Status.PENDING_SEND],
    )
    if gs.min_seconds_between_replies and ai_replies.filter(
        created_at__gte=now - timedelta(seconds=gs.min_seconds_between_replies)
    ).exists():
        return "rate_limited_interval"
    if ai_replies.filter(created_at__gte=now - timedelta(hours=1)).count() >= gs.max_replies_per_hour:
        return "rate_limited_hourly"
    return None
