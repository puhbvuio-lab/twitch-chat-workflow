from __future__ import annotations

import json
from pathlib import Path

from twitch_chat_workflow.youtube import parse_live_chat


def _line(message_id: str, offset_ms: str, renderer: dict[str, object]) -> str:
    return json.dumps(
        {
            "replayChatItemAction": {
                "videoOffsetTimeMsec": offset_ms,
                "actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
                    "id": message_id,
                    "authorName": {"simpleText": "viewer"},
                    "timestampUsec": "1700000000123456",
                    **renderer,
                }}}}],
            }
        }
    )


def test_parse_live_chat_extracts_text_emoji_and_fractional_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "chat.jsonl"
    path.write_text(_line("m1", "1500", {"message": {"runs": [
        {"text": "hello "}, {"emoji": {"shortcuts": [":wave:"]}},
    ]}}), encoding="utf-8")

    messages = list(parse_live_chat(path))

    assert [(m.message_id, m.timestamp, m.author, m.text) for m in messages] == [
        ("m1", 1.5, "viewer", "hello :wave:")
    ]
    assert messages[0].timestamp_iso == "2023-11-14T22:13:20.123456+00:00"


def test_parse_live_chat_filters_bounds_and_deduplicates_ids(tmp_path: Path) -> None:
    path = tmp_path / "chat.jsonl"
    rows = [
        _line("early", "999", {"message": {"simpleText": "early"}}),
        _line("keep", "1000", {"message": {"simpleText": "kept"}}),
        _line("keep", "1000", {"message": {"simpleText": "duplicate"}}),
        _line("late", "2001", {"message": {"simpleText": "late"}}),
        "{malformed",
    ]
    path.write_text("\n".join(rows), encoding="utf-8")

    messages = list(parse_live_chat(path, start_seconds=1, end_seconds=2))

    assert [(message.message_id, message.text) for message in messages] == [("keep", "kept")]
