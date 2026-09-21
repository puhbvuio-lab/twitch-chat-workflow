"""Typed configuration sections for the standalone chat workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LabelingConfig(BaseModel):
    """Optional semantic-labeling settings."""

    enabled: bool = False
    provider: Literal["codex_session", "openai_responses"] = "codex_session"
    fallback_provider: Literal["openai_responses"] | None = "openai_responses"
    model: str | None = None
    batch_size: int = Field(default=50, ge=1)
    concurrency: int = Field(default=1, ge=1)
    context_messages: int = Field(default=0, ge=0)


class AggregationConfig(BaseModel):
    """Settings for fixed-width chat trend buckets."""

    interval_seconds: int = Field(default=60, ge=1)


class RawMessage(BaseModel):
    """One downloader record, retained without lossy transformation."""

    timestamp: float
    text: str
    author: str = ""
    message_id: str | None = None
    timestamp_iso: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """Canonical normalized chat row used by labeling and aggregation."""

    message_id: str
    timestamp_seconds: float
    timestamp_ms: int | None = None
    timestamp_iso: str | None = None
    author: str = ""
    text: str
    original_text: str
    encoding_warning: bool = False


class MessageLabel(BaseModel):
    """Auditable semantic label for one canonical message."""

    message_id: str
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    topic: str = ""
    interest_signal: bool = False
    provider: str = ""
    model: str | None = None
    batch_number: int = 0
