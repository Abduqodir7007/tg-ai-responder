import json
from functools import lru_cache

import redis
from django.conf import settings

SEND_MESSAGE = "send_message"
BOOTSTRAP_DIALOGS = "bootstrap_dialogs"
FETCH_CHAT_HISTORY = "fetch_chat_history"


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL)


def push(command: dict) -> None:
    get_redis().rpush(settings.TELEGRAM_OUTBOX_KEY, json.dumps(command))


def send_message(account_id: int, chat_id: int, text: str, log_id: int, delay: float) -> None:
    push(
        {
            "action": SEND_MESSAGE,
            "account_id": account_id,
            "chat_id": chat_id,
            "text": text,
            "log_id": log_id,
            "delay": round(delay, 2),
        }
    )


def request_bootstrap(account_id: int, dialog_limit: int, messages_per_dialog: int) -> None:
    push(
        {
            "action": BOOTSTRAP_DIALOGS,
            "account_id": account_id,
            "dialog_limit": dialog_limit,
            "messages_per_dialog": messages_per_dialog,
        }
    )


def request_chat_history(account_id: int, chat_id: int, limit: int) -> None:
    push(
        {
            "action": FETCH_CHAT_HISTORY,
            "account_id": account_id,
            "chat_id": chat_id,
            "limit": limit,
        }
    )
