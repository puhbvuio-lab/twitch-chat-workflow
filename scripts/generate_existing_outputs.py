import csv
import ast
from pathlib import Path
from twitch_chat_workflow.analysis import build_analysis_tables
from twitch_chat_workflow.workbook import write_analysis_workbook

OUT = Path(r"D:\主播分析结果\游戏影响分析_20260922")
SOURCES = {
    "Sayu": Path(r"D:\主播分析结果\图表_20260907\Sayu_chat_first_option\06_弹幕趋势对齐\chat_labeled.csv"),
    "Dinah": Path(r"D:\主播分析结果\图表_20260907\Dinah_chat_first_option\06_弹幕趋势对齐\chat_labeled.csv"),
    "Lucy": Path(r"D:\主播分析结果\弹幕数据\LucyPyre\02_弹幕\twitchchatdownloader_first_option_2854377589.csv"),
}
GAME_PRIMARY = {"剧情与世界观", "战斗体验", "探索与互动", "其他整体兴趣"}
GAME_SECONDARY = {"电影化过场/演出高光", "剧情内容/叙事情绪", "整体剧情世界观感受", "BOSS战", "常规战斗", "综合战斗感受", "跑图与移动", "调查与解谜", "角色兴趣", "整体美术与音声兴趣", "游戏整体兴趣", "其他"}
NON_GAME = {"直播体验", "主播表现", "观众互动", "技术问题", "技术与直播质量", "系统与机器人", "机器人通知", "生活闲聊", "其他非游戏内容"}

def load(path):
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        for i, r in enumerate(csv.DictReader(f), 1):
            text = r.get("clean_message") or r.get("text") or r.get("message") or r.get("content") or ""
            raw = r.get("raw_message") or r.get("original_text") or r.get("message") or text
            sentiment = {"正向": "positive", "正面": "positive", "中性": "neutral", "负向": "negative", "负面": "negative"}.get(r.get("sentiment") or r.get("sentiment_label"), "neutral")
            primary = r.get("primary_module") or r.get("topic_primary") or "其他"
            secondary = r.get("secondary_module") or r.get("topic_secondary") or ""
            try:
                parsed = ast.literal_eval(secondary) if isinstance(secondary, str) and secondary.startswith("[") else secondary
                secondary = parsed[0] if isinstance(parsed, list) and parsed else (parsed or primary)
            except (ValueError, SyntaxError):
                secondary = secondary or primary
            target = r.get("evaluation_target") or ""
            direction = r.get("impact_direction") or ("非游戏影响" if any(x in target for x in ("观众", "主播", "社区", "直播")) else "游戏影响" if primary != "其他" else "无法判断")
            if primary in NON_GAME or any(x in primary for x in ("直播", "主播", "观众", "机器人", "技术", "闲聊")):
                direction = "非游戏影响"
                secondary = "其他"
            elif primary not in GAME_PRIMARY:
                direction = "无法判断"
                primary = "其他"
                secondary = "其他"
            elif direction != "非游戏影响":
                direction = "游戏影响"
                if secondary not in GAME_SECONDARY:
                    secondary = "其他"
            rows.append({
                "message_id": r.get("message_id") or r.get("comment_id") or r.get("id") or f"row-{i:06d}",
                "timestamp_seconds": r.get("vod_second") or r.get("timestamp_seconds") or r.get("time_in_seconds") or 0,
                "author": r.get("user_name") or r.get("author") or r.get("username") or "",
                "text": text, "original_text": raw,
                "sentiment": sentiment,
                "raw_topic": r.get("raw_topic") or r.get("topic_raw") or r.get("topic") or "其他",
                "impact_direction": direction,
                "primary_module": primary,
                "secondary_module": secondary,
                "needs_review": r.get("needs_review") or "true",
                "confidence": r.get("confidence") or "低",
                "interest_signal": r.get("interest_signal") or "false",
            })
    return rows

for name, source in SOURCES.items():
    if name == "Lucy":
        continue
    rows = load(source)
    tables = build_analysis_tables(rows, interval_seconds=60)
    target = OUT / name / "弹幕分析_修订_v2.xlsx"
    write_analysis_workbook(tables, target)
    print(name, len(rows), target)
