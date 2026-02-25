# src/cerebral_clawtex/sessions.py
from __future__ import annotations

import json
import time
from pathlib import Path


def discover_sessions(
    claude_home: Path,
    max_age_days: int = 30,
    min_idle_hours: int = 1,
    include_projects: list[str] | None = None,
    exclude_projects: list[str] | None = None,
) -> list[dict]:
    """Scan Claude Code projects for session JSONL files."""
    projects_dir = claude_home / "projects"
    if not projects_dir.exists():
        return []

    now = time.time()
    max_age_seconds = max_age_days * 86400
    min_idle_seconds = min_idle_hours * 3600
    results = []

    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        project_path = project_dir.name

        # Apply project filters (fuzzy match)
        if include_projects:
            if not any(inc in project_path for inc in include_projects):
                continue
        if exclude_projects:
            if any(exc in project_path for exc in exclude_projects):
                continue

        for jsonl_file in sorted(project_dir.glob("*.jsonl")):
            try:
                stat = jsonl_file.stat()
            except OSError:
                continue
            age = now - stat.st_mtime

            if age > max_age_seconds:
                continue
            if age < min_idle_seconds:
                continue

            results.append(
                {
                    "session_id": f"{project_path}:{jsonl_file.stem}",
                    "project_path": project_path,
                    "session_file": str(jsonl_file),
                    "file_modified_at": int(stat.st_mtime),
                    "file_size_bytes": stat.st_size,
                }
            )

    return results


def _extract_content_from_message(message: object) -> str:
    """Extract readable text from a message's content field."""
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")
        if block_type == "text":
            parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            name = block.get("name", "unknown")
            inp = block.get("input", {})
            parts.append(f"[Tool: {name}] {json.dumps(inp, indent=None)}")
        elif block_type == "tool_result":
            result_content = block.get("content", "")
            if isinstance(result_content, list):
                result_content = " ".join(
                    b.get("text", "")
                    for b in result_content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            parts.append(f"[Tool Result] {result_content}")
        elif block_type == "thinking":
            parts.append(f"[Thinking] {block.get('thinking', '')}")
    return "\n".join(parts)


_MAX_SESSION_FILE_BYTES = 50 * 1024 * 1024  # 50 MB safety limit


def parse_session(session_file: Path) -> list[dict]:
    """Parse a session JSONL file into a list of conversation messages."""
    messages = []

    try:
        if session_file.stat().st_size > _MAX_SESSION_FILE_BYTES:
            return []
        text = session_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue

        record_type = record.get("type", "")

        if record_type == "user" and "message" in record:
            msg = record["message"]
            content = _extract_content_from_message(msg)
            if content.strip():
                messages.append(
                    {
                        "role": "user",
                        "content": content,
                        "timestamp": record.get("timestamp", ""),
                    }
                )

        elif record_type == "assistant" and "message" in record:
            msg = record["message"]
            content = _extract_content_from_message(msg)
            if content.strip():
                messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "timestamp": record.get("timestamp", ""),
                    }
                )

        # Skip: progress, system, file-history-snapshot, pr-link, queue-operation

    return messages


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


def truncate_content(messages: list[dict], max_tokens: int = 80_000) -> list[dict]:
    """Truncate messages to fit within token budget.

    Preserves the beginning (context setup) and end (results/outcomes),
    trims the middle.
    """
    total = sum(_estimate_tokens(m["content"]) for m in messages)
    if total <= max_tokens:
        return messages

    # Reserve 40% for start (context setup), 40% for end (results/outcomes), ~20% for marker overhead
    start_budget = int(max_tokens * 0.4)
    end_budget = int(max_tokens * 0.4)

    start_messages = []
    start_used = 0
    for m in messages:
        tokens = _estimate_tokens(m["content"])
        if start_used + tokens > start_budget:
            break
        start_messages.append(m)
        start_used += tokens

    end_messages = []
    end_used = 0
    for m in reversed(messages):
        tokens = _estimate_tokens(m["content"])
        if end_used + tokens > end_budget:
            break
        end_messages.insert(0, m)
        end_used += tokens

    # Deduplicate if start and end overlap
    start_ids = {id(m) for m in start_messages}
    end_messages = [m for m in end_messages if id(m) not in start_ids]

    return (
        start_messages
        + [
            {
                "role": "system",
                "content": f"[... {len(messages) - len(start_messages) - len(end_messages)} messages truncated ...]",
            }
        ]
        + end_messages
    )
