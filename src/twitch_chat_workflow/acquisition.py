"""Twitch chat acquisition behind a small, fakeable downloader boundary."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from .config import JobConfig
from .io import JobPaths, runtime_cookie_source
from .models import RawMessage
from .state import StageStateStore, stage_fingerprint


class ChatDownloader(Protocol):
    def fetch(
        self, vod_url: str, start_seconds: int | None, end_seconds: int | None, cookie_source: str | None
    ) -> Iterable[RawMessage]: ...


class TwitchChatDownloaderAdapter:
    """Lazy adapter so importing the workflow never imports an optional network package."""

    def fetch(
        self, vod_url: str, start_seconds: int | None, end_seconds: int | None, cookie_source: str | None
    ) -> Iterable[RawMessage]:
        try:
            from twitch_chat_downloader import ChatDownloader as ExternalDownloader
        except ImportError as error:  # pragma: no cover - depends on optional extra
            raise RuntimeError("TwitchChatDownloader is unavailable; install the acquisition extra") from error
        downloader = ExternalDownloader()
        options: dict[str, Any] = {"start_time": start_seconds, "end_time": end_seconds}
        if cookie_source:
            options["cookies_from_browser"] = cookie_source
        for item in downloader.get_chat(vod_url, **{key: value for key, value in options.items() if value is not None}):
            yield _raw_message(item)


def _raw_message(item: Any) -> RawMessage:
    value = dict(item) if isinstance(item, dict) else dict(vars(item))
    timestamp = value.get("time_in_seconds", value.get("timestamp", value.get("time", 0)))
    text = value.get("message", value.get("text", ""))
    author = value.get("author", value.get("author_name", value.get("user_name", "")))
    if isinstance(author, dict):
        author = author.get("name", author.get("display_name", ""))
    return RawMessage(
        timestamp=float(timestamp), text=str(text), author=str(author or ""),
        message_id=str(value.get("message_id", value.get("id", ""))) or None,
        timestamp_iso=value.get("timestamp_iso", value.get("created_at")), payload=value,
    )


def acquire_chat(config: JobConfig, paths: JobPaths, downloader: ChatDownloader) -> Path:
    """Fetch and preserve raw records as immutable JSONL, recording safe resumable state."""
    raw_path = paths.raw_chat / "raw_chat.jsonl"
    state = StageStateStore(paths.status)
    fingerprint = stage_fingerprint(config, {})
    if not state.should_run("acquire", fingerprint, [raw_path]):
        return raw_path
    state.start("acquire", fingerprint, [raw_path])
    try:
        with raw_path.open("w", encoding="utf-8", newline="\n") as output:
            for message in downloader.fetch(
                config.vod_url, config.start_seconds, config.end_seconds, runtime_cookie_source(config)
            ):
                output.write(json.dumps(message.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
                output.write("\n")
        state.complete("acquire", fingerprint, [raw_path])
    except BaseException as error:
        state.fail("acquire", fingerprint, [raw_path], error)
        raise
    return raw_path
