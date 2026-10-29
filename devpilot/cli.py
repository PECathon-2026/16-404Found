"""DevPilot command-line interface entry point."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="devpilot",
    help="DevPilot — Autonomous Multi-Agent AI Engineering Guild",
    no_args_is_help=True,
)


@app.command()
def demo() -> None:
    """Run reference demo mission."""
    typer.echo("Running DevPilot demo (FX2 Bug Investigation)...")


@app.command()
def doctor() -> None:
    """Check installed tools, dependencies, and environment health."""
    typer.echo("Checking DevPilot environment health...")


if __name__ == "__main__":
    app()
