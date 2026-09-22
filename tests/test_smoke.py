from __future__ import annotations

import csv
from pathlib import Path

from twitch_chat_workflow.acquisition import acquire_chat
from twitch_chat_workflow.aggregation import aggregate_stage
from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.labeling import label_chat
from twitch_chat_workflow.models import MessageLabel, RawMessage
from twitch_chat_workflow.normalization import normalize_chat


class FixtureDownloader:
    def fetch(self, *_args: object):
        yield RawMessage(timestamp=0.25, author="viewer", text="hello", message_id="one")
        yield RawMessage(timestamp=2.5, author="viewer2", text="cafÃ©", message_id="two")


class FixtureProvider:
    name = "codex_session"

    def label(self, messages):
        return [MessageLabel(message_id=message.message_id, sentiment="positive", topic="测试") for message in messages]


def test_offline_smoke_runs_fake_acquisition_clean_label_and_analysis_workbook(tmp_path: Path) -> None:
    config = JobConfig(vod_url="https://www.twitch.tv/videos/123", output_dir=tmp_path, end_seconds=4, labeling={"enabled": True}, aggregation={"interval_seconds": 1})
    paths = JobPaths.create(config)

    raw = acquire_chat(config, paths, FixtureDownloader())
    clean = normalize_chat(raw, paths, config)
    assert clean.is_file()
    assert label_chat(config, paths, FixtureProvider()) is not None
    trends = aggregate_stage(config, paths)

    assert trends.name == "弹幕趋势.csv"
    assert (paths.chat_trends / "弹幕趋势.json").is_file()
    assert (paths.chat_trends / "弹幕分析.xlsx").is_file()

    with trends.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    assert [int(row["message_count"]) for row in rows] == [1, 0, 1, 0]
