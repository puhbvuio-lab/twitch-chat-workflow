from __future__ import annotations

from twitch_chat_workflow.analysis import build_analysis_tables


def test_builds_sorted_traceable_sentiment_topic_and_quote_tables() -> None:
    """Catches lost empty windows, unstable ordering, or untraceable topic rows."""
    rows = [
        {"message_id": "m3", "timestamp_seconds": "75", "author": "c", "text": "later", "original_text": "第三句", "sentiment": "negative", "topic": "游戏", "interest_signal": "false", "impact_direction": "游戏影响", "primary_module": "战斗体验", "secondary_module": "常规战斗"},
        {"message_id": "m2", "timestamp_seconds": "5", "author": "b", "text": "two", "original_text": "第一句", "sentiment": "neutral", "topic": "", "interest_signal": "false", "impact_direction": "无法判断", "primary_module": "其他", "secondary_module": "其他"},
        {"message_id": "m1", "timestamp_seconds": "5", "author": "a", "text": "one", "original_text": "第一句", "sentiment": "positive", "topic": "游戏", "interest_signal": "true", "impact_direction": "游戏影响", "primary_module": "战斗体验", "secondary_module": "BOSS战"},
        {"message_id": "m5", "timestamp_seconds": "110", "author": "e", "text": "five", "original_text": "第五句", "sentiment": "positive", "topic": "其他", "interest_signal": "true", "impact_direction": "游戏影响", "primary_module": "剧情与世界观", "secondary_module": "剧情内容/叙事情绪"},
        {"message_id": "m4", "timestamp_seconds": "80", "author": "d", "text": "four", "original_text": "第四句", "sentiment": "positive", "topic": "游戏", "interest_signal": "false", "impact_direction": "非游戏影响", "primary_module": "技术与直播质量", "secondary_module": "技术与直播质量"},
    ]

    tables = build_analysis_tables(rows, interval_seconds=60, bounds=(0, 180))

    assert [row["message_id"] for row in tables.label_rows] == ["m1", "m2", "m3", "m4", "m5"]
    assert tables.label_rows[1]["raw_topic"] == "其他"
    assert tables.sentiment_rows == [
        {"start_seconds": 0, "end_seconds": 60, "message_count": 2, "unique_authors": 2, "positive": 1, "neutral": 1, "negative": 0, "interest_signals": 1, "positive_share": 0.5, "neutral_share": 0.5, "negative_share": 0.0},
        {"start_seconds": 60, "end_seconds": 120, "message_count": 3, "unique_authors": 3, "positive": 2, "neutral": 0, "negative": 1, "interest_signals": 1, "positive_share": 2 / 3, "neutral_share": 0.0, "negative_share": 1 / 3},
        {"start_seconds": 120, "end_seconds": 180, "message_count": 0, "unique_authors": 0, "positive": 0, "neutral": 0, "negative": 0, "interest_signals": 0, "positive_share": 0.0, "neutral_share": 0.0, "negative_share": 0.0},
    ]
    # BOSS战与常规战斗保持独立，非游戏技术弹幕不得混入游戏影响模块。
    assert [(row["secondary_module"], row["message_count"]) for row in tables.topic_summary_rows] == [
        ("BOSS战", 1), ("其他", 1), ("剧情内容/叙事情绪", 1), ("常规战斗", 1), ("技术与直播质量", 1),
    ]
    assert tables.topic_summary_rows[0] == {
        "secondary_module": "BOSS战", "report_topic": "BOSS战", "message_count": 1, "share": 0.2,
        "first_seconds": 5.0, "last_seconds": 5.0, "positive": 1, "neutral": 0, "negative": 0,
        "representative_quote_1": "第一句", "representative_quote_2": "", "representative_quote_3": "",
    }
    assert tables.topic_trend_rows == [
        {"start_seconds": 0, "end_seconds": 60, "secondary_module": "BOSS战", "report_topic": "BOSS战", "message_count": 1, "topic_share": 0.5, "positive": 1, "neutral": 0, "negative": 0},
        {"start_seconds": 0, "end_seconds": 60, "secondary_module": "其他", "report_topic": "其他", "message_count": 1, "topic_share": 0.5, "positive": 0, "neutral": 1, "negative": 0},
        {"start_seconds": 60, "end_seconds": 120, "secondary_module": "剧情内容/叙事情绪", "report_topic": "剧情内容/叙事情绪", "message_count": 1, "topic_share": 1 / 3, "positive": 1, "neutral": 0, "negative": 0},
        {"start_seconds": 60, "end_seconds": 120, "secondary_module": "常规战斗", "report_topic": "常规战斗", "message_count": 1, "topic_share": 1 / 3, "positive": 0, "neutral": 0, "negative": 1},
        {"start_seconds": 60, "end_seconds": 120, "secondary_module": "技术与直播质量", "report_topic": "技术与直播质量", "message_count": 1, "topic_share": 1 / 3, "positive": 1, "neutral": 0, "negative": 0},
    ]
    assert tables.quote_rows == [
        {"timestamp_seconds": 5.0, "author": "a", "original_text": "第一句", "raw_topic": "游戏", "impact_direction": "游戏影响", "primary_module": "战斗体验", "secondary_module": "BOSS战", "sentiment": "positive", "message_id": "m1"},
        {"timestamp_seconds": 5.0, "author": "b", "original_text": "第一句", "raw_topic": "其他", "impact_direction": "无法判断", "primary_module": "其他", "secondary_module": "其他", "sentiment": "neutral", "message_id": "m2"},
        {"timestamp_seconds": 75.0, "author": "c", "original_text": "第三句", "raw_topic": "游戏", "impact_direction": "游戏影响", "primary_module": "战斗体验", "secondary_module": "常规战斗", "sentiment": "negative", "message_id": "m3"},
        {"timestamp_seconds": 80.0, "author": "d", "original_text": "第四句", "raw_topic": "游戏", "impact_direction": "非游戏影响", "primary_module": "技术与直播质量", "secondary_module": "技术与直播质量", "sentiment": "positive", "message_id": "m4"},
        {"timestamp_seconds": 110.0, "author": "e", "original_text": "第五句", "raw_topic": "其他", "impact_direction": "游戏影响", "primary_module": "剧情与世界观", "secondary_module": "剧情内容/叙事情绪", "sentiment": "positive", "message_id": "m5"},
    ]


def test_returns_empty_tables_without_rows_and_keeps_bounded_zero_windows() -> None:
    """Catches division by zero and dropping requested empty intervals."""
    empty = build_analysis_tables([], interval_seconds=60)
    bounded = build_analysis_tables([], interval_seconds=60, bounds=(0, 60))

    assert empty.label_rows == []
    assert empty.sentiment_rows == []
    assert empty.topic_summary_rows == []
    assert empty.topic_trend_rows == []


def test_groups_raw_topics_under_one_fixed_report_topic() -> None:
    rows = [
        {"message_id": "m1", "timestamp_seconds": "1", "original_text": "脚趾痛", "raw_topic": "撞脚趾", "report_topic": "其他", "sentiment": "negative"},
        {"message_id": "m2", "timestamp_seconds": "2", "original_text": "别切脚趾", "raw_topic": "脚趾处理", "report_topic": "其他", "sentiment": "neutral"},
    ]
    tables = build_analysis_tables(rows, 60)
    assert tables.topic_summary_rows[0]["report_topic"] == "其他"
    assert tables.topic_summary_rows[0]["message_count"] == 2
    assert tables.label_rows[0]["raw_topic"] == "撞脚趾"


def test_legacy_topic_is_preserved_as_raw_topic_and_safely_reported_as_other() -> None:
    row = build_analysis_tables([{"message_id": "m1", "timestamp_seconds": "1", "topic": "旧主题"}], 60).label_rows[0]
    assert (row["raw_topic"], row["report_topic"]) == ("旧主题", "其他")


def test_topic_summary_uses_first_three_unique_nonblank_quotes_and_name_tiebreaker() -> None:
    """Catches duplicate/blank quote selection and unstable equal-count topic order."""
    rows = [
        {"message_id": "a6", "timestamp_seconds": "60", "original_text": "第四句", "sentiment": "neutral", "topic": "A"},
        {"message_id": "b6", "timestamp_seconds": "6", "original_text": "b6", "sentiment": "neutral", "topic": "B"},
        {"message_id": "a3", "timestamp_seconds": "30", "original_text": "  ", "sentiment": "neutral", "topic": "A"},
        {"message_id": "b1", "timestamp_seconds": "1", "original_text": "b1", "sentiment": "neutral", "topic": "B"},
        {"message_id": "a2", "timestamp_seconds": "20", "original_text": "第一句", "sentiment": "neutral", "topic": "A"},
        {"message_id": "b5", "timestamp_seconds": "5", "original_text": "b5", "sentiment": "neutral", "topic": "B"},
        {"message_id": "a1", "timestamp_seconds": "10", "original_text": "第一句", "sentiment": "neutral", "topic": "A"},
        {"message_id": "b2", "timestamp_seconds": "2", "original_text": "b2", "sentiment": "neutral", "topic": "B"},
        {"message_id": "a5", "timestamp_seconds": "50", "original_text": "第三句", "sentiment": "neutral", "topic": "A"},
        {"message_id": "b4", "timestamp_seconds": "4", "original_text": "b4", "sentiment": "neutral", "topic": "B"},
        {"message_id": "a4", "timestamp_seconds": "40", "original_text": "第二句", "sentiment": "neutral", "topic": "A"},
        {"message_id": "b3", "timestamp_seconds": "3", "original_text": "b3", "sentiment": "neutral", "topic": "B"},
    ]

    summaries = build_analysis_tables(rows, interval_seconds=60).topic_summary_rows

    assert [summary["report_topic"] for summary in summaries] == ["其他"]
    assert summaries[0]["representative_quote_1"] == "b1"
    assert summaries[0]["representative_quote_2"] == "b2"
    assert summaries[0]["representative_quote_3"] == "b3"
