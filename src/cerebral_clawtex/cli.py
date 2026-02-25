# src/cerebral_clawtex/cli.py
"""Cerebral Clawtex CLI — full implementation of all commands."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from cerebral_clawtex.config import ClawtexConfig, load_config
from cerebral_clawtex.db import ClawtexDB
from cerebral_clawtex.hooks import session_start_hook
from cerebral_clawtex.phase1 import run_phase1
from cerebral_clawtex.phase2 import run_phase2
from cerebral_clawtex.storage import MemoryStore

app = typer.Typer(
    name="clawtex",
    help="Cerebral Clawtex — Claude Code memory plugin",
    invoke_without_command=True,
)

hook_app = typer.Typer(help="Hook entry points for Claude Code integration.")
app.add_typer(hook_app, name="hook")

console = Console()


@app.callback()
def main():
    """Cerebral Clawtex — Claude Code memory plugin."""


# --- Helper functions ---


def _get_db(config: ClawtexConfig) -> ClawtexDB:
    """Create a DB connection from config, ensuring the directory exists."""
    db_path = config.general.data_dir / "clawtex.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return ClawtexDB(db_path)


def _get_store(config: ClawtexConfig) -> MemoryStore:
    """Create a MemoryStore from config."""
    return MemoryStore(config.general.data_dir)


def _resolve_project_from_env() -> str:
    """Resolve project path from CLAUDE_PROJECT_DIR environment variable."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    if not project_dir:
        return ""
    return project_dir.replace("/", "-")


def _open_config_in_editor() -> None:
    """Open the config file in the user's preferred editor."""
    config_path = Path.home() / ".config" / "cerebral-clawtex" / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if not config_path.exists():
        config_path.write_text(
            "# Cerebral Clawtex configuration\n"
            "# See documentation for available options.\n\n"
            "[general]\n"
            "# data_dir = \"~/.local/share/cerebral-clawtex\"\n"
            "# claude_home = \"~/.claude\"\n\n"
            "[phase1]\n"
            '# model = "anthropic/claude-haiku-4-5-20251001"\n\n'
            "[phase2]\n"
            '# model = "anthropic/claude-sonnet-4-6-20250514"\n',
        )

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))
    subprocess.run([editor, str(config_path)], check=False)


# --- Commands ---


@app.command()
def status(
    project: str | None = typer.Option(None, "--project", help="Filter by project path"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show extraction status summary (counts by status per project)."""
    config = load_config()
    db = _get_db(config)

    try:
        # Query session counts by project and status
        if project:
            rows = db.execute(
                "SELECT project_path, status, COUNT(*) as count "
                "FROM sessions WHERE project_path = ? "
                "GROUP BY project_path, status ORDER BY project_path",
                (project,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT project_path, status, COUNT(*) as count "
                "FROM sessions GROUP BY project_path, status ORDER BY project_path",
            ).fetchall()

        if not rows:
            if json_output:
                typer.echo(json.dumps({"projects": {}, "total": 0}))
            else:
                console.print("[dim]No sessions found.[/dim]")
            return

        # Organize by project
        projects: dict[str, dict[str, int]] = {}
        for row in rows:
            proj = row["project_path"]
            if proj not in projects:
                projects[proj] = {}
            projects[proj][row["status"]] = row["count"]

        if json_output:
            total = sum(count for proj in projects.values() for count in proj.values())
            typer.echo(json.dumps({"projects": projects, "total": total}))
            return

        # Rich table output
        table = Table(title="Extraction Status")
        table.add_column("Project", style="cyan")
        table.add_column("Pending", justify="right")
        table.add_column("Extracted", justify="right", style="green")
        table.add_column("Skipped", justify="right", style="yellow")
        table.add_column("Failed", justify="right", style="red")
        table.add_column("Total", justify="right", style="bold")

        for proj, counts in projects.items():
            pending = counts.get("pending", 0)
            extracted = counts.get("extracted", 0)
            skipped = counts.get("skipped", 0)
            failed = counts.get("failed", 0)
            total = pending + extracted + skipped + failed
            table.add_row(
                proj,
                str(pending),
                str(extracted),
                str(skipped),
                str(failed),
                str(total),
            )

        console.print(table)

    finally:
        db.close()


@app.command()
def extract(
    project: str | None = typer.Option(None, "--project", help="Extract only this project"),
    retry_failed: bool = typer.Option(False, "--retry-failed", help="Retry previously failed sessions"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Run Phase 1 extraction on pending sessions."""
    config = load_config()

    result = asyncio.run(
        run_phase1(config, project_path=project, retry_failed=retry_failed)
    )

    if json_output:
        typer.echo(json.dumps(result))
        return

    console.print(f"[green]Extracted:[/green] {result['extracted']}")
    console.print(f"[yellow]Skipped:[/yellow] {result['skipped']}")
    console.print(f"[red]Failed:[/red] {result['failed']}")


@app.command()
def consolidate(
    project: str | None = typer.Option(None, "--project", help="Consolidate only this project"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Run Phase 2 consolidation."""
    config = load_config()

    result = asyncio.run(run_phase2(config, project_path=project))

    if json_output:
        typer.echo(json.dumps(result))
        return

    console.print(f"[green]Projects consolidated:[/green] {result['projects_consolidated']}")
    console.print(f"[green]Global consolidation:[/green] {'Yes' if result['global'] else 'No'}")


@app.command()
def sessions(
    failed: bool = typer.Option(False, "--failed", help="Show only failed sessions"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List recent sessions with extraction status."""
    config = load_config()
    db = _get_db(config)

    try:
        if failed:
            rows = db.execute(
                "SELECT session_id, project_path, status, error_message, "
                "file_modified_at, updated_at FROM sessions "
                "WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 50",
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT session_id, project_path, status, error_message, "
                "file_modified_at, updated_at FROM sessions "
                "ORDER BY updated_at DESC LIMIT 50",
            ).fetchall()

        if json_output:
            data = [
                {
                    "session_id": row["session_id"],
                    "project_path": row["project_path"],
                    "status": row["status"],
                    "error_message": row["error_message"],
                }
                for row in rows
            ]
            typer.echo(json.dumps(data))
            return

        if not rows:
            console.print("[dim]No sessions found.[/dim]")
            return

        table = Table(title="Sessions")
        table.add_column("Session ID", style="cyan", max_width=20)
        table.add_column("Project", style="blue")
        table.add_column("Status", justify="center")
        table.add_column("Error", style="red", max_width=40)

        for row in rows:
            status_style = {
                "pending": "[yellow]pending[/yellow]",
                "extracted": "[green]extracted[/green]",
                "skipped": "[dim]skipped[/dim]",
                "failed": "[red]failed[/red]",
            }.get(row["status"], row["status"])

            table.add_row(
                row["session_id"][:16] + "..." if len(row["session_id"]) > 16 else row["session_id"],
                row["project_path"],
                status_style,
                row["error_message"] or "",
            )

        console.print(table)

    finally:
        db.close()


@app.command()
def memories(
    full: bool = typer.Option(False, "--full", help="Show MEMORY.md and rollout summaries too"),
    global_: bool = typer.Option(False, "--global", help="Show global memory files"),
) -> None:
    """Print memory files for current/specified project."""
    config = load_config()
    store = _get_store(config)

    if global_:
        # Show global memory files
        summary = store.read_memory_summary(None)
        if summary:
            console.print("[bold cyan]Global Memory Summary[/bold cyan]")
            console.print(summary)
        else:
            console.print("[dim]No global memory files found.[/dim]")
            return

        if full:
            memory_md = store.read_memory_md(None)
            if memory_md:
                console.print("\n[bold cyan]Global MEMORY.md[/bold cyan]")
                console.print(memory_md)
        return

    # Project memory
    project_path = _resolve_project_from_env()
    if not project_path:
        # Try to list all projects with memory files
        projects = store.list_projects()
        if not projects:
            console.print("[dim]No memory files found. Run 'clawtex extract' and 'clawtex consolidate' first.[/dim]")
            return

        for proj in projects:
            summary = store.read_memory_summary(proj)
            if summary:
                console.print(f"\n[bold cyan]Project: {proj}[/bold cyan]")
                console.print(summary)
        return

    summary = store.read_memory_summary(project_path)
    if not summary:
        console.print("[dim]No memory files found for this project.[/dim]")
        return

    console.print(f"[bold cyan]Memory Summary ({project_path})[/bold cyan]")
    console.print(summary)

    if full:
        memory_md = store.read_memory_md(project_path)
        if memory_md:
            console.print(f"\n[bold cyan]MEMORY.md ({project_path})[/bold cyan]")
            console.print(memory_md)

        rollouts = store.list_rollout_summaries(project_path)
        if rollouts:
            console.print(f"\n[bold cyan]Rollout Summaries ({len(rollouts)} files)[/bold cyan]")
            for rollout_path in rollouts:
                console.print(f"\n[dim]--- {rollout_path.name} ---[/dim]")
                console.print(rollout_path.read_text(encoding="utf-8"))

        skills = store.list_skills(project_path)
        if skills:
            console.print(f"\n[bold cyan]Skills ({len(skills)} files)[/bold cyan]")
            for skill_path in skills:
                console.print(f"\n[dim]--- {skill_path.parent.name} ---[/dim]")
                console.print(skill_path.read_text(encoding="utf-8"))


@app.command("config")
def config_cmd(
    edit: bool = typer.Option(False, "--edit", help="Open config file in editor"),
) -> None:
    """Print resolved config or open in editor."""
    if edit:
        _open_config_in_editor()
        return

    config = load_config()

    console.print("[bold]Resolved Configuration[/bold]\n")
    console.print(f"[cyan]general.claude_home[/cyan] = {config.general.claude_home}")
    console.print(f"[cyan]general.data_dir[/cyan] = {config.general.data_dir}")
    console.print(f"[cyan]phase1.model[/cyan] = {config.phase1.model}")
    console.print(f"[cyan]phase1.max_sessions_per_run[/cyan] = {config.phase1.max_sessions_per_run}")
    console.print(f"[cyan]phase1.max_session_age_days[/cyan] = {config.phase1.max_session_age_days}")
    console.print(f"[cyan]phase1.min_session_idle_hours[/cyan] = {config.phase1.min_session_idle_hours}")
    console.print(f"[cyan]phase1.max_input_tokens[/cyan] = {config.phase1.max_input_tokens}")
    console.print(f"[cyan]phase1.concurrent_extractions[/cyan] = {config.phase1.concurrent_extractions}")
    console.print(f"[cyan]phase2.model[/cyan] = {config.phase2.model}")
    console.print(
        f"[cyan]phase2.max_memories_for_consolidation[/cyan] = {config.phase2.max_memories_for_consolidation}"
    )
    console.print(f"[cyan]phase2.run_after_phase1[/cyan] = {config.phase2.run_after_phase1}")
    console.print(f"[cyan]redaction.placeholder[/cyan] = {config.redaction.placeholder}")
    console.print(f"[cyan]redaction.extra_patterns[/cyan] = {config.redaction.extra_patterns}")
    console.print(f"[cyan]projects.include[/cyan] = {config.projects.include}")
    console.print(f"[cyan]projects.exclude[/cyan] = {config.projects.exclude}")


CLAWTEX_HOOK_ENTRY = {
    "matcher": "startup",
    "hooks": [
        {
            "type": "command",
            "command": "clawtex hook session-start",
            "timeout": 10,
        }
    ],
}


def _is_clawtex_hook(entry: dict) -> bool:
    """Check if a hook entry is the clawtex hook."""
    hooks = entry.get("hooks", [])
    return any(
        isinstance(h, dict) and "clawtex" in h.get("command", "")
        for h in hooks
    )


def _read_settings(settings_path: Path) -> dict:
    """Read Claude Code settings.json, returning empty dict if missing."""
    if settings_path.exists():
        return json.loads(settings_path.read_text(encoding="utf-8"))
    return {}


def _write_settings(settings_path: Path, settings: dict) -> None:
    """Write Claude Code settings.json, creating parent dirs if needed."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


@app.command()
def install() -> None:
    """Register SessionStart hook in Claude Code settings."""
    config = load_config()

    # Create config dir if missing
    config_dir = Path.home() / ".config" / "cerebral-clawtex"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Create data dir if missing
    config.general.data_dir.mkdir(parents=True, exist_ok=True)

    # Initialize DB schema
    db = _get_db(config)
    db.close()

    # Read settings.json (or create if missing)
    settings_path = config.general.claude_home / "settings.json"
    settings = _read_settings(settings_path)

    # Ensure hooks structure exists
    if "hooks" not in settings:
        settings["hooks"] = {}
    if "SessionStart" not in settings["hooks"]:
        settings["hooks"]["SessionStart"] = []

    # Check if clawtex hook already registered
    session_start_hooks = settings["hooks"]["SessionStart"]
    already_installed = any(_is_clawtex_hook(entry) for entry in session_start_hooks)

    if not already_installed:
        session_start_hooks.append(CLAWTEX_HOOK_ENTRY)

    # Write back settings.json
    _write_settings(settings_path, settings)

    console.print("[green]Installed:[/green] directories created, DB initialized, hook registered.")
    if already_installed:
        console.print("[dim]Hook was already registered.[/dim]")


@app.command()
def uninstall(
    purge: bool = typer.Option(False, "--purge", help="Also remove all data"),
) -> None:
    """Remove clawtex hook from Claude Code settings. --purge also removes all data."""
    config = load_config()

    # Read settings.json
    settings_path = config.general.claude_home / "settings.json"
    settings = _read_settings(settings_path)

    # Remove only the clawtex hook entry, preserve others
    if "hooks" in settings and "SessionStart" in settings["hooks"]:
        original_hooks = settings["hooks"]["SessionStart"]
        settings["hooks"]["SessionStart"] = [
            entry for entry in original_hooks if not _is_clawtex_hook(entry)
        ]
        # Write back settings.json
        _write_settings(settings_path, settings)

    console.print("[green]Uninstalled:[/green] clawtex hook removed from settings.json.")

    if purge:
        data_dir = config.general.data_dir
        if data_dir.exists():
            shutil.rmtree(data_dir)
            console.print(f"[red]Purged data directory:[/red] {data_dir}")


@app.command()
def reset(
    project: str | None = typer.Option(None, "--project", help="Reset only this project"),
    all_: bool = typer.Option(False, "--all", help="Reset all projects"),
) -> None:
    """Clear data and re-extract from scratch."""
    config = load_config()

    if not project and not all_:
        console.print("[yellow]Specify --project <name> or --all to reset.[/yellow]")
        return

    # Confirmation prompt
    scope = f"project '{project}'" if project else "ALL projects"
    confirm = typer.prompt(f"This will delete extraction data for {scope}. Continue? (y/n)")
    if confirm.lower() not in ("y", "yes"):
        console.print("[dim]Aborted.[/dim]")
        return

    db = _get_db(config)
    store = _get_store(config)

    try:
        if project:
            # Reset specific project
            db.execute("DELETE FROM phase1_outputs WHERE project_path = ?", (project,))
            db.execute(
                "UPDATE sessions SET status = 'pending', locked_by = NULL, locked_at = NULL "
                "WHERE project_path = ?",
                (project,),
            )
            db.conn.commit()

            # Remove project memory files
            proj_dir = store.project_dir(project)
            if proj_dir.exists():
                shutil.rmtree(proj_dir)

            console.print(f"[green]Reset project:[/green] {project}")

        elif all_:
            # Reset everything
            db.execute("DELETE FROM phase1_outputs")
            db.execute("DELETE FROM consolidation_runs")
            db.execute("DELETE FROM consolidation_lock")
            db.execute(
                "UPDATE sessions SET status = 'pending', locked_by = NULL, locked_at = NULL",
            )
            db.conn.commit()

            # Remove all memory files
            projects_dir = store.data_dir / "projects"
            if projects_dir.exists():
                shutil.rmtree(projects_dir)
            global_dir = store.global_dir
            if global_dir.exists():
                shutil.rmtree(global_dir)

            console.print("[green]Reset all extraction data.[/green]")

    finally:
        db.close()


# --- Hook subcommand group ---


@hook_app.command("session-start")
def hook_session_start() -> None:
    """Entry point for the SessionStart hook. Called by Claude Code."""
    session_start_hook()


if __name__ == "__main__":
    app()
