from __future__ import annotations

import json
from pathlib import Path

from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths, runtime_cookie_source, write_json_atomic


def test_job_paths_create_makes_the_five_workflow_directories(tmp_path: Path) -> None:
    config = JobConfig(
        vod_url="https://www.twitch.tv/videos/123",
        output_dir=tmp_path / "results",
    )

    paths = JobPaths.create(config)

    assert paths.root.parent == config.output_dir
    assert {path.name for path in paths.root.iterdir()} == {
        "01_raw_chat",
        "02_clean_chat",
        "03_labeled_chat",
        "04_chat_trends",
        "09_status",
    }
    assert all(
        path.is_dir()
        for path in (paths.raw_chat, paths.clean_chat, paths.labeled_chat, paths.chat_trends, paths.status)
    )


def test_write_json_atomic_writes_valid_utf8_json_without_a_temporary_left_behind(tmp_path: Path) -> None:
    destination = tmp_path / "status.json"
    value = {"message": "弹幕", "count": 1}

    write_json_atomic(destination, value)

    assert json.loads(destination.read_text(encoding="utf-8")) == value
    assert list(tmp_path.glob(".status.json.*.tmp")) == []


def test_cookie_source_is_runtime_only_and_absent_from_serialized_snapshot(tmp_path: Path) -> None:
    config = JobConfig(
        vod_url="https://www.twitch.tv/videos/123",
        output_dir=tmp_path,
        cookies_from_browser="chrome",
    )

    snapshot_text = json.dumps(config.redacted_snapshot(), ensure_ascii=False)

    assert runtime_cookie_source(config) == "chrome"
    assert "chrome" not in snapshot_text
    assert "cookies_from_browser" not in snapshot_text
