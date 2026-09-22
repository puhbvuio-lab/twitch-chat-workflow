"""Typed configuration sections for the standalone chat workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


GAME_TAXONOMY = {
    "剧情与世界观": {"电影化过场/演出高光", "剧情内容/叙事情绪", "整体剧情世界观感受"},
    "战斗体验": {"BOSS战", "常规战斗", "综合战斗感受"},
    "探索与互动": {"跑图与移动", "调查与解谜"},
    "其他整体兴趣": {"角色兴趣", "整体美术与音声兴趣", "游戏整体兴趣"},
    "其他": {"其他"},
}
NON_GAME_MODULES = {"主播表现", "观众互动", "技术与直播质量", "系统与机器人", "生活闲聊", "其他非游戏内容"}


class LabelingConfig(BaseModel):
    """Optional semantic-labeling settings."""

    enabled: bool = False
    provider: Literal["codex_session", "external_api"] = "codex_session"
    fallback_provider: Literal["external_api"] | None = None
    model: str | None = None
    base_url: str | None = None
    api_key_env: str = "GLM_API_KEY"
    batch_size: int = Field(default=50, ge=1)
    concurrency: int = Field(default=1, ge=1)
    context_messages: int = Field(default=0, ge=0)
    codex_command: str = "codex"
    timeout_seconds: int = Field(default=300, ge=1)
    max_retries: int = Field(default=3, ge=0)


class AggregationConfig(BaseModel):
    """Settings for fixed-width chat trend buckets."""

    interval_seconds: int = Field(default=60, ge=1)


class RawMessage(BaseModel):
    """One downloader record, retained without lossy transformation."""

    timestamp: float
    text: str
    author: str = ""
    message_id: str | None = None
    timestamp_iso: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """Canonical normalized chat row used by labeling and aggregation."""

    message_id: str
    timestamp_seconds: float
    timestamp_ms: int | None = None
    timestamp_iso: str | None = None
    author: str = ""
    text: str
    original_text: str
    encoding_warning: bool = False


class MessageLabel(BaseModel):
    """Auditable semantic label for one canonical message."""

    message_id: str
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"
    raw_topic: str = "其他"
    impact_direction: Literal["游戏影响", "非游戏影响", "无法判断"] = "无法判断"
    primary_module: str = "其他"
    secondary_module: str = "其他"
    content_type: Literal[
        "游戏内容", "直播互动", "主播内容", "技术与平台", "日常话题", "社区文化", "其他"
    ] = "其他"
    message_type: Literal[
        "评价反馈", "提问求助", "信息陈述", "玩笑梗图", "表情或刷屏", "机器人通知", "其他"
    ] = "其他"
    is_bot: bool = False
    needs_review: bool = False
    confidence: Literal["高", "中", "低"] = "中"
    interest_signal: bool = False
    provider: str = ""
    model: str | None = None
    batch_number: int = 0

    @property
    def report_topic(self) -> str:
        """Backward-compatible alias for the new secondary module."""
        return self.secondary_module

    @model_validator(mode="after")
    def validate_taxonomy(self) -> "MessageLabel":
        if self.impact_direction == "游戏影响":
            if self.secondary_module not in GAME_TAXONOMY.get(self.primary_module, set()):
                raise ValueError("game impact primary/secondary taxonomy mismatch")
        elif self.impact_direction == "非游戏影响":
            if self.primary_module not in NON_GAME_MODULES or self.secondary_module != self.primary_module:
                raise ValueError("non-game impact primary/secondary taxonomy mismatch")
        elif (self.primary_module, self.secondary_module) != ("其他", "其他"):
            raise ValueError("undetermined impact must use 其他/其他")
        return self
