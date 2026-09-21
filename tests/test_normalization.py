from __future__ import annotations

import csv
import json
from pathlib import Path

from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.normalization import normalize_chat, repair_mojibake


def test_normalization_sorts_repairs_warns_and_only_removes_exact_duplicate(tmp_path: Path) -> None:
    paths = JobPaths.create(JobConfig(vod_url="https://www.twitch.tv/videos/123", output_dir=tmp_path))
    raw = paths.raw_chat / "raw_chat.jsonl"
    records = [
        {"id": "later", "timestamp": 2.25, "author": "a", "text": "same"},
        {"id": "first", "timestamp": 1.005, "timestamp_ms": 1005, "author": "a", "text": "cafÃ©"},
        {"id": "other", "timestamp": 1.5, "author": "b", "text": "same"},
        {"id": "later", "timestamp": 2.25, "author": "a", "text": "same"},
        {"id": "ambiguous", "timestamp": 3, "author": "c", "text": "Ã"},
    ]
    raw.write_text("\n".join(json.dumps(row) for row in records), encoding="utf-8")

    clean = normalize_chat(raw, paths)

    with clean.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    assert [row["message_id"] for row in rows] == ["first", "other", "later", "ambiguous"]
    assert rows[0]["text"] == "café"
    assert rows[0]["timestamp_ms"] == "1005"
    assert rows[-1]["encoding_warning"] == "true"
    assert json.loads((paths.clean_chat / "repair_statistics.json").read_text(encoding="utf-8"))["exact_duplicates"] == 1


def test_repair_mojibake_refuses_uncertain_text() -> None:
    assert repair_mojibake("Ã")[:2] == ("Ã", "ambiguous")
