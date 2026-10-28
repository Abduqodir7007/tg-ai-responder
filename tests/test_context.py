from core.context import build_reply_context, get_contact_context
from core.models import MessageLog


def all_text(messages):
    return [part["text"] for message in messages for part in message["content"] if part["type"] == "text"]


def test_reply_context_uses_stored_card_and_last_eight_messages(gs, chat, make_log):
    context = get_contact_context(chat)
    context.name = "Ali"
    context.relationship = "university friend"
    context.summary = "Discussed a trip to Samarkand."
    context.facts = {"birthday": "12 May"}
    context.save()
    for index in range(1, 31):
        direction = MessageLog.Direction.IN if index % 2 else MessageLog.Direction.OUT
        make_log(chat, index, f"msg-{index}", direction=direction, minutes_ago=100 - index)

    result = build_reply_context(chat, gs)

    assert [log.telegram_msg_id for log in result.recent] == list(range(23, 31))
    texts = all_text(result.messages)
    assert "msg-1" not in texts
    assert all(int(text.split("-")[1]) >= 23 for text in texts)
    assert "university friend" in result.system
    assert "Samarkand" in result.system
    assert "12 May" in result.system
    assert "Jasur" in result.system


def test_messages_start_and_end_with_user_and_merge_roles(gs, chat, make_log):
    make_log(chat, 1, "owner first", direction=MessageLog.Direction.OUT, minutes_ago=10)
    make_log(chat, 2, "hi", minutes_ago=9)
    make_log(chat, 3, "are you there?", minutes_ago=8)
    make_log(chat, 4, "yes", direction=MessageLog.Direction.OUT, minutes_ago=7)
    make_log(chat, 5, "great", minutes_ago=6)

    messages = build_reply_context(chat, gs).messages

    assert [message["role"] for message in messages] == ["user", "assistant", "user"]
    assert all_text(messages[:1]) == ["hi", "are you there?"]


def test_unsent_ai_replies_are_not_part_of_context(gs, chat, make_log):
    make_log(chat, 1, "hello", minutes_ago=5)
    MessageLog.objects.create(
        account=chat.account,
        chat=chat,
        direction=MessageLog.Direction.OUT,
        source=MessageLog.Source.AI,
        status=MessageLog.Status.SKIPPED,
        text="draft that was never sent",
    )

    messages = build_reply_context(chat, gs).messages

    assert "draft that was never sent" not in all_text(messages)


def test_photo_is_sent_to_ai_as_image(gs, chat, make_log, media_root):
    (media_root / "photo.jpg").write_bytes(b"\xff\xd8fake-jpeg")
    make_log(chat, 1, "look at this", media_type=MessageLog.MediaType.PHOTO, media_path="photo.jpg",
             media_mime="image/jpeg")

    messages = build_reply_context(chat, gs).messages

    parts = messages[-1]["content"]
    assert parts[0]["type"] == "image"
    assert parts[0]["mime_type"] == "image/jpeg"
    assert parts[1]["text"] == "[photo] look at this"
