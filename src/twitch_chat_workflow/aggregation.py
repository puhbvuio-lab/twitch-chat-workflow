"""Fixed-width, lossless timestamp aggregation for cleaned or labeled chat."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .config import JobConfig
from .io import JobPaths, write_json_atomic
from .state import StageStateStore, stage_fingerprint


def aggregate_chat(input_csv: Path, interval_seconds: int, bounds: tuple[int, int] | None = None) -> list[dict[str, Any]]:
    """Return every half-open bucket in bounds, including empty zero-message windows."""
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be at least 1")
    with input_csv.open(encoding="utf-8", newline="") as input_file:
        messages = list(csv.DictReader(input_file))
    timestamps = [float(row["timestamp_seconds"]) for row in messages]
    if bounds is None:
        if not timestamps:
            return []
        start, end = 0, int(max(timestamps)) + 1
    else:
        start, end = bounds
    if end < start:
        raise ValueError("bounds end must not precede start")
    buckets: list[dict[str, Any]] = []
    for bucket_start in range(start, end, interval_seconds):
        bucket_end = min(bucket_start + interval_seconds, end)
        members = [row for row in messages if bucket_start <= float(row["timestamp_seconds"]) < bucket_end]
        count = len(members)
        sentiments = {name: sum(row.get("sentiment", "") == name for row in members) for name in ("positive", "neutral", "negative")}
        buckets.append({
            "start_seconds": bucket_start, "end_seconds": bucket_end, "message_count": count,
            "unique_authors": len({row.get("author", "") for row in members if row.get("author", "")}),
            **sentiments, "interest_signals": sum(row.get("interest_signal", "").lower() == "true" for row in members),
            "positive_share": sentiments["positive"] / count if count else 0.0,
            "neutral_share": sentiments["neutral"] / count if count else 0.0,
            "negative_share": sentiments["negative"] / count if count else 0.0,
        })
    return buckets


def aggregate_stage(config: JobConfig, paths: JobPaths) -> Path:
    input_csv = paths.labeled_chat / "labeled_chat.csv" if (paths.labeled_chat / "labeled_chat.csv").is_file() else paths.clean_chat / "clean_chat.csv"
    output_csv = paths.chat_trends / "trends.csv"
    output_json = paths.chat_trends / "trends.json"
    state = StageStateStore(paths.status)
    fingerprint = stage_fingerprint(config, {"chat": input_csv})
    artifacts = [output_csv, output_json]
    if not state.should_run("aggregate", fingerprint, artifacts):
        return output_csv
    state.start("aggregate", fingerprint, artifacts)
    try:
        bounds = (config.start_seconds or 0, config.end_seconds) if config.end_seconds is not None else None
        rows = aggregate_chat(input_csv, config.aggregation.interval_seconds, bounds)
        fields = list(rows[0]) if rows else ["start_seconds", "end_seconds", "message_count", "unique_authors", "positive", "neutral", "negative", "interest_signals", "positive_share", "neutral_share", "negative_share"]
        with output_csv.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
        write_json_atomic(output_json, {"interval_seconds": config.aggregation.interval_seconds, "windows": rows})
        state.complete("aggregate", fingerprint, artifacts)
    except BaseException as error:
        state.fail("aggregate", fingerprint, artifacts, error)
        raise
    return output_csv
