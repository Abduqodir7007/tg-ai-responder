from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MediaKind = Literal["photo", "video", "video_note", "voice", "audio"]


class Part(BaseModel):
    type: Literal["text", "image", "audio", "video"]
    text: str | None = None
    mime_type: str | None = None
    data_b64: str | None = None


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: list[Part]


class ProviderRequest(BaseModel):
    api_key: str = Field(min_length=1)
    model: str | None = None


class GenerateRequest(ProviderRequest):
    system: str = ""
    messages: list[Message] = Field(min_length=1)
    max_tokens: int = Field(default=800, ge=1, le=8192)


class GenerateResponse(BaseModel):
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str


class SummaryLine(BaseModel):
    id: int | None = None
    role: str
    date: str | None = None
    text: str


class ContactContextData(BaseModel):
    name: str = ""
    relationship: str = ""
    language: str = ""
    tone: str = ""
    topics: list[str] = Field(default_factory=list)
    summary: str = ""
    facts: dict[str, Any] = Field(default_factory=dict)
    open_tasks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    @field_validator("facts", mode="before")
    @classmethod
    def coerce_facts(cls, value):
        if value is None:
            return {}
        if isinstance(value, list):
            return {str(index + 1): item for index, item in enumerate(value)}
        return value

    @field_validator("topics", "open_tasks", "open_questions", mode="before")
    @classmethod
    def coerce_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        return [item if isinstance(item, str) else str(item) for item in value]

    @field_validator("name", "relationship", "language", "tone", "summary", mode="before")
    @classmethod
    def coerce_text(cls, value):
        return "" if value is None else str(value)


class SummarizeRequest(ProviderRequest):
    existing_context: dict[str, Any] = Field(default_factory=dict)
    messages: list[SummaryLine] = Field(min_length=1)
    mode: Literal["bootstrap", "update"] = "update"


class SummarizeResponse(BaseModel):
    context: ContactContextData
    input_tokens: int = 0
    output_tokens: int = 0
    model: str


class DescribeMediaRequest(ProviderRequest):
    media_type: MediaKind
    mime_type: str
    data_b64: str = Field(min_length=1)


class DescribeMediaResponse(BaseModel):
    text: str
    transcript: str = ""
    description: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str
