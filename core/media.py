import base64
import logging
import mimetypes
from pathlib import Path

from django.conf import settings

from .models import MessageLog

logger = logging.getLogger(__name__)

DEFAULT_MIME = {
    MessageLog.MediaType.PHOTO: "image/jpeg",
    MessageLog.MediaType.VIDEO: "video/mp4",
    MessageLog.MediaType.VIDEO_NOTE: "video/mp4",
    MessageLog.MediaType.VOICE: "audio/ogg",
    MessageLog.MediaType.AUDIO: "audio/mpeg",
}


def resolve_path(media_path: str) -> Path:
    path = Path(media_path)
    return path if path.is_absolute() else Path(settings.MEDIA_ROOT) / path


def read_media(log: MessageLog) -> bytes | None:
    if not log.media_path:
        return None
    path = resolve_path(log.media_path)
    if not path.is_file() or path.stat().st_size > settings.MAX_MEDIA_BYTES:
        return None
    return path.read_bytes()


def mime_for(log: MessageLog) -> str:
    if log.media_mime:
        return log.media_mime
    guessed, _ = mimetypes.guess_type(log.media_path)
    return guessed or DEFAULT_MIME.get(log.media_type, "application/octet-stream")


def image_part(log: MessageLog) -> dict | None:
    if log.media_type != MessageLog.MediaType.PHOTO:
        return None
    data = read_media(log)
    if data is None:
        return None
    return {"type": "image", "mime_type": mime_for(log), "data_b64": base64.b64encode(data).decode()}


def ensure_transcript(log: MessageLog, client) -> bool:
    if not log.needs_transcript:
        return False
    data = read_media(log)
    if data is None:
        return False
    try:
        result = client.describe_media(media_type=log.media_type, mime_type=mime_for(log), data=data)
    except Exception as exc:
        logger.warning("describe-media failed for log %s: %s", log.pk, exc)
        log.error = f"describe-media: {exc}"
        log.save(update_fields=["error"])
        return False
    log.transcript = (result.get("text") or "").strip()
    log.input_tokens += int(result.get("input_tokens") or 0)
    log.output_tokens += int(result.get("output_tokens") or 0)
    log.save(update_fields=["transcript", "input_tokens", "output_tokens"])
    return bool(log.transcript)
