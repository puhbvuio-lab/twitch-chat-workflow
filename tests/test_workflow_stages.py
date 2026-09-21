from __future__ import annotations

import csv
from pathlib import Path

import pytest

from twitch_chat_workflow.acquisition import acquire_chat
from twitch_chat_workflow.aggregation import aggregate_chat
from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.labeling import label_chat
from twitch_chat_workflow.models import ChatMessage, MessageLabel, RawMessage


class FakeDownloader:
    def __init__(self) -> None:
        self.args: tuple[object, ...] | None = None

    def fetch(self, *args: object):
        self.args = args
        return [RawMessage(timestamp=1.005, text="hi", author="viewer", message_id="one")]


def test_acquisition_preserves_jsonl_and_forwards_bounds_and_cookie_without_persisting_it(tmp_path: Path) -> None:
    config = JobConfig(vod_url="https://www.twitch.tv/videos/123", output_dir=tmp_path, start_seconds=4, end_seconds=9, cookies_from_browser="chrome")
    paths = JobPaths.create(config); downloader = FakeDownloader()

    raw = acquire_chat(config, paths, downloader)

    assert downloader.args == (config.vod_url, 4, 9, "chrome")
    assert '"timestamp": 1.005' in raw.read_text(encoding="utf-8")
    assert "chrome" not in (paths.status / "acquire.state.json").read_text(encoding="utf-8")


class FakeProvider:
    name = "codex_session"

    def label(self, messages: list[ChatMessage]) -> list[MessageLabel]:
        return [MessageLabel(message_id=message.message_id, sentiment="positive") for message in messages]


def test_labeling_persists_ordered_batches_and_disabled_labeling_is_skipped(tmp_path: Path) -> None:
    config = JobConfig(vod_url="https://www.twitch.tv/videos/123", output_dir=tmp_path, labeling={"enabled": True, "batch_size": 1})
    paths = JobPaths.create(config)
    (paths.clean_chat / "clean_chat.csv").write_text("message_id,timestamp_seconds,timestamp_ms,timestamp_iso,author,text,original_text,encoding_warning\na,1,,,,u,hi,hi,false\nb,2,,,,v,yo,yo,false\n", encoding="utf-8")
    output = label_chat(config, paths, FakeProvider())
    assert output is not None
    with output.open(encoding="utf-8", newline="") as input_file:
        assert [row["message_id"] for row in csv.DictReader(input_file)] == ["a", "b"]
    disabled = JobConfig.model_validate({**config.model_dump(mode="json"), "labeling": {"enabled": False}})
    assert label_chat(disabled, paths, None) is None
    assert '"status": "skipped"' in (paths.status / "label.state.json").read_text(encoding="utf-8")


def test_partial_label_batch_fails_and_state_is_retryable(tmp_path: Path) -> None:
    class PartialProvider(FakeProvider):
        def label(self, messages: list[ChatMessage]) -> list[MessageLabel]:
            return []
    config = JobConfig(vod_url="https://www.twitch.tv/videos/123", output_dir=tmp_path, labeling={"enabled": True})
    paths = JobPaths.create(config)
    (paths.clean_chat / "clean_chat.csv").write_text("message_id,timestamp_seconds,timestamp_ms,timestamp_iso,author,text,original_text,encoding_warning\na,1,,,,u,hi,hi,false\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="incomplete"):
        label_chat(config, paths, PartialProvider())
    assert '"status": "failed"' in (paths.status / "label.state.json").read_text(encoding="utf-8")


def test_aggregation_emits_empty_one_second_windows_and_half_open_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "clean.csv"
    source.write_text("message_id,timestamp_seconds,author,sentiment,interest_signal\na,0.999,u,positive,true\nb,1.0,v,negative,false\nc,60.0,w,neutral,false\n", encoding="utf-8")
    one_second = aggregate_chat(source, 1, (0, 3))
    assert [row["message_count"] for row in one_second] == [1, 1, 0]
    minute = aggregate_chat(source, 60, (0, 120))
    assert [row["message_count"] for row in minute] == [2, 1]
