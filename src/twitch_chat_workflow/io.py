"""Filesystem layout and safe local I/O for a workflow job."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .config import JobConfig


@dataclass(frozen=True)
class JobPaths:
    """The directories owned by one deterministic workflow job."""

    root: Path
    raw_chat: Path
    clean_chat: Path
    labeled_chat: Path
    chat_trends: Path
    status: Path

    @classmethod
    def create(cls, config: JobConfig) -> "JobPaths":
        """Create and return the fixed directory layout for ``config``."""
        snapshot = json.dumps(
            config.redacted_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        job_id = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]
        root = config.output_dir / f"job-{job_id}"
        paths = cls(
            root=root,
            raw_chat=root / "01_raw_chat",
            clean_chat=root / "02_clean_chat",
            labeled_chat=root / "03_labeled_chat",
            chat_trends=root / "04_chat_trends",
            status=root / "09_status",
        )
        for directory in (
            paths.raw_chat,
            paths.clean_chat,
            paths.labeled_chat,
            paths.chat_trends,
            paths.status,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return paths


def write_json_atomic(path: Path, value: object) -> None:
    """Write UTF-8 JSON through a sibling temporary file and replace it atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(value, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def runtime_cookie_source(config: JobConfig) -> str | None:
    """Return the runtime-only browser cookie source without serializing it."""
    return config.cookies_from_browser
