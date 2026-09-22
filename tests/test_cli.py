from __future__ import annotations

import json
from pathlib import Path

from twitch_chat_workflow import cli
from twitch_chat_workflow.config import JobConfig
from twitch_chat_workflow.io import JobPaths
from twitch_chat_workflow.models import ChatMessage, MessageLabel


class CapturingCodexProvider:
    instances: list["CapturingCodexProvider"] = []
    name = "codex_session"

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.instances.append(self)

    def label(self, messages: list[ChatMessage]) -> list[MessageLabel]:
        return [MessageLabel(message_id=message.message_id, topic="其他") for message in messages]


def test_label_stage_constructs_the_default_codex_session_provider(
    tmp_path: Path, monkeypatch
) -> None:
    """Passing None to label_chat instead of constructing the configured provider must fail."""
    CapturingCodexProvider.instances.clear()
    config = JobConfig(
        vod_url="https://www.twitch.tv/videos/123",
        output_dir=tmp_path,
        labeling={
            "enabled": True,
            "codex_command": "custom-codex",
            "model": "gpt-test",
            "context_messages": 2,
            "timeout_seconds": 42,
        },
    )
    paths = JobPaths.create(config)
    (paths.clean_chat / "clean_chat.csv").write_text(
        "message_id,timestamp_seconds,timestamp_ms,timestamp_iso,author,text,original_text,encoding_warning\n"
        "m1,1,,,,u,text,text,false\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "job.json"
    config_path.write_text(json.dumps(config.model_dump(mode="json")), encoding="utf-8")
    monkeypatch.setattr(cli, "CodexSessionProvider", CapturingCodexProvider)

    output = cli.run_stage("label", config_path)

    assert output is not None
    assert len(CapturingCodexProvider.instances) == 1
    assert CapturingCodexProvider.instances[0].kwargs == {
        "command": "custom-codex",
        "model": "gpt-test",
        "context_messages": 2,
        "timeout_seconds": 42,
    }
