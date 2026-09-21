"""Job configuration loading and safe snapshot support."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import AggregationConfig, LabelingConfig


class JobConfig(BaseModel):
    """Validated, standalone configuration for one Twitch chat workflow job."""

    model_config = ConfigDict(str_strip_whitespace=True)

    vod_url: str = Field(min_length=1)
    output_dir: Path = Path("output")
    start_seconds: int | None = Field(default=None, ge=0)
    end_seconds: int | None = Field(default=None, ge=0)
    cookies_from_browser: str | None = None
    labeling: LabelingConfig = Field(default_factory=LabelingConfig)
    aggregation: AggregationConfig = Field(default_factory=AggregationConfig)

    @model_validator(mode="after")
    def validate_time_bounds(self) -> "JobConfig":
        if (
            self.start_seconds is not None
            and self.end_seconds is not None
            and self.end_seconds <= self.start_seconds
        ):
            raise ValueError("end_seconds must be greater than start_seconds")
        return self

    @classmethod
    def from_file(cls, path: Path) -> "JobConfig":
        """Load and validate a UTF-8 JSON job configuration."""
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def redacted_snapshot(self) -> dict[str, object]:
        """Return a JSON-compatible snapshot without runtime-only cookie settings."""
        snapshot: dict[str, Any] = self.model_dump(mode="json", exclude={"cookies_from_browser"})
        return snapshot
