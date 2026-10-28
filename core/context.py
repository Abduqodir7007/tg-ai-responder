import json
from dataclasses import dataclass, field

from django.db.models import F, Q

from .media import image_part
from .models import Account, Chat, ContactContext, GlobalSettings, MessageLog

BASE_INSTRUCTIONS = (
    "You reply on behalf of the account owner in a private Telegram chat, in the owner's voice. "
    "If the contact sincerely asks whether they are talking to a bot or AI, or who is replying, never deny it: "
    "say briefly that this is the owner's auto-reply assistant and the owner will answer personally.\n"
    "Rules:\n"
    "1. Always reply in the language the contact writes in (English to English, Russian to Russian). "
    "Copy the owner's style from the examples: length, tone, punctuation; when replying in Uzbek also use the "
    "owner's script (Cyrillic or Latin). Usually 1 short sentence. No emojis unless the owner uses them.\n"
    "2. Answer the actual question using the contact card, the owner's other chats and the recent messages. "
    "If the answer is there, state it concretely (names, versions, numbers).\n"
    "3. Never claim you checked, sent, received or did something unless it is visible in the provided data. "
    "Never invent statuses, dates, prices or promises.\n"
    "4. If the needed fact is not in the data, ask one short clarifying question or say briefly that you will "
    "answer a bit later. Do not repeat the same stalling phrase twice in a row.\n"
    "5. Do not thank or apologise without a reason. Do not start with greetings if the conversation is ongoing.\n"
    "Return only the message text."
)
STYLE_EXAMPLES = 15
OTHER_CHAT_MESSAGES = 20


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
        .order_by(F("telegram_msg_id").desc(nulls_first=True), "-id")[:limit]
    )
    return list(reversed(list(qs)))


def owner_style_examples(account: Account, limit: int = STYLE_EXAMPLES) -> list[str]:
    qs = (
        MessageLog.objects.filter(account=account, direction=MessageLog.Direction.OUT)
        .exclude(source=MessageLog.Source.AI)
        .exclude(text="")
        .order_by(F("telegram_msg_id").desc(nulls_last=True), "-id")
        .values_list("text", flat=True)[:limit]
    )
    return [text.strip()[:200] for text in qs if text.strip()]


def other_chats_digest(chat: Chat, limit: int = OTHER_CHAT_MESSAGES) -> str:
    lines = []
    others = (
        ContactContext.objects.filter(chat__account=chat.account)
        .exclude(chat=chat)
        .exclude(chat__list_status=Chat.ListStatus.BLACKLISTED)
        .select_related("chat")
    )
    for other in others:
        if other.summary:
            lines.append(f"- {other.name or other.chat}: {other.summary[:300]}")
    logs = (
        MessageLog.objects.filter(account=chat.account)
        .exclude(chat=chat)
        .exclude(chat__list_status=Chat.ListStatus.BLACKLISTED)
        .select_related("chat")
        .order_by(F("telegram_msg_id").desc(nulls_last=True), "-id")[:limit]
    )
    recent = []
    for log in reversed(list(logs)):
        text = log.as_text()
        if not text:
            continue
        who = "owner" if log.direction == MessageLog.Direction.OUT else "contact"
        recent.append(f"- [{log.chat}] {who}: {text[:200]}")
    parts = []
    if lines:
        parts.append("Other contacts:\n" + "\n".join(lines))
    if recent:
        parts.append("Latest messages in the owner's other chats:\n" + "\n".join(recent))
    return "\n\n".join(parts)


def contact_card(context: ContactContext) -> str:
    data = {key: value for key, value in context.as_dict().items() if value}
    if not data:
        return "No stored information about this contact yet."
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_system_prompt(account: Account, context: ContactContext) -> str:
    sections = [BASE_INSTRUCTIONS]
    if account.persona_prompt.strip():
        sections.append("Owner persona and rules:\n" + account.persona_prompt.strip())
    examples = owner_style_examples(account)
    if examples:
        sections.append("Owner's real messages (style examples):\n" + "\n".join(f"- {e}" for e in examples))
    sections.append("Contact card (stored context):\n" + contact_card(context))
    digest = other_chats_digest(context.chat) if context.chat_id else ""
    if digest:
        sections.append(digest)
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
