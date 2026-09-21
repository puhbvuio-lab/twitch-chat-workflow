"""Batch persistence and resumable optional semantic labeling."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .config import JobConfig
from .io import JobPaths, write_json_atomic
from .models import ChatMessage, MessageLabel
from .providers import SemanticLabelProvider
from .state import StageStateStore, stage_fingerprint


def label_chat(config: JobConfig, paths: JobPaths, provider: SemanticLabelProvider | None) -> Path | None:
    """Label canonical rows in stable batches; failures remain explicitly retryable."""
    clean_path = paths.clean_chat / "clean_chat.csv"
    output_path = paths.labeled_chat / "labeled_chat.csv"
    state = StageStateStore(paths.status)
    fingerprint = stage_fingerprint(config, {"clean_chat": clean_path})
    if not config.labeling.enabled:
        state.skip("label", fingerprint)
        return None
    if provider is None:
        raise ValueError("a semantic provider is required when labeling is enabled")
    if not state.should_run("label", fingerprint, [output_path]):
        return output_path
    messages = _read_messages(clean_path)
    artifacts = [output_path]
    state.start("label", fingerprint, artifacts)
    labels: list[MessageLabel] = []
    try:
        for offset in range(0, len(messages), config.labeling.batch_size):
            number = offset // config.labeling.batch_size + 1
            batch = messages[offset : offset + config.labeling.batch_size]
            batch_path = paths.labeled_chat / f"batch-{number:04d}.json"
            batch_labels = provider.label(batch)
            expected = [message.message_id for message in batch]
            received = [label.message_id for label in batch_labels]
            if received != expected:
                raise RuntimeError(f"batch-{number:04d} returned incomplete or out-of-order labels")
            normalized = [label.model_copy(update={"provider": provider.name, "model": label.model or config.labeling.model, "batch_number": number}) for label in batch_labels]
            write_json_atomic(batch_path, {"batch_number": number, "provider": provider.name, "rows": [label.model_dump(mode="json") for label in normalized]})
            labels.extend(normalized)
            artifacts.append(batch_path)
        _write_labeled(output_path, messages, labels)
        state.complete("label", fingerprint, artifacts)
    except BaseException as error:
        state.fail("label", fingerprint, artifacts, error)
        raise
    return output_path


def _read_messages(path: Path) -> list[ChatMessage]:
    with path.open(encoding="utf-8", newline="") as input_file:
        rows = list(csv.DictReader(input_file))
    return [ChatMessage(
        message_id=row["message_id"], timestamp_seconds=float(row["timestamp_seconds"]),
        timestamp_ms=int(row["timestamp_ms"]) if row.get("timestamp_ms") else None,
        timestamp_iso=row.get("timestamp_iso") or None, author=row.get("author", ""),
        text=row["text"], original_text=row.get("original_text", row["text"]),
        encoding_warning=row.get("encoding_warning", "").lower() == "true",
    ) for row in rows]


def _write_labeled(path: Path, messages: list[ChatMessage], labels: list[MessageLabel]) -> None:
    labels_by_id = {label.message_id: label for label in labels}
    fields = ["message_id", "timestamp_seconds", "timestamp_ms", "timestamp_iso", "author", "text", "original_text", "encoding_warning", "sentiment", "topic", "interest_signal", "label_provider", "label_model", "batch_number"]
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for message in messages:
            label = labels_by_id[message.message_id]
            writer.writerow({**message.model_dump(), "sentiment": label.sentiment, "topic": label.topic, "interest_signal": str(label.interest_signal).lower(), "label_provider": label.provider, "label_model": label.model or "", "batch_number": label.batch_number})
