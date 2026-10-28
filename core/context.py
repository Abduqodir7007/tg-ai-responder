import json
from dataclasses import dataclass, field

from django.db.models import Q

from .media import image_part
from .models import Account, Chat, ContactContext, GlobalSettings, MessageLog

BASE_INSTRUCTIONS = (
    "You are replying on behalf of the account owner in a private Telegram chat. "
    "Write as the owner would: short, natural, human messages in the contact's language and tone. "
    "Use the contact card and recent messages; do not invent facts or commitments. "
    "If something needs the owner's personal decision, answer politely and say you will get back later. "
    "Return only the message text."
)


@dataclass
class ReplyContext:
    system: str
    messages: list[dict]
    recent: list[MessageLog] = field(default_factory=list)


def get_contact_context(chat: Chat) -> ContactContext:
    context, _ = ContactContext.objects.get_or_create(chat=chat)
    return context


def recent_messages(chat: Chat, limit: int) -> list[MessageLog]:
    qs = (
        MessageLog.objects.filter(chat=chat)
        .filter(Q(direction=MessageLog.Direction.IN) | Q(status=MessageLog.Status.SENT))
        .order_by("-created_at", "-id")[:limit]
    )
    return list(reversed(list(qs)))


def contact_card(context: ContactContext) -> str:
    data = {key: value for key, value in context.as_dict().items() if value}
    if not data:
        return "No stored information about this contact yet."
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_system_prompt(account: Account, context: ContactContext) -> str:
    sections = [BASE_INSTRUCTIONS]
    if account.persona_prompt.strip():
        sections.append("Owner persona and rules:\n" + account.persona_prompt.strip())
    sections.append("Contact card (stored context):\n" + contact_card(context))
    return "\n\n".join(sections)


def to_role(log: MessageLog) -> str:
    return "user" if log.direction == MessageLog.Direction.IN else "assistant"


def build_messages(recent: list[MessageLog], max_images: int) -> list[dict]:
    photo_ids = [
        log.pk
        for log in reversed(recent)
        if log.media_type == MessageLog.MediaType.PHOTO and log.direction == MessageLog.Direction.IN
    ]
    image_ids = set(photo_ids[:max_images])
    messages: list[dict] = []
    for log in recent:
        parts = []
        if log.pk in image_ids:
            part = image_part(log)
            if part:
                parts.append(part)
        text = log.as_text()
        if text:
            parts.append({"type": "text", "text": text})
        if not parts:
            continue
        role = to_role(log)
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(parts)
        else:
            messages.append({"role": role, "content": parts})
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    while messages and messages[-1]["role"] != "user":
        messages.pop()
    return messages


def build_reply_context(chat: Chat, gs: GlobalSettings) -> ReplyContext:
    context = get_contact_context(chat)
    recent = recent_messages(chat, gs.recent_messages_count)
    return ReplyContext(
        system=build_system_prompt(chat.account, context),
        messages=build_messages(recent, gs.max_images_in_reply),
        recent=recent,
    )


def serialize_for_summary(logs: list[MessageLog]) -> list[dict]:
    return [
        {
            "id": log.telegram_msg_id,
            "role": "contact" if log.direction == MessageLog.Direction.IN else "owner",
            "date": log.created_at.isoformat(),
            "text": log.as_text(),
        }
        for log in logs
        if log.as_text()
    ]
