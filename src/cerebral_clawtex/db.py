from __future__ import annotations

import sqlite3
import time
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    session_file TEXT NOT NULL,
    file_modified_at INTEGER NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    locked_by TEXT,
    locked_at INTEGER,
    error_message TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS phase1_outputs (
    session_id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    raw_memory TEXT NOT NULL,
    rollout_summary TEXT NOT NULL,
    rollout_slug TEXT NOT NULL,
    task_outcome TEXT NOT NULL,
    token_usage_input INTEGER,
    token_usage_output INTEGER,
    generated_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS consolidation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    phase1_count INTEGER,
    input_watermark INTEGER,
    token_usage_input INTEGER,
    token_usage_output INTEGER,
    error_message TEXT,
    started_at INTEGER NOT NULL,
    completed_at INTEGER
);

CREATE TABLE IF NOT EXISTS consolidation_lock (
    scope TEXT PRIMARY KEY,
    locked_by TEXT,
    locked_at INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status, file_modified_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_path, status);
CREATE INDEX IF NOT EXISTS idx_phase1_project ON phase1_outputs(project_path, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_consolidation_scope ON consolidation_runs(scope, started_at DESC);
"""


class ClawtexDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def __enter__(self) -> ClawtexDB:
        return self

    def __exit__(self, exc_type: type | None, exc_val: BaseException | None, exc_tb: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        row = self.conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
            self.conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def close(self) -> None:
        self.conn.close()

    # --- Sessions ---

    def register_session(
        self,
        session_id: str,
        project_path: str,
        session_file: str,
        file_modified_at: int,
        file_size_bytes: int,
    ) -> None:
        now = int(time.time())
        self.conn.execute(
            """INSERT INTO sessions (session_id, project_path, session_file,
               file_modified_at, file_size_bytes, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
               file_modified_at=excluded.file_modified_at,
               file_size_bytes=excluded.file_size_bytes,
               updated_at=excluded.updated_at""",
            (session_id, project_path, session_file, file_modified_at, file_size_bytes, now, now),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()

    def get_pending_sessions(self, project_path: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        if project_path:
            return self.conn.execute(
                "SELECT * FROM sessions WHERE status = 'pending' AND project_path = ? "
                "ORDER BY file_modified_at DESC LIMIT ?",
                (project_path, limit),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM sessions WHERE status = 'pending' ORDER BY file_modified_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def update_session_status(self, session_id: str, status: str, error_message: str | None = None) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE sessions SET status = ?, error_message = ?, updated_at = ? WHERE session_id = ?",
            (status, error_message, now, session_id),
        )
        self.conn.commit()

    def claim_session(self, session_id: str, worker_id: str, stale_threshold: int = 600) -> bool:
        now = int(time.time())
        stale_cutoff = now - stale_threshold
        cursor = self.conn.execute(
            """UPDATE sessions SET locked_by = ?, locked_at = ?, updated_at = ?
               WHERE session_id = ? AND status = 'pending'
               AND (locked_by IS NULL OR locked_at < ?)""",
            (worker_id, now, now, session_id, stale_cutoff),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def release_session(self, session_id: str, status: str = "pending", error_message: str | None = None) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE sessions SET locked_by = NULL, locked_at = NULL, status = ?, "
            "error_message = ?, updated_at = ? WHERE session_id = ?",
            (status, error_message, now, session_id),
        )
        self.conn.commit()

    # --- Phase 1 Outputs ---

    def store_phase1_output(
        self,
        session_id: str,
        project_path: str,
        raw_memory: str,
        rollout_summary: str,
        rollout_slug: str,
        task_outcome: str,
        token_usage_input: int,
        token_usage_output: int,
    ) -> None:
        now = int(time.time())
        self.conn.execute(
            """INSERT INTO phase1_outputs
               (session_id, project_path, raw_memory, rollout_summary, rollout_slug,
                task_outcome, token_usage_input, token_usage_output, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                project_path,
                raw_memory,
                rollout_summary,
                rollout_slug,
                task_outcome,
                token_usage_input,
                token_usage_output,
                now,
            ),
        )
        self.conn.commit()

    def get_phase1_outputs(
        self,
        project_path: str | None = None,
        since_watermark: int | None = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        conditions = []
        params: list = []
        if project_path:
            conditions.append("project_path = ?")
            params.append(project_path)
        if since_watermark is not None:
            conditions.append("generated_at > ?")
            params.append(since_watermark)
        where = " AND ".join(conditions)
        if where:
            where = "WHERE " + where
        params.append(limit)
        return self.conn.execute(
            f"SELECT * FROM phase1_outputs {where} ORDER BY generated_at DESC LIMIT ?",
            tuple(params),
        ).fetchall()

    # --- Consolidation Lock ---

    def acquire_consolidation_lock(self, scope: str, worker_id: str, stale_threshold: int = 600) -> bool:
        now = int(time.time())
        stale_cutoff = now - stale_threshold
        # Try insert first
        try:
            self.conn.execute(
                "INSERT INTO consolidation_lock (scope, locked_by, locked_at) VALUES (?, ?, ?)",
                (scope, worker_id, now),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            pass
        # Try claim stale lock
        cursor = self.conn.execute(
            "UPDATE consolidation_lock SET locked_by = ?, locked_at = ? WHERE scope = ? AND locked_at < ?",
            (worker_id, now, scope, stale_cutoff),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def release_consolidation_lock(self, scope: str) -> None:
        self.conn.execute("DELETE FROM consolidation_lock WHERE scope = ?", (scope,))
        self.conn.commit()

    # --- Consolidation Runs ---

    def record_consolidation_run(
        self,
        scope: str,
        status: str,
        phase1_count: int,
        input_watermark: int,
        token_usage_input: int,
        token_usage_output: int,
        error_message: str | None = None,
    ) -> int:
        now = int(time.time())
        cursor = self.conn.execute(
            """INSERT INTO consolidation_runs
               (scope, status, phase1_count, input_watermark,
                token_usage_input, token_usage_output, error_message, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                scope,
                status,
                phase1_count,
                input_watermark,
                token_usage_input,
                token_usage_output,
                error_message,
                now,
                now,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_last_watermark(self, scope: str) -> int | None:
        row = self.conn.execute(
            "SELECT input_watermark FROM consolidation_runs "
            "WHERE scope = ? AND status = 'completed' ORDER BY started_at DESC LIMIT 1",
            (scope,),
        ).fetchone()
        return row[0] if row else None
