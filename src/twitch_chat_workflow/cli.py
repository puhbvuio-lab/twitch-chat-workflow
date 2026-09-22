"""Thin command-line orchestration for independently retryable workflow stages."""

from __future__ import annotations

import os
from pathlib import Path

from .acquisition import TwitchChatDownloaderAdapter, acquire_chat
from .aggregation import aggregate_stage
from .config import JobConfig
from .io import JobPaths
from .labeling import label_chat
from .normalization import normalize_chat
from .providers import CodexSessionProvider, ExternalApiProvider, SemanticLabelProvider


def build_label_provider(config: JobConfig) -> SemanticLabelProvider | None:
    """Construct the configured provider; secrets come from the environment only."""
    labeling = config.labeling
    if not labeling.enabled:
        return None
    if labeling.provider == "external_api":
        api_key = os.environ.get(labeling.api_key_env, "")
        if not api_key:
            raise ValueError(f"external_api 标注需要环境变量 {labeling.api_key_env} 提供 API 密钥")
        if not labeling.base_url:
            raise ValueError("external_api 标注需要在配置中提供 labeling.base_url")
        return ExternalApiProvider(
            base_url=labeling.base_url,
            api_key=api_key,
            model=labeling.model,
            context_messages=labeling.context_messages,
            timeout_seconds=labeling.timeout_seconds,
            max_retries=labeling.max_retries,
        )
    return CodexSessionProvider(
        command=labeling.codex_command,
        model=labeling.model,
        context_messages=labeling.context_messages,
        timeout_seconds=labeling.timeout_seconds,
    )


def run_stage(name: str, config_path: Path) -> Path | None:
    config = JobConfig.from_file(config_path)
    paths = JobPaths.create(config)
    if name == "acquire":
        return acquire_chat(config, paths, TwitchChatDownloaderAdapter())
    if name == "clean":
        return normalize_chat(paths.raw_chat / "raw_chat.jsonl", paths, config)
    if name == "label":
        return label_chat(config, paths, build_label_provider(config))
    if name == "aggregate":
        return aggregate_stage(config, paths)
    raise ValueError(f"unknown stage: {name}")


try:  # Typer is a declared dependency; the fallback keeps source-only checkout tests importable.
    import typer

    app = typer.Typer(help="Resumable Twitch VOD chat workflow")

    def _command(name: str):
        def command(config: Path = typer.Option(..., "--config", exists=True, readable=True)) -> None:
            result = run_stage(name, config)
            if result is not None:
                typer.echo(str(result))
        return command

    app.command("acquire")(_command("acquire"))
    app.command("clean")(_command("clean"))
    app.command("label")(_command("label"))
    app.command("aggregate")(_command("aggregate"))

    @app.command("run")
    def run(config: Path = typer.Option(..., "--config", exists=True, readable=True)) -> None:
        for stage in ("acquire", "clean", "label", "aggregate"):
            run_stage(stage, config)
except ModuleNotFoundError:  # pragma: no cover - exercised only before package installation
    app = None
