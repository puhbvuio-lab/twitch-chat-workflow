from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.labeling import _load_valid_batch, label_chat
from twitch_chat_workflow.models import ChatMessage, MessageLabel
from twitch_chat_workflow.state import stage_fingerprint


class CountingProvider:
    name = "codex_session"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def label(self, messages: list[ChatMessage]) -> list[MessageLabel]:
        self.calls.append([message.message_id for message in messages])
        return [
            MessageLabel(
                message_id=message.message_id,
                sentiment="neutral",
                topic="其他",
                interest_signal=False,
            )
            for message in messages
        ]


def _prepare_paths(tmp_path: Path, message_ids: list[str]) -> tuple[JobConfig, JobPaths]:
    config = JobConfig(
        vod_url="https://www.twitch.tv/videos/123",
        output_dir=tmp_path,
        labeling={"enabled": True, "batch_size": 1},
    )
    paths = JobPaths.create(config)
    rows = [
        "message_id,timestamp_seconds,timestamp_ms,timestamp_iso,author,text,original_text,encoding_warning"
    ]
    rows.extend(f"{message_id},{index + 1},,,,u,text,text,false" for index, message_id in enumerate(message_ids))
    (paths.clean_chat / "clean_chat.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return config, paths


def _write_batch(
    path: Path,
    number: int,
    rows: list[dict[str, object]],
    provider: str = "codex_session",
    input_fingerprint: str | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "batch_number": number,
                "provider": provider,
                "input_fingerprint": input_fingerprint,
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )


def test_labeling_reuses_only_a_valid_matching_completed_batch(tmp_path: Path) -> None:
    """Removing validated reuse must make the provider receive the first batch too."""
    config, paths = _prepare_paths(tmp_path, ["m1", "m2"])
    _write_batch(
        paths.labeled_chat / "batch-0001.json",
        1,
        [
            {
                "message_id": "m1",
                "sentiment": "positive",
                "topic": "直播反馈",
                "interest_signal": True,
                "provider": "codex_session",
                "model": None,
                "batch_number": 1,
            }
        ],
        input_fingerprint=stage_fingerprint(config, {"clean_chat": paths.clean_chat / "clean_chat.csv"}),
    )
    provider = CountingProvider()

    output = label_chat(config, paths, provider)

    assert provider.calls == [["m2"]]
    assert output is not None
    with output.open(encoding="utf-8", newline="") as input_file:
        assert [row["message_id"] for row in csv.DictReader(input_file)] == ["m1", "m2"]


def test_labeling_reruns_a_cache_when_the_clean_input_fingerprint_changes(tmp_path: Path) -> None:
    """Reusing same-ID labels after the message text changes is a stale-label bug."""
    config, paths = _prepare_paths(tmp_path, ["m1"])
    _write_batch(
        paths.labeled_chat / "batch-0001.json",
        1,
        [
            {
                "message_id": "m1",
                "sentiment": "positive",
                "topic": "直播反馈",
                "interest_signal": True,
                "provider": "codex_session",
                "model": None,
                "batch_number": 1,
            }
        ],
        input_fingerprint="a-prior-clean-input",
    )
    provider = CountingProvider()

    label_chat(config, paths, provider)

    assert provider.calls == [["m1"]]


@pytest.mark.parametrize(
    "rows",
    [
        [
            {
                "message_id": "wrong",
                "sentiment": "positive",
                "topic": "直播反馈",
                "interest_signal": True,
                "provider": "codex_session",
                "model": None,
                "batch_number": 1,
            }
        ],
        [
            {
                "message_id": "m1",
                "sentiment": "invalid",
                "topic": "直播反馈",
                "interest_signal": True,
                "provider": "codex_session",
                "model": None,
                "batch_number": 1,
            }
        ],
    ],
)
def test_labeling_reruns_cached_batches_with_wrong_ids_or_schema(
    tmp_path: Path, rows: list[dict[str, object]]
) -> None:
    """Accepting stale or invalid cached rows would silently corrupt final labels."""
    config, paths = _prepare_paths(tmp_path, ["m1"])
    _write_batch(paths.labeled_chat / "batch-0001.json", 1, rows)
    provider = CountingProvider()

    label_chat(config, paths, provider)

    assert provider.calls == [["m1"]]


def test_load_valid_batch_rejects_duplicate_or_out_of_order_ids(tmp_path: Path) -> None:
    """Dropping unique ordered-ID validation makes a corrupt batch reusable."""
    path = tmp_path / "batch-0001.json"
    _write_batch(
        path,
        1,
        [
            {"message_id": "m2", "sentiment": "positive", "topic": "a", "interest_signal": True},
            {"message_id": "m2", "sentiment": "neutral", "topic": "b", "interest_signal": False},
        ],
    )

    assert _load_valid_batch(path, ["m1", "m2"]) is None
