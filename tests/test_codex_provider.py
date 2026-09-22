from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from twitch_chat_workflow import providers
from twitch_chat_workflow.models import ChatMessage, MessageLabel
from twitch_chat_workflow.providers import CodexSessionProvider


def _label(message_id: str, **updates: object) -> dict[str, object]:
    return {
        "message_id": message_id, "sentiment": "neutral", "raw_topic": "其他",
        "impact_direction": "无法判断", "primary_module": "其他", "secondary_module": "其他",
        "content_type": "其他", "message_type": "其他",
        "is_bot": False, "needs_review": False, "confidence": "中",
        "interest_signal": False, **updates,
    }


class FakeRunner:
    def __init__(self, result: str) -> None:
        self.result = result
        self.command: list[str] | None = None
        self.stdin = ""
        self.timeout_seconds: int | None = None
        self.schema: dict[str, object] | None = None

    def __call__(self, command: list[str], stdin: str, timeout_seconds: int) -> str:
        self.command = command
        self.stdin = stdin
        self.timeout_seconds = timeout_seconds
        schema_path = Path(command[command.index("--output-schema") + 1])
        self.schema = json.loads(schema_path.read_text(encoding="utf-8"))
        return self.result


def test_codex_session_provider_submits_messages_with_a_structured_schema() -> None:
    """Removing the Codex command/schema contract must break this test."""
    runner = FakeRunner(
        json.dumps(
            {
                "labels": [
                    _label(
                        "m1",
                        sentiment="positive",
                        raw_topic="直播反馈",
                        impact_direction="游戏影响",
                        primary_module="战斗体验",
                        secondary_module="BOSS战",
                        content_type="游戏内容",
                        message_type="评价反馈",
                        interest_signal=True,
                    )
                ]
            }
        )
    )
    provider = CodexSessionProvider(runner=runner, command="codex", timeout_seconds=120)

    labels = provider.label(
        [ChatMessage(message_id="m1", timestamp_seconds=1, text="好耶", original_text="好耶")]
    )

    assert labels == [
        MessageLabel(
            message_id="m1", sentiment="positive", raw_topic="直播反馈",
            impact_direction="游戏影响", primary_module="战斗体验", secondary_module="BOSS战",
            content_type="游戏内容", message_type="评价反馈", interest_signal=True,
        )
    ]
    assert runner.command is not None
    assert runner.command[:3] == ["codex", "exec", "--ephemeral"]
    assert "--output-schema" in runner.command
    assert runner.timeout_seconds == 120
    assert '"message_id": "m1"' in runner.stdin
    assert runner.schema is not None
    assert runner.schema["type"] == "object"
    assert runner.schema["required"] == ["labels"]


def test_codex_session_provider_requires_the_complete_fixed_taxonomy() -> None:
    """The semantic contract must preserve raw detail but constrain report labels."""
    runner = FakeRunner(
        '{"labels": [{"message_id": "m1", "sentiment": "neutral", '
        '"raw_topic": "撞脚趾", "impact_direction": "无法判断", '
        '"primary_module": "其他", "secondary_module": "其他", '
        '"content_type": "日常话题", "message_type": "信息陈述", '
        '"is_bot": false, "needs_review": true, "confidence": "中", '
        '"interest_signal": false}]}'
    )
    provider = CodexSessionProvider(runner=runner)

    label = provider.label(
        [ChatMessage(message_id="m1", timestamp_seconds=1, text="脚趾好痛", original_text="脚趾好痛")]
    )[0]

    assert label.raw_topic == "撞脚趾"
    assert label.impact_direction == "无法判断"
    assert label.secondary_module == "其他"
    assert label.needs_review is True
    assert runner.schema is not None
    assert runner.schema["properties"]["labels"]["items"]["properties"]["impact_direction"]["enum"] == [
        "游戏影响", "非游戏影响", "无法判断"
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [("secondary_module", "脚趾处理"), ("confidence", "很高")],
)
def test_codex_session_provider_rejects_values_outside_fixed_taxonomy(
    field: str, value: str
) -> None:
    """Free-form report topics or confidence values must not reach exports."""
    payload = {
        "message_id": "m1", "sentiment": "neutral", "raw_topic": "细节",
        "impact_direction": "游戏影响", "primary_module": "战斗体验", "secondary_module": "BOSS战",
        "content_type": "日常话题", "message_type": "信息陈述",
        "is_bot": False, "needs_review": False, "confidence": "中", "interest_signal": False,
    }
    payload[field] = value
    provider = CodexSessionProvider(runner=FakeRunner(json.dumps({"labels": [payload]})))

    with pytest.raises(RuntimeError, match="did not match label schema"):
        provider.label([ChatMessage(message_id="m1", timestamp_seconds=1, text="一", original_text="一")])


@pytest.mark.parametrize(
    ("labels", "message"),
    [([_label("m1"), _label("m1")], "duplicate message IDs"), ([ _label("m2"), _label("m1")], "input order")],
)
def test_codex_session_provider_rejects_misaligned_complete_labels(
    labels: list[dict[str, object]], message: str
) -> None:
    provider = CodexSessionProvider(runner=FakeRunner(json.dumps({"labels": labels})))
    messages = [
        ChatMessage(message_id="m1", timestamp_seconds=1, text="一", original_text="一"),
        ChatMessage(message_id="m2", timestamp_seconds=2, text="二", original_text="二"),
    ]
    with pytest.raises(RuntimeError, match=message):
        provider.label(messages)


def test_codex_session_provider_supplies_only_configured_neighboring_context() -> None:
    """Ignoring context_messages would allow unrelated batch messages to influence a label."""
    runner = FakeRunner(json.dumps({"labels": [_label("m1"), _label("m2"), _label("m3")]}))
    provider = CodexSessionProvider(runner=runner, context_messages=1)

    provider.label(
        [
            ChatMessage(message_id="m1", timestamp_seconds=1, text="一", original_text="一"),
            ChatMessage(message_id="m2", timestamp_seconds=2, text="二", original_text="二"),
            ChatMessage(message_id="m3", timestamp_seconds=3, text="三", original_text="三"),
        ]
    )

    payload = json.loads(runner.stdin.split("弹幕：", maxsplit=1)[1])
    assert payload[1]["context"] == [
        {"message_id": "m1", "text": "一"},
        {"message_id": "m3", "text": "三"},
    ]


@pytest.mark.parametrize(
    ("result", "message"),
    [
        ("not-json", "did not match label schema"),
        ('{"labels": [{"sentiment": "positive", "topic": "x", "interest_signal": true}]}', "did not match label schema"),
        ('{"labels": [{"message_id": "m1", "sentiment": "positive", "topic": "x", "interest_signal": true}, {"message_id": "m1", "sentiment": "neutral", "topic": "y", "interest_signal": false}]}', "did not match label schema"),
        ('{"labels": [{"message_id": "m2", "sentiment": "positive", "topic": "x", "interest_signal": true}, {"message_id": "m1", "sentiment": "neutral", "topic": "y", "interest_signal": false}]}', "did not match label schema"),
        ('{"labels": [{"message_id": "m1", "sentiment": "mixed", "topic": "x", "interest_signal": true}]}', "did not match label schema"),
        ('{"labels": [{"message_id": "m1", "sentiment": "positive", "topic": "x", "interest_signal": "true"}]}', "did not match label schema"),
        ('{"labels": [{"message_id": "m1", "sentiment": "positive", "topic": "x", "interest_signal": true, "access_token": "super-secret-token"}]}', "did not match label schema"),
    ],
)
def test_codex_session_provider_rejects_malformed_or_misaligned_labels(
    result: str, message: str
) -> None:
    """Removing response validation must make malformed batches reach the CSV stage."""
    provider = CodexSessionProvider(runner=FakeRunner(result))
    messages = [
        ChatMessage(message_id="m1", timestamp_seconds=1, text="一", original_text="一"),
        ChatMessage(message_id="m2", timestamp_seconds=2, text="二", original_text="二"),
    ]

    with pytest.raises(RuntimeError, match=message) as raised:
        provider.label(messages)

    assert "super-secret-token" not in str(raised.value)


class RaisingRunner:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    def __call__(self, _command: list[str], _stdin: str, _timeout_seconds: int) -> str:
        raise self.error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            subprocess.CalledProcessError(
                17, ["codex"], output="", stderr="access_token=super-secret-token"
            ),
            "exited with code 17",
        ),
        (subprocess.TimeoutExpired(["codex"], timeout=120), "timed out after 120 seconds"),
        (RuntimeError("access_token=super-secret-token"), "[redacted]"),
    ],
)
def test_codex_session_provider_reports_bounded_redacted_failures(
    error: BaseException, expected: str
) -> None:
    """Leaking a CLI diagnostic containing credentials must break this test."""
    provider = CodexSessionProvider(runner=RaisingRunner(error), timeout_seconds=120)
    message = ChatMessage(message_id="m1", timestamp_seconds=1, text="hi", original_text="hi")

    with pytest.raises(RuntimeError, match=expected) as raised:
        provider.label([message])

    assert "super-secret-token" not in str(raised.value)
    assert len(str(raised.value)) <= 800


def test_subprocess_runner_redacts_json_formatted_credentials(monkeypatch) -> None:
    """Returning raw JSON stderr with a token-like field must never expose its value."""
    class FailedProcess:
        returncode = 17
        stderr = '{"access_token": "super-secret-token"}'
        stdout = ""

    monkeypatch.setattr(providers.subprocess, "run", lambda *_args, **_kwargs: FailedProcess())

    with pytest.raises(RuntimeError, match="exited with code 17") as raised:
        providers.run_codex(["codex"], "input", 12)

    assert "super-secret-token" not in str(raised.value)
