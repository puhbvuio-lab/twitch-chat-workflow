"""Thin command-line orchestration for independently retryable workflow stages."""

from __future__ import annotations

from pathlib import Path

from .acquisition import TwitchChatDownloaderAdapter, acquire_chat
from .aggregation import aggregate_stage
from .config import JobConfig
from .io import JobPaths
from .labeling import label_chat
from .normalization import normalize_chat


def run_stage(name: str, config_path: Path) -> Path | None:
    config = JobConfig.from_file(config_path)
    paths = JobPaths.create(config)
    if name == "acquire":
        return acquire_chat(config, paths, TwitchChatDownloaderAdapter())
    if name == "clean":
        return normalize_chat(paths.raw_chat / "raw_chat.jsonl", paths, config)
    if name == "label":
        # Real provider construction is intentionally application-specific; disabled labeling remains offline.
        return label_chat(config, paths, None)
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
