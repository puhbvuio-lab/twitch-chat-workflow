# Twitch/YouTube Dual-Platform Chat Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Add URL-routed Twitch and YouTube live-chat replay acquisition while preserving normalization, labeling, aggregation, and Excel output.

**Architecture:** Keep the downloader protocol and Twitch adapter. Add strict platform detection, a yt-dlp-backed YouTube adapter, and a downloader factory used by the CLI. Both adapters emit the existing RawMessage model.

**Tech Stack:** Python 3.11, Pydantic 2, Typer, yt-dlp, twitch-chat-downloader, pytest

**Spec:** docs/superpowers/specs/2026-11-04-dual-platform-chat-acquisition-design.md

## Global Constraints

- Preserve Twitch job JSON compatibility.
- Default platform to auto.
- Never serialize cookies_from_browser.
- Unit tests must not access external services.
- Do not treat a missing YouTube replay as an empty successful acquisition.

## Review Focus

- Reject hostname spoofing such as youtube.com.evil.example.
- Fail explicit platform and URL mismatches before invoking a downloader.
- Deduplicate duplicate YouTube ticker/chat records by message ID.
- Skip malformed renderer fields without corrupting valid rows.
- Preserve fractional-second timestamps and time boundaries.

### Task 1: Platform detection and configuration

Files: config.py, new platforms.py, test_config.py, new test_platforms.py.

- [ ] Write failing URL and configuration tests.
- [ ] Run and confirm RED.
- [ ] Implement strict URL parsing and validation.
- [ ] Run and confirm GREEN.

### Task 2: YouTube live-chat parsing

Files: new youtube.py and test_youtube.py.

- [ ] Write failing fixture tests for text, emoji, paid messages, stickers, memberships, duplicates, malformed rows and time filtering.
- [ ] Run and confirm RED.
- [ ] Implement the parser.
- [ ] Run and confirm GREEN.

### Task 3: YouTube adapter and CLI routing

Files: acquisition.py, cli.py, test_acquisition.py and test_cli.py.

- [ ] Write failing tests for yt-dlp arguments, Cookie forwarding, missing output, subprocess failure and adapter selection.
- [ ] Run and confirm RED.
- [ ] Implement temporary-file download and routing.
- [ ] Run and confirm GREEN.

### Task 4: Packaging and documentation

Files: pyproject.toml, README.md, examples/job.json and new examples/youtube-job.json.

- [ ] Add platform-specific and combined acquisition extras.
- [ ] Document URL forms, platform selection, Cookie behavior and limitations.
- [ ] Add Twitch and YouTube examples and verify both parse.

### Task 5: Verification and publication

- [ ] Run the complete pytest suite.
- [ ] Run a public YouTube replay acquisition smoke test without labeling.
- [ ] Verify non-empty raw JSONL, unique IDs and ordered timestamps.
- [ ] Run git diff --check and review status/diff.
- [ ] Commit and push codex/youtube-chat-adapter to GitHub.
- [ ] Create or provide the pull-request URL against release/2.0.
