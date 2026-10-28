from core.models import Account, Chat, GlobalSettings, MessageLog
from listener.handlers import ChatInfo, EventInfo, process_event


def event(message_id=1, outgoing=False, chat_type=Chat.ChatType.PRIVATE, chat_id=555, sender_id=777, **extra):
    return EventInfo(
        chat=ChatInfo(chat_id=chat_id, chat_type=chat_type, title="Ali"),
        message_id=message_id,
        outgoing=outgoing,
        sender_id=sender_id,
        text=extra.pop("text", "salom"),
        **extra,
    )


def test_private_message_is_stored_and_queued_with_burst_delay(gs, account, celery_calls):
    assert process_event(account.pk, event()) == "queued"

    log = MessageLog.objects.get()
    assert log.status == MessageLog.Status.QUEUED
    assert log.direction == MessageLog.Direction.IN
    call = celery_calls["handle_incoming"][0]
    assert call["kwargs"] == {"args": [log.pk], "countdown": gs.burst_window_seconds}


def test_own_manual_message_is_logged_but_never_replied(gs, account, celery_calls):
    assert process_event(account.pk, event(outgoing=True, sender_id=1000, text="o'zim yozdim")) == "owner_message"

    log = MessageLog.objects.get()
    assert log.source == MessageLog.Source.OWNER
    assert log.direction == MessageLog.Direction.OUT
    assert celery_calls["handle_incoming"] == []


def test_own_ai_message_echo_is_ignored(gs, account, celery_calls):
    assert process_event(account.pk, event(outgoing=True, from_ai=True)) == "own_ai_message"
    assert not MessageLog.objects.exists()
    assert celery_calls["handle_incoming"] == []


def test_message_from_self_in_saved_messages_is_ignored(gs, account, celery_calls):
    assert process_event(account.pk, event(sender_id=account.telegram_user_id, chat_id=1000)) == "own_message"
    assert celery_calls["handle_incoming"] == []


def test_group_and_channel_messages_are_ignored_by_default(gs, account, celery_calls):
    assert process_event(account.pk, event(chat_type=Chat.ChatType.GROUP, chat_id=-100)) == "ignored_chat_type"
    assert process_event(account.pk, event(chat_type=Chat.ChatType.CHANNEL, chat_id=-200)) == "ignored_chat_type"

    assert not MessageLog.objects.exists()
    assert celery_calls["handle_incoming"] == []
    assert Chat.objects.get(telegram_chat_id=-100).auto_reply_enabled is False


def test_group_replies_only_when_explicitly_enabled(gs, account, celery_calls):
    account.allow_groups = True
    account.save()
    process_event(account.pk, event(chat_type=Chat.ChatType.GROUP, chat_id=-100))
    assert celery_calls["handle_incoming"] == []

    Chat.objects.filter(telegram_chat_id=-100).update(auto_reply_enabled=True)

    assert process_event(account.pk, event(message_id=2, chat_type=Chat.ChatType.GROUP, chat_id=-100)) == "queued"


def test_kill_switch_stops_queueing(gs, account, celery_calls):
    GlobalSettings.objects.update(kill_switch=True)

    assert process_event(account.pk, event()) == "kill_switch"

    log = MessageLog.objects.get()
    assert log.status == MessageLog.Status.SKIPPED
    assert log.error == "kill_switch"
    assert celery_calls["handle_incoming"] == []


def test_paused_account_does_not_queue(gs, account, celery_calls):
    Account.objects.filter(pk=account.pk).update(auto_reply_enabled=False)

    assert process_event(account.pk, event()) == "account_paused"
    assert celery_calls["handle_incoming"] == []


def test_whitelist_and_blacklist_modes(gs, account, celery_calls):
    Account.objects.filter(pk=account.pk).update(chat_filter_mode=Account.FilterMode.WHITELIST)
    assert process_event(account.pk, event(message_id=1)) == "not_whitelisted"

    Chat.objects.filter(telegram_chat_id=555).update(list_status=Chat.ListStatus.WHITELISTED)
    assert process_event(account.pk, event(message_id=2)) == "queued"

    Account.objects.filter(pk=account.pk).update(chat_filter_mode=Account.FilterMode.BLACKLIST)
    Chat.objects.filter(telegram_chat_id=555).update(list_status=Chat.ListStatus.BLACKLISTED)
    assert process_event(account.pk, event(message_id=3)) == "blacklisted"


def test_duplicate_event_is_not_processed_twice(gs, account, celery_calls):
    process_event(account.pk, event())

    assert process_event(account.pk, event()) == "duplicate"
    assert len(celery_calls["handle_incoming"]) == 1
