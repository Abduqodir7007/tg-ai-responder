import logging
import random
from datetime import timedelta

from celery import shared_task
from django.db.models import F, Q
from django.utils import timezone

from . import bus
from .ai_client import AIClient, AIServiceError, ProviderNotConfigured
from .context import build_reply_context, get_contact_context, serialize_for_summary
from .media import ensure_transcript
from .models import Account, Chat, ContactContext, GlobalSettings, MessageLog
from .policy import is_superseded, owner_replied_since, rate_limit_reason, reply_block_reason

logger = logging.getLogger(__name__)


def register_new_message(chat: Chat, gs: GlobalSettings | None = None) -> bool:
    gs = gs or GlobalSettings.load()
    Chat.objects.filter(pk=chat.pk).update(
        messages_since_summary=F("messages_since_summary") + 1,
        last_message_at=timezone.now(),
    )
    chat.refresh_from_db(fields=["messages_since_summary", "last_message_at"])
    threshold = gs.resummarize_every_n_messages
    if threshold and chat.messages_since_summary == threshold:
        summarize_chat.delay(chat.pk, "update")
        return True
    return False


def skip(log: MessageLog, reason: str) -> str:
    log.status = MessageLog.Status.SKIPPED
    log.error = reason
    log.save(update_fields=["status", "error"])
    return reason


def reply_delay(gs: GlobalSettings) -> float:
    low = min(gs.reply_delay_min_seconds, gs.reply_delay_max_seconds)
    high = max(gs.reply_delay_min_seconds, gs.reply_delay_max_seconds)
    return random.uniform(low, high)


@shared_task
def handle_incoming(log_id: int) -> str:
    log = MessageLog.objects.select_related("chat", "account").filter(pk=log_id).first()
    if log is None or log.status != MessageLog.Status.QUEUED:
        return "not_queued"
    chat, account = log.chat, log.account
    gs = GlobalSettings.load()

    reason = reply_block_reason(account, chat, gs)
    if reason:
        return skip(log, reason)
    if is_superseded(log):
        return skip(log, "superseded")
    if owner_replied_since(chat, log.created_at):
        return skip(log, "owner_replied")
    reason = rate_limit_reason(chat, gs)
    if reason:
        return skip(log, reason)

    try:
        client = AIClient.for_account(account, gs)
    except ProviderNotConfigured as exc:
        log.status = MessageLog.Status.FAILED
        log.error = str(exc)
        log.save(update_fields=["status", "error"])
        return "provider_not_configured"

    context = build_reply_context(chat, gs)
    if any(item.needs_transcript for item in context.recent):
        for item in context.recent:
            ensure_transcript(item, client)
        context = build_reply_context(chat, gs)
    if not context.messages:
        return skip(log, "empty_context")

    try:
        result = client.generate(system=context.system, messages=context.messages, max_tokens=gs.reply_max_tokens)
    except AIServiceError as exc:
        log.status = MessageLog.Status.FAILED
        log.error = str(exc)
        log.save(update_fields=["status", "error"])
        return "ai_failed"

    text = (result.get("text") or "").strip()
    if not text:
        return skip(log, "empty_reply")

    reply = MessageLog.objects.create(
        account=account,
        chat=chat,
        direction=MessageLog.Direction.OUT,
        source=MessageLog.Source.AI,
        status=MessageLog.Status.PENDING_SEND,
        text=text,
        provider=client.provider,
        input_tokens=int(result.get("input_tokens") or 0),
        output_tokens=int(result.get("output_tokens") or 0),
        reply_to=log,
    )
    log.status = MessageLog.Status.REPLIED
    log.provider = client.provider
    log.save(update_fields=["status", "provider"])
    bus.send_message(account.pk, chat.telegram_chat_id, text, reply.pk, reply_delay(gs))
    return "reply_queued"


def chunked(items: list, size: int):
    size = max(size, 1)
    for start in range(0, len(items), size):
        yield items[start : start + size]


@shared_task
def summarize_chat(chat_id: int, mode: str = "update") -> int:
    chat = Chat.objects.select_related("account").filter(pk=chat_id).first()
    if chat is None:
        return 0
    gs = GlobalSettings.load()
    context = get_contact_context(chat)
    pending = (
        MessageLog.objects.filter(chat=chat, telegram_msg_id__gt=context.last_summarized_msg_id)
        .filter(Q(direction=MessageLog.Direction.IN) | Q(status=MessageLog.Status.SENT))
        .order_by("-telegram_msg_id")[: gs.summary_max_messages]
    )
    logs = sorted(pending, key=lambda item: item.telegram_msg_id)
    if not logs:
        Chat.objects.filter(pk=chat.pk).update(messages_since_summary=0)
        return 0
    try:
        client = AIClient.for_account(chat.account, gs)
    except ProviderNotConfigured as exc:
        logger.warning("Cannot summarize chat %s: %s", chat.pk, exc)
        return 0

    calls = 0
    for chunk in chunked(logs, gs.summary_chunk_size):
        lines = serialize_for_summary(chunk)
        if lines:
            try:
                result = client.summarize(existing=context.as_dict(), messages=lines, mode=mode)
            except AIServiceError as exc:
                logger.warning("Summarize failed for chat %s: %s", chat.pk, exc)
                break
            context.apply(result.get("context") or {})
            calls += 1
        context.last_summarized_msg_id = chunk[-1].telegram_msg_id
        context.save()
    Chat.objects.filter(pk=chat.pk).update(messages_since_summary=0)
    return calls


@shared_task
def maintain_contexts() -> int:
    gs = GlobalSettings.load()
    stale_before = timezone.now() - timedelta(hours=gs.context_refresh_hours)
    threshold = max(gs.resummarize_every_n_messages, 1)
    due = Chat.objects.filter(account__status=Account.Status.CONNECTED).filter(
        Q(messages_since_summary__gte=threshold)
        | (
            Q(messages_since_summary__gt=0)
            & (Q(context__isnull=True) | Q(context__updated_at__lt=stale_before))
        )
    )
    count = 0
    for chat_id in due.values_list("pk", flat=True):
        summarize_chat.delay(chat_id, "update")
        count += 1
    return count


@shared_task
def start_bootstrap(account_id: int) -> bool:
    account = Account.objects.filter(pk=account_id).first()
    if account is None or not account.is_connected:
        return False
    gs = GlobalSettings.load()
    account.bootstrap_status = Account.BootstrapStatus.RUNNING
    account.save(update_fields=["bootstrap_status"])
    bus.request_bootstrap(account.pk, gs.bootstrap_dialog_limit, gs.bootstrap_messages_per_dialog)
    return True


@shared_task
def rebootstrap_chat(chat_id: int) -> bool:
    chat = Chat.objects.select_related("account").filter(pk=chat_id).first()
    if chat is None or not chat.account.is_connected:
        return False
    gs = GlobalSettings.load()
    ContactContext.objects.filter(chat=chat).delete()
    ContactContext.objects.create(chat=chat)
    bus.request_chat_history(chat.account.pk, chat.telegram_chat_id, gs.bootstrap_messages_per_dialog)
    return True
