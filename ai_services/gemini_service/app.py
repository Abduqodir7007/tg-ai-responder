import base64
import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from google import genai
from google.genai import errors, types

from ai_services.common.prompts import (
    MEDIA_JSON_SUFFIX,
    MEDIA_PROMPTS,
    SUMMARY_SYSTEM,
    build_summary_prompt,
    combine_media_text,
    merge_context,
    parse_json_object,
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

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("GEMINI_DEFAULT_MODEL", "gemini-2.5-flash")
SUMMARY_MAX_TOKENS = int(os.environ.get("SUMMARY_MAX_TOKENS", "2000"))

app = FastAPI(title="gemini-service")


def get_client_factory():
    return lambda api_key: genai.Client(api_key=api_key)


def to_parts(parts: list[Part]) -> list[types.Part]:
    result = []
    for part in parts:
        if part.type == "text" and part.text:
            result.append(types.Part.from_text(text=part.text))
        elif part.data_b64:
            result.append(types.Part.from_bytes(data=base64.b64decode(part.data_b64),
                                                mime_type=part.mime_type or "application/octet-stream"))
    return result or [types.Part.from_text(text="(empty message)")]


def call_gemini(client, model: str, contents, config: types.GenerateContentConfig):
    try:
        return client.models.generate_content(model=model, contents=contents, config=config)
    except errors.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini error {exc.code}: {exc.message}") from exc


def usage(response) -> tuple[int, int]:
    data = getattr(response, "usage_metadata", None)
    return int(getattr(data, "prompt_token_count", 0) or 0), int(getattr(data, "candidates_token_count", 0) or 0)


def response_text(response) -> str:
    return (getattr(response, "text", None) or "").strip()


@app.get("/health")
def health():
    return {"status": "ok", "provider": "gemini"}


@app.post("/generate", response_model=GenerateResponse, dependencies=[Depends(verify_internal_token)])
def generate(request: GenerateRequest, client_factory=Depends(get_client_factory)):
    model = request.model or DEFAULT_MODEL
    contents = [
        types.Content(role="user" if message.role == "user" else "model", parts=to_parts(message.content))
        for message in request.messages
    ]
    config = types.GenerateContentConfig(system_instruction=request.system or None,
                                         max_output_tokens=request.max_tokens)
    response = call_gemini(client_factory(request.api_key), model, contents, config)
    input_tokens, output_tokens = usage(response)
    return GenerateResponse(text=response_text(response), input_tokens=input_tokens, output_tokens=output_tokens,
                            model=model)


@app.post("/summarize", response_model=SummarizeResponse, dependencies=[Depends(verify_internal_token)])
def summarize(request: SummarizeRequest, client_factory=Depends(get_client_factory)):
    model = request.model or DEFAULT_MODEL
    prompt = build_summary_prompt(request.existing_context, request.messages, request.mode)
    config = types.GenerateContentConfig(system_instruction=SUMMARY_SYSTEM, max_output_tokens=SUMMARY_MAX_TOKENS,
                                         response_mime_type="application/json")
    response = call_gemini(client_factory(request.api_key), model, [types.Part.from_text(text=prompt)], config)
    input_tokens, output_tokens = usage(response)
    context = merge_context(request.existing_context, response_text(response))
    return SummarizeResponse(context=context, input_tokens=input_tokens, output_tokens=output_tokens, model=model)


@app.post("/describe-media", response_model=DescribeMediaResponse, dependencies=[Depends(verify_internal_token)])
def describe_media(request: DescribeMediaRequest, client_factory=Depends(get_client_factory)):
    model = request.model or DEFAULT_MODEL
    contents = [
        types.Part.from_bytes(data=base64.b64decode(request.data_b64), mime_type=request.mime_type),
        types.Part.from_text(text=MEDIA_PROMPTS[request.media_type] + MEDIA_JSON_SUFFIX),
    ]
    config = types.GenerateContentConfig(response_mime_type="application/json", max_output_tokens=2000)
    response = call_gemini(client_factory(request.api_key), model, contents, config)
    raw = response_text(response)
    data = parse_json_object(raw)
    transcript = str(data.get("transcript") or "") if data else ""
    description = str(data.get("description") or "") if data else raw
    input_tokens, output_tokens = usage(response)
    return DescribeMediaResponse(
        text=combine_media_text(transcript, description),
        transcript=transcript,
        description=description,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
    )
