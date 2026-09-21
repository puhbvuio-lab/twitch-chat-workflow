"""Optional semantic provider selection, deliberately isolated from workflow code."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

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
