"""Module entry point for ``python -m twitch_chat_workflow``."""

from .cli import app

if app is None:  # pragma: no cover
    raise SystemExit("Typer is required for the command line; install project dependencies")

app()
