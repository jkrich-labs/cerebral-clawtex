# tests/test_phase2.py
"""Tests for Phase 2 consolidation pipeline.

All tests mock litellm.acompletion to avoid real LLM calls.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cerebral_clawtex.config import ClawtexConfig, GeneralConfig, Phase2Config
from cerebral_clawtex.db import ClawtexDB
from cerebral_clawtex.storage import MemoryStore


def _make_config(data_dir: Path, claude_home: Path) -> ClawtexConfig:
    """Create a test config pointing to temp directories."""
    cfg = ClawtexConfig()
    cfg.general = GeneralConfig(claude_home=claude_home, data_dir=data_dir)
    cfg.phase2 = Phase2Config(model="anthropic/claude-sonnet-4-6-20250514")
    return cfg


def _make_llm_response(content: dict) -> SimpleNamespace:
    """Create a mock LLM response object matching LiteLLM's structure."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(content))
            )
        ],
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=300),
    )


def _seed_phase1_output(
    db: ClawtexDB,
    session_id: str,
    project_path: str,
    raw_memory: str = "- Test learning from session",
    rollout_summary: str = "## Session\nTest summary",
    rollout_slug: str = "test-session",
    task_outcome: str = "success",
) -> None:
    """Register a session and store a Phase 1 output in the DB."""
    now = int(time.time())
    db.register_session(
        session_id=session_id,
        project_path=project_path,
        session_file=f"/fake/{session_id}.jsonl",
        file_modified_at=now,
        file_size_bytes=1000,
    )
    db.update_session_status(session_id, "extracted")
    db.store_phase1_output(
        session_id=session_id,
        project_path=project_path,
        raw_memory=raw_memory,
        rollout_summary=rollout_summary,
        rollout_slug=rollout_slug,
        task_outcome=task_outcome,
        token_usage_input=100,
        token_usage_output=50,
    )


SAMPLE_LLM_RESPONSE = {
    "memory_summary": "## User Profile\n\nDeveloper using Python.\n\n## General Tips\n\n1. Use type hints\n\n## Routing Index\n\n| Topic | Location | Keywords |\n|-------|----------|----------|\n| Python | MEMORY.md > Python | typing, hints |",
    "memory_md": "# Project Memory\n\n## Python Development\n\n<!--\nrollout_files:\n  - rollout_summaries/test-session.md\nkeywords: [python, typing]\n-->\n\n- Always use type hints for function signatures\n- Use ruff for linting",
    "skills": [],
}

SAMPLE_LLM_RESPONSE_WITH_SKILLS = {
    "memory_summary": "## User Profile\n\nDeveloper.\n\n## General Tips\n\n1. Use venv\n\n## Routing Index\n\n| Topic | Location | Keywords |\n|-------|----------|----------|\n| deploy | skills/deploy-workflow/SKILL.md | deploy, staging |",
    "memory_md": "# Project Memory\n\n## Deployment\n\n<!--\nrollout_files:\n  - rollout_summaries/deploy-1.md\nkeywords: [deploy, staging]\n-->\n\n- Always run tests before deploying",
    "skills": [
        {
            "name": "deploy-workflow",
            "skill_md": "---\nname: deploy-workflow\ndescription: Standard deployment procedure\nkeywords: [deploy, staging]\n---\n\n# Skill: Deploy Workflow\n\n## Procedure\n\n1. Run tests\n2. Build\n3. Deploy",
        }
    ],
}

SAMPLE_GLOBAL_RESPONSE = {
    "memory_summary": "## User Profile\n\nCross-project developer profile.\n\n## General Tips\n\n1. Always use virtual environments\n\n## Routing Index\n\n| Topic | Location | Keywords |\n|-------|----------|----------|\n| Git | MEMORY.md > Git | rebase, merge |",
    "memory_md": "# Global Memory\n\n## Git Workflows\n\n<!--\nsource_projects:\n  - project-a\n  - project-b\nkeywords: [git, rebase, merge]\n-->\n\n- Always rebase before merge to keep history clean",
    "skills": [],
}


class TestConsolidateProject:
    """Tests for consolidate_project()."""

    @pytest.fixture
    def setup(self, tmp_data_dir: Path, tmp_claude_home: Path):
        """Create DB, store, and config for testing."""
        db = ClawtexDB(tmp_data_dir / "clawtex.db")
        store = MemoryStore(tmp_data_dir)
        config = _make_config(tmp_data_dir, tmp_claude_home)
        return db, store, config

    @pytest.mark.asyncio
    async def test_init_mode_writes_memory_files(self, setup):
        """INIT mode: no existing files, writes memory_summary and MEMORY.md."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        # Seed Phase 1 output
        _seed_phase1_output(db, "sess-1", project_path)

        mock_response = _make_llm_response(SAMPLE_LLM_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_project

            result = await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        assert result is True

        # Verify files were written
        summary = store.read_memory_summary(project_path)
        assert summary is not None
        assert "User Profile" in summary

        memory_md = store.read_memory_md(project_path)
        assert memory_md is not None
        assert "Project Memory" in memory_md

    @pytest.mark.asyncio
    async def test_incremental_mode_loads_existing_files(self, setup):
        """INCREMENTAL mode: existing files are loaded and passed to LLM."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        # Write existing memory files
        store.write_memory_summary(project_path, "## Existing Summary\n\nOld content.")
        store.write_memory_md(project_path, "# Existing Memory\n\n## Old Topic\n\n- Old learning")

        # Seed Phase 1 output
        _seed_phase1_output(db, "sess-inc-1", project_path)

        # We also need a prior consolidation run with a watermark to make incremental work
        # The first call with existing files should detect INCREMENTAL mode
        mock_acompletion = AsyncMock(return_value=_make_llm_response(SAMPLE_LLM_RESPONSE))

        with patch("cerebral_clawtex.phase2.acompletion", mock_acompletion):
            from cerebral_clawtex.phase2 import consolidate_project

            result = await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        assert result is True

        # Verify the LLM was called with INCREMENTAL mode prompt content
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0] if call_args[0] else None
        if messages is None:
            messages = call_args.kwargs["messages"]
        user_msg = messages[-1]["content"]
        assert "INCREMENTAL" in user_msg
        assert "Existing Summary" in user_msg

    @pytest.mark.asyncio
    async def test_skills_created(self, setup):
        """Skills returned by LLM are written to disk."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        _seed_phase1_output(db, "sess-skill-1", project_path)

        mock_response = _make_llm_response(SAMPLE_LLM_RESPONSE_WITH_SKILLS)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_project

            result = await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        assert result is True

        # Verify skill was written
        skills = store.list_skills(project_path)
        assert len(skills) == 1
        skill_content = skills[0].read_text()
        assert "Deploy Workflow" in skill_content

    @pytest.mark.asyncio
    async def test_consolidation_run_recorded(self, setup):
        """Consolidation run is recorded in DB with watermark."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        _seed_phase1_output(db, "sess-rec-1", project_path)

        mock_response = _make_llm_response(SAMPLE_LLM_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_project

            await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        # Verify consolidation run was recorded
        runs = db.execute(
            "SELECT * FROM consolidation_runs WHERE scope = ?",
            (f"project:{project_path}",),
        ).fetchall()
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"
        assert runs[0]["phase1_count"] == 1
        assert runs[0]["input_watermark"] is not None

    @pytest.mark.asyncio
    async def test_watermark_advances(self, setup):
        """After consolidation, the watermark advances so only new outputs are picked up next time."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        _seed_phase1_output(db, "sess-wm-1", project_path)

        mock_response = _make_llm_response(SAMPLE_LLM_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_project

            await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        # Check watermark was set
        scope = f"project:{project_path}"
        watermark = db.get_last_watermark(scope)
        assert watermark is not None
        assert watermark > 0

    @pytest.mark.asyncio
    async def test_lock_acquired_and_released(self, setup):
        """Consolidation lock is acquired before processing and released after."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        _seed_phase1_output(db, "sess-lock-1", project_path)

        mock_response = _make_llm_response(SAMPLE_LLM_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_project

            await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        # Lock should be released after consolidation
        lock = db.execute(
            "SELECT * FROM consolidation_lock WHERE scope = ?",
            (f"project:{project_path}",),
        ).fetchone()
        assert lock is None  # Lock is released (deleted)

    @pytest.mark.asyncio
    async def test_lock_failure_returns_false(self, setup):
        """If lock cannot be acquired, consolidation returns False."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        _seed_phase1_output(db, "sess-lockfail-1", project_path)

        # Pre-acquire the lock by another worker
        scope = f"project:{project_path}"
        db.acquire_consolidation_lock(scope, "other-worker")

        from cerebral_clawtex.phase2 import consolidate_project

        result = await consolidate_project(
            project_path=project_path,
            db=db,
            store=store,
            config=config,
            worker_id="test-worker",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_no_phase1_outputs_returns_false(self, setup):
        """If there are no Phase 1 outputs to consolidate, returns False."""
        db, store, config = setup
        project_path = "-home-user-project-empty"

        from cerebral_clawtex.phase2 import consolidate_project

        result = await consolidate_project(
            project_path=project_path,
            db=db,
            store=store,
            config=config,
            worker_id="test-worker",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_post_scan_redaction(self, setup):
        """Post-scan redaction is applied to all LLM output strings before writing."""
        db, store, config = setup
        project_path = "-home-user-project-a"

        _seed_phase1_output(db, "sess-redact-1", project_path)

        # LLM response contains a secret that should be redacted
        response_with_secret = {
            "memory_summary": "## Summary\n\nUse API key sk-proj-abcdefghijklmnopqrstuvwxyz1234567890 for auth",
            "memory_md": "# Memory\n\n- Configure with password='supersecretvalue123' in the settings",
            "skills": [
                {
                    "name": "auth-setup",
                    "skill_md": "---\nname: auth-setup\n---\n\nUse token Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret.data for auth",
                }
            ],
        }
        mock_response = _make_llm_response(response_with_secret)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_project

            await consolidate_project(
                project_path=project_path,
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        # Verify secrets were redacted in written files
        summary = store.read_memory_summary(project_path)
        assert "sk-proj-" not in summary
        assert "REDACTED" in summary

        memory_md = store.read_memory_md(project_path)
        assert "supersecretvalue123" not in memory_md
        assert "REDACTED" in memory_md

        # Verify skill content was also redacted
        skills = store.list_skills(project_path)
        assert len(skills) == 1
        skill_content = skills[0].read_text()
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in skill_content
        assert "REDACTED" in skill_content


class TestConsolidateGlobal:
    """Tests for consolidate_global()."""

    @pytest.fixture
    def setup(self, tmp_data_dir: Path, tmp_claude_home: Path):
        db = ClawtexDB(tmp_data_dir / "clawtex.db")
        store = MemoryStore(tmp_data_dir)
        config = _make_config(tmp_data_dir, tmp_claude_home)
        return db, store, config

    @pytest.mark.asyncio
    async def test_global_consolidation_merges_project_summaries(self, setup):
        """Global consolidation loads project summaries and writes global files."""
        db, store, config = setup

        # Create two projects with memory summaries
        store.write_memory_summary("-home-user-project-a", "## Project A\n\nLearnings from project A.")
        store.write_memory_summary("-home-user-project-b", "## Project B\n\nLearnings from project B.")

        mock_acompletion = AsyncMock(return_value=_make_llm_response(SAMPLE_GLOBAL_RESPONSE))

        with patch("cerebral_clawtex.phase2.acompletion", mock_acompletion):
            from cerebral_clawtex.phase2 import consolidate_global

            result = await consolidate_global(
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        assert result is True

        # Verify global files were written
        global_summary = store.read_memory_summary(None)
        assert global_summary is not None
        assert "Cross-project" in global_summary

        global_memory = store.read_memory_md(None)
        assert global_memory is not None
        assert "Global Memory" in global_memory

        # Verify the LLM was called with project summaries
        call_args = mock_acompletion.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        if messages is None and call_args[0]:
            messages = call_args[0][0]
        if messages is None:
            messages = call_args.kwargs["messages"]
        user_msg = messages[-1]["content"]
        assert "Project A" in user_msg or "project-a" in user_msg
        assert "Project B" in user_msg or "project-b" in user_msg

    @pytest.mark.asyncio
    async def test_global_no_projects_returns_false(self, setup):
        """If no projects have memory summaries, global consolidation returns False."""
        db, store, config = setup

        from cerebral_clawtex.phase2 import consolidate_global

        result = await consolidate_global(
            db=db,
            store=store,
            config=config,
            worker_id="test-worker",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_global_post_scan_redaction(self, setup):
        """Post-scan redaction is applied to global consolidation output."""
        db, store, config = setup

        store.write_memory_summary("-home-user-project-a", "## Project A\n\nSome learnings.")

        response_with_secret = {
            "memory_summary": "## Global\n\nUse key AKIAIOSFODNN7EXAMPLE for AWS",
            "memory_md": "# Global Memory\n\n- AWS setup with AKIAIOSFODNN7EXAMPLE",
            "skills": [],
        }
        mock_response = _make_llm_response(response_with_secret)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_global

            await consolidate_global(
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        global_summary = store.read_memory_summary(None)
        assert "AKIAIOSFODNN7EXAMPLE" not in global_summary
        assert "REDACTED" in global_summary

    @pytest.mark.asyncio
    async def test_global_lock_acquired_and_released(self, setup):
        """Global consolidation acquires and releases the global lock."""
        db, store, config = setup

        store.write_memory_summary("-home-user-project-a", "## Project A\n\nSome learnings.")

        mock_response = _make_llm_response(SAMPLE_GLOBAL_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", new_callable=AsyncMock, return_value=mock_response):
            from cerebral_clawtex.phase2 import consolidate_global

            await consolidate_global(
                db=db,
                store=store,
                config=config,
                worker_id="test-worker",
            )

        # Lock should be released
        lock = db.execute(
            "SELECT * FROM consolidation_lock WHERE scope = ?",
            ("global",),
        ).fetchone()
        assert lock is None


class TestRunPhase2:
    """Tests for run_phase2()."""

    @pytest.fixture
    def setup(self, tmp_data_dir: Path, tmp_claude_home: Path):
        db = ClawtexDB(tmp_data_dir / "clawtex.db")
        store = MemoryStore(tmp_data_dir)
        config = _make_config(tmp_data_dir, tmp_claude_home)
        return db, store, config

    @pytest.mark.asyncio
    async def test_orchestrates_project_and_global(self, setup):
        """run_phase2 consolidates projects and then runs global consolidation."""
        db, store, config = setup

        # Seed two projects with Phase 1 outputs
        _seed_phase1_output(db, "sess-p2-1", "-home-user-proj-a")
        _seed_phase1_output(db, "sess-p2-2", "-home-user-proj-b")

        # The mock needs to return different responses for project and global calls
        call_count = 0

        async def mock_acompletion_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # Project consolidation calls
                return _make_llm_response(SAMPLE_LLM_RESPONSE)
            else:
                # Global consolidation call
                return _make_llm_response(SAMPLE_GLOBAL_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", side_effect=mock_acompletion_fn):
            from cerebral_clawtex.phase2 import run_phase2

            result = await run_phase2(config=config)

        assert result["projects_consolidated"] == 2
        assert result["global"] is True

    @pytest.mark.asyncio
    async def test_specific_project(self, setup):
        """run_phase2 can consolidate a specific project only."""
        db, store, config = setup

        _seed_phase1_output(db, "sess-sp-1", "-home-user-proj-a")
        _seed_phase1_output(db, "sess-sp-2", "-home-user-proj-b")

        call_count = 0

        async def mock_acompletion_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(SAMPLE_LLM_RESPONSE)
            else:
                return _make_llm_response(SAMPLE_GLOBAL_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", side_effect=mock_acompletion_fn):
            from cerebral_clawtex.phase2 import run_phase2

            result = await run_phase2(config=config, project_path="-home-user-proj-a")

        # Only the specified project should be consolidated
        assert result["projects_consolidated"] == 1

    @pytest.mark.asyncio
    async def test_no_projects_to_consolidate(self, setup):
        """run_phase2 returns zeros when no projects have Phase 1 outputs."""
        _, _, config = setup

        from cerebral_clawtex.phase2 import run_phase2

        result = await run_phase2(config=config)

        assert result["projects_consolidated"] == 0
        assert result["global"] is False
