import json
import re

from .schemas import ContactContextData, SummaryLine

SUMMARY_SYSTEM = (
    "You maintain a structured memory card about one contact of a Telegram user (the owner). "
    "You receive the existing card and a chunk of chat messages. Merge the new information into the card. "
    "Keep facts that are still valid, drop resolved tasks and answered questions, keep the summary under 1200 characters. "
    "Respond with a single JSON object and nothing else, with keys: "
    "name (string), relationship (string, relation to the owner), language (string), tone (string), "
    "topics (array of strings), summary (string), facts (object of short key/value facts), "
    "open_tasks (array of strings, promises or tasks still pending), "
    "open_questions (array of strings, questions still unanswered)."
)

MEDIA_PROMPTS = {
    "photo": "Describe this image in 1-3 sentences, including any visible text.",
    "voice": "Transcribe this voice message verbatim in its original language.",
    "audio": "Transcribe the speech in this audio verbatim in its original language and note any music briefly.",
    "video": "Transcribe all speech verbatim and describe briefly what is visible in the video.",
    "video_note": "This is a round Telegram video message. Transcribe all speech verbatim and describe briefly what is visible.",
}

MEDIA_JSON_SUFFIX = ' Respond as JSON: {"transcript": "...", "description": "..."}.'


def build_summary_prompt(existing: dict, lines: list[SummaryLine], mode: str) -> str:
    header = (
        "This is the first pass over the existing chat history: build the card from scratch."
        if mode == "bootstrap"
        else "These are new messages since the last update: update the card."
    )
    transcript = "\n".join(
        f"[{line.id or '-'}] {line.date or ''} {line.role}: {line.text}".strip() for line in lines
    )
    return (
        f"{header}\n\nExisting card:\n{json.dumps(existing or {}, ensure_ascii=False)}"
        f"\n\nMessages (oldest first):\n{transcript}"
    )


FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict:
    cleaned = FENCE.sub("", (text or "").strip()).strip()
    try:
        value = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            return {}
        try:
            value = json.loads(cleaned[start : end + 1])
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def merge_context(existing: dict, text: str) -> ContactContextData:
    base = ContactContextData.model_validate(existing or {})
    update = parse_json_object(text)
    if not update:
        return base
    merged = {**base.model_dump(), **{key: value for key, value in update.items() if value is not None}}
    return ContactContextData.model_validate(merged)


def combine_media_text(transcript: str, description: str) -> str:
    parts = []
    if transcript.strip():
        parts.append(f"Transcript: {transcript.strip()}")
    if description.strip():
        parts.append(f"Visual: {description.strip()}")
    return "\n".join(parts)
