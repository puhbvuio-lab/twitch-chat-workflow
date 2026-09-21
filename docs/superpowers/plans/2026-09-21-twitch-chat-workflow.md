# Twitch Chat Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, resumable Twitch VOD chat acquisition, cleanup, optional semantic-labeling, and aggregation command-line project.

**Architecture:** A configuration-driven CLI orchestrates four pure stages—acquire, clean, label, aggregate—whose only shared contract is typed CSV/JSON written inside one job directory. A state manager fingerprints inputs and records atomically written stage status, so the stages can be rerun independently without altering raw downloads.

**Tech Stack:** Python 3.11+, Typer, Pydantic v2, pandas, TwitchChatDownloader adapter, pytest, optional Codex/OpenAI provider adapters.

**Spec:** `D:\twitch-chat-workflow\docs\superpowers\specs\2026-09-21-twitch-chat-workflow-design.md`

## Global Constraints

- The project is self-contained: no import, relative path, config, output folder, or command may depend on either sibling project or prior Twitch-analysis repositories.
- The sole mandatory input is `vod_url`; time bounds, cookies, labeling and aggregation interval are optional.
- Preserve source timestamps to their available precision; aggregation accepts every positive integer interval, with 1 second as the minimum.
- Raw downloads are immutable. Never write credentials, cookies, tokens, or secrets to a job snapshot, log, error, CSV, or JSON output.
- Only confirmed encoding repair is automatic. Ambiguous text is retained with `encoding_warning`.
- Network and model calls are behind adapters; unit tests use fakes and never need Twitch, Codex, or OpenAI access.

## Review Focus

- Empty one-second windows must exist with zero message metrics, while message-level timestamp precision remains unchanged (Task 6).
- Identical text from different authors must not be deduplicated merely because the text matches (Task 4).
- A partial semantic-label batch must be surfaced as failed/retryable, not silently converted to neutral labels (Task 5).
- A retry with identical config and complete artifacts must skip the completed stage, whereas a changed source/config must invalidate it (Task 3).
- A cookie source must be accepted as runtime-only input but absent from snapshots/logs and provider errors (Task 2).

---

## File Structure

```text
twitch-chat-workflow/
  pyproject.toml
  README.md
  examples/job.json
  src/twitch_chat_workflow/
    __init__.py  __main__.py  cli.py  config.py  models.py  state.py
    acquisition.py  normalization.py  labeling.py  aggregation.py
    providers.py  io.py
  tests/
    conftest.py  test_config.py  test_state.py  test_acquisition.py
    test_normalization.py  test_labeling.py  test_aggregation.py  test_cli.py
```

### Task 1: Project scaffold and configuration contract

**Files:**
- Create: `pyproject.toml`, `README.md`, `examples/job.json`
- Create: `src/twitch_chat_workflow/__init__.py`, `src/twitch_chat_workflow/config.py`, `src/twitch_chat_workflow/models.py`
- Test: `tests/test_config.py`

**Interfaces:** `JobConfig.from_file(path: Path) -> JobConfig`; `JobConfig.redacted_snapshot() -> dict[str, object]`.

- [ ] Write failing validation tests for a one-second interval, missing VOD URL, reversed bounds, and cookie redaction.
- [ ] Run `pytest tests/test_config.py -v`; expect failure.
- [ ] Implement Pydantic models: enforce `interval_seconds >= 1`, `end_seconds > start_seconds` when both exist, and omit `cookies_from_browser` from snapshots.
- [ ] Add packaging and a credential-free example config with a 60-second default interval.
- [ ] Run `pytest tests/test_config.py -v`; expect PASS.

### Task 2: Filesystem layout, safe I/O, and runtime secret handling

**Files:**
- Create: `src/twitch_chat_workflow/io.py`, `tests/test_acquisition.py`
- Modify: `src/twitch_chat_workflow/config.py`

**Interfaces:** `JobPaths.create(config: JobConfig) -> JobPaths`; `write_json_atomic(path: Path, value: object) -> None`; `runtime_cookie_source(config: JobConfig) -> str | None`.

- [ ] Write failing tests asserting all five job subdirectories are created, JSON writes are atomic, and cookie source does not appear in snapshot text.
- [ ] Run `pytest tests/test_acquisition.py -v`; expect failure.
- [ ] Implement directory creation and UTF-8 JSON/CSV helpers with temporary sibling files plus replace; isolate cookie access to runtime.
- [ ] Run `pytest tests/test_acquisition.py -v`; expect PASS.

### Task 3: Resumable stage state manager

**Files:**
- Create: `src/twitch_chat_workflow/state.py`, `tests/test_state.py`

**Interfaces:** `StageStateStore.should_run(stage: str, fingerprint: str, expected: list[Path]) -> bool`; `start/complete/fail(stage: str, ...) -> None`.

- [ ] Write failing tests for completed-artifact skip, missing-artifact rerun, changed-fingerprint rerun, and failed-state error preservation.
- [ ] Run `pytest tests/test_state.py -v`; expect failure.
- [ ] Implement SHA-256 fingerprints from redacted config plus named input file hashes and atomic per-stage state files under `09_status`.
- [ ] Run `pytest tests/test_state.py -v`; expect PASS.

### Task 4: Acquisition and deterministic normalization

**Files:**
- Create: `src/twitch_chat_workflow/acquisition.py`, `src/twitch_chat_workflow/normalization.py`
- Test: `tests/test_normalization.py`, `tests/test_acquisition.py`

**Interfaces:** `ChatDownloader.fetch(vod_url, start_seconds, end_seconds, cookie_source) -> Iterable[RawMessage]`; `acquire_chat(config, paths, downloader) -> Path`; `normalize_chat(raw_path, paths) -> Path`.

- [ ] Write fake-downloader tests for raw preservation, bounds forwarding, and cookie redaction in exception text.
- [ ] Write normalization tests for timestamp sorting, confirmed mojibake repair, ambiguous warning, same-text/different-author retention, and exact-record de-duplication.
- [ ] Run `pytest tests/test_acquisition.py tests/test_normalization.py -v`; expect failure.
- [ ] Implement a TwitchChatDownloader adapter and raw JSONL writer, then generate UTF-8 CSV, excluded-row CSV, and repair statistics JSON.
- [ ] Run the two test files; expect PASS.

### Task 5: Optional semantic-label provider contract

**Files:**
- Create: `src/twitch_chat_workflow/providers.py`, `src/twitch_chat_workflow/labeling.py`
- Test: `tests/test_labeling.py`

**Interfaces:** `SemanticLabelProvider.label(messages: list[ChatMessage]) -> list[MessageLabel]`; `label_chat(config, paths, provider) -> Path | None`.

- [ ] Write failing tests for disabled labeling (`skipped`), batch ordering, `codex_session` with `openai_responses` fallback, and a failed batch remaining retryable.
- [ ] Run `pytest tests/test_labeling.py -v`; expect failure.
- [ ] Implement provider selection and JSON batch persistence; map provider failures to failed state without synthesizing labels.
- [ ] Run `pytest tests/test_labeling.py -v`; expect PASS.

### Task 6: Per-second-or-larger aggregation and CLI orchestration

**Files:**
- Create: `src/twitch_chat_workflow/aggregation.py`, `src/twitch_chat_workflow/cli.py`, `src/twitch_chat_workflow/__main__.py`
- Test: `tests/test_aggregation.py`, `tests/test_cli.py`

**Interfaces:** `aggregate_chat(input_csv: Path, interval_seconds: int, bounds: tuple[int, int] | None) -> DataFrame`; CLI commands `acquire`, `clean`, `label`, `aggregate`, `run`, all accepting `--config PATH`.

- [ ] Write failing aggregation tests for 1-second empty windows, 60-second half-open boundaries, preserved millisecond timestamps, and labeled/unlabeled metrics.
- [ ] Write CLI tests verifying `run` executes stages in order and stops after a failed stage.
- [ ] Run `pytest tests/test_aggregation.py tests/test_cli.py -v`; expect failure.
- [ ] Implement trends CSV/JSON and Typer CLI, with every stage consulting `StageStateStore`.
- [ ] Run `pytest -q`; expect all tests PASS.

### Task 7: Copy-and-run documentation and offline smoke fixture

**Files:**
- Modify: `README.md`, `examples/job.json`
- Create: `tests/fixtures/raw_chat.jsonl`, `tests/test_smoke.py`

- [ ] Write an offline smoke test that runs fake acquisition through clean, disabled label, and 1-second aggregate.
- [ ] Run `pytest tests/test_smoke.py -v`; expect failure.
- [ ] Document standalone installation, execution, retries, 1-second aggregation, cookie practice, and explicit media/audio exclusion.
- [ ] Run `pytest -q`; expect PASS.
