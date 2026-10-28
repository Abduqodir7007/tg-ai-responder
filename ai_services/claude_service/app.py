import base64
import logging
import os

import anthropic
from fastapi import Depends, FastAPI, HTTPException

from ai_services.common.prompts import (
    MEDIA_PROMPTS,
    SUMMARY_SYSTEM,
    build_summary_prompt,
    combine_media_text,
    merge_context,
)
from ai_services.common.schemas import (
    DescribeMediaRequest,
    DescribeMediaResponse,
    GenerateRequest,
    GenerateResponse,
    Part,
    SummarizeRequest,
    SummarizeResponse,
)
from ai_services.common.security import verify_internal_token

from . import media

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("CLAUDE_DEFAULT_MODEL", "claude-sonnet-5-5")
SUMMARY_MAX_TOKENS = int(os.environ.get("SUMMARY_MAX_TOKENS", "2000"))

app = FastAPI(title="claude-service")


def get_client_factory():
    return lambda api_key: anthropic.Anthropic(api_key=api_key, max_retries=2)


def image_block(mime_type: str, data_b64: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": data_b64}}


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def media_blocks(kind: str, mime_type: str, data_b64: str) -> list[dict]:
    extract = media.process_media(kind, mime_type, base64.b64decode(data_b64))
    blocks = [image_block("image/jpeg", base64.b64encode(frame).decode()) for frame in extract.frames]
    label = "video frames above; " if extract.frames else ""
    blocks.append(text_block(f"[{kind}: {label}transcript] {extract.transcript or '(no speech)'}"))
    return blocks


def to_blocks(parts: list[Part]) -> list[dict]:
    blocks: list[dict] = []
    for part in parts:
        if part.type == "text" and part.text:
            blocks.append(text_block(part.text))
        elif part.type == "image" and part.data_b64:
            blocks.append(image_block(part.mime_type or "image/jpeg", part.data_b64))
        elif part.type in {"audio", "video"} and part.data_b64:
            blocks.extend(media_blocks(part.type, part.mime_type or "", part.data_b64))
    return blocks or [text_block("(empty message)")]


def call_claude(client, model: str, system: str, messages: list[dict], max_tokens: int):
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    try:
        return client.messages.create(**kwargs)
    except anthropic.APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Anthropic error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Anthropic error: {exc}") from exc


def response_text(response) -> str:
    return "".join(block.text for block in response.content if getattr(block, "type", "") == "text").strip()


def usage(response) -> tuple[int, int]:
    data = getattr(response, "usage", None)
    return int(getattr(data, "input_tokens", 0) or 0), int(getattr(data, "output_tokens", 0) or 0)


@app.get("/health")
def health():
    return {"status": "ok", "provider": "claude"}


@app.post("/generate", response_model=GenerateResponse, dependencies=[Depends(verify_internal_token)])
def generate(request: GenerateRequest, client_factory=Depends(get_client_factory)):
    model = request.model or DEFAULT_MODEL
    messages = [{"role": message.role, "content": to_blocks(message.content)} for message in request.messages]
    response = call_claude(client_factory(request.api_key), model, request.system, messages, request.max_tokens)
    input_tokens, output_tokens = usage(response)
    return GenerateResponse(text=response_text(response), input_tokens=input_tokens, output_tokens=output_tokens,
                            model=model)


@app.post("/summarize", response_model=SummarizeResponse, dependencies=[Depends(verify_internal_token)])
def summarize(request: SummarizeRequest, client_factory=Depends(get_client_factory)):
    model = request.model or DEFAULT_MODEL
    prompt = build_summary_prompt(request.existing_context, request.messages, request.mode)
    response = call_claude(client_factory(request.api_key), model, SUMMARY_SYSTEM,
                           [{"role": "user", "content": [text_block(prompt)]}], SUMMARY_MAX_TOKENS)
    input_tokens, output_tokens = usage(response)
    context = merge_context(request.existing_context, response_text(response))
    return SummarizeResponse(context=context, input_tokens=input_tokens, output_tokens=output_tokens, model=model)


@app.post("/describe-media", response_model=DescribeMediaResponse, dependencies=[Depends(verify_internal_token)])
def describe_media(request: DescribeMediaRequest, client_factory=Depends(get_client_factory)):
    model = request.model or DEFAULT_MODEL
    if request.media_type == "photo":
        content = [image_block(request.mime_type, request.data_b64), text_block(MEDIA_PROMPTS["photo"])]
        response = call_claude(client_factory(request.api_key), model, "", [{"role": "user", "content": content}], 400)
        description = response_text(response)
        input_tokens, output_tokens = usage(response)
        return DescribeMediaResponse(text=combine_media_text("", description), description=description,
                                     input_tokens=input_tokens, output_tokens=output_tokens, model=model)

    try:
        extract = media.process_media(request.media_type, request.mime_type, base64.b64decode(request.data_b64))
    except Exception as exc:
        logger.exception("Media processing failed")
        raise HTTPException(status_code=422, detail=f"Media processing failed: {exc}") from exc

    if not extract.frames:
        return DescribeMediaResponse(text=combine_media_text(extract.transcript, ""), transcript=extract.transcript,
                                     model="faster-whisper")

    content = [image_block("image/jpeg", base64.b64encode(frame).decode()) for frame in extract.frames]
    content.append(
        text_block(
            f"These are frames sampled in order from a Telegram {request.media_type.replace('_', ' ')}. "
            f"Speech transcript: {extract.transcript or '(no speech)'}\n"
            "Describe briefly what is visible and what happens. Do not repeat the transcript."
        )
    )
    response = call_claude(client_factory(request.api_key), model, "", [{"role": "user", "content": content}], 500)
    description = response_text(response)
    input_tokens, output_tokens = usage(response)
    return DescribeMediaResponse(
        text=combine_media_text(extract.transcript, description),
        transcript=extract.transcript,
        description=description,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )
