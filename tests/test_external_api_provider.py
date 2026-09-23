from __future__ import annotations

import json

import pytest

from twitch_chat_workflow.models import ChatMessage, MessageLabel
from twitch_chat_workflow.providers import ExternalApiProvider, KeepAliveTransport

API_KEY = "secret-key-123"

LABELS = [
    {
        "message_id": "m1", "sentiment": "positive", "raw_topic": "BOSS战很精彩",
        "impact_direction": "游戏影响", "primary_module": "战斗体验", "secondary_module": "BOSS战",
        "content_type": "游戏内容", "message_type": "评价反馈", "is_bot": False,
        "needs_review": False, "confidence": "高", "interest_signal": True,
    },
    {
        "message_id": "m2", "sentiment": "neutral", "raw_topic": "机器人提示",
        "impact_direction": "非游戏影响", "primary_module": "系统与机器人", "secondary_module": "系统与机器人",
        "content_type": "技术与平台", "message_type": "机器人通知", "is_bot": True,
        "needs_review": False, "confidence": "高", "interest_signal": False,
    },
]


def _envelope(labels: list[dict[str, object]], *, fenced: bool = False) -> tuple[int, str]:
    text = json.dumps({"labels": labels}, ensure_ascii=False)
    if fenced:
        text = f"```json\n{text}\n```"
    return 200, json.dumps(
        {"content": [{"type": "text", "text": text}]}, ensure_ascii=False
    )


class FakeTransport:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, str], str, int]] = []

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: str, timeout_seconds: int
    ) -> tuple[int, str]:
        self.calls.append((method, url, dict(headers), body, timeout_seconds))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response  # type: ignore[return-value]


def _messages() -> list[ChatMessage]:
    return [
        ChatMessage(message_id="m1", timestamp_seconds=1, text="这BOSS战太帅了", original_text="这BOSS战太帅了"),
        ChatMessage(message_id="m2", timestamp_seconds=2, text="欢迎回来", original_text="欢迎回来"),
    ]


def _provider(transport: FakeTransport, **kwargs: object) -> ExternalApiProvider:
    return ExternalApiProvider(
        base_url="https://api.example.com/anthropic",
        api_key=API_KEY,
        model="glm-test",
        transport=transport,
        backoff_seconds=0,
        **kwargs,
    )


def test_external_api_provider_submits_anthropic_style_request_and_parses_labels() -> None:
    transport = FakeTransport(_envelope(LABELS))
    provider = _provider(transport)

    labels = provider.label(_messages())

    assert labels == [
        MessageLabel.model_validate(LABELS[0]),
        MessageLabel.model_validate(LABELS[1]),
    ]
    method, url, headers, body, timeout_seconds = transport.calls[0]
    assert (method, url) == ("POST", "https://api.example.com/anthropic/v1/messages")
    assert headers["x-api-key"] == API_KEY
    assert headers["anthropic-version"] == "2023-06-01"
    payload = json.loads(body)
    assert payload["model"] == "glm-test"
    assert payload["max_tokens"] == 8192
    assert payload["messages"][0]["role"] == "user"
    assert '"message_id": "m1"' in payload["messages"][0]["content"]
    assert "topic_code" in payload["messages"][0]["content"]
    assert timeout_seconds == 300


def test_external_api_provider_strips_markdown_fences_from_output() -> None:
    provider = _provider(FakeTransport(_envelope(LABELS, fenced=True)))

    labels = provider.label(_messages())

    assert [label.message_id for label in labels] == ["m1", "m2"]


def test_external_api_provider_retries_transient_statuses_then_succeeds() -> None:
    transport = FakeTransport((503, "overloaded"), (429, "rate limited"), _envelope(LABELS))
    provider = _provider(transport)

    labels = provider.label(_messages())

    assert len(labels) == 2
    assert len(transport.calls) == 3


def test_external_api_provider_does_not_retry_permanent_client_errors() -> None:
    transport = FakeTransport((401, "bad key"))
    provider = _provider(transport)

    with pytest.raises(RuntimeError, match="status 401"):
        provider.label(_messages())

    assert len(transport.calls) == 1


def test_external_api_provider_retries_transport_failures_until_exhausted() -> None:
    transport = FakeTransport(RuntimeError("connection reset"), RuntimeError("timed out"))
    provider = _provider(transport, max_retries=1)

    with pytest.raises(RuntimeError, match="timed out"):
        provider.label(_messages())

    assert len(transport.calls) == 2


def test_external_api_provider_never_leaks_the_api_key_in_failures() -> None:
    transport = FakeTransport((500, f"upstream rejected key {API_KEY}"))
    provider = _provider(transport, max_retries=0)

    with pytest.raises(RuntimeError) as raised:
        provider.label(_messages())

    assert API_KEY not in str(raised.value)
    assert "[redacted]" in str(raised.value)


def test_external_api_provider_rejects_misaligned_model_output() -> None:
    swapped = [LABELS[1], LABELS[0]]
    provider = _provider(FakeTransport(_envelope(swapped)))

    with pytest.raises(RuntimeError, match="did not exactly match the input order"):
        provider.label(_messages())


def test_external_api_provider_skips_the_transport_for_empty_batches() -> None:
    transport = FakeTransport()
    provider = _provider(transport)

    assert provider.label([]) == []

    assert transport.calls == []


def test_external_api_provider_omits_thinking_by_default_and_disables_it_on_request() -> None:
    default_transport = FakeTransport(_envelope(LABELS))
    disabled_transport = FakeTransport(_envelope(LABELS))

    _provider(default_transport).label(_messages())
    _provider(disabled_transport, disable_thinking=True).label(_messages())

    assert "thinking" not in json.loads(default_transport.calls[0][3])
    assert json.loads(disabled_transport.calls[0][3])["thinking"] == {"type": "disabled"}


class FakeResponse:
    def __init__(self, status: int, text: str) -> None:
        self.status = status
        self._text = text

    def read(self) -> bytes:
        return self._text.encode("utf-8")


class FakeConnection:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, str]] = []
        self.closed = False

    def request(self, method: str, target: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        self.requests.append((method, target))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        self._pending = response  # type: ignore[attr-defined]

    def getresponse(self) -> FakeResponse:
        status, text = self._pending  # type: ignore[attr-defined]
        return FakeResponse(status, text)

    def close(self) -> None:
        self.closed = True


def test_keep_alive_transport_reuses_one_connection_across_requests() -> None:
    connection = FakeConnection((200, '{"content": []}'), (200, '{"content": []}'))
    transport = KeepAliveTransport(connector=lambda *_args: connection)

    first = transport("POST", "https://api.example.com/v1/messages", {}, "{}", 5)
    second = transport("POST", "https://api.example.com/v1/messages", {}, "{}", 5)

    assert first == second == (200, '{"content": []}')
    assert len(connection.requests) == 2
    assert not connection.closed


def test_keep_alive_transport_reconnects_once_on_a_stale_connection() -> None:
    stale = FakeConnection(OSError("SSL: UNEXPECTED_EOF_WHILE_READING"))
    fresh = FakeConnection((200, "ok"))
    connections = iter([stale, fresh])
    transport = KeepAliveTransport(connector=lambda *_args: next(connections))

    status, text = transport("POST", "https://api.example.com/v1/messages", {}, "{}", 5)

    assert (status, text) == (200, "ok")
    assert stale.closed
    assert transport._local.connection is fresh


def test_keep_alive_transport_raises_retryable_error_after_two_failures() -> None:
    connections = iter([FakeConnection(OSError("reset")), FakeConnection(OSError("reset"))])
    transport = KeepAliveTransport(connector=lambda *_args: next(connections))

    with pytest.raises(RuntimeError, match="external API request failed") as raised:
        transport("POST", "https://api.example.com/v1/messages", {}, "{}", 5)

    assert "reset" in str(raised.value)
