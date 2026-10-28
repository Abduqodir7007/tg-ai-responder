from core import bus
from core.models import GlobalSettings, MessageLog
from core.tasks import handle_incoming
from listener.handlers import can_send


def queued(chat, make_log, msg_id, text, minutes_ago=0):
    return make_log(chat, msg_id, text, minutes_ago=minutes_ago, status=MessageLog.Status.QUEUED)


def test_reply_uses_only_stored_context_and_recent_window(gs, chat, make_log, fake_ai, bus_commands):
    for index in range(1, 40):
        direction = MessageLog.Direction.IN if index % 2 else MessageLog.Direction.OUT
        make_log(chat, index, f"old-{index}", direction=direction, minutes_ago=200 - index)
    log = queued(chat, make_log, 40, "qachon kelasan?")

    assert handle_incoming(log.pk) == "reply_queued"

    assert len(fake_ai.generate_calls) == 1
    call = fake_ai.generate_calls[0]
    texts = [part["text"] for message in call["messages"] for part in message["content"]]
    assert len(texts) <= gs.recent_messages_count
    assert texts[-1] == "qachon kelasan?"
    assert "old-1" not in texts
    assert [command["action"] for command in bus_commands] == [bus.SEND_MESSAGE]
    command = bus_commands[0]
    assert command["chat_id"] == chat.telegram_chat_id
    assert command["text"] == fake_ai.reply_text
    assert gs.reply_delay_min_seconds <= command["delay"] <= gs.reply_delay_max_seconds
    reply = MessageLog.objects.get(pk=command["log_id"])
    assert reply.status == MessageLog.Status.PENDING_SEND
    assert reply.source == MessageLog.Source.AI
    assert reply.reply_to_id == log.pk
    assert reply.input_tokens == 120
    log.refresh_from_db()
    assert log.status == MessageLog.Status.REPLIED


def test_burst_replies_only_to_last_message(gs, chat, make_log, fake_ai, bus_commands):
    first = queued(chat, make_log, 1, "salom", minutes_ago=1)
    second = queued(chat, make_log, 2, "qalaysan?", minutes_ago=1)
    last = queued(chat, make_log, 3, "javob ber", minutes_ago=0)

    results = [handle_incoming(item.pk) for item in (first, second, last)]

    assert results == ["superseded", "superseded", "reply_queued"]
    assert len(fake_ai.generate_calls) == 1
    assert len(bus_commands) == 1


def test_skips_when_owner_already_answered(gs, chat, make_log, fake_ai, bus_commands):
    log = queued(chat, make_log, 1, "salom", minutes_ago=1)
    make_log(chat, 2, "salom, hozir", direction=MessageLog.Direction.OUT)

    assert handle_incoming(log.pk) == "owner_replied"
    assert fake_ai.generate_calls == []
    assert bus_commands == []


def test_rate_limit_blocks_extra_replies(gs, chat, make_log, fake_ai, bus_commands):
    gs.max_replies_per_hour = 1
    gs.save()
    MessageLog.objects.create(
        account=chat.account,
        chat=chat,
        direction=MessageLog.Direction.OUT,
        source=MessageLog.Source.AI,
        status=MessageLog.Status.SENT,
        text="earlier ai reply",
    )
    log = queued(chat, make_log, 2, "yana savol")

    assert handle_incoming(log.pk) == "rate_limited_hourly"
    assert bus_commands == []


def test_kill_switch_checked_again_before_send(gs, chat, make_log, fake_ai, bus_commands):
    log = queued(chat, make_log, 1, "salom")
    handle_incoming(log.pk)
    reply_id = bus_commands[0]["log_id"]

    GlobalSettings.objects.update(kill_switch=True)

    assert can_send(reply_id) == "kill_switch"
    assert MessageLog.objects.get(pk=reply_id).status == MessageLog.Status.SKIPPED


def test_owner_reply_after_generation_cancels_send(gs, chat, make_log, fake_ai, bus_commands):
    log = queued(chat, make_log, 1, "salom", minutes_ago=1)
    handle_incoming(log.pk)
    reply_id = bus_commands[0]["log_id"]
    make_log(chat, 2, "men o'zim yozdim", direction=MessageLog.Direction.OUT)

    assert can_send(reply_id) == "owner_replied"


def test_missing_provider_marks_failed(gs, chat, make_log, bus_commands):
    log = queued(chat, make_log, 1, "salom")

    assert handle_incoming(log.pk) == "provider_not_configured"
    log.refresh_from_db()
    assert log.status == MessageLog.Status.FAILED
    assert bus_commands == []
