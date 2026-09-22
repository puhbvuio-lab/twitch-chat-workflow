"""Optional semantic provider selection, deliberately isolated from workflow code."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
import re
import subprocess
import tempfile
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
        required = {"message_id", "sentiment", "topic", "interest_signal"}
        for label in value["labels"]:
            if not isinstance(label, dict) or set(label) != required:
                raise ValueError("each label must contain exactly the required fields")
            if (
                not isinstance(label["message_id"], str)
                or not isinstance(label["sentiment"], str)
                or not isinstance(label["topic"], str)
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
                        "topic": {"type": "string"},
                        "interest_signal": {"type": "boolean"},
                    },
                    "required": ["message_id", "sentiment", "topic", "interest_signal"],
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
                output = self._runner(command, self._prompt(messages), self._timeout_seconds)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(f"Codex CLI timed out after {self._timeout_seconds} seconds") from error
            except subprocess.CalledProcessError as error:
                raise RuntimeError(f"Codex CLI exited with code {error.returncode}") from error
            except RuntimeError as error:
                raise RuntimeError(_safe_diagnostic(error)) from error
            return self._parse_labels(output, [message.message_id for message in messages])
        finally:
            schema_path.unlink(missing_ok=True)

    @staticmethod
    def _write_schema() -> Path:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False) as schema_file:
            json.dump(_label_schema(), schema_file, ensure_ascii=False)
            return Path(schema_file.name)

    def _prompt(self, messages: list[ChatMessage]) -> str:
        payload = []
        for index, message in enumerate(messages):
            context_start = max(0, index - self._context_messages)
            context_end = min(len(messages), index + self._context_messages + 1)
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
            "情绪只能为 positive、neutral、negative；topic 使用简洁、稳定的中文主题短语，无明确主题时使用其他；"
            "interest_signal 必须为布尔值。输出必须保持输入 message_id 的顺序，且每个 ID 恰好一次。"
            f"相邻上下文窗口：{self._context_messages}。\n"
            f"弹幕：{json.dumps(payload, ensure_ascii=False)}"
        )

    @staticmethod
    def _parse_labels(output: str, expected_ids: list[str]) -> list[MessageLabel]:
        try:
            response = _CodexResponse.model_validate_json(output, strict=True)
        except (ValidationError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Codex response did not match label schema ({type(error).__name__})"
            ) from error
        labels = response.labels
        received_ids = [label.message_id for label in labels]
        if len(received_ids) != len(set(received_ids)):
            raise RuntimeError("Codex response contained duplicate message IDs")
        if received_ids != expected_ids:
            raise RuntimeError("Codex response message IDs did not exactly match the input order")
        return labels


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
