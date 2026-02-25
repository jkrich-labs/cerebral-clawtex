# src/cerebral_clawtex/hooks.py
"""SessionStart hook integration for Cerebral Clawtex.

This module provides the entry point for Claude Code's SessionStart hook.
When Claude Code starts a new session, it calls this hook which:
1. Injects relevant memory context into the session
2. Spawns background extraction of previous sessions
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

from cerebral_clawtex.config import ClawtexConfig, derive_project_name, load_config
from cerebral_clawtex.storage import MemoryStore

logger = logging.getLogger(__name__)


def _resolve_project_path(project_dir: str, config: ClawtexConfig) -> str:
    """Convert a project directory path to the encoded project path used in storage.

    Claude Code encodes project paths by replacing '/' with '-' for use as
    directory names in ~/.claude/projects/.

    Args:
        project_dir: The raw project directory path (e.g. "/home/user/myproject")
        config: Application configuration

    Returns:
        Encoded project path (e.g. "-home-user-myproject"), or empty string if not set.
    """
    if not project_dir:
        return ""

    # Normalize path separators to / before encoding (handles Windows backslashes)
    normalized = project_dir.replace(os.sep, "/")
    # Claude Code encodes project paths by replacing / with -
    # e.g. /home/user/myproject -> -home-user-myproject
    return normalized.replace("/", "-")


def _build_navigation_instructions(project_path: str, config: ClawtexConfig) -> str:
    """Build navigation instructions for accessing detailed memory files.

    Tells the AI how to find and read MEMORY.md, rollout summaries, and skills
    when it needs deeper context than the summary provides.

    Args:
        project_path: Encoded project path
        config: Application configuration

    Returns:
        Markdown-formatted navigation instructions.
    """
    data_dir = config.general.data_dir
    parts = ["### How to Access Detailed Memory\n"]

    if project_path:
        project_dir = data_dir / "projects" / project_path
        parts.append(
            f"- **Detailed learnings**: Read `{project_dir}/MEMORY.md` for "
            f"topic-organized learnings with keyword-searchable sections."
        )
        parts.append(
            f"- **Session rollout summaries**: Browse `{project_dir}/rollout_summaries/` "
            f"for per-session summaries of past work. Use `grep -r` to search across them."
        )
        parts.append(
            f"- **Skills/procedures**: Check `{project_dir}/skills/` for "
            f"reusable step-by-step procedures extracted from repeated patterns."
        )

    global_dir = data_dir / "global"
    parts.append(
        f"- **Cross-project patterns**: Read `{global_dir}/MEMORY.md` for learnings that apply across all projects."
    )

    return "\n".join(parts)


def session_start_hook() -> None:
    """Entry point for the SessionStart hook. Prints JSON to stdout.

    This function is called by Claude Code when a new session starts.
    It:
    1. Loads config via load_config()
    2. Creates MemoryStore from config
    3. Resolves project path from CLAUDE_PROJECT_DIR env var
    4. Reads project memory_summary.md and global memory_summary.md
    5. Combines with navigation instructions
    6. Truncates combined content to ~5,000 tokens (~20,000 chars)
    7. Prints JSON to stdout: {"additional_context": "## Cerebral Clawtex Memory\n\n..."}
    8. Spawns background extraction via _spawn_background_extraction()
    """
    config = load_config()
    store = MemoryStore(config.general.data_dir)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    project_path = _resolve_project_path(project_dir, config)

    context_parts: list[str] = []

    # Project memory
    if project_path:
        project_summary = store.read_memory_summary(project_path)
        if project_summary:
            project_name = derive_project_name(project_path)
            context_parts.append(f"### Project Memory ({project_name})\n\n{project_summary}")

    # Global memory
    global_summary = store.read_memory_summary(None)
    if global_summary:
        context_parts.append(f"### Global Memory\n\n{global_summary}")

    if not context_parts:
        # No memories yet -- just trigger background extraction
        _spawn_background_extraction(config)
        return

    # Build navigation instructions
    nav = _build_navigation_instructions(project_path, config)
    context_parts.append(nav)

    combined = "## Cerebral Clawtex Memory\n\n" + "\n\n".join(context_parts)

    # Truncate to ~5000 tokens (~20000 chars)
    if len(combined) > 20000:
        combined = combined[:20000] + "\n\n[... truncated ...]"

    output = {"additional_context": combined}
    print(json.dumps(output))

    # Spawn background extraction
    _spawn_background_extraction(config)


def _spawn_background_extraction(config: ClawtexConfig) -> None:
    """Spawn a detached child process that runs Phase 1 (and optionally Phase 2) extraction.

    Uses subprocess.Popen with appropriate flags for cross-platform detachment.

    Args:
        config: Application configuration
    """
    cmd = [sys.executable, "-m", "cerebral_clawtex.cli", "extract"]
    if config.phase2.run_after_phase1:
        # Run extract then consolidate via a shell command chain
        cmd = [
            sys.executable, "-c",
            "import asyncio; "
            "from cerebral_clawtex.config import load_config; "
            "from cerebral_clawtex.phase1 import run_phase1; "
            "from cerebral_clawtex.phase2 import run_phase2; "
            "config = load_config(); "
            "asyncio.run(run_phase1(config)); "
            "asyncio.run(run_phase2(config))",
        ]

    try:
        kwargs: dict = {}
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        else:
            # On Windows, use CREATE_NEW_PROCESS_GROUP to detach
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except OSError:
        logger.warning("Failed to spawn background extraction process")
