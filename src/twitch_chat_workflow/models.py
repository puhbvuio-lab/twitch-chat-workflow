"""Typed configuration sections for the standalone chat workflow."""

from __future__ import annotations

from typing import Literal

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
