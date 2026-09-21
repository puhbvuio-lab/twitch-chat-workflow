"""Atomic, resumable state tracking for individual workflow stages."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping

from .config import JobConfig
from .io import write_json_atomic


_STAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_SECRET_VALUE = re.compile(
    r"(?i)\b(token|secret|password|authorization|cookie)\s*([=:])\s*([^\s,;]+)"
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[^\s,;]+")
_STATUSES = frozenset({"pending", "running", "completed", "failed", "skipped"})


def stage_fingerprint(config: JobConfig, input_files: Mapping[str, Path]) -> str:
    """Return a stable SHA-256 digest for safe config and named input contents."""
    named_hashes = {
        name: _file_sha256(path)
        for name, path in sorted(input_files.items())
    }
    payload = {
        "config": config.redacted_snapshot(),
        "inputs": named_hashes,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class StageStateStore:
    """Persist and consult one atomic JSON state document per workflow stage."""

    def __init__(self, status_dir: Path) -> None:
        self.status_dir = status_dir
        self.status_dir.mkdir(parents=True, exist_ok=True)

    def state_path(self, stage: str) -> Path:
        """Return the state-file path for a safe stage identifier."""
        if not _STAGE_NAME.fullmatch(stage):
            raise ValueError("stage must contain only letters, digits, underscores, and hyphens")
        return self.status_dir / f"{stage}.state.json"

    def should_run(self, stage: str, fingerprint: str, expected: list[Path]) -> bool:
        """Return whether a stage needs execution for its current inputs and artifacts."""
        state = self._read(stage)
        if state is None:
            return True
        if state.get("status") != "completed":
            return True
        if state.get("fingerprint") != fingerprint:
            return True
        return not all(path.is_file() for path in expected)

    def start(self, stage: str, fingerprint: str, artifacts: list[Path]) -> None:
        """Record that a stage began running with the supplied inputs."""
        now = _utc_now()
        previous = self._read(stage)
        self._write(
            stage,
            status="running",
            fingerprint=fingerprint,
            artifacts=artifacts,
            created_at=previous.get("created_at", now) if previous else now,
            started_at=now,
        )

    def complete(self, stage: str, fingerprint: str, artifacts: list[Path]) -> None:
        """Record a successfully completed stage and its output artifacts."""
        now = _utc_now()
        previous = self._read(stage)
        self._write(
            stage,
            status="completed",
            fingerprint=fingerprint,
            artifacts=artifacts,
            created_at=previous.get("created_at", now) if previous else now,
            started_at=previous.get("started_at", now) if previous else now,
            completed_at=now,
        )

    def skip(self, stage: str, fingerprint: str) -> None:
        """Record an intentionally disabled optional stage without creating artifacts."""
        now = _utc_now()
        previous = self._read(stage)
        self._write(
            stage,
            status="skipped",
            fingerprint=fingerprint,
            artifacts=[],
            created_at=previous.get("created_at", now) if previous else now,
        )

    def fail(self, stage: str, fingerprint: str, artifacts: list[Path], error: BaseException) -> None:
        """Record a retryable failed stage without retaining secret-bearing error text."""
        now = _utc_now()
        previous = self._read(stage)
        self._write(
            stage,
            status="failed",
            fingerprint=fingerprint,
            artifacts=artifacts,
            created_at=previous.get("created_at", now) if previous else now,
            started_at=previous.get("started_at", now) if previous else now,
            failed_at=now,
            error_summary=_sanitize_error(error),
        )

    def _read(self, stage: str) -> dict[str, object] | None:
        path = self.state_path(stage)
        if not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("status") not in _STATUSES:
            return None
        return value

    def _write(
        self,
        stage: str,
        *,
        status: str,
        fingerprint: str,
        artifacts: list[Path],
        created_at: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        failed_at: str | None = None,
        error_summary: str | None = None,
    ) -> None:
        state: dict[str, object] = {
            "status": status,
            "fingerprint": fingerprint,
            "created_at": created_at,
            "updated_at": _utc_now(),
            "artifacts": [str(path) for path in artifacts],
        }
        if started_at is not None:
            state["started_at"] = started_at
        if completed_at is not None:
            state["completed_at"] = completed_at
        if failed_at is not None:
            state["failed_at"] = failed_at
        if error_summary is not None:
            state["error_summary"] = error_summary
        write_json_atomic(self.state_path(stage), state)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sanitize_error(error: BaseException) -> str:
    message = f"{type(error).__name__}: {error}"
    message = _SECRET_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", message)
    message = _BEARER_VALUE.sub("Bearer [redacted]", message)
    return message[:1000]
