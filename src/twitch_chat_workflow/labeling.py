"""Batch persistence and resumable optional semantic labeling."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, ValidationError

from .config import JobConfig
from .io import JobPaths, write_json_atomic
from .models import ChatMessage, MessageLabel
from .providers import SemanticLabelProvider
from .state import StageStateStore, stage_fingerprint


class _BatchArtifact(BaseModel):
    """On-disk shape of one completed, reusable label batch."""

    model_config = ConfigDict(extra="forbid")

    batch_number: int
    provider: str
    input_fingerprint: str
    rows: list[MessageLabel]


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
    messages = _read_messages(clean_path)
    batch_paths = [
        paths.labeled_chat / f"batch-{number:04d}.json"
        for number in range(1, (len(messages) - 1) // config.labeling.batch_size + 2)
    ]
    artifacts = [output_path, *batch_paths]
    if not state.should_run("label", fingerprint, artifacts):
        return output_path
    state.start("label", fingerprint, artifacts)
    labels: list[MessageLabel] = []
    try:
        for offset in range(0, len(messages), config.labeling.batch_size):
            number = offset // config.labeling.batch_size + 1
            batch = messages[offset : offset + config.labeling.batch_size]
            batch_path = paths.labeled_chat / f"batch-{number:04d}.json"
            expected = [message.message_id for message in batch]
            cached = _load_reusable_batch(
                batch_path,
                number=number,
                provider_name=provider.name,
                model=config.labeling.model,
                input_fingerprint=fingerprint,
                expected_ids=expected,
            )
            if cached is None:
                batch_labels = provider.label(batch)
                received = [label.message_id for label in batch_labels]
                if len(received) != len(set(received)) or received != expected:
                    raise RuntimeError(f"batch-{number:04d} returned incomplete or out-of-order labels")
                normalized = _normalize_labels(
                    batch_labels, provider.name, config.labeling.model, number
                )
                write_json_atomic(
                    batch_path,
                    {
                        "batch_number": number,
                        "provider": provider.name,
                        "input_fingerprint": fingerprint,
                        "rows": [label.model_dump(mode="json") for label in normalized],
                    },
                )
            else:
                normalized = cached
            labels.extend(normalized)
        _write_labeled(output_path, messages, labels)
        state.complete("label", fingerprint, artifacts)
    except BaseException as error:
        state.fail("label", fingerprint, artifacts, error)
        raise
    return output_path


def _load_valid_batch(path: Path, expected_ids: list[str]) -> list[MessageLabel] | None:
    """Load a batch only when its schema and exact ordered IDs remain valid."""
    artifact = _read_batch_artifact(path)
    if artifact is None or artifact.batch_number != _batch_number_from_path(path):
        return None
    received_ids = [row.message_id for row in artifact.rows]
    if len(received_ids) != len(set(received_ids)) or received_ids != expected_ids:
        return None
    return artifact.rows


def _load_reusable_batch(
    path: Path,
    *,
    number: int,
    provider_name: str,
    model: str | None,
    input_fingerprint: str,
    expected_ids: list[str],
) -> list[MessageLabel] | None:
    """Return a cache hit only when metadata agrees with this exact request."""
    artifact = _read_batch_artifact(path)
    if (
        artifact is None
        or artifact.batch_number != number
        or artifact.provider != provider_name
        or artifact.input_fingerprint != input_fingerprint
    ):
        return None
    received_ids = [row.message_id for row in artifact.rows]
    if len(received_ids) != len(set(received_ids)) or received_ids != expected_ids:
        return None
    if any(
        row.provider != provider_name or row.model != model or row.batch_number != number
        for row in artifact.rows
    ):
        return None
    return artifact.rows


def _read_batch_artifact(path: Path) -> _BatchArtifact | None:
    try:
        return _BatchArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def _batch_number_from_path(path: Path) -> int | None:
    match = re.fullmatch(r"batch-(\d+)", path.stem)
    return int(match.group(1)) if match else None


def _normalize_labels(
    labels: list[MessageLabel], provider_name: str, model: str | None, batch_number: int
) -> list[MessageLabel]:
    return [
        label.model_copy(
            update={
                "topic": label.topic.strip() or "其他",
                "provider": provider_name,
                "model": label.model or model,
                "batch_number": batch_number,
            }
        )
        for label in labels
    ]


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
