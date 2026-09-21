"""Deterministic conversion of raw JSONL chat into canonical CSV rows."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .config import JobConfig
from .io import JobPaths, write_json_atomic
from .state import StageStateStore, stage_fingerprint


_SUSPICIOUS = re.compile(r"(?:Ã.?|Â.|â€|ðŸ|锛|鏅|浠|閰|闃|鏂|鍙|鍥|鈥)")


def repair_mojibake(text: str) -> tuple[str, str, str]:
    """Repair only reversible, clearly improved UTF-8-as-single-byte corruption."""
    if not text or not _SUSPICIOUS.search(text):
        return text, "original", "none"
    score = _mojibake_score(text)
    candidates: list[tuple[str, str]] = []
    for encoding in ("latin1", "cp1252", "gb18030"):
        try:
            candidate = text.encode(encoding).decode("utf-8")
        except UnicodeError:
            continue
        if candidate != text:
            candidates.append((candidate, encoding))
    if not candidates:
        return text, "ambiguous", "no_reversible_candidate"
    candidate, encoding = min(candidates, key=lambda item: _mojibake_score(item[0]))
    if score - _mojibake_score(candidate) >= 8 and "\ufffd" not in candidate:
        return candidate, "repaired", f"{encoding}_bytes_to_utf8"
    return text, "ambiguous", "candidate_not_certain"


def _mojibake_score(value: str) -> int:
    return value.count("\ufffd") * 30 + len(_SUSPICIOUS.findall(value)) * 12


_FIELDS = ["message_id", "timestamp_seconds", "timestamp_ms", "timestamp_iso", "author", "text", "original_text", "encoding_warning"]


def normalize_chat(raw_path: Path, paths: JobPaths, config: JobConfig | None = None) -> Path:
    """Sort, repair conservatively, de-duplicate exact source records, and write audit outputs."""
    clean_path = paths.clean_chat / "clean_chat.csv"
    excluded_path = paths.clean_chat / "excluded_rows.csv"
    audit_path = paths.clean_chat / "repair_statistics.json"
    state = StageStateStore(paths.status)
    fingerprint = stage_fingerprint(config, {"raw_chat": raw_path}) if config else _file_fingerprint(raw_path)
    artifacts = [clean_path, excluded_path, audit_path]
    if not state.should_run("clean", fingerprint, artifacts):
        return clean_path
    state.start("clean", fingerprint, artifacts)
    try:
        seen: set[str] = set()
        rows: list[dict[str, Any]] = []
        excluded: list[dict[str, str]] = []
        repaired = ambiguous = duplicates = 0
        for line_number, line in enumerate(raw_path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                source = json.loads(line)
                if not isinstance(source, dict):
                    raise ValueError("record is not an object")
                timestamp = float(source.get("timestamp", source.get("time_in_seconds", 0)))
                original = str(source.get("text", source.get("message", "")))
            except (ValueError, TypeError, json.JSONDecodeError) as error:
                excluded.append({"line_number": str(line_number), "reason": str(error), "raw": line})
                continue
            exact = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            if exact in seen:
                duplicates += 1
                excluded.append({"line_number": str(line_number), "reason": "exact_duplicate", "raw": line})
                continue
            seen.add(exact)
            text, status, _method = repair_mojibake(original)
            repaired += status == "repaired"
            ambiguous += status == "ambiguous"
            message_id = str(source.get("message_id") or source.get("id") or _message_id(source, line_number))
            timestamp_ms = source.get("timestamp_ms")
            if timestamp_ms is None and isinstance(source.get("timestamp"), int):
                timestamp_ms = int(round(timestamp * 1000))
            rows.append({
                "message_id": message_id, "timestamp_seconds": timestamp,
                "timestamp_ms": "" if timestamp_ms is None else int(timestamp_ms),
                "timestamp_iso": source.get("timestamp_iso", ""), "author": source.get("author", source.get("user_name", "")),
                "text": text, "original_text": original, "encoding_warning": str(status == "ambiguous").lower(),
            })
        rows.sort(key=lambda row: (float(row["timestamp_seconds"]), str(row["message_id"])))
        _write_csv(clean_path, _FIELDS, rows)
        _write_csv(excluded_path, ["line_number", "reason", "raw"], excluded)
        write_json_atomic(audit_path, {"source_rows": len(rows) + len(excluded), "clean_rows": len(rows), "excluded_rows": len(excluded), "repaired_rows": repaired, "ambiguous_rows": ambiguous, "exact_duplicates": duplicates})
        state.complete("clean", fingerprint, artifacts)
    except BaseException as error:
        state.fail("clean", fingerprint, artifacts, error)
        raise
    return clean_path


def _message_id(source: dict[str, Any], line_number: int) -> str:
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{line_number}:{canonical}".encode("utf-8")).hexdigest()[:20]


def _file_fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
