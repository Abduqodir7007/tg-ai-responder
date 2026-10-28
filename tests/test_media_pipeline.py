from core.ai_client import AIServiceError
from core.models import MessageLog
from core.tasks import handle_incoming


def voice_log(chat, make_log, media_root, msg_id=1, media_type=MessageLog.MediaType.VOICE, mime="audio/ogg"):
    path = media_root / f"{msg_id}.ogg"
    path.write_bytes(b"OggS-fake-voice")
    return make_log(chat, msg_id, "", media_type=media_type, media_path=path.name, media_mime=mime,
                    status=MessageLog.Status.QUEUED)


def test_voice_is_transcribed_and_used_as_text(gs, chat, make_log, media_root, fake_ai):
    log = voice_log(chat, make_log, media_root)

    assert handle_incoming(log.pk) == "reply_queued"

    assert fake_ai.describe_calls == [{"media_type": "voice", "mime_type": "audio/ogg", "data": b"OggS-fake-voice"}]
    log.refresh_from_db()
    assert log.transcript == "Transcript: ertaga uchrashamizmi?"
    assert log.input_tokens == 7
    texts = [part["text"] for message in fake_ai.generate_calls[0]["messages"] for part in message["content"]]
    assert texts[-1] == "[voice] Transcript: ertaga uchrashamizmi?"


def test_video_note_is_transcribed_once(gs, chat, make_log, media_root, fake_ai):
    log = voice_log(chat, make_log, media_root, media_type=MessageLog.MediaType.VIDEO_NOTE, mime="video/mp4")
    handle_incoming(log.pk)
    log.refresh_from_db()
    log.status = MessageLog.Status.QUEUED
    log.save()
    MessageLog.objects.filter(source=MessageLog.Source.AI).delete()

    handle_incoming(log.pk)

    assert len(fake_ai.describe_calls) == 1
    assert fake_ai.describe_calls[0]["media_type"] == "video_note"


def test_media_failure_still_replies(gs, chat, make_log, media_root, fake_ai):
    fake_ai.describe_error = AIServiceError("boom")
    log = voice_log(chat, make_log, media_root)

    assert handle_incoming(log.pk) == "reply_queued"
    log.refresh_from_db()
    assert log.transcript == ""
    assert "describe-media" in log.error


def test_photo_goes_as_image_not_transcript(gs, chat, make_log, media_root, fake_ai):
    (media_root / "p.jpg").write_bytes(b"\xff\xd8jpeg")
    log = make_log(chat, 1, "nima deysan?", media_type=MessageLog.MediaType.PHOTO, media_path="p.jpg",
                   media_mime="image/jpeg", status=MessageLog.Status.QUEUED)

    handle_incoming(log.pk)

    assert fake_ai.describe_calls == []
    parts = fake_ai.generate_calls[0]["messages"][-1]["content"]
    assert parts[0]["type"] == "image"
    assert parts[0]["data_b64"]
