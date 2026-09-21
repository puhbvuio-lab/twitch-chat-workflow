# Twitch Chat Workflow

This is a standalone workflow for acquiring, cleaning, optionally labeling, and aggregating Twitch VOD chat. It does not download or analyze media, and it has no dependency on sibling projects.

## Setup

Use Python 3.11 or newer, then install this project and its test tools:

```powershell
python -m pip install -e ".[dev]"
```

Create a job from `examples/job.json`, replace the VOD URL, and choose an output directory. `cookies_from_browser` is runtime-only and is deliberately excluded from saved configuration snapshots.

The default aggregation interval is 60 seconds; any positive whole-second interval, including 1 second, is valid.
