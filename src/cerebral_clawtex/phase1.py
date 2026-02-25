# src/cerebral_clawtex/phase1.py
"""Phase 1: Per-session extraction pipeline.

Extracts reusable learnings from individual Claude Code sessions using an LLM
(Haiku by default). Each session is parsed, redacted, sent to the LLM for
analysis, and the structured output is stored in both the filesystem and DB.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path

from litellm import acompletion

from cerebral_clawtex.config import ClawtexConfig, Phase1Config, derive_project_name
from cerebral_clawtex.db import ClawtexDB
from cerebral_clawtex.prompts import load_prompt
from cerebral_clawtex.redact import Redactor
from cerebral_clawtex.sessions import discover_sessions, parse_session, truncate_content
from cerebral_clawtex.storage import MemoryStore

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"task_outcome", "rollout_slug", "rollout_summary", "raw_memory"}

RETRY_NUDGE = "Your response was not valid JSON. Please respond with only valid JSON matching the schema."


def _build_prompts(
    messages: list[dict],
    project_path: str,
    session_id: str,
) -> tuple[str, str]:
    """Build system and user prompts from templates and session data."""
    system_prompt = load_prompt("phase1_system.md")
    user_template = load_prompt("phase1_user.md")

    # Format the session content as a readable transcript
    content_parts = []
    for msg in messages:
        role = msg["role"].upper()
        ts = msg.get("timestamp", "")
        prefix = f"[{ts}] {role}" if ts else role
        content_parts.append(f"{prefix}:\n{msg['content']}")

    redacted_session_content = "\n\n".join(content_parts)

    project_name = derive_project_name(project_path)

    # Simple template substitution (Jinja2-style placeholders)
    user_prompt = user_template.replace("{{ project_name }}", project_name)
    user_prompt = user_prompt.replace("{{ project_path }}", project_path)
    user_prompt = user_prompt.replace("{{ session_id }}", session_id)
    user_prompt = user_prompt.replace("{{ session_date }}", "")
    user_prompt = user_prompt.replace("{{ redacted_session_content }}", redacted_session_content)

    return system_prompt, user_prompt


def _validate_response(data: dict) -> bool:
    """Validate that the LLM response has all required fields."""
    return REQUIRED_FIELDS.issubset(data.keys())


def _is_noop(data: dict) -> bool:
    """Check if the response is a no-op (empty fields)."""
    return not data.get("rollout_slug") and not data.get("rollout_summary") and not data.get("raw_memory")


async def extract_session(
    session_id: str,
    session_file: Path,
    project_path: str,
    db: ClawtexDB,
    store: MemoryStore,
    redactor: Redactor,
    config: Phase1Config,
    worker_id: str,
) -> str:
    """Extract learnings from a single session.

    Implements the full 11-step pipeline:
    1. Claim session
    2. Parse JSONL
    3. Redact
    4. Truncate
    5. Build prompts
    6. Call LLM
    7. Validate JSON (retry once on failure)
    8. Post-scan redaction
    9. Write rollout summary
    10. Store in DB
    11. Release session

    Returns: "extracted" | "skipped" | "failed"
    """
    # Step 1: Claim session
    claimed = db.claim_session(session_id, worker_id)
    if not claimed:
        logger.info("Session %s could not be claimed, skipping", session_id)
        return "skipped"

    try:
        # Step 2: Parse JSONL
        messages = parse_session(session_file)
        if not messages:
            logger.info("Session %s has no messages, skipping", session_id)
            db.release_session(session_id, status="skipped")
            return "skipped"

        # Step 3: Redact
        for msg in messages:
            msg["content"] = redactor.redact(msg["content"])

        # Step 4: Truncate
        messages = truncate_content(messages, max_tokens=config.max_input_tokens)

        # Step 5: Build prompts
        system_prompt, user_prompt = _build_prompts(messages, project_path, session_id)

        # Step 6: Call LLM
        llm_messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = await acompletion(
            model=config.model,
            messages=llm_messages,
            response_format={"type": "json_object"},
            timeout=120,
        )
        content = response.choices[0].message.content

        # Step 7: Validate JSON response
        data = None
        try:
            data = json.loads(content)
            if not _validate_response(data):
                data = None
        except (json.JSONDecodeError, TypeError):
            data = None

        # Retry once on invalid JSON
        if data is None:
            logger.warning("Invalid JSON from LLM for session %s, retrying", session_id)
            llm_messages.append({"role": "assistant", "content": content})
            llm_messages.append({"role": "user", "content": RETRY_NUDGE})

            response = await acompletion(
                model=config.model,
                messages=llm_messages,
                response_format={"type": "json_object"},
                timeout=120,
            )
            content = response.choices[0].message.content

            try:
                data = json.loads(content)
                if not _validate_response(data):
                    data = None
            except (json.JSONDecodeError, TypeError):
                data = None

            if data is None:
                logger.error("Invalid JSON after retry for session %s", session_id)
                db.release_session(
                    session_id,
                    status="failed",
                    error_message="Invalid JSON response after retry",
                )
                return "failed"

        # Check for no-op response
        if _is_noop(data):
            logger.info("Session %s produced no learnings, skipping", session_id)
            db.release_session(session_id, status="skipped")
            return "skipped"

        # Step 8: Post-scan redaction on all LLM output fields
        data["rollout_summary"] = redactor.redact(data["rollout_summary"])
        data["raw_memory"] = redactor.redact(data["raw_memory"])
        data["rollout_slug"] = redactor.redact(data["rollout_slug"])

        # Step 9: Write rollout summary
        store.write_rollout_summary(
            project_path=project_path,
            slug=data["rollout_slug"],
            content=data["rollout_summary"],
        )

        # Step 10: Store in DB
        usage = response.usage
        db.store_phase1_output(
            session_id=session_id,
            project_path=project_path,
            raw_memory=data["raw_memory"],
            rollout_summary=data["rollout_summary"],
            rollout_slug=data["rollout_slug"],
            task_outcome=data["task_outcome"],
            token_usage_input=getattr(usage, "prompt_tokens", 0),
            token_usage_output=getattr(usage, "completion_tokens", 0),
        )

        # Step 11: Release session
        db.release_session(session_id, status="extracted")

        logger.info("Session %s extracted successfully", session_id)
        return "extracted"

    except Exception as exc:
        logger.error("Failed to extract session %s: %s", session_id, exc)
        # Redact error message before storing — library exceptions may contain secrets
        safe_error = redactor.redact(str(exc))[:500]
        db.release_session(
            session_id,
            status="failed",
            error_message=safe_error,
        )
        return "failed"


async def run_phase1(
    config: ClawtexConfig,
    project_path: str | None = None,
    retry_failed: bool = False,
) -> dict:
    """Top-level Phase 1 orchestrator.

    Discovers sessions, registers them in the DB, and extracts them
    concurrently using an asyncio.Semaphore.

    Returns: {"extracted": N, "skipped": N, "failed": N}
    """
    worker_id = f"phase1-{uuid.uuid4().hex[:8]}"

    # Set up dependencies
    db_path = config.general.data_dir / "clawtex.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = ClawtexDB(db_path)
    store = MemoryStore(config.general.data_dir)
    redactor = Redactor(
        extra_patterns=config.redaction.extra_patterns or None,
        placeholder=config.redaction.placeholder,
    )

    try:
        # Discover sessions
        sessions = discover_sessions(
            claude_home=config.general.claude_home,
            max_age_days=config.phase1.max_session_age_days,
            min_idle_hours=config.phase1.min_session_idle_hours,
            include_projects=config.projects.include or None,
            exclude_projects=config.projects.exclude or None,
        )

        if not sessions:
            if not retry_failed:
                return {"extracted": 0, "skipped": 0, "failed": 0}

        # Limit sessions per run
        sessions = sessions[: config.phase1.max_sessions_per_run]

        # Register sessions in DB
        for sess in sessions:
            db.register_session(
                session_id=sess["session_id"],
                project_path=sess["project_path"],
                session_file=sess["session_file"],
                file_modified_at=sess["file_modified_at"],
                file_size_bytes=sess["file_size_bytes"],
            )

        # Re-queue failed sessions for retry
        if retry_failed:
            conditions = ["status = 'failed'"]
            params: list = []
            if project_path:
                conditions.append("project_path = ?")
                params.append(project_path)
            where = " AND ".join(conditions)
            params.append(config.phase1.max_sessions_per_run)
            failed_rows = db.execute(
                f"SELECT session_id, project_path, session_file, file_modified_at, file_size_bytes "
                f"FROM sessions WHERE {where} LIMIT ?",
                tuple(params),
            ).fetchall()
            for row in failed_rows:
                db.execute(
                    "UPDATE sessions SET status = 'pending', error_message = NULL, "
                    "locked_by = NULL, locked_at = NULL WHERE session_id = ?",
                    (row["session_id"],),
                )
                # Add to sessions list if not already discovered
                if not any(s["session_id"] == row["session_id"] for s in sessions):
                    sessions.append(
                        {
                            "session_id": row["session_id"],
                            "project_path": row["project_path"],
                            "session_file": row["session_file"],
                            "file_modified_at": row["file_modified_at"],
                            "file_size_bytes": row["file_size_bytes"],
                        }
                    )
            db.conn.commit()

        # Extract with concurrency control
        semaphore = asyncio.Semaphore(config.phase1.concurrent_extractions)
        results: list[str] = []

        async def _extract_with_semaphore(sess: dict) -> str:
            async with semaphore:
                return await extract_session(
                    session_id=sess["session_id"],
                    session_file=Path(sess["session_file"]),
                    project_path=sess["project_path"],
                    db=db,
                    store=store,
                    redactor=redactor,
                    config=config.phase1,
                    worker_id=worker_id,
                )

        tasks = [_extract_with_semaphore(sess) for sess in sessions]
        results = await asyncio.gather(*tasks)

        return {
            "extracted": results.count("extracted"),
            "skipped": results.count("skipped"),
            "failed": results.count("failed"),
        }
    finally:
        db.close()
