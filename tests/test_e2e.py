# tests/test_e2e.py
"""End-to-end tests for the Cerebral Clawtex pipeline.

Gated behind the @pytest.mark.e2e marker for organizational grouping.
All LLM calls are MOCKED — these tests are deterministic and do not
require API keys.

Run with: pytest tests/test_e2e.py -v
Or selectively: pytest -m e2e -v
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from cerebral_clawtex.config import ClawtexConfig, GeneralConfig, Phase1Config, Phase2Config
from cerebral_clawtex.db import ClawtexDB
from cerebral_clawtex.redact import Redactor
from cerebral_clawtex.storage import MemoryStore

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Realistic session JSONL content
# ---------------------------------------------------------------------------

SESSION_RECORDS = [
    {
        "type": "user",
        "uuid": "u1",
        "parentUuid": None,
        "sessionId": "e2e-session-001",
        "timestamp": "2026-02-24T14:00:00Z",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": "I need to add pagination to the /api/users endpoint. Currently it returns all users at once.",
        },
    },
    {
        "type": "assistant",
        "uuid": "a1",
        "parentUuid": "u1",
        "sessionId": "e2e-session-001",
        "timestamp": "2026-02-24T14:01:00Z",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-6",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "I'll add cursor-based pagination to the /api/users endpoint. "
                        "Let me first look at the current implementation."
                    ),
                },
                {
                    "type": "tool_use",
                    "name": "Read",
                    "input": {"file_path": "/home/user/webapp/routes/users.py"},
                },
            ],
            "usage": {"input_tokens": 200, "output_tokens": 100},
        },
    },
    {
        "type": "user",
        "uuid": "u2",
        "parentUuid": "a1",
        "sessionId": "e2e-session-001",
        "timestamp": "2026-02-24T14:02:00Z",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": "def get_users():\n    return db.query(User).all()",
                }
            ],
        },
    },
    {
        "type": "assistant",
        "uuid": "a2",
        "parentUuid": "u2",
        "sessionId": "e2e-session-001",
        "timestamp": "2026-02-24T14:03:00Z",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-6",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "I'll implement cursor-based pagination using the user's created_at "
                        "timestamp and ID as the cursor. This avoids the offset performance "
                        "issues with large datasets. I'll also add a default page_size of 50."
                    ),
                }
            ],
            "usage": {"input_tokens": 300, "output_tokens": 200},
        },
    },
    {
        "type": "user",
        "uuid": "u3",
        "parentUuid": "a2",
        "sessionId": "e2e-session-001",
        "timestamp": "2026-02-24T14:05:00Z",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": "That works perfectly. The tests pass now too. Thanks!",
        },
    },
]

# ---------------------------------------------------------------------------
# Mock LLM responses
# ---------------------------------------------------------------------------

PHASE1_LLM_RESPONSE = {
    "task_outcome": "success",
    "rollout_slug": "add-cursor-pagination-to-users-api",
    "rollout_summary": (
        "## Session: Add Cursor Pagination to Users API\n\n"
        "**Goal:** Add pagination to /api/users endpoint\n"
        "**Approach:** Implemented cursor-based pagination using created_at + ID composite cursor\n"
        "**Outcome:** Successfully added pagination with default page_size of 50\n"
        "**Key Learnings:**\n"
        "- Cursor-based pagination avoids offset performance issues on large datasets\n"
        "- Use composite cursor (timestamp + ID) for deterministic ordering\n"
    ),
    "raw_memory": (
        "---\n"
        "rollout_summary_file: rollout_summaries/add-cursor-pagination-to-users-api.md\n"
        "description: Added cursor-based pagination to /api/users endpoint\n"
        "keywords: [pagination, cursor, api, performance]\n"
        "---\n"
        "- Cursor-based pagination using (created_at, id) composite avoids offset issues\n"
        "- Default page_size of 50 is a good starting point for user listings\n"
        "- Always include next_cursor and has_more in paginated responses\n"
    ),
}

PHASE2_PROJECT_RESPONSE = {
    "memory_summary": (
        "## User Profile\n\n"
        "Developer working on a Python web application with REST API endpoints.\n\n"
        "## General Tips\n\n"
        "1. Use cursor-based pagination over offset-based for large datasets\n"
        "2. Include next_cursor and has_more fields in paginated API responses\n"
        "3. Use composite cursors (timestamp + ID) for deterministic ordering\n\n"
        "## Routing Index\n\n"
        "| Topic | Location | Keywords |\n"
        "|-------|----------|----------|\n"
        "| Pagination | MEMORY.md > API Design | cursor, pagination, performance |"
    ),
    "memory_md": (
        "# Project Memory\n\n"
        "## API Design\n\n"
        "<!--\n"
        "rollout_files:\n"
        "  - rollout_summaries/add-cursor-pagination-to-users-api.md\n"
        "keywords: [pagination, cursor, api, performance]\n"
        "-->\n\n"
        "- Cursor-based pagination using (created_at, id) composite avoids offset performance issues\n"
        "- Default page_size of 50 is appropriate for user listings\n"
        "- Always include next_cursor and has_more fields in paginated responses\n"
    ),
    "skills": [],
}

PHASE2_GLOBAL_RESPONSE = {
    "memory_summary": (
        "## User Profile\n\n"
        "Developer working across multiple Python projects.\n\n"
        "## General Tips\n\n"
        "1. Prefer cursor-based pagination for REST APIs\n\n"
        "## Routing Index\n\n"
        "| Topic | Location | Keywords |\n"
        "|-------|----------|----------|\n"
        "| API | MEMORY.md > REST API Patterns | pagination, cursor |"
    ),
    "memory_md": (
        "# Global Memory\n\n"
        "## REST API Patterns\n\n"
        "<!--\n"
        "source_projects:\n"
        "  - webapp\n"
        "keywords: [api, pagination, cursor]\n"
        "-->\n\n"
        "- Cursor-based pagination scales better than offset-based for large datasets\n"
    ),
    "skills": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_llm_response(content: dict | str) -> SimpleNamespace:
    """Create a mock LiteLLM response object."""
    if isinstance(content, dict):
        content = json.dumps(content)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=500, completion_tokens=300),
    )


def _write_session_jsonl(path: Path, records: list[dict] | None = None) -> None:
    """Write session records as JSONL."""
    if records is None:
        records = SESSION_RECORDS
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _seed_claude_home(claude_home: Path, project_name: str = "-home-user-webapp") -> Path:
    """Create a fake Claude home with a realistic session JSONL.

    Returns the path to the session JSONL file.
    """
    project_dir = claude_home / "projects" / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    session_path = project_dir / "e2e-session-001.jsonl"
    _write_session_jsonl(session_path)

    # Backdate the file so it passes idle time filter (2 hours ago)
    old_time = time.time() - 7200
    os.utime(session_path, (old_time, old_time))

    return session_path


def _check_no_secrets(text: str) -> None:
    """Assert that no common secret patterns exist in text."""
    redactor = Redactor()
    redacted = redactor.redact(text)
    # If the redactor changed anything, there was a secret
    assert redacted == text, "Found potential secret in output (redaction changed the text)"


def _collect_all_output_files(data_dir: Path) -> list[Path]:
    """Collect all .md files in the data directory."""
    return list(data_dir.rglob("*.md"))


# ---------------------------------------------------------------------------
# E2E Test Class
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestEndToEnd:
    """Full pipeline end-to-end test: Phase 1 -> Phase 2 -> Hook.

    All LLM calls are mocked. This test validates the entire data flow:
    session JSONL -> extraction -> consolidation -> hook output.
    """

    @pytest.fixture
    def e2e_env(self, tmp_path: Path):
        """Set up a complete E2E environment with fake Claude home, config, DB, and store."""
        claude_home = tmp_path / ".claude"
        claude_home.mkdir()
        (claude_home / "projects").mkdir()

        data_dir = tmp_path / "clawtex-data"
        data_dir.mkdir()

        config = ClawtexConfig(
            general=GeneralConfig(claude_home=claude_home, data_dir=data_dir),
            phase1=Phase1Config(
                model="test/mock-haiku",
                max_sessions_per_run=20,
                max_session_age_days=30,
                min_session_idle_hours=0,
                max_input_tokens=80_000,
                concurrent_extractions=2,
            ),
            phase2=Phase2Config(
                model="test/mock-sonnet",
                run_after_phase1=False,
            ),
        )

        return {
            "tmp_path": tmp_path,
            "claude_home": claude_home,
            "data_dir": data_dir,
            "config": config,
        }

    async def test_full_pipeline(self, e2e_env):
        """Full E2E: seed session -> Phase 1 -> Phase 2 -> hook output -> secret scan."""
        claude_home = e2e_env["claude_home"]
        data_dir = e2e_env["data_dir"]
        config = e2e_env["config"]

        project_name = "-home-user-webapp"

        # ---------------------------------------------------------------
        # Step 1: Seed a fake Claude home with a realistic session JSONL
        # ---------------------------------------------------------------
        session_path = _seed_claude_home(claude_home, project_name)
        assert session_path.exists()
        assert session_path.stat().st_size > 0

        # ---------------------------------------------------------------
        # Step 2: Run Phase 1 extraction (with MOCKED LiteLLM)
        # ---------------------------------------------------------------
        phase1_mock = AsyncMock(return_value=_make_llm_response(PHASE1_LLM_RESPONSE))

        with patch("cerebral_clawtex.phase1.acompletion", phase1_mock):
            from cerebral_clawtex.phase1 import run_phase1

            phase1_result = await run_phase1(config=config)

        # Verify Phase 1 results
        assert phase1_result["extracted"] == 1, f"Expected 1 extracted, got {phase1_result}"
        assert phase1_result["skipped"] == 0
        assert phase1_result["failed"] == 0

        # Verify LLM was called with correct model
        phase1_mock.assert_called_once()
        call_kwargs = phase1_mock.call_args.kwargs
        assert call_kwargs["model"] == "test/mock-haiku"
        assert call_kwargs["response_format"] == {"type": "json_object"}

        # ---------------------------------------------------------------
        # Step 3: Verify session is marked as extracted in DB
        # ---------------------------------------------------------------
        db = ClawtexDB(data_dir / "clawtex.db")
        try:
            session = db.get_session(f"{project_name}:e2e-session-001")
            assert session is not None, "Session not found in DB"
            assert session["status"] == "extracted"

            # Verify Phase 1 output is stored in DB
            outputs = db.get_phase1_outputs(project_path=project_name)
            assert len(outputs) == 1
            assert outputs[0]["task_outcome"] == "success"
            assert outputs[0]["rollout_slug"] == "add-cursor-pagination-to-users-api"
        finally:
            db.close()

        # ---------------------------------------------------------------
        # Step 4: Verify rollout summary file exists on disk
        # ---------------------------------------------------------------
        store = MemoryStore(data_dir)
        summaries = store.list_rollout_summaries(project_name)
        assert len(summaries) == 1, f"Expected 1 rollout summary, found {len(summaries)}"
        assert "add-cursor-pagination" in summaries[0].stem
        rollout_content = summaries[0].read_text()
        assert "Cursor Pagination" in rollout_content

        # ---------------------------------------------------------------
        # Step 5: Run Phase 2 consolidation (with MOCKED LiteLLM)
        # ---------------------------------------------------------------
        phase2_call_count = 0

        async def phase2_mock_fn(**kwargs):
            nonlocal phase2_call_count
            phase2_call_count += 1
            if phase2_call_count == 1:
                # Project consolidation
                return _make_llm_response(PHASE2_PROJECT_RESPONSE)
            else:
                # Global consolidation
                return _make_llm_response(PHASE2_GLOBAL_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", side_effect=phase2_mock_fn):
            from cerebral_clawtex.phase2 import run_phase2

            phase2_result = await run_phase2(config=config)

        assert phase2_result["projects_consolidated"] == 1
        assert phase2_result["global"] is True

        # ---------------------------------------------------------------
        # Step 6: Verify memory_summary.md and MEMORY.md exist
        # ---------------------------------------------------------------

        # Project memory files
        project_summary = store.read_memory_summary(project_name)
        assert project_summary is not None, "Project memory_summary.md not found"
        assert "User Profile" in project_summary
        assert "cursor-based pagination" in project_summary

        project_memory_md = store.read_memory_md(project_name)
        assert project_memory_md is not None, "Project MEMORY.md not found"
        assert "API Design" in project_memory_md
        assert "Cursor-based pagination" in project_memory_md

        # Global memory files
        global_summary = store.read_memory_summary(None)
        assert global_summary is not None, "Global memory_summary.md not found"
        assert "REST API" in global_summary or "pagination" in global_summary

        global_memory_md = store.read_memory_md(None)
        assert global_memory_md is not None, "Global MEMORY.md not found"

        # ---------------------------------------------------------------
        # Step 7: Check no secrets in any output file
        # ---------------------------------------------------------------
        all_output_files = _collect_all_output_files(data_dir)
        assert len(all_output_files) > 0, "No output files found"

        for output_file in all_output_files:
            content = output_file.read_text()
            _check_no_secrets(content)

        # ---------------------------------------------------------------
        # Step 8: Run the hook to verify JSON output contains memory content
        # ---------------------------------------------------------------
        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch(
                "cerebral_clawtex.hooks._resolve_project_path",
                return_value=project_name,
            ),
            patch("cerebral_clawtex.hooks._spawn_background_extraction"),
        ):
            from cerebral_clawtex.hooks import session_start_hook

            # Capture stdout
            import io
            import sys

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                session_start_hook()
            finally:
                sys.stdout = old_stdout

            hook_output_raw = captured.getvalue().strip()

        assert hook_output_raw, "Hook produced no output"
        hook_output = json.loads(hook_output_raw)

        assert "additional_context" in hook_output
        context = hook_output["additional_context"]

        # Verify the hook output contains memory content
        assert "Cerebral Clawtex Memory" in context
        assert "cursor-based pagination" in context or "pagination" in context
        assert "MEMORY.md" in context  # Navigation instructions

    async def test_phase1_secret_redaction_in_pipeline(self, e2e_env):
        """Verify that secrets in LLM responses are caught by post-scan redaction."""
        claude_home = e2e_env["claude_home"]
        data_dir = e2e_env["data_dir"]
        config = e2e_env["config"]

        project_name = "-home-user-webapp"
        _seed_claude_home(claude_home, project_name)

        # LLM response that contains a leaked secret
        leaky_response = {
            "task_outcome": "success",
            "rollout_slug": "configure-aws-auth",
            "rollout_summary": (
                "## Session: Configure AWS Auth\n\nUsed key AKIAIOSFODNN7EXAMPLE for authentication setup."
            ),
            "raw_memory": (
                "---\n"
                "rollout_summary_file: rollout_summaries/configure-aws-auth.md\n"
                "description: AWS auth configuration\n"
                "keywords: [aws, auth]\n"
                "---\n"
                "- Use key AKIAIOSFODNN7EXAMPLE for the production S3 bucket\n"
            ),
        }

        phase1_mock = AsyncMock(return_value=_make_llm_response(leaky_response))

        with patch("cerebral_clawtex.phase1.acompletion", phase1_mock):
            from cerebral_clawtex.phase1 import run_phase1

            result = await run_phase1(config=config)

        assert result["extracted"] == 1

        # Verify the secret was redacted in stored outputs
        db = ClawtexDB(data_dir / "clawtex.db")
        try:
            outputs = db.get_phase1_outputs(project_path=project_name)
            assert len(outputs) == 1
            assert "AKIAIOSFODNN7EXAMPLE" not in outputs[0]["raw_memory"]
            assert "REDACTED" in outputs[0]["raw_memory"]
        finally:
            db.close()

        # Verify the rollout summary file is also redacted
        store = MemoryStore(data_dir)
        summaries = store.list_rollout_summaries(project_name)
        assert len(summaries) == 1
        content = summaries[0].read_text()
        assert "AKIAIOSFODNN7EXAMPLE" not in content
        assert "REDACTED" in content

    async def test_phase2_secret_redaction_in_pipeline(self, e2e_env):
        """Verify that secrets in Phase 2 LLM responses are caught before writing to disk."""
        claude_home = e2e_env["claude_home"]
        data_dir = e2e_env["data_dir"]
        config = e2e_env["config"]

        project_name = "-home-user-webapp"
        _seed_claude_home(claude_home, project_name)

        # Run Phase 1 first (clean response)
        phase1_mock = AsyncMock(return_value=_make_llm_response(PHASE1_LLM_RESPONSE))
        with patch("cerebral_clawtex.phase1.acompletion", phase1_mock):
            from cerebral_clawtex.phase1 import run_phase1

            await run_phase1(config=config)

        # Phase 2 with a leaky response
        leaky_phase2_response = {
            "memory_summary": ("## Summary\n\nUse API key sk-proj-abc123def456ghi789jkl012mno for service auth"),
            "memory_md": (
                "# Memory\n\n## Auth\n\n- Configure postgres://admin:supersecretpass@db.example.com:5432/prod for DB"
            ),
            "skills": [],
        }

        phase2_call_count = 0

        async def phase2_mock_fn(**kwargs):
            nonlocal phase2_call_count
            phase2_call_count += 1
            if phase2_call_count == 1:
                return _make_llm_response(leaky_phase2_response)
            else:
                return _make_llm_response(PHASE2_GLOBAL_RESPONSE)

        with patch("cerebral_clawtex.phase2.acompletion", side_effect=phase2_mock_fn):
            from cerebral_clawtex.phase2 import run_phase2

            await run_phase2(config=config)

        # Verify secrets were redacted in the written files
        store = MemoryStore(data_dir)
        summary = store.read_memory_summary(project_name)
        assert summary is not None
        assert "sk-proj-" not in summary
        assert "REDACTED" in summary

        memory_md = store.read_memory_md(project_name)
        assert memory_md is not None
        assert "supersecretpass" not in memory_md
        assert "REDACTED" in memory_md

    async def test_empty_session_produces_no_extraction(self, e2e_env):
        """An empty/minimal session JSONL that produces a no-op LLM response is skipped."""
        claude_home = e2e_env["claude_home"]
        config = e2e_env["config"]

        project_name = "-home-user-webapp"
        project_dir = claude_home / "projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Write a session with minimal content
        minimal_records = [
            {
                "type": "user",
                "uuid": "u1",
                "parentUuid": None,
                "sessionId": "minimal-sess",
                "timestamp": "2026-02-24T14:00:00Z",
                "isSidechain": False,
                "message": {"role": "user", "content": "Hello"},
            },
            {
                "type": "assistant",
                "uuid": "a1",
                "parentUuid": "u1",
                "sessionId": "minimal-sess",
                "timestamp": "2026-02-24T14:00:01Z",
                "isSidechain": False,
                "message": {
                    "role": "assistant",
                    "model": "claude-opus-4-6",
                    "content": [{"type": "text", "text": "Hi there!"}],
                    "usage": {"input_tokens": 10, "output_tokens": 5},
                },
            },
        ]

        session_path = project_dir / "minimal-sess.jsonl"
        _write_session_jsonl(session_path, minimal_records)
        old_time = time.time() - 7200
        os.utime(session_path, (old_time, old_time))

        # LLM returns a no-op response (session has no useful learnings)
        noop_response = {
            "task_outcome": "uncertain",
            "rollout_slug": "",
            "rollout_summary": "",
            "raw_memory": "",
        }

        phase1_mock = AsyncMock(return_value=_make_llm_response(noop_response))

        with patch("cerebral_clawtex.phase1.acompletion", phase1_mock):
            from cerebral_clawtex.phase1 import run_phase1

            result = await run_phase1(config=config)

        assert result["extracted"] == 0
        assert result["skipped"] == 1
        assert result["failed"] == 0

    async def test_hook_with_no_memories_produces_empty_context_json(self, e2e_env):
        """When there are no memory files, hook still emits valid JSON with empty context."""
        config = e2e_env["config"]

        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch(
                "cerebral_clawtex.hooks._resolve_project_path",
                return_value="-home-user-webapp",
            ),
            patch("cerebral_clawtex.hooks._spawn_background_extraction"),
        ):
            from cerebral_clawtex.hooks import session_start_hook

            import io
            import sys

            captured = io.StringIO()
            old_stdout = sys.stdout
            sys.stdout = captured
            try:
                session_start_hook()
            finally:
                sys.stdout = old_stdout

            output = captured.getvalue().strip()

        payload = json.loads(output)
        assert payload["additional_context"] == ""

    async def test_multiple_sessions_concurrent_extraction(self, e2e_env):
        """Multiple sessions are discovered and extracted concurrently."""
        claude_home = e2e_env["claude_home"]
        data_dir = e2e_env["data_dir"]
        config = e2e_env["config"]

        project_name = "-home-user-webapp"
        project_dir = claude_home / "projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create 3 session files
        for i in range(3):
            session_path = project_dir / f"session-{i}.jsonl"
            _write_session_jsonl(session_path)
            old_time = time.time() - 7200
            os.utime(session_path, (old_time, old_time))

        phase1_mock = AsyncMock(return_value=_make_llm_response(PHASE1_LLM_RESPONSE))

        with patch("cerebral_clawtex.phase1.acompletion", phase1_mock):
            from cerebral_clawtex.phase1 import run_phase1

            result = await run_phase1(config=config)

        assert result["extracted"] == 3
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert phase1_mock.call_count == 3

        # Verify all sessions are marked extracted in DB
        db = ClawtexDB(data_dir / "clawtex.db")
        try:
            for i in range(3):
                session = db.get_session(f"{project_name}:session-{i}")
                assert session is not None
                assert session["status"] == "extracted"
        finally:
            db.close()
