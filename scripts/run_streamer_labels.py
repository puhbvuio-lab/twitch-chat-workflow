"""Label existing TwitchChatDownloader CSVs through the external BigModel API.

Reads danmaku CSVs from D:/mCloudDownload/主播数据, converts each to the
workflow's canonical clean_chat.csv, then runs the resumable label and
aggregate stages.  The API key is resolved from the GLM_API_KEY environment
variable or the local ZCode provider configuration; it is never written into
job configs, snapshots, or logs.

Usage:
    python scripts/run_streamer_labels.py [Sayu] [Dinah] [Lucy]
"""

import csv
import json
import os
import sys
import time
from pathlib import Path

from twitch_chat_workflow.aggregation import aggregate_stage
from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.labeling import label_chat
from twitch_chat_workflow.providers import ExternalApiProvider

SOURCES = {
    "Sayu": Path(r"D:\mCloudDownload\主播数据\Sayu\02_弹幕\twitchchatdownloader_first_option.csv"),
    "Dinah": Path(r"D:\mCloudDownload\主播数据\Dinah\02_弹幕\twitchchatdownloader_first_option.csv"),
    "Lucy": Path(r"D:\mCloudDownload\主播数据\LucyPyre\02_弹幕\twitchchatdownloader_first_option_2854377589.csv"),
}
OUTPUT_ROOT = Path(r"D:\twitch-chat-workflow\results\游戏影响_外接API_20260922")
BATCH_SIZE = 50
CONCURRENCY = 4
LABEL_ATTEMPTS = 8
CLEAN_FIELDS = [
    "message_id", "timestamp_seconds", "timestamp_ms", "timestamp_iso",
    "author", "text", "original_text", "encoding_warning",
]


def resolve_api_key() -> str:
    """Resolve the external API key from the environment or local ZCode config."""
    key = os.environ.get("GLM_API_KEY", "").strip()
    if key:
        return key
    config_path = Path.home() / ".zcode" / "v2" / "config.json"
    if config_path.is_file():
        providers = json.loads(config_path.read_text(encoding="utf-8")).get("provider", {})
        for name in ("builtin:bigmodel-coding-plan", "builtin:bigmodel"):
            candidate = (providers.get(name, {}).get("options", {}).get("apiKey") or "").strip()
            if candidate:
                return candidate
    credentials_path = Path.home() / ".zcode" / "v2" / "credentials.json"
    if credentials_path.is_file():
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
        for name, value in credentials.items():
            if (
                name.startswith("account-provider:")
                and name.endswith(":api-key")
                and isinstance(value, str)
                and value.strip()
                and not value.startswith("enc:")
            ):
                return value.strip()
    raise SystemExit("未找到可用的 API 密钥；请设置 GLM_API_KEY 环境变量后重试")


def resolve_endpoint() -> tuple[str, str]:
    """Return the configured BigModel Anthropic-compatible base URL and model."""
    config_path = Path.home() / ".zcode" / "v2" / "config.json"
    if config_path.is_file():
        entry = json.loads(config_path.read_text(encoding="utf-8")).get("provider", {}).get(
            "builtin:bigmodel-coding-plan", {}
        )
        base_url = (entry.get("options", {}).get("baseURL") or "").strip()
        if base_url:
            return base_url, "GLM-5.3-Flash"
    return "https://open.bigmodel.cn/api/anthropic", "GLM-5.3-Flash"


def convert_clean(name: str, source: Path, clean: Path) -> int:
    """Convert one TwitchChatDownloader CSV into canonical clean rows."""
    count = 0
    with source.open(encoding="utf-8-sig", newline="") as input_file, clean.open(
        "w", encoding="utf-8", newline=""
    ) as output_file:
        reader = csv.DictReader(input_file)
        writer = csv.DictWriter(output_file, fieldnames=CLEAN_FIELDS)
        writer.writeheader()
        for index, row in enumerate(reader, 1):
            text = row.get("message") or ""
            writer.writerow({
                "message_id": row.get("comment_id") or f"{name}-{index:06d}",
                "timestamp_seconds": row.get("time") or 0,
                "timestamp_ms": "",
                "timestamp_iso": row.get("created_at") or "",
                "author": row.get("user_name") or "",
                "text": text,
                "original_text": text,
                "encoding_warning": "false",
            })
            count += 1
    return count


def run_streamer(name: str, source: Path, provider: ExternalApiProvider) -> None:
    print(f"[{name}] source: {source}", flush=True)
    config = JobConfig(
        vod_url=f"local://{name}",
        output_dir=OUTPUT_ROOT / name,
        labeling={
            "enabled": True,
            "provider": "external_api",
            "batch_size": BATCH_SIZE,
            "concurrency": CONCURRENCY,
            "timeout_seconds": 600,
            "max_retries": 5,
        },
        aggregation={"interval_seconds": 60},
    )
    paths = JobPaths.create(config)
    clean_path = paths.clean_chat / "clean_chat.csv"
    if not clean_path.is_file():
        count = convert_clean(name, source, clean_path)
        print(f"[{name}] converted {count} rows -> {clean_path}", flush=True)
    else:
        count = sum(1 for _ in clean_path.open(encoding="utf-8")) - 1
        print(f"[{name}] reusing {count} clean rows", flush=True)
    for attempt in range(1, LABEL_ATTEMPTS + 1):
        try:
            label_chat(config, paths, provider)
            break
        except Exception as error:  # noqa: BLE001 - stage-level retry of failed batches
            if attempt == LABEL_ATTEMPTS:
                raise
            print(f"[{name}] label attempt {attempt} failed ({error}); retrying missing batches", flush=True)
            time.sleep(5)
    labeled = paths.labeled_chat / "labeled_chat.csv"
    print(f"[{name}] labeled -> {labeled}", flush=True)
    aggregate_stage(config, paths)
    workbook = paths.chat_trends / "弹幕分析.xlsx"
    print(f"[{name}] workbook -> {workbook}", flush=True)


def main() -> None:
    selected = [name for name in sys.argv[1:] if name in SOURCES] or list(SOURCES)
    api_key = resolve_api_key()
    base_url, model = resolve_endpoint()
    print(f"external API: {base_url} model={model} concurrency={CONCURRENCY} batch={BATCH_SIZE}", flush=True)
    provider = ExternalApiProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=600,
        max_retries=5,
        max_output_tokens=32768,
        disable_thinking=True,
    )
    for name in selected:
        run_streamer(name, SOURCES[name], provider)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
