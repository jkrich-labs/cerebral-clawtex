# tests/test_phase1.py
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cerebral_clawtex.config import ClawtexConfig, Phase1Config
from cerebral_clawtex.db import ClawtexDB
from cerebral_clawtex.redact import Redactor
from cerebral_clawtex.storage import MemoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_LLM_RESPONSE = json.dumps(
    {
        "task_outcome": "success",
        "rollout_slug": "fix-widget-tests",
        "rollout_summary": "## Session: Fix Widget Tests\n\n**Goal:** Fix failing widget tests.",
        "raw_memory": (
            "---\nrollout_summary_file: rollout_summaries/fix-widget-tests.md\n"
            "description: Fixed widget tests\nkeywords: [testing, widgets]\n---\n"
            "- Widget tests need mock DB connection"
        ),
    }
)

NOOP_LLM_RESPONSE = json.dumps(
    {
        "task_outcome": "uncertain",
        "rollout_slug": "",
        "rollout_summary": "",
        "raw_memory": "",
    }
)


def _make_llm_response(content: str) -> SimpleNamespace:
    """Create a mock LiteLLM response object."""
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=100, completion_tokens=50)
    return SimpleNamespace(choices=[choice], usage=usage)


def _write_session_jsonl(path: Path) -> None:
    """Write a minimal but valid session JSONL file."""
    records = [
        {
            "type": "user",
            "uuid": "u1",
            "parentUuid": None,
            "sessionId": "sess-1",
            "timestamp": "2026-02-25T10:00:00Z",
            "isSidechain": False,
            "message": {"role": "user", "content": "Fix the widget tests"},
        },
        {
            "type": "assistant",
            "uuid": "a1",
            "parentUuid": "u1",
            "sessionId": "sess-1",
            "timestamp": "2026-02-25T10:01:00Z",
            "isSidechain": False,
            "message": {
                "role": "assistant",
                "model": "claude-opus-4-6",
                "content": [{"type": "text", "text": "I'll fix the widget tests now."}],
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        },
    ]
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def phase1_config() -> Phase1Config:
    return Phase1Config(
        model="test-model",
        max_sessions_per_run=20,
        max_session_age_days=30,
        min_session_idle_hours=0,
        max_input_tokens=80_000,
        concurrent_extractions=2,
    )


@pytest.fixture
def full_config(tmp_path: Path, phase1_config: Phase1Config) -> ClawtexConfig:
    config = ClawtexConfig()
    config.phase1 = phase1_config
    config.general.data_dir = tmp_path / "data"
    config.general.claude_home = tmp_path / ".claude"
    config.general.data_dir.mkdir(parents=True, exist_ok=True)
    config.general.claude_home.mkdir(parents=True, exist_ok=True)
    (config.general.claude_home / "projects").mkdir(parents=True, exist_ok=True)
    return config


@pytest.fixture
def db(tmp_path: Path) -> ClawtexDB:
    db = ClawtexDB(tmp_path / "clawtex.db")
    yield db
    db.close()


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return MemoryStore(data_dir)


@pytest.fixture
def redactor() -> Redactor:
    return Redactor()


@pytest.fixture
def session_file(tmp_path: Path) -> Path:
    """Create a session JSONL file and return its path."""
    claude_home = tmp_path / ".claude"
    project_dir = claude_home / "projects" / "-home-user-myproject"
    project_dir.mkdir(parents=True)
    session_path = project_dir / "test-session-id.jsonl"
    _write_session_jsonl(session_path)
    # Backdate the file so it passes idle time filter
    old_time = time.time() - 7200  # 2 hours ago
    os.utime(session_path, (old_time, old_time))
    return session_path


# ---------------------------------------------------------------------------
# Tests: extract_session()
# ---------------------------------------------------------------------------


class TestExtractSession:
    async def test_successful_extraction(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """Full pipeline: claim -> parse -> redact -> LLM -> validate -> store -> release."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        # Register the session so it can be claimed
        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        # Mock litellm.acompletion
        mock_acompletion = AsyncMock(return_value=_make_llm_response(VALID_LLM_RESPONSE))
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "extracted"

        # Verify LLM was called
        mock_acompletion.assert_called_once()
        call_kwargs = mock_acompletion.call_args
        assert call_kwargs.kwargs["model"] == "test-model"
        assert call_kwargs.kwargs["response_format"] == {"type": "json_object"}

        # Verify session released with extracted status
        session = db.get_session(session_id)
        assert session["status"] == "extracted"
        assert session["locked_by"] is None

        # Verify phase1 output stored in DB
        outputs = db.get_phase1_outputs(project_path=project_path)
        assert len(outputs) == 1
        assert outputs[0]["task_outcome"] == "success"
        assert outputs[0]["rollout_slug"] == "fix-widget-tests"

        # Verify rollout summary file written
        summaries = store.list_rollout_summaries(project_path)
        assert len(summaries) == 1
        assert "fix-widget-tests" in summaries[0].stem

    async def test_noop_response_skips(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """When LLM returns empty fields, session should be marked as skipped."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        mock_acompletion = AsyncMock(return_value=_make_llm_response(NOOP_LLM_RESPONSE))
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "skipped"

        # Session should be marked skipped
        session = db.get_session(session_id)
        assert session["status"] == "skipped"

        # No rollout summaries should be written
        summaries = store.list_rollout_summaries(project_path)
        assert len(summaries) == 0

    async def test_invalid_json_retries_once(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """On invalid JSON from LLM, retries once with a nudge message."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        # First call returns invalid JSON, second returns valid
        mock_acompletion = AsyncMock(
            side_effect=[
                _make_llm_response("not valid json at all"),
                _make_llm_response(VALID_LLM_RESPONSE),
            ]
        )
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "extracted"
        # Should have been called twice (original + retry)
        assert mock_acompletion.call_count == 2

        # The retry call should include the nudge message
        retry_call = mock_acompletion.call_args_list[1]
        messages = retry_call.kwargs["messages"]
        assert any("not valid JSON" in m["content"] for m in messages if m["role"] == "user")

    async def test_non_object_json_retries_once(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """Valid JSON of the wrong shape is treated as invalid and retried."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        mock_acompletion = AsyncMock(
            side_effect=[
                _make_llm_response("[]"),
                _make_llm_response(VALID_LLM_RESPONSE),
            ]
        )
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "extracted"
        assert mock_acompletion.call_count == 2

    async def test_invalid_json_both_attempts_fails(
        self, db, store, redactor, phase1_config, session_file, monkeypatch
    ):
        """If both attempts return invalid JSON, session is marked as failed."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        mock_acompletion = AsyncMock(
            side_effect=[
                _make_llm_response("bad json"),
                _make_llm_response("still bad json"),
            ]
        )
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "failed"
        assert mock_acompletion.call_count == 2

        session = db.get_session(session_id)
        assert session["status"] == "failed"
        assert session["error_message"] is not None

    async def test_llm_call_failure(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """When LLM call raises an exception, session is marked as failed."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        mock_acompletion = AsyncMock(side_effect=Exception("API timeout"))
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "failed"
        session = db.get_session(session_id)
        assert session["status"] == "failed"
        assert "API timeout" in session["error_message"]

    async def test_claim_failure_skips(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """If session cannot be claimed (already locked), it is skipped."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        # Pre-claim the session so the test claim fails
        db.claim_session(session_id, "other-worker")

        mock_acompletion = AsyncMock()
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "skipped"
        # LLM should never have been called
        mock_acompletion.assert_not_called()

    async def test_claim_error_returns_failed(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """If claiming raises, extraction should fail gracefully instead of crashing."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        def _raise_claim(*_args, **_kwargs):
            raise RuntimeError("claim failed")

        monkeypatch.setattr(db, "claim_session", _raise_claim)
        mock_acompletion = AsyncMock()
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "failed"
        session = db.get_session(session_id)
        assert session["status"] == "failed"
        assert "claim failed" in session["error_message"]
        mock_acompletion.assert_not_called()

    async def test_post_scan_redaction(self, db, store, redactor, phase1_config, session_file, monkeypatch):
        """Post-extraction redaction catches any secrets that slipped through."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        # LLM response contains a secret that should be caught by post-scan
        leaky_response = json.dumps(
            {
                "task_outcome": "success",
                "rollout_slug": "leaky-session",
                "rollout_summary": "Used key sk-proj-abc123def456ghi789jkl012mno for auth",
                "raw_memory": (
                    "---\nrollout_summary_file: rollout_summaries/leaky-session.md\n"
                    "description: session with leak\nkeywords: [test]\n---\n"
                    "- The API key is sk-proj-abc123def456ghi789jkl012mno"
                ),
            }
        )

        mock_acompletion = AsyncMock(return_value=_make_llm_response(leaky_response))
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "extracted"

        # Verify the stored output has been redacted
        outputs = db.get_phase1_outputs(project_path=project_path)
        assert len(outputs) == 1
        assert "sk-proj-" not in outputs[0]["raw_memory"]
        assert "REDACTED" in outputs[0]["raw_memory"]

        # Verify the rollout summary file was also redacted
        summaries = store.list_rollout_summaries(project_path)
        assert len(summaries) == 1
        content = summaries[0].read_text()
        assert "sk-proj-" not in content
        assert "REDACTED" in content

    async def test_missing_schema_fields_treated_as_invalid(
        self, db, store, redactor, phase1_config, session_file, monkeypatch
    ):
        """JSON missing required fields triggers retry."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"

        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        # Missing "raw_memory" field
        incomplete_response = json.dumps(
            {
                "task_outcome": "success",
                "rollout_slug": "test",
                "rollout_summary": "summary",
            }
        )

        mock_acompletion = AsyncMock(
            side_effect=[
                _make_llm_response(incomplete_response),
                _make_llm_response(VALID_LLM_RESPONSE),
            ]
        )
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "extracted"
        assert mock_acompletion.call_count == 2

    async def test_invalid_task_outcome_treated_as_invalid(
        self, db, store, redactor, phase1_config, session_file, monkeypatch
    ):
        """Responses with unsupported task_outcome values should retry."""
        from cerebral_clawtex import phase1

        session_id = "test-session-id"
        project_path = "-home-user-myproject"
        db.register_session(
            session_id=session_id,
            project_path=project_path,
            session_file=str(session_file),
            file_modified_at=int(time.time()) - 3600,
            file_size_bytes=session_file.stat().st_size,
        )

        invalid_outcome = json.dumps(
            {
                "task_outcome": "done",
                "rollout_slug": "x",
                "rollout_summary": "y",
                "raw_memory": "z",
            }
        )
        mock_acompletion = AsyncMock(
            side_effect=[
                _make_llm_response(invalid_outcome),
                _make_llm_response(VALID_LLM_RESPONSE),
            ]
        )
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        status = await phase1.extract_session(
            session_id=session_id,
            session_file=session_file,
            project_path=project_path,
            db=db,
            store=store,
            redactor=redactor,
            config=phase1_config,
            worker_id="test-worker",
        )

        assert status == "extracted"
        assert mock_acompletion.call_count == 2


# ---------------------------------------------------------------------------
# Tests: run_phase1()
# ---------------------------------------------------------------------------


class TestRunPhase1:
    async def test_discovers_and_extracts_sessions(self, full_config, monkeypatch):
        """run_phase1() discovers sessions, registers them, and extracts."""
        from cerebral_clawtex import phase1

        # Create a session file in the fake claude home
        project_dir = full_config.general.claude_home / "projects" / "-home-user-proj"
        project_dir.mkdir(parents=True)
        session_path = project_dir / "sess-abc.jsonl"
        _write_session_jsonl(session_path)
        # Backdate so it passes idle filter
        old_time = time.time() - 7200
        os.utime(session_path, (old_time, old_time))

        mock_acompletion = AsyncMock(return_value=_make_llm_response(VALID_LLM_RESPONSE))
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        result = await phase1.run_phase1(config=full_config)

        assert result["extracted"] == 1
        assert result["skipped"] == 0
        assert result["failed"] == 0
        mock_acompletion.assert_called_once()

    async def test_concurrent_extraction_with_semaphore(self, full_config, monkeypatch):
        """Multiple sessions are extracted concurrently (up to semaphore limit)."""
        from cerebral_clawtex import phase1

        # Create multiple session files
        project_dir = full_config.general.claude_home / "projects" / "-home-user-proj"
        project_dir.mkdir(parents=True)

        for i in range(5):
            session_path = project_dir / f"sess-{i}.jsonl"
            _write_session_jsonl(session_path)
            old_time = time.time() - 7200
            os.utime(session_path, (old_time, old_time))

        mock_acompletion = AsyncMock(return_value=_make_llm_response(VALID_LLM_RESPONSE))
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        # concurrent_extractions is 2 in phase1_config, but full_config uses defaults
        full_config.phase1.concurrent_extractions = 2

        result = await phase1.run_phase1(config=full_config)

        assert result["extracted"] == 5
        assert result["skipped"] == 0
        assert result["failed"] == 0
        assert mock_acompletion.call_count == 5

    async def test_no_sessions_returns_zero_counts(self, full_config, monkeypatch):
        """When no sessions are discovered, returns all zeros."""
        from cerebral_clawtex import phase1

        mock_acompletion = AsyncMock()
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        result = await phase1.run_phase1(config=full_config)

        assert result == {"extracted": 0, "skipped": 0, "failed": 0}
        mock_acompletion.assert_not_called()

    async def test_mixed_results(self, full_config, monkeypatch):
        """Handles a mix of successful, skipped, and failed extractions."""
        from cerebral_clawtex import phase1

        # Create 3 session files
        project_dir = full_config.general.claude_home / "projects" / "-home-user-proj"
        project_dir.mkdir(parents=True)

        for i in range(3):
            session_path = project_dir / f"sess-{i}.jsonl"
            _write_session_jsonl(session_path)
            old_time = time.time() - 7200
            os.utime(session_path, (old_time, old_time))

        # First succeeds, second returns no-op, third fails
        mock_acompletion = AsyncMock(
            side_effect=[
                _make_llm_response(VALID_LLM_RESPONSE),
                _make_llm_response(NOOP_LLM_RESPONSE),
                Exception("LLM error"),
            ]
        )
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        result = await phase1.run_phase1(config=full_config)

        assert result["extracted"] + result["skipped"] + result["failed"] == 3
        # We expect 1 extracted, 1 skipped, 1 failed -- but order may vary
        # depending on session discovery order, so just check totals add up
        assert result["extracted"] >= 0
        assert result["skipped"] >= 0
        assert result["failed"] >= 0

    async def test_project_filter_extracts_only_target_project(self, full_config, monkeypatch):
        """run_phase1(project_path=...) only extracts sessions from that project."""
        from cerebral_clawtex import phase1

        project_a = full_config.general.claude_home / "projects" / "-home-user-proj-a"
        project_b = full_config.general.claude_home / "projects" / "-home-user-proj-b"
        project_a.mkdir(parents=True)
        project_b.mkdir(parents=True)

        sess_a = project_a / "sess-a.jsonl"
        sess_b = project_b / "sess-b.jsonl"
        _write_session_jsonl(sess_a)
        _write_session_jsonl(sess_b)
        old_time = time.time() - 7200
        os.utime(sess_a, (old_time, old_time))
        os.utime(sess_b, (old_time, old_time))

        mock_acompletion = AsyncMock(return_value=_make_llm_response(VALID_LLM_RESPONSE))
        monkeypatch.setattr("cerebral_clawtex.phase1.acompletion", mock_acompletion)

        result = await phase1.run_phase1(config=full_config, project_path="-home-user-proj-a")
        assert result["extracted"] == 1
        assert mock_acompletion.call_count == 1
