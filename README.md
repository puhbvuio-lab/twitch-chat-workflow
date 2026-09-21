# Twitch Chat Workflow

This is a standalone workflow for acquiring, cleaning, optionally labeling, and aggregating Twitch VOD chat. It does not download or analyze media, and it has no dependency on sibling projects.

## Setup

Use Python 3.11 or newer, then install this project and its test tools:

```powershell
python -m pip install -e ".[dev]"
```

Create a job from `examples/job.json`, replace the VOD URL, and choose an output directory. `cookies_from_browser` is runtime-only and is deliberately excluded from saved configuration snapshots.

The default aggregation interval is 60 seconds; any positive whole-second interval, including 1 second, is valid.

## Run the workflow

Copy `examples/job.json`, set a VOD URL, then invoke individual retryable stages or the complete sequence:

```powershell
python -m twitch_chat_workflow acquire --config job.json
python -m twitch_chat_workflow clean --config job.json
python -m twitch_chat_workflow label --config job.json
python -m twitch_chat_workflow aggregate --config job.json
python -m twitch_chat_workflow run --config job.json
```

Each job writes raw JSONL, normalized CSV, optional labeled CSV, trends CSV/JSON, and atomic stage state under its own `output/job-*/` directory. A completed stage is skipped only when its redacted configuration/input fingerprint and all expected artifacts still match; missing artifacts, changed inputs, and failed batches rerun safely. Raw chat is never overwritten by cleaning or labeling.

Set `aggregation.interval_seconds` to `1` for one-second windows. Empty windows are intentionally emitted with zero metrics, while message-level timestamps retain their original fractional-second and `timestamp_ms` precision.

`cookies_from_browser` is a runtime-only browser source such as `chrome` or `edge`. It is passed to the acquisition adapter but deliberately omitted from job snapshots and sanitized error records. Do not put cookie values, access tokens, or secrets in the JSON config.

The optional acquisition integration is installed with `pip install -e ".[acquisition]"`. Semantic labeling is disabled by default; applications can supply a fakeable `codex_session` provider with `openai_responses` as its configured fallback. This project only handles VOD chat: it does not download media, inspect video, analyze audio, create CCV/history data, or write Excel reports.
