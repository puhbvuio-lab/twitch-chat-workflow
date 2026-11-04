from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from twitch_chat_workflow.acquisition import YouTubeChatDownloaderAdapter, build_downloader
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


def test_youtube_adapter_invokes_ytdlp_and_forwards_browser_cookie(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        output_template = Path(command[command.index("--output") + 1])
        chat_path = Path(str(output_template).replace("%(ext)s", "live_chat.json"))
        chat_path.write_text(
            json.dumps({"replayChatItemAction": {"videoOffsetTimeMsec": "1000", "actions": [
                {"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
                    "id": "m1", "authorName": {"simpleText": "a"},
                    "message": {"simpleText": "hello"},
                }}}}
            ]}}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    messages = list(YouTubeChatDownloaderAdapter(runner=runner).fetch(
        "https://youtu.be/abc", None, None, "chrome"
    ))

    assert [message.text for message in messages] == ["hello"]
    assert "--cookies-from-browser" in commands[0]
    assert commands[0][commands[0].index("--cookies-from-browser") + 1] == "chrome"


def test_youtube_adapter_rejects_missing_replay_output() -> None:
    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(RuntimeError, match="replay"):
        list(YouTubeChatDownloaderAdapter(runner=runner).fetch("https://youtu.be/abc", None, None, None))


def test_downloader_factory_selects_platform_adapter() -> None:
    assert type(build_downloader("twitch")).__name__ == "TwitchChatDownloaderAdapter"
    assert type(build_downloader("youtube")).__name__ == "YouTubeChatDownloaderAdapter"
