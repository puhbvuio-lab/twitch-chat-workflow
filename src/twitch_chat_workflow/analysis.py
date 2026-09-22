"""Pure, traceable analysis tables derived from complete labeled chat rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_SENTIMENTS = ("positive", "neutral", "negative")
_REPORT_TOPICS = {"游戏内容", "直播体验", "主播表现", "观众互动", "技术问题", "角色或剧情", "其他"}


@dataclass(frozen=True)
class AnalysisTables:
    """Sorted, presentation-neutral data used by the CSV and workbook exporters."""

    label_rows: list[dict[str, Any]]
    sentiment_rows: list[dict[str, Any]]
    topic_summary_rows: list[dict[str, Any]]
    topic_trend_rows: list[dict[str, Any]]
    quote_rows: list[dict[str, Any]]


def build_analysis_tables(
    rows: list[dict[str, str]],
    interval_seconds: int,
    bounds: tuple[int, int] | None = None,
) -> AnalysisTables:
    """Build sorted label, sentiment, topic, and original-quote tables.

    Windows are half-open and follow :func:`aggregate_chat` semantics.  The
    input dictionaries are copied before normalization, so callers can safely
    retain their original parsed CSV rows for other compatibility outputs.
    """
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be at least 1")

    normalized = [_normalize_row(row) for row in rows]
    normalized.sort(key=lambda row: (row["_timestamp"], row["message_id"]))
    windows = _windows(normalized, interval_seconds, bounds)

    return AnalysisTables(
        label_rows=[_public_label_row(row) for row in normalized],
        sentiment_rows=[_sentiment_row(start, end, members) for start, end, members in windows],
        topic_summary_rows=_topic_summary_rows(normalized),
        topic_trend_rows=_topic_trend_rows(windows),
        quote_rows=[_quote_row(row) for row in normalized],
    )


def _normalize_row(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    result["message_id"] = str(result.get("message_id", ""))
    result["_timestamp"] = float(result.get("timestamp_seconds", 0))
    legacy_topic = str(result.get("topic") or "").strip()
    result["raw_topic"] = str(result.get("raw_topic") or legacy_topic or "其他").strip() or "其他"
    report_topic = str(result.get("report_topic") or "其他").strip() or "其他"
    if report_topic not in _REPORT_TOPICS:
        raise ValueError("report_topic must use the fixed taxonomy")
    result["report_topic"] = report_topic
    result["sentiment"] = str(result.get("sentiment") or "neutral")
    result["_interest_signal"] = _as_bool(result.get("interest_signal"))
    return result


def _as_bool(value: object) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _windows(
    rows: list[dict[str, Any]], interval_seconds: int, bounds: tuple[int, int] | None,
) -> list[tuple[int, int, list[dict[str, Any]]]]:
    if bounds is None:
        if not rows:
            return []
        start, end = 0, int(max(row["_timestamp"] for row in rows)) + 1
    else:
        start, end = bounds
    if end < start:
        raise ValueError("bounds end must not precede start")
    return [
        (
            window_start,
            min(window_start + interval_seconds, end),
            [row for row in rows if window_start <= row["_timestamp"] < min(window_start + interval_seconds, end)],
        )
        for window_start in range(start, end, interval_seconds)
    ]


def _sentiment_row(start: int, end: int, members: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(members)
    counts = {sentiment: sum(row["sentiment"] == sentiment for row in members) for sentiment in _SENTIMENTS}
    return {
        "start_seconds": start,
        "end_seconds": end,
        "message_count": count,
        "unique_authors": len({str(row.get("author", "")) for row in members if row.get("author", "")}),
        **counts,
        "interest_signals": sum(row["_interest_signal"] for row in members),
        **{f"{sentiment}_share": counts[sentiment] / count if count else 0.0 for sentiment in _SENTIMENTS},
    }


def _topic_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = len(rows)
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_topic.setdefault(row["report_topic"], []).append(row)
    summaries: list[dict[str, Any]] = []
    for topic, members in by_topic.items():
        quotes = _representative_quotes(members)
        counts = {sentiment: sum(row["sentiment"] == sentiment for row in members) for sentiment in _SENTIMENTS}
        summaries.append({
            "report_topic": topic,
            "message_count": len(members),
            "share": len(members) / total if total else 0.0,
            "first_seconds": members[0]["_timestamp"],
            "last_seconds": members[-1]["_timestamp"],
            **counts,
            "representative_quote_1": quotes[0] if len(quotes) > 0 else "",
            "representative_quote_2": quotes[1] if len(quotes) > 1 else "",
            "representative_quote_3": quotes[2] if len(quotes) > 2 else "",
        })
    return sorted(summaries, key=lambda row: (-row["message_count"], row["report_topic"]))


def _representative_quotes(members: list[dict[str, Any]]) -> list[str]:
    quotes: list[str] = []
    seen: set[str] = set()
    for row in members:
        quote = str(row.get("original_text", ""))
        if quote.strip() and quote not in seen:
            quotes.append(quote)
            seen.add(quote)
        if len(quotes) == 3:
            break
    return quotes


def _topic_trend_rows(windows: list[tuple[int, int, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    trends: list[dict[str, Any]] = []
    for start, end, members in windows:
        total = len(members)
        by_topic: dict[str, list[dict[str, Any]]] = {}
        for row in members:
            by_topic.setdefault(row["report_topic"], []).append(row)
        for topic in sorted(by_topic):
            topic_members = by_topic[topic]
            trends.append({
                "start_seconds": start,
                "end_seconds": end,
                "report_topic": topic,
                "message_count": len(topic_members),
                "topic_share": len(topic_members) / total if total else 0.0,
                **{sentiment: sum(row["sentiment"] == sentiment for row in topic_members) for sentiment in _SENTIMENTS},
            })
    return trends


def _public_label_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _quote_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp_seconds": row["_timestamp"],
        "author": str(row.get("author", "")),
        "original_text": str(row.get("original_text", "")),
        "raw_topic": row["raw_topic"],
        "report_topic": row["report_topic"],
        "sentiment": row["sentiment"],
        "message_id": row["message_id"],
    }
