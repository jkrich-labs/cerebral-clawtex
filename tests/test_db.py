import time
from pathlib import Path

import pytest

from cerebral_clawtex.db import ClawtexDB


class TestContextManager:
    def test_with_statement_provides_usable_db(self, tmp_data_dir: Path):
        db_path = tmp_data_dir / "ctx.db"
        with ClawtexDB(db_path) as db:
            db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)
            row = db.get_session("s1")
            assert row is not None
            assert row["session_id"] == "s1"

    def test_connection_closed_after_exit(self, tmp_data_dir: Path):
        db_path = tmp_data_dir / "ctx.db"
        with ClawtexDB(db_path) as db:
            # db should be usable inside the context
            db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)

        # After exiting the context, the connection should be closed
        import sqlite3

        with pytest.raises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")


class TestSchemaCreation:
    def test_creates_tables(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {row[0] for row in tables}
        assert "sessions" in table_names
        assert "phase1_outputs" in table_names
        assert "consolidation_runs" in table_names
        assert "consolidation_lock" in table_names
        assert "schema_version" in table_names
        db.close()

    def test_schema_version_is_set(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        row = db.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == 1
        db.close()


class TestSessionTracking:
    def test_register_session(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session(
            session_id="abc-123",
            project_path="-home-user-project",
            session_file="/home/user/.claude/projects/-home-user-project/abc-123.jsonl",
            file_modified_at=1000000,
            file_size_bytes=5000,
        )
        row = db.get_session("abc-123")
        assert row is not None
        assert row["status"] == "pending"
        assert row["project_path"] == "-home-user-project"
        db.close()

    def test_register_duplicate_is_upsert(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("abc-123", "-proj", "/path.jsonl", 1000, 5000)
        db.register_session("abc-123", "-proj", "/path.jsonl", 2000, 6000)
        row = db.get_session("abc-123")
        assert row["file_modified_at"] == 2000
        assert row["file_size_bytes"] == 6000
        db.close()

    def test_get_pending_sessions(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj", "/p1.jsonl", 1000, 5000)
        db.register_session("s2", "-proj", "/p2.jsonl", 2000, 5000)
        db.update_session_status("s1", "extracted")
        pending = db.get_pending_sessions()
        assert len(pending) == 1
        assert pending[0]["session_id"] == "s2"
        db.close()

    def test_get_pending_sessions_by_project(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj-a", "/p1.jsonl", 1000, 5000)
        db.register_session("s2", "-proj-b", "/p2.jsonl", 2000, 5000)
        pending = db.get_pending_sessions(project_path="-proj-a")
        assert len(pending) == 1
        assert pending[0]["session_id"] == "s1"
        db.close()


class TestOptimisticLocking:
    def test_claim_session(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)
        claimed = db.claim_session("s1", worker_id="w1")
        assert claimed is True
        row = db.get_session("s1")
        assert row["locked_by"] == "w1"
        db.close()

    def test_claim_already_locked_fails(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)
        db.claim_session("s1", worker_id="w1")
        claimed = db.claim_session("s1", worker_id="w2")
        assert claimed is False
        db.close()

    def test_claim_stale_lock_succeeds(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)
        db.claim_session("s1", worker_id="w1")
        # Manually backdate the lock to simulate staleness
        db.execute(
            "UPDATE sessions SET locked_at = ? WHERE session_id = ?",
            (int(time.time()) - 700, "s1"),
        )
        db.conn.commit()
        claimed = db.claim_session("s1", worker_id="w2", stale_threshold=600)
        assert claimed is True
        row = db.get_session("s1")
        assert row["locked_by"] == "w2"
        db.close()

    def test_release_session(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)
        db.claim_session("s1", worker_id="w1")
        db.release_session("s1", status="extracted")
        row = db.get_session("s1")
        assert row["status"] == "extracted"
        assert row["locked_by"] is None
        db.close()


class TestPhase1Outputs:
    def test_store_and_retrieve(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)
        db.store_phase1_output(
            session_id="s1",
            project_path="-proj",
            raw_memory="- lesson one",
            rollout_summary="## Summary",
            rollout_slug="fix-the-thing",
            task_outcome="success",
            token_usage_input=500,
            token_usage_output=200,
        )
        outputs = db.get_phase1_outputs(project_path="-proj")
        assert len(outputs) == 1
        assert outputs[0]["rollout_slug"] == "fix-the-thing"
        assert outputs[0]["task_outcome"] == "success"
        db.close()

    def test_get_unprocessed_since_watermark(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.register_session("s1", "-proj", "/p.jsonl", 1000, 5000)
        db.register_session("s2", "-proj", "/p2.jsonl", 2000, 5000)
        db.store_phase1_output("s1", "-proj", "mem1", "sum1", "slug1", "success", 0, 0)
        # Backdate s1's generated_at so s2 gets a strictly later timestamp
        db.execute("UPDATE phase1_outputs SET generated_at = 1000 WHERE session_id = 's1'")
        db.conn.commit()
        db.store_phase1_output("s2", "-proj", "mem2", "sum2", "slug2", "success", 0, 0)
        # Get outputs after the first one (watermark = 1000)
        newer = db.get_phase1_outputs(project_path="-proj", since_watermark=1000)
        assert len(newer) == 1
        assert newer[0]["session_id"] == "s2"
        db.close()


class TestConsolidationLock:
    def test_acquire_lock(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        acquired = db.acquire_consolidation_lock("-proj", worker_id="w1")
        assert acquired is True
        db.close()

    def test_acquire_already_locked_fails(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.acquire_consolidation_lock("-proj", worker_id="w1")
        acquired = db.acquire_consolidation_lock("-proj", worker_id="w2")
        assert acquired is False
        db.close()

    def test_release_consolidation_lock(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.acquire_consolidation_lock("-proj", worker_id="w1")
        db.release_consolidation_lock("-proj")
        acquired = db.acquire_consolidation_lock("-proj", worker_id="w2")
        assert acquired is True
        db.close()


class TestConsolidationRuns:
    def test_record_run(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        run_id = db.record_consolidation_run(
            scope="-proj",
            status="completed",
            phase1_count=5,
            input_watermark=1000,
            token_usage_input=2000,
            token_usage_output=800,
        )
        assert run_id > 0
        db.close()

    def test_get_last_watermark(self, tmp_data_dir: Path):
        db = ClawtexDB(tmp_data_dir / "test.db")
        db.record_consolidation_run("-proj", "completed", 5, 1000, 0, 0)
        # Backdate the first run so the second one has a strictly later started_at
        db.execute("UPDATE consolidation_runs SET started_at = 100 WHERE input_watermark = 1000")
        db.conn.commit()
        db.record_consolidation_run("-proj", "completed", 3, 2000, 0, 0)
        watermark = db.get_last_watermark("-proj")
        assert watermark == 2000
        db.close()
