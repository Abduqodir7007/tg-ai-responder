from datetime import timedelta

from django.utils import timezone

from core import bus
from core.models import Account, Chat, ContactContext, MessageLog
from core.tasks import maintain_contexts, rebootstrap_chat, register_new_message, start_bootstrap, summarize_chat
from listener.handlers import ChatInfo, EventInfo, finish_history, store_history


def test_resummarize_triggered_after_n_new_messages(gs, chat, celery_calls):
    gs.resummarize_every_n_messages = 3
    gs.save()

    results = [register_new_message(chat, gs) for _ in range(4)]

    assert results == [False, False, True, False]
    assert celery_calls["summarize_chat"] == [{"args": (chat.pk, "update"), "kwargs": {}}]


def test_beat_job_selects_due_chats(gs, account, celery_calls):
    gs.resummarize_every_n_messages = 10
    gs.context_refresh_hours = 6
    gs.save()
    busy = Chat.objects.create(account=account, telegram_chat_id=1, messages_since_summary=12)
    stale = Chat.objects.create(account=account, telegram_chat_id=2, messages_since_summary=2)
    ContactContext.objects.create(chat=stale)
    ContactContext.objects.filter(chat=stale).update(updated_at=timezone.now() - timedelta(hours=7))
    fresh = Chat.objects.create(account=account, telegram_chat_id=3, messages_since_summary=2)
    ContactContext.objects.create(chat=fresh)
    idle = Chat.objects.create(account=account, telegram_chat_id=4, messages_since_summary=0)
    ContactContext.objects.create(chat=idle)
    ContactContext.objects.filter(chat=idle).update(updated_at=timezone.now() - timedelta(days=3))
    offline = Account.objects.create(name="Off", api_id=1, status=Account.Status.DISCONNECTED)
    Chat.objects.create(account=offline, telegram_chat_id=5, messages_since_summary=50)

    assert maintain_contexts() == 2

    queued = {call["args"][0] for call in celery_calls["summarize_chat"]}
    assert queued == {busy.pk, stale.pk}


def test_summarize_updates_context_in_chunks(gs, chat, make_log, fake_ai):
    gs.summary_chunk_size = 5
    gs.save()
    context = ContactContext.objects.create(chat=chat, summary="old", last_summarized_msg_id=3)
    for index in range(1, 14):
        direction = MessageLog.Direction.IN if index % 2 else MessageLog.Direction.OUT
        make_log(chat, index, f"m{index}", direction=direction, minutes_ago=50 - index)
    Chat.objects.filter(pk=chat.pk).update(messages_since_summary=10)

    assert summarize_chat(chat.pk) == 2

    assert [len(call["messages"]) for call in fake_ai.summarize_calls] == [5, 5]
    assert fake_ai.summarize_calls[0]["messages"][0]["id"] == 4
    assert fake_ai.summarize_calls[0]["existing"]["summary"] == "old"
    assert fake_ai.summarize_calls[1]["existing"]["name"] == "Ali"
    context.refresh_from_db()
    assert context.last_summarized_msg_id == 13
    assert context.summary == "Ali is planning a trip."
    assert context.facts == {"city": "Samarkand"}
    assert context.open_tasks == ["send photos"]
    chat.refresh_from_db()
    assert chat.messages_since_summary == 0


def test_summarize_without_new_messages_only_resets_counter(gs, chat, fake_ai):
    Chat.objects.filter(pk=chat.pk).update(messages_since_summary=4)

    assert summarize_chat(chat.pk) == 0
    assert fake_ai.summarize_calls == []
    chat.refresh_from_db()
    assert chat.messages_since_summary == 0


def test_bootstrap_flows_through_listener_queue(gs, account, bus_commands, celery_calls):
    assert start_bootstrap(account.pk) is True
    assert bus_commands == [
        {
            "action": bus.BOOTSTRAP_DIALOGS,
            "account_id": account.pk,
            "dialog_limit": gs.bootstrap_dialog_limit,
            "messages_per_dialog": gs.bootstrap_messages_per_dialog,
        }
    ]
    history = [
        EventInfo(chat=None, message_id=i, outgoing=bool(i % 2 == 0), text=f"h{i}") for i in range(1, 6)
    ]
    chat = store_history(account.pk, ChatInfo(chat_id=999, title="Vali"), history)
    finish_history(chat.pk)

    assert MessageLog.objects.filter(chat=chat, source=MessageLog.Source.BOOTSTRAP).count() == 5
    assert celery_calls["summarize_chat"] == [{"args": (chat.pk, "bootstrap"), "kwargs": {}}]
    store_history(account.pk, ChatInfo(chat_id=999, title="Vali"), history)
    assert MessageLog.objects.filter(chat=chat).count() == 5


def test_rebootstrap_resets_context_and_requests_history(gs, chat, bus_commands):
    ContactContext.objects.create(chat=chat, summary="stale", last_summarized_msg_id=50)

    assert rebootstrap_chat(chat.pk) is True

    context = ContactContext.objects.get(chat=chat)
    assert context.summary == ""
    assert context.last_summarized_msg_id == 0
    assert bus_commands[-1]["action"] == bus.FETCH_CHAT_HISTORY
    assert bus_commands[-1]["chat_id"] == chat.telegram_chat_id
