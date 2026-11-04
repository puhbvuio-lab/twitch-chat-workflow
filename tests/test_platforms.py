from __future__ import annotations

import pytest

from twitch_chat_workflow.platforms import detect_platform, resolve_platform


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.twitch.tv/videos/123", "twitch"),
        ("https://youtube.com/watch?v=abc", "youtube"),
        ("https://www.youtube.com/live/abc", "youtube"),
        ("https://youtu.be/abc", "youtube"),
    ],
)
def test_detect_platform_accepts_supported_video_urls(url: str, expected: str) -> None:
    assert detect_platform(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com.evil.example/watch?v=abc",
        "https://twitch.tv.evil.example/videos/123",
        "https://www.twitch.tv/some_channel",
        "https://www.youtube.com/watch?list=not-a-video",
        "https://example.com/video/123",
    ],
)
def test_detect_platform_rejects_unsupported_or_spoofed_urls(url: str) -> None:
    with pytest.raises(ValueError, match="unsupported"):
        detect_platform(url)


def test_explicit_platform_must_match_url() -> None:
    with pytest.raises(ValueError, match="does not match"):
        resolve_platform("twitch", "https://www.youtube.com/watch?v=abc")
