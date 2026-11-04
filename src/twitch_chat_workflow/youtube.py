"""Parse yt-dlp's YouTube live-chat replay JSONL into canonical raw messages."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import RawMessage


def _text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    if "simpleText" in value:
        return str(value["simpleText"])
    pieces: list[str] = []
    for run in value.get("runs", []):
        if not isinstance(run, dict):
            continue
        if "text" in run:
            pieces.append(str(run["text"]))
        elif isinstance(run.get("emoji"), dict):
            emoji = run["emoji"]
            shortcuts = emoji.get("shortcuts") or []
            pieces.append(str(shortcuts[0]) if shortcuts else str(emoji.get("emojiId", "")))
    return "".join(pieces)


def _renderers(item: Any) -> Iterable[tuple[str, dict[str, Any]]]:
    if isinstance(item, dict):
        for key, value in item.items():
            if key.startswith("liveChat") and key.endswith("Renderer") and isinstance(value, dict):
                yield key, value
            else:
                yield from _renderers(value)
    elif isinstance(item, list):
        for value in item:
            yield from _renderers(value)


def parse_live_chat(
    path: Path, start_seconds: int | None = None, end_seconds: int | None = None
) -> Iterable[RawMessage]:
    """Yield valid replay messages, keeping start inclusive and end exclusive."""
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        for raw_line in source:
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            replay = record.get("replayChatItemAction", {}) if isinstance(record, dict) else {}
            try:
                timestamp = float(replay.get("videoOffsetTimeMsec")) / 1000
            except (TypeError, ValueError):
                continue
            if start_seconds is not None and timestamp < start_seconds:
                continue
            if end_seconds is not None and timestamp >= end_seconds:
                continue
            for renderer_type, renderer in _renderers(replay.get("actions", [])):
                message_id = str(renderer.get("id", ""))
                if not message_id or message_id in seen:
                    continue
                text = _text(renderer.get("message"))
                if not text:
                    text = _text(renderer.get("purchaseAmountText")) or _text(renderer.get("headerSubtext"))
                if not text and "Sticker" in renderer_type:
                    text = "[付费贴纸]"
                if not text:
                    continue
                timestamp_iso = None
                try:
                    usec = int(renderer.get("timestampUsec"))
                    timestamp_iso = datetime.fromtimestamp(usec / 1_000_000, timezone.utc).isoformat()
                except (TypeError, ValueError, OSError):
                    pass
                seen.add(message_id)
                yield RawMessage(
                    timestamp=timestamp,
                    text=text,
                    author=_text(renderer.get("authorName")),
                    message_id=message_id,
                    timestamp_iso=timestamp_iso,
                    payload={"platform": "youtube", "renderer_type": renderer_type, "raw": renderer},
                )
