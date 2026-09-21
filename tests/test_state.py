from __future__ import annotations

import json
from pathlib import Path

from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.state import StageStateStore, stage_fingerprint


def make_store(tmp_path: Path) -> StageStateStore:
    paths = JobPaths.create(
        JobConfig(vod_url="https://www.twitch.tv/videos/123", output_dir=tmp_path / "results")
    )
    return StageStateStore(paths.status)


def test_completed_stage_with_matching_fingerprint_and_artifact_is_skipped(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    artifact = tmp_path / "clean.csv"
    artifact.write_text("timestamp,text\n", encoding="utf-8")

    store.start("clean", "same-input", [artifact])
    store.complete("clean", "same-input", [artifact])

    assert store.should_run("clean", "same-input", [artifact]) is False


def test_completed_stage_reruns_when_an_expected_artifact_is_missing(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    artifact = tmp_path / "clean.csv"

    store.start("clean", "same-input", [artifact])
    store.complete("clean", "same-input", [artifact])

    assert store.should_run("clean", "same-input", [artifact]) is True


def test_completed_stage_reruns_when_its_input_fingerprint_changes(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    artifact = tmp_path / "clean.csv"
    artifact.write_text("timestamp,text\n", encoding="utf-8")

    store.start("clean", "old-input", [artifact])
    store.complete("clean", "old-input", [artifact])

    assert store.should_run("clean", "new-input", [artifact]) is True


def test_failed_state_preserves_a_sanitized_error_summary_and_is_retryable(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    artifact = tmp_path / "clean.csv"

    store.start("clean", "same-input", [artifact])
    store.fail("clean", "same-input", [artifact], RuntimeError("request failed; token=super-secret"))

    state = json.loads(store.state_path("clean").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert "request failed" in state["error_summary"]
    assert "super-secret" not in state["error_summary"]
    assert state["fingerprint"] == "same-input"
    assert state["artifacts"] == [str(artifact)]
    assert store.should_run("clean", "same-input", [artifact]) is True


def test_stage_fingerprint_uses_redacted_configuration_and_named_input_hashes(tmp_path: Path) -> None:
    input_file = tmp_path / "raw.jsonl"
    input_file.write_text("first", encoding="utf-8")
    config = JobConfig(
        vod_url="https://www.twitch.tv/videos/123",
        output_dir=tmp_path,
        cookies_from_browser="chrome",
    )

    first = stage_fingerprint(config, {"raw_chat": input_file})
    input_file.write_text("second", encoding="utf-8")
    second = stage_fingerprint(config, {"raw_chat": input_file})

    assert len(first) == 64
    assert first != second
