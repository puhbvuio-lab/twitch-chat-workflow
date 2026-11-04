"""Strict video-platform detection and configuration resolution."""

from __future__ import annotations

from typing import Literal
from urllib.parse import parse_qs, urlparse

Platform = Literal["twitch", "youtube"]
PlatformSetting = Literal["auto", "twitch", "youtube"]


def detect_platform(vod_url: str) -> Platform:
    parsed = urlparse(vod_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.rstrip("/")
    if parsed.scheme in {"http", "https"} and host in {"twitch.tv", "www.twitch.tv"}:
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == "videos" and parts[2]:
            return "twitch"
    if parsed.scheme in {"http", "https"} and host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if (path == "/watch" and parse_qs(parsed.query).get("v")) or path.startswith("/live/"):
            return "youtube"
    if parsed.scheme in {"http", "https"} and host == "youtu.be" and path not in {"", "/"}:
        return "youtube"
    raise ValueError(f"unsupported VOD URL: {vod_url}")


def resolve_platform(setting: PlatformSetting, vod_url: str) -> Platform:
    detected = detect_platform(vod_url)
    if setting != "auto" and setting != detected:
        raise ValueError(f"configured platform {setting!r} does not match URL platform {detected!r}")
    return detected
