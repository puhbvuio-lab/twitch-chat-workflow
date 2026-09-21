from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from twitch_chat_workflow.config import JobConfig


def write_config(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "job.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_one_second_aggregation_interval_is_valid(tmp_path: Path) -> None:
    config = JobConfig.from_file(
        write_config(
            tmp_path,
            {"vod_url": "https://www.twitch.tv/videos/123", "aggregation": {"interval_seconds": 1}},
        )
    )

    assert config.aggregation.interval_seconds == 1


@pytest.mark.parametrize("vod_url", [None, "", "   "])
def test_missing_or_blank_vod_url_fails(tmp_path: Path, vod_url: object) -> None:
    path = write_config(tmp_path, {"vod_url": vod_url})

    with pytest.raises(ValidationError):
        JobConfig.from_file(path)


def test_end_seconds_must_be_after_start_seconds(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        {"vod_url": "https://www.twitch.tv/videos/123", "start_seconds": 30, "end_seconds": 30},
    )

    with pytest.raises(ValidationError, match="end_seconds"):
        JobConfig.from_file(path)


def test_redacted_snapshot_excludes_cookie_source(tmp_path: Path) -> None:
    config = JobConfig.from_file(
        write_config(
            tmp_path,
            {
                "vod_url": "https://www.twitch.tv/videos/123",
                "cookies_from_browser": "chrome",
            },
        )
    )

    assert "cookies_from_browser" not in config.redacted_snapshot()
