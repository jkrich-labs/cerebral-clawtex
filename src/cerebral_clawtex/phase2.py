# src/cerebral_clawtex/phase2.py
"""Phase 2: Memory consolidation pipeline.

Consolidates per-session Phase 1 extraction outputs into organized memory files
(memory_summary.md, MEMORY.md, skills) using an LLM (Sonnet by default).
Supports both per-project consolidation and global cross-project consolidation.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from litellm import acompletion

from cerebral_clawtex.config import ClawtexConfig, derive_project_name
from cerebral_clawtex.db import ClawtexDB
from cerebral_clawtex.prompts import load_prompt
from cerebral_clawtex.redact import Redactor
from cerebral_clawtex.storage import MemoryStore

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = {"memory_summary", "memory_md", "skills"}


def _build_project_prompts(
    mode: str,
    project_path: str,
    phase1_outputs: list[str],
    existing_summary: str | None,
    existing_memory_md: str | None,
) -> tuple[str, str]:
    """Build system and user prompts for per-project consolidation."""
    system_prompt = load_prompt("phase2_system.md")
    user_template = load_prompt("phase2_user.md")

    project_name = derive_project_name(project_path)

    # Build the user prompt with template substitution
    user_prompt = user_template.replace("{{ mode }}", mode)
    user_prompt = user_prompt.replace("{{ project_name }}", project_name)

    # Handle conditional INCREMENTAL/INIT sections
    if mode == "INCREMENTAL" and existing_summary and existing_memory_md:
        # Keep the INCREMENTAL block, remove the INIT block
        # Replace Jinja-style conditionals with actual content
        incremental_block = (
            f"## Existing Memory Summary\n\n"
            f"The current `memory_summary.md` for this project:\n\n"
            f"```markdown\n{existing_summary}\n```\n\n"
            f"## Existing MEMORY.md\n\n"
            f"The current `MEMORY.md` for this project:\n\n"
            f"```markdown\n{existing_memory_md}\n```\n\n"
            f"Merge the new Phase 1 outputs below into these existing files. "
            f"Deduplicate, prune contradicted entries, and reorganize as needed. "
            f"Return the complete updated files.\n"
        )
        # Remove Jinja blocks and replace with rendered content
        user_prompt = _replace_jinja_conditionals(user_prompt, incremental_block)
    else:
        init_block = (
            "## No Existing Memory Files\n\n"
            "This is an INIT consolidation -- build the memory files from scratch "
            "using the Phase 1 outputs below.\n"
        )
        user_prompt = _replace_jinja_conditionals(user_prompt, init_block)

    # Build phase1 outputs section
    outputs_section = ""
    for i, output in enumerate(phase1_outputs, 1):
        outputs_section += f"### Session {i}\n\n```markdown\n{output}\n```\n\n"

    # Replace the Jinja for loop
    user_prompt = _replace_jinja_for_loop(user_prompt, outputs_section)

    return system_prompt, user_prompt


def _build_global_prompts(
    mode: str,
    project_summaries: list[dict],
    existing_summary: str | None,
    existing_memory_md: str | None,
) -> tuple[str, str]:
    """Build system and user prompts for global consolidation."""
    system_prompt = load_prompt("phase2_global_system.md")
    user_template = load_prompt("phase2_global_user.md")

    user_prompt = user_template.replace("{{ mode }}", mode)

    # Handle conditional INCREMENTAL/INIT sections
    if mode == "INCREMENTAL" and existing_summary and existing_memory_md:
        incremental_block = (
            f"## Existing Global Memory Summary\n\n"
            f"The current global `memory_summary.md`:\n\n"
            f"```markdown\n{existing_summary}\n```\n\n"
            f"## Existing Global MEMORY.md\n\n"
            f"The current global `MEMORY.md`:\n\n"
            f"```markdown\n{existing_memory_md}\n```\n\n"
            f"Merge the per-project summaries below into these existing global files. "
            f"Extract only cross-project transferable patterns. "
            f"Deduplicate, prune contradicted entries, and reorganize as needed. "
            f"Return the complete updated files.\n"
        )
        user_prompt = _replace_jinja_conditionals(user_prompt, incremental_block)
    else:
        init_block = (
            "## No Existing Global Memory Files\n\n"
            "This is an INIT consolidation -- build the global memory files from scratch "
            "using the per-project summaries below.\n"
        )
        user_prompt = _replace_jinja_conditionals(user_prompt, init_block)

    # Build project summaries section
    summaries_section = ""
    for proj in project_summaries:
        summaries_section += f"### Project: {proj['name']}\n\n```markdown\n{proj['summary']}\n```\n\n"

    user_prompt = _replace_jinja_for_loop(user_prompt, summaries_section)

    return system_prompt, user_prompt


def _replace_jinja_conditionals(template: str, replacement: str) -> str:
    """Replace Jinja2 {% if %} / {% else %} / {% endif %} blocks with rendered content."""
    pattern = r"\{%\s*if\s+.*?%\}.*?\{%\s*endif\s*%\}"
    result = re.sub(pattern, replacement, template, flags=re.DOTALL)
    return result


def _replace_jinja_for_loop(template: str, replacement: str) -> str:
    """Replace Jinja2 {% for %} / {% endfor %} blocks with rendered content."""
    pattern = r"\{%\s*for\s+.*?%\}.*?\{%\s*endfor\s*%\}"
    result = re.sub(pattern, replacement, template, flags=re.DOTALL)
    return result


def _validate_response(data: object) -> bool:
    """Validate that the LLM response has all required fields."""
    if not isinstance(data, dict):
        return False
    if not REQUIRED_FIELDS.issubset(data.keys()):
        return False
    if not isinstance(data.get("memory_summary"), str):
        return False
    if not isinstance(data.get("memory_md"), str):
        return False
    skills = data.get("skills")
    if not isinstance(skills, list):
        return False
    for skill in skills:
        if not isinstance(skill, dict):
            return False
        if "name" in skill and not isinstance(skill["name"], str):
            return False
        if "skill_md" in skill and not isinstance(skill["skill_md"], str):
            return False
    return True


def _redact_response(data: dict, redactor: Redactor) -> dict:
    """Apply post-scan redaction to all string fields in the LLM response.

    This is the Layer 3 safety net: even if the LLM produces content
    containing secrets, they are caught before writing to disk.
    """
    data["memory_summary"] = redactor.redact(data["memory_summary"])
    data["memory_md"] = redactor.redact(data["memory_md"])

    for skill in data.get("skills", []):
        if not isinstance(skill, dict):
            continue
        if "name" in skill:
            skill["name"] = redactor.redact(skill["name"])
        if "skill_md" in skill:
            skill["skill_md"] = redactor.redact(skill["skill_md"])

    return data


async def consolidate_project(
    project_path: str,
    db: ClawtexDB,
    store: MemoryStore,
    config: ClawtexConfig,
    worker_id: str,
    redactor: Redactor | None = None,
) -> bool:
    """Consolidate Phase 1 outputs for a single project.

    Steps:
    1. Acquire consolidation lock
    2. Detect mode (INIT vs INCREMENTAL)
    3. Load Phase 1 outputs from DB
    4. Load existing memory files (for INCREMENTAL)
    5. Build prompt from templates
    6. Call LLM
    7. Parse JSON response
    7a. Post-scan redaction
    8. Write memory files and skills
    9. Record consolidation run
    10. Release lock

    Returns True if consolidation ran, False if skipped.
    """
    scope = f"project:{project_path}"
    if redactor is None:
        redactor = Redactor(
            extra_patterns=config.redaction.extra_patterns or None,
            placeholder=config.redaction.placeholder,
        )

    # Step 1: Acquire consolidation lock
    if not db.acquire_consolidation_lock(scope, worker_id):
        logger.info("Could not acquire consolidation lock for %s", scope)
        return False

    try:
        # Step 2: Detect mode
        existing_summary = store.read_memory_summary(project_path)
        existing_memory_md = store.read_memory_md(project_path)

        if existing_summary is not None and existing_memory_md is not None:
            mode = "INCREMENTAL"
        else:
            mode = "INIT"

        # Step 3: Load Phase 1 outputs from DB
        last_watermark = db.get_last_watermark(scope)
        phase1_rows = db.get_phase1_outputs_for_consolidation(
            project_path=project_path,
            since_cursor=last_watermark,
            limit=config.phase2.max_memories_for_consolidation,
        )

        if not phase1_rows:
            logger.info("No Phase 1 outputs to consolidate for %s", project_path)
            db.release_consolidation_lock(scope)
            return False

        # Extract raw_memory text from rows
        phase1_outputs = [row["raw_memory"] for row in phase1_rows]

        # Determine new cursor watermark based on stable row ordering.
        new_watermark = max(row["output_rowid"] for row in phase1_rows)

        # Step 4: Load existing memory files (already done in step 2)

        # Step 5: Build prompt from templates
        system_prompt, user_prompt = _build_project_prompts(
            mode=mode,
            project_path=project_path,
            phase1_outputs=phase1_outputs,
            existing_summary=existing_summary if mode == "INCREMENTAL" else None,
            existing_memory_md=existing_memory_md if mode == "INCREMENTAL" else None,
        )

        # Step 6: Call LLM
        response = await acompletion(
            model=config.phase2.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            timeout=180,
        )
        content = response.choices[0].message.content

        # Step 7: Parse JSON response
        try:
            data = json.loads(content)
            if not _validate_response(data):
                raise ValueError("Missing required fields in response")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Invalid JSON from LLM for %s: %s", scope, exc)
            db.record_consolidation_run(
                scope=scope,
                status="failed",
                phase1_count=len(phase1_outputs),
                input_watermark=new_watermark,
                token_usage_input=getattr(response.usage, "prompt_tokens", 0),
                token_usage_output=getattr(response.usage, "completion_tokens", 0),
                error_message=f"Invalid JSON: {exc}",
            )
            return False

        # Step 7a: Post-scan redaction (Layer 3 safety net)
        data = _redact_response(data, redactor)

        # Step 8: Write memory files and skills
        store.write_memory_summary(project_path, data["memory_summary"])
        store.write_memory_md(project_path, data["memory_md"])

        for skill in data.get("skills", []):
            if isinstance(skill, dict) and skill.get("name") and skill.get("skill_md"):
                store.write_skill(project_path, skill["name"], skill["skill_md"])

        # Step 9: Record consolidation run in DB
        db.record_consolidation_run(
            scope=scope,
            status="completed",
            phase1_count=len(phase1_outputs),
            input_watermark=new_watermark,
            token_usage_input=getattr(response.usage, "prompt_tokens", 0),
            token_usage_output=getattr(response.usage, "completion_tokens", 0),
        )

        logger.info("Consolidated %d outputs for %s (mode=%s)", len(phase1_outputs), project_path, mode)
        return True

    except Exception as exc:
        logger.error("Consolidation failed for %s: %s", scope, exc)
        # Redact error message before storing — library exceptions may contain secrets
        safe_error = redactor.redact(str(exc))[:500]
        db.record_consolidation_run(
            scope=scope,
            status="failed",
            phase1_count=0,
            input_watermark=0,
            token_usage_input=0,
            token_usage_output=0,
            error_message=safe_error,
        )
        return False

    finally:
        # Step 10: Release consolidation lock
        db.release_consolidation_lock(scope)


async def consolidate_global(
    db: ClawtexDB,
    store: MemoryStore,
    config: ClawtexConfig,
    worker_id: str,
    redactor: Redactor | None = None,
) -> bool:
    """Consolidate all project summaries into global cross-project memory.

    Loads each project's memory_summary.md, uses global prompt templates
    to extract cross-project transferable patterns, and writes to the
    global/ directory.

    Returns True if consolidation ran, False if skipped.
    """
    scope = "global"
    if redactor is None:
        redactor = Redactor(
            extra_patterns=config.redaction.extra_patterns or None,
            placeholder=config.redaction.placeholder,
        )

    # Load project summaries
    projects = store.list_projects()
    project_summaries = []
    for proj in projects:
        summary = store.read_memory_summary(proj)
        if summary:
            # Derive project name from the encoded path
            name = derive_project_name(proj)
            project_summaries.append({"name": name, "summary": summary})

    if not project_summaries:
        logger.info("No project summaries found for global consolidation")
        return False

    # Acquire lock
    if not db.acquire_consolidation_lock(scope, worker_id):
        logger.info("Could not acquire global consolidation lock")
        return False

    try:
        # Detect mode
        existing_summary = store.read_memory_summary(None)
        existing_memory_md = store.read_memory_md(None)

        if existing_summary is not None and existing_memory_md is not None:
            mode = "INCREMENTAL"
        else:
            mode = "INIT"

        # Build prompts
        system_prompt, user_prompt = _build_global_prompts(
            mode=mode,
            project_summaries=project_summaries,
            existing_summary=existing_summary if mode == "INCREMENTAL" else None,
            existing_memory_md=existing_memory_md if mode == "INCREMENTAL" else None,
        )

        # Call LLM
        response = await acompletion(
            model=config.phase2.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            timeout=180,
        )
        content = response.choices[0].message.content

        # Parse JSON response
        try:
            data = json.loads(content)
            if not _validate_response(data):
                raise ValueError("Missing required fields in global response")
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.error("Invalid JSON from LLM for global: %s", exc)
            db.record_consolidation_run(
                scope=scope,
                status="failed",
                phase1_count=len(project_summaries),
                input_watermark=0,
                token_usage_input=getattr(response.usage, "prompt_tokens", 0),
                token_usage_output=getattr(response.usage, "completion_tokens", 0),
                error_message=f"Invalid JSON: {exc}",
            )
            return False

        # Post-scan redaction (Layer 3 safety net)
        data = _redact_response(data, redactor)

        # Write global memory files
        store.write_memory_summary(None, data["memory_summary"])
        store.write_memory_md(None, data["memory_md"])

        # Global skills (if any)
        for skill in data.get("skills", []):
            if isinstance(skill, dict) and skill.get("name") and skill.get("skill_md"):
                store.write_skill(None, skill["name"], skill["skill_md"])

        # Record consolidation run
        db.record_consolidation_run(
            scope=scope,
            status="completed",
            phase1_count=len(project_summaries),
            input_watermark=0,
            token_usage_input=getattr(response.usage, "prompt_tokens", 0),
            token_usage_output=getattr(response.usage, "completion_tokens", 0),
        )

        logger.info("Global consolidation completed with %d project summaries (mode=%s)", len(project_summaries), mode)
        return True

    except Exception as exc:
        logger.error("Global consolidation failed: %s", exc)
        safe_error = redactor.redact(str(exc))[:500]
        db.record_consolidation_run(
            scope=scope,
            status="failed",
            phase1_count=0,
            input_watermark=0,
            token_usage_input=0,
            token_usage_output=0,
            error_message=safe_error,
        )
        return False

    finally:
        db.release_consolidation_lock(scope)


async def run_phase2(
    config: ClawtexConfig,
    project_path: str | None = None,
    include_global: bool | None = None,
) -> dict:
    """Top-level Phase 2 orchestrator.

    Consolidates each project with new Phase 1 outputs, then runs global
    consolidation.

    Args:
        config: Application configuration
        project_path: If specified, only consolidate this project
        include_global: Whether to run global consolidation. Defaults to True for full runs and
            False for project-scoped runs.

    Returns:
        {"projects_consolidated": N, "global": bool}
    """
    worker_id = f"phase2-{uuid.uuid4().hex[:8]}"
    if include_global is None:
        include_global = project_path is None

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
        projects_consolidated = 0

        if project_path:
            # Consolidate specific project
            result = await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id=worker_id,
                redactor=redactor,
            )
            if result:
                projects_consolidated = 1
        else:
            # Find all projects with Phase 1 outputs
            rows = db.execute("SELECT DISTINCT project_path FROM phase1_outputs").fetchall()
            project_paths = [row["project_path"] for row in rows]

            for pp in project_paths:
                result = await consolidate_project(
                    project_path=pp,
                    db=db,
                    store=store,
                    config=config,
                    worker_id=worker_id,
                    redactor=redactor,
                )
                if result:
                    projects_consolidated += 1

        global_result = False
        if include_global:
            global_result = await consolidate_global(
                db=db,
                store=store,
                config=config,
                worker_id=worker_id,
                redactor=redactor,
            )

        return {
            "projects_consolidated": projects_consolidated,
            "global": global_result,
        }

    finally:
        db.close()
