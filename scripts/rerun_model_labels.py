import csv
import sys
from pathlib import Path
from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.labeling import label_chat
from twitch_chat_workflow.providers import CodexSessionProvider

sources = {
 "Sayu": Path(r"D:\主播分析结果\图表_20260907\Sayu_chat_first_option\06_弹幕趋势对齐\chat_labeled.csv"),
 "Dinah": Path(r"D:\主播分析结果\图表_20260907\Dinah_chat_first_option\06_弹幕趋势对齐\chat_labeled.csv"),
 "Lucy": Path(r"D:\主播分析结果\弹幕数据\LucyPyre\02_弹幕\twitchchatdownloader_first_option_2854377589.csv"),
}
selected = set(sys.argv[1:]) or set(sources)
for name, source in sources.items():
    if name not in selected:
        continue
    out = Path(r"D:\主播分析结果\游戏影响模型重跑_luna_b50_c6_20260922") / name
    config = JobConfig(vod_url=f"local://{name}", output_dir=out, labeling={"enabled": True, "model": "gpt-5.6-luna", "batch_size": 50, "concurrency": 6, "timeout_seconds": 300}, aggregation={"interval_seconds": 60})
    paths = JobPaths.create(config)
    clean = paths.clean_chat / "clean_chat.csv"
    clean.parent.mkdir(parents=True, exist_ok=True)
    with source.open(encoding="utf-8-sig", newline="") as f, clean.open("w", encoding="utf-8", newline="") as g:
        reader = csv.DictReader(f)
        fields = ["message_id", "timestamp_seconds", "timestamp_ms", "timestamp_iso", "author", "text", "original_text", "encoding_warning"]
        writer = csv.DictWriter(g, fieldnames=fields); writer.writeheader()
        for i, row in enumerate(reader, 1):
            text = row.get("clean_message") or row.get("message") or row.get("text") or ""
            writer.writerow({"message_id": row.get("comment_id") or row.get("message_id") or row.get("id") or f"{name}-{i}", "timestamp_seconds": row.get("vod_second") or row.get("timestamp_seconds") or 0, "timestamp_ms": "", "timestamp_iso": "", "author": row.get("user_name") or row.get("author") or "", "text": text, "original_text": row.get("raw_message") or text, "encoding_warning": "false"})
    print(f"{name}: labeling {sum(1 for _ in clean.open(encoding='utf-8'))-1} rows", flush=True)
    label_chat(config, paths, CodexSessionProvider(command=config.labeling.codex_command, model=config.labeling.model, timeout_seconds=config.labeling.timeout_seconds))
    print(f"{name}: complete {paths.labeled_chat / 'labeled_chat.csv'}", flush=True)
