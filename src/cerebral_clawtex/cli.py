import typer

app = typer.Typer(name="clawtex", help="Cerebral Clawtex — Claude Code memory plugin", invoke_without_command=True)


@app.callback()
def main():
    """Cerebral Clawtex — Claude Code memory plugin."""


@app.command()
def status():
    """Show extraction status summary."""
    typer.echo("Cerebral Clawtex v0.1.0 — no data yet")


if __name__ == "__main__":
    app()
