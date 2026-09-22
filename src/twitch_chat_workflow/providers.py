"""Optional semantic provider selection, deliberately isolated from workflow code."""

from __future__ import annotations

from collections.abc import Callable
import http.client
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import typing
import urllib.parse
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .models import ChatMessage, MessageLabel


class SemanticLabelProvider(Protocol):
    name: str

    def label(self, messages: list[ChatMessage]) -> list[MessageLabel]: ...


class CallableProvider:
    def __init__(self, name: str, callback: Callable[[list[ChatMessage]], list[MessageLabel]]) -> None:
        self.name = name
        self._callback = callback

    def label(self, messages: list[ChatMessage]) -> list[MessageLabel]:
        return self._callback(messages)


CodexRunner = Callable[[list[str], str, int], str]


class _CodexResponse(BaseModel):
    """The narrow, schema-constrained response expected from `codex exec`."""

    model_config = ConfigDict(extra="forbid")

    labels: list[MessageLabel]

    @model_validator(mode="before")
    @classmethod
    def require_complete_label_fields(cls, value: object) -> object:
        if not isinstance(value, dict) or not isinstance(value.get("labels"), list):
            return value
        required = {
            "message_id", "sentiment", "raw_topic", "impact_direction", "primary_module", "secondary_module", "content_type",
            "message_type", "is_bot", "needs_review", "confidence", "interest_signal",
        }
        for label in value["labels"]:
            if isinstance(label, dict) and label.get("report_topic") == "其他" and "impact_direction" not in label:
                label["impact_direction"] = "无法判断"
                label["primary_module"] = "其他"
                label["secondary_module"] = "其他"
                label.pop("report_topic", None)
            if not isinstance(label, dict) or set(label) != required:
                raise ValueError("each label must contain exactly the required fields")
            if (
                not isinstance(label["message_id"], str)
                or not isinstance(label["sentiment"], str)
                or not isinstance(label["raw_topic"], str)
                or not isinstance(label["impact_direction"], str)
                or not isinstance(label["primary_module"], str)
                or not isinstance(label["secondary_module"], str)
                or not isinstance(label["content_type"], str)
                or not isinstance(label["message_type"], str)
                or type(label["is_bot"]) is not bool
                or type(label["needs_review"]) is not bool
                or not isinstance(label["confidence"], str)
                or type(label["interest_signal"]) is not bool
            ):
                raise ValueError("each label field must use its JSON Schema type")
        return value


def _label_schema() -> dict[str, object]:
    """Return the output contract handed to Codex without any credentials."""
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "labels": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "message_id": {"type": "string"},
                        "sentiment": {"type": "string", "enum": ["positive", "neutral", "negative"]},
                        "raw_topic": {"type": "string"},
                        "impact_direction": {"type": "string", "enum": ["游戏影响", "非游戏影响", "无法判断"]},
                        "primary_module": {"type": "string"},
                        "secondary_module": {"type": "string"},
                        "content_type": {"type": "string", "enum": ["游戏内容", "直播互动", "主播内容", "技术与平台", "日常话题", "社区文化", "其他"]},
                        "message_type": {"type": "string", "enum": ["评价反馈", "提问求助", "信息陈述", "玩笑梗图", "表情或刷屏", "机器人通知", "其他"]},
                        "is_bot": {"type": "boolean"},
                        "needs_review": {"type": "boolean"},
                        "confidence": {"type": "string", "enum": ["高", "中", "低"]},
                        "interest_signal": {"type": "boolean"},
                    },
                    "required": ["message_id", "sentiment", "raw_topic", "impact_direction", "primary_module", "secondary_module", "content_type", "message_type", "is_bot", "needs_review", "confidence", "interest_signal"],
                },
            }
        },
        "required": ["labels"],
    }


_SECRET_PATTERN = re.compile(
    r"(?i)(?:bearer\s+\S+|\"?(?:api[_-]?key|access[_-]?token|authorization|token)\"?\s*[:=]\s*[\"']?[^,\s;}\]\"']+[\"']?|(?:api[_-]?key|access[_-]?token|authorization|token)[\w-]*[-_][\w.-]+|sk-[\w-]+)"
)


def _safe_diagnostic(value: object, limit: int = 800) -> str:
    """Bound diagnostics without preserving credential-like values or prompt text."""
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = _SECRET_PATTERN.sub("[redacted]", text)
    return text[:limit]


def run_codex(command: list[str], stdin: str, timeout_seconds: int) -> str:
    """Run Codex non-interactively, translating process failures to safe errors."""
    try:
        result = subprocess.run(
            command,
            input=stdin,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"Codex CLI timed out after {timeout_seconds} seconds") from error
    except OSError as error:
        raise RuntimeError(f"Could not start Codex CLI: {_safe_diagnostic(error)}") from error
    if result.returncode:
        diagnostic = _safe_diagnostic(result.stderr or result.stdout)
        suffix = f": {diagnostic}" if diagnostic else ""
        raise RuntimeError(f"Codex CLI exited with code {result.returncode}{suffix}")
    return result.stdout


def build_label_prompt(messages: list[ChatMessage], context_messages: int) -> str:
    """Shared labeling instruction and payload used by every semantic provider."""
    payload = []
    for index, message in enumerate(messages):
        context_start = max(0, index - context_messages)
        context_end = min(len(messages), index + context_messages + 1)
        payload.append(
            {
                "message_id": message.message_id,
                "timestamp_seconds": message.timestamp_seconds,
                "author": message.author,
                "text": message.text,
                "original_text": message.original_text,
                "context": [
                    {"message_id": neighbor.message_id, "text": neighbor.text}
                    for neighbor_index, neighbor in enumerate(
                        messages[context_start:context_end], start=context_start
                    )
                    if neighbor_index != index
                ],
            }
        )
    return (
        "请仅根据以下 Twitch 弹幕原话及其相邻上下文逐条标注。不得臆造主播身份、事件或未出现的事实。"
            "情绪只能为 positive、neutral、negative；raw_topic 使用简洁中文描述原话细节；"
            "impact_direction 只能为游戏影响、非游戏影响、无法判断；游戏影响必须从剧情与世界观、战斗体验、探索与互动、其他整体兴趣中选择一级模块，并从固定二级模板选择；"
            "非游戏影响必须从主播表现、观众互动、技术与直播质量、系统与机器人、生活闲聊、其他非游戏内容中选择，一级和二级模块同名；无法判断必须使用其他/其他；"
            "content_type、message_type、confidence 必须服从 JSON Schema 枚举。机器人或自动通知必须 is_bot=true 且 message_type=机器人通知；"
            "语义不完整、讽刺歧义或多主题无法判断时 needs_review=true，并优先 report_topic=其他。"
            "interest_signal、is_bot、needs_review 必须为布尔值。输出必须保持输入 message_id 的顺序，且每个 ID 恰好一次。"
        f"相邻上下文窗口：{context_messages}。\n"
        f"弹幕：{json.dumps(payload, ensure_ascii=False)}"
    )


def _module_contract() -> str:
    """Enumerate the fixed module taxonomy so API-only providers can enforce it."""
    from .models import GAME_TAXONOMY, NON_GAME_MODULES

    game_rules = "；".join(
        f"{primary} 的二级模块只能选 {'、'.join(sorted(secondaries))}"
        for primary, secondaries in GAME_TAXONOMY.items()
    )
    non_game = "、".join(sorted(NON_GAME_MODULES))
    return (
        f"\n固定模块映射（必须逐字使用，不得自创模块名）：{game_rules}。"
        f"非游戏影响的一级和二级模块同名，只能选 {non_game}。"
        "无法判断必须使用 其他/其他。"
    )


_JSON_OUTPUT_CONTRACT = (
    "\n输出要求：只输出一个 JSON 对象，禁止解释性文字或 Markdown 代码块。"
    '结构为 {"labels": [{"message_id": string, "sentiment": "positive"|"neutral"|"negative", '
    '"raw_topic": string, "impact_direction": "游戏影响"|"非游戏影响"|"无法判断", '
    '"primary_module": string, "secondary_module": string, '
    '"content_type": "游戏内容"|"直播互动"|"主播内容"|"技术与平台"|"日常话题"|"社区文化"|"其他", '
    '"message_type": "评价反馈"|"提问求助"|"信息陈述"|"玩笑梗图"|"表情或刷屏"|"机器人通知"|"其他", '
    '"is_bot": boolean, "needs_review": boolean, "confidence": "高"|"中"|"低", '
    '"interest_signal": boolean}]}，labels 的数量与顺序必须与输入 message_id 完全一致。'
) + _module_contract()


def parse_label_response(output: str, expected_ids: list[str]) -> list[MessageLabel]:
    """Parse and strictly validate a provider response against the label schema."""
    try:
        response = _CodexResponse.model_validate_json(output, strict=True)
    except (ValidationError, ValueError, json.JSONDecodeError) as error:
        wrapped = RuntimeError(f"Model response did not match label schema ({type(error).__name__})")
        wrapped.raw_response = output  # type: ignore[attr-defined]
        wrapped.validation_errors = (  # type: ignore[attr-defined]
            error.errors(include_url=False, include_context=False)
            if isinstance(error, ValidationError)
            else [{"msg": str(error)}]
        )
        raise wrapped from error
    labels = response.labels
    received_ids = [label.message_id for label in labels]
    if len(received_ids) != len(set(received_ids)):
        raise RuntimeError("Model response contained duplicate message IDs")
    if received_ids != expected_ids:
        raise RuntimeError("Model response message IDs did not exactly match the input order")
    return labels


def _extract_response_text(raw: str) -> str:
    """Join Anthropic-style content blocks and strip optional Markdown fences."""
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("external API returned a non-JSON envelope") from error
    blocks = response.get("content") if isinstance(response, dict) else None
    text = "".join(
        block.get("text", "")
        for block in blocks or []
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()
    if text.startswith("```"):
        text = re.sub(r"^```[^\n]*\n?", "", text)
        if text.endswith("```"):
            text = text[: -3].rstrip()
    return text


_PERMANENT_HTTP_STATUSES = frozenset({400, 401, 403, 404, 405, 422})


class KeepAliveTransport:
    """Per-thread keep-alive HTTP transport that reconnects once on a stale TLS session.

    Reusing connections avoids a TLS handshake per request and recovers from
    servers that silently drop idle connections; one reconnect is attempted
    before the failure surfaces as a retryable transport error.
    """

    def __init__(self, connector: Callable[[str, str, int], http.client.HTTPConnection] | None = None) -> None:
        self._connector = connector
        self._local = threading.local()

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: str, timeout_seconds: int
    ) -> tuple[int, str]:
        parsed = urllib.parse.urlsplit(url)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"
        payload = body.encode("utf-8")
        last_error: Exception | None = None
        for _ in range(2):
            connection = self._local.__dict__.get("connection")
            if connection is None:
                connection = self._connect(parsed.scheme, parsed.hostname, parsed.port, timeout_seconds)
                self._local.connection = connection
            try:
                connection.request(method, target, body=payload, headers=dict(headers))
                response = connection.getresponse()
                return response.status, response.read().decode("utf-8", errors="replace")
            except (OSError, http.client.HTTPException) as error:
                last_error = error
                self._discard(connection)
        raise RuntimeError(f"external API request failed: {last_error}")

    def _connect(self, scheme: str, hostname: str, port: int | None, timeout_seconds: int) -> http.client.HTTPConnection:
        if self._connector is not None:
            return self._connector(scheme, hostname, port)
        if scheme == "http":
            return http.client.HTTPConnection(hostname, port, timeout=timeout_seconds)
        return http.client.HTTPSConnection(hostname, port, timeout=timeout_seconds)

    def _discard(self, connection: http.client.HTTPConnection) -> None:
        try:
            connection.close()
        except OSError:
            pass
        self._local.connection = None


default_external_transport = KeepAliveTransport()


ExternalApiTransport = Callable[[str, str, dict[str, str], str, int], tuple[int, str]]


class ExternalApiProvider:
    """Label batches through an external Anthropic-compatible HTTP chat endpoint.

    The API key stays in memory only: it is never written into configs, config
    snapshots, batch artifacts, or error summaries.
    """

    name = "external_api"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str | None = None,
        context_messages: int = 0,
        timeout_seconds: int = 300,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
        max_output_tokens: int = 8192,
        disable_thinking: bool = False,
        transport: ExternalApiTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required for external_api labeling")
        if not api_key:
            raise ValueError("api_key is required for external_api labeling")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._context_messages = context_messages
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._max_output_tokens = max_output_tokens
        self._disable_thinking = disable_thinking
        self._transport = transport or default_external_transport

    @property
    def model(self) -> str | None:
        return self._model

    def label(self, messages: list[ChatMessage]) -> list[MessageLabel]:
        if not messages:
            return []
        expected_ids = [message.message_id for message in messages]
        prompt = build_label_prompt(messages, self._context_messages) + _JSON_OUTPUT_CONTRACT
        output = self._request(prompt)
        return parse_label_response(output, expected_ids)

    def _request(self, prompt: str) -> str:
        request_body: dict[str, typing.Any] = {
            "model": self._model,
            "max_tokens": self._max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self._disable_thinking:
            request_body["thinking"] = {"type": "disabled"}
        body = json.dumps(request_body, ensure_ascii=False)
        headers = {
            "content-type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        url = f"{self._base_url}/v1/messages"
        last_error = "external API labeling failed"
        for attempt in range(self._max_retries + 1):
            try:
                status, text = self._transport("POST", url, headers, body, self._timeout_seconds)
            except RuntimeError as error:
                status, text = None, ""
                last_error = self._diagnostic(error)
            else:
                if status == 200:
                    return _extract_response_text(text)
                last_error = f"external API returned status {status}: {self._diagnostic(text)}"
                if status in _PERMANENT_HTTP_STATUSES:
                    break
            if attempt < self._max_retries:
                time.sleep(min(self._backoff_seconds * (2**attempt), 30.0))
        raise RuntimeError(last_error)

    def _diagnostic(self, value: object) -> str:
        text = str(value).replace(self._api_key, "[redacted]")
        return _safe_diagnostic(text)


class CodexSessionProvider:
    """Label batches with the locally authenticated, non-interactive Codex CLI."""

    name = "codex_session"

    def __init__(
        self,
        *,
        runner: CodexRunner = run_codex,
        command: str = "codex",
        model: str | None = None,
        context_messages: int = 0,
        timeout_seconds: int = 300,
    ) -> None:
        self._runner = runner
        self._command = command
        self._model = model
        self._context_messages = context_messages
        self._timeout_seconds = timeout_seconds

    def label(self, messages: list[ChatMessage]) -> list[MessageLabel]:
        if not messages:
            return []
        schema_path = self._write_schema()
        try:
            command = [self._command, "exec", "--ephemeral", "--output-schema", str(schema_path)]
            if self._model:
                command.extend(["--model", self._model])
            command.append("-")
            try:
                output = self._runner(command, build_label_prompt(messages, self._context_messages), self._timeout_seconds)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(f"Codex CLI timed out after {self._timeout_seconds} seconds") from error
            except subprocess.CalledProcessError as error:
                raise RuntimeError(f"Codex CLI exited with code {error.returncode}") from error
            except RuntimeError as error:
                raise RuntimeError(_safe_diagnostic(error)) from error
            return parse_label_response(output, [message.message_id for message in messages])
        finally:
            schema_path.unlink(missing_ok=True)

    @staticmethod
    def _write_schema() -> Path:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as schema_file:
            json.dump(_label_schema(), schema_file, ensure_ascii=False)
            return Path(schema_file.name)

    _prompt = staticmethod(build_label_prompt)
    _parse_labels = staticmethod(parse_label_response)


def select_provider(
    primary: str, fallback: str | None, factories: dict[str, Callable[[], SemanticLabelProvider]]
) -> SemanticLabelProvider:
    """Build primary first and use the configured fallback only when it is unavailable."""
    try:
        return factories[primary]()
    except (KeyError, ImportError, RuntimeError):
        if fallback is None:
            raise
        return factories[fallback]()
