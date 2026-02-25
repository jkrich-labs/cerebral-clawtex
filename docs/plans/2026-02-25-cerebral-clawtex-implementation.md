# Cerebral Clawtex Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Claude Code memory plugin that automatically extracts learnings from past sessions and consolidates them into a progressive-disclosure memory hierarchy.

**Architecture:** Two-phase LLM pipeline (Haiku 4.5 extraction, Sonnet 4.6 consolidation) triggered by SessionStart hook or CLI. SQLite for job tracking with row-level optimistic locking. Filesystem storage with markdown files in progressive-disclosure hierarchy.

**Tech Stack:** Python 3.12, uv, typer, LiteLLM, SQLite3, rich, tomli/tomllib

**Repo:** `~/dev/repos/cerebral-clawtex/`

---

## Task 0: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/cerebral_clawtex/__init__.py`
- Create: `src/cerebral_clawtex/cli.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore`
- Create: `.python-version`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "cerebral-clawtex"
version = "0.1.0"
description = "Claude Code memory plugin — automatic session learning extraction and consolidation"
requires-python = ">=3.12"
dependencies = [
    "typer>=0.15",
    "rich>=13.0",
    "litellm>=1.60",
    "tomli>=2.0; python_version < '3.11'",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.5",
]

[project.scripts]
clawtex = "cerebral_clawtex.cli:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = "-v --tb=short"

[tool.ruff]
target-version = "py312"
line-length = 120
```

**Step 2: Create package init**

```python
# src/cerebral_clawtex/__init__.py
__version__ = "0.1.0"
```

**Step 3: Create minimal CLI**

```python
# src/cerebral_clawtex/cli.py
import typer

app = typer.Typer(name="clawtex", help="Cerebral Clawtex — Claude Code memory plugin")


@app.command()
def status():
    """Show extraction status summary."""
    typer.echo("Cerebral Clawtex v0.1.0 — no data yet")


if __name__ == "__main__":
    app()
```

**Step 4: Create test conftest**

```python
# tests/conftest.py
from pathlib import Path
import pytest


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Temporary data directory for tests."""
    data_dir = tmp_path / "clawtex-data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def tmp_config_dir(tmp_path: Path) -> Path:
    """Temporary config directory for tests."""
    config_dir = tmp_path / "clawtex-config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def tmp_claude_home(tmp_path: Path) -> Path:
    """Temporary Claude home directory for tests."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()
    (claude_home / "projects").mkdir()
    return claude_home
```

**Step 5: Create .gitignore**

```
__pycache__/
*.pyc
.venv/
*.egg-info/
dist/
build/
.ruff_cache/
.pytest_cache/
.coverage
uv.lock
```

**Step 6: Create .python-version**

```
3.12
```

**Step 7: Install dependencies and verify CLI**

Run: `cd ~/dev/repos/cerebral-clawtex && uv sync --extra dev`
Expected: Dependencies resolve and install

Run: `cd ~/dev/repos/cerebral-clawtex && uv run clawtex status`
Expected: `Cerebral Clawtex v0.1.0 — no data yet`

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest`
Expected: 0 tests collected (no test files yet), exits 0

**Step 8: Commit**

```bash
git add -A
git commit -m "feat: project scaffolding with uv, typer CLI, and pytest"
```

---

## Task 1: Configuration Module

**Files:**
- Create: `src/cerebral_clawtex/config.py`
- Create: `tests/test_config.py`

**Step 1: Write failing tests**

```python
# tests/test_config.py
from pathlib import Path

from cerebral_clawtex.config import ClawtexConfig, load_config


class TestDefaultConfig:
    def test_default_phase1_model(self):
        cfg = ClawtexConfig()
        assert cfg.phase1.model == "anthropic/claude-haiku-4-5-20251001"

    def test_default_phase2_model(self):
        cfg = ClawtexConfig()
        assert cfg.phase2.model == "anthropic/claude-sonnet-4-6-20250514"

    def test_default_data_dir(self):
        cfg = ClawtexConfig()
        assert "cerebral-clawtex" in str(cfg.general.data_dir)

    def test_default_claude_home(self):
        cfg = ClawtexConfig()
        assert str(cfg.general.claude_home).endswith(".claude")

    def test_default_max_sessions_per_run(self):
        cfg = ClawtexConfig()
        assert cfg.phase1.max_sessions_per_run == 20

    def test_default_concurrent_extractions(self):
        cfg = ClawtexConfig()
        assert cfg.phase1.concurrent_extractions == 4

    def test_default_redaction_placeholder(self):
        cfg = ClawtexConfig()
        assert cfg.redaction.placeholder == "[REDACTED]"


class TestLoadFromToml:
    def test_load_overrides_model(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text(
            '[phase1]\nmodel = "openai/gpt-4o-mini"\n'
        )
        cfg = load_config(config_path=config_file)
        assert cfg.phase1.model == "openai/gpt-4o-mini"
        # Other fields keep defaults
        assert cfg.phase2.model == "anthropic/claude-sonnet-4-6-20250514"

    def test_load_expands_tilde(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text(
            '[general]\ndata_dir = "~/my-clawtex-data"\n'
        )
        cfg = load_config(config_path=config_file)
        assert "~" not in str(cfg.general.data_dir)
        assert str(cfg.general.data_dir).endswith("my-clawtex-data")

    def test_load_missing_file_uses_defaults(self, tmp_config_dir: Path):
        cfg = load_config(config_path=tmp_config_dir / "nonexistent.toml")
        assert cfg.phase1.model == "anthropic/claude-haiku-4-5-20251001"

    def test_load_project_include_exclude(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text(
            '[projects]\ninclude = ["pinion"]\nexclude = ["tmp-project"]\n'
        )
        cfg = load_config(config_path=config_file)
        assert cfg.projects.include == ["pinion"]
        assert cfg.projects.exclude == ["tmp-project"]

    def test_load_extra_redaction_patterns(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text(
            '[redaction]\nextra_patterns = ["CORP_SECRET_[A-Z]+"]\n'
        )
        cfg = load_config(config_path=config_file)
        assert len(cfg.redaction.extra_patterns) == 1
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_config.py -v`
Expected: FAIL — `cannot import name 'ClawtexConfig'`

**Step 3: Implement config module**

```python
# src/cerebral_clawtex/config.py
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GeneralConfig:
    claude_home: Path = field(default_factory=lambda: Path.home() / ".claude")
    data_dir: Path = field(default_factory=lambda: Path.home() / ".local" / "share" / "cerebral-clawtex")


@dataclass
class Phase1Config:
    model: str = "anthropic/claude-haiku-4-5-20251001"
    max_sessions_per_run: int = 20
    max_session_age_days: int = 30
    min_session_idle_hours: int = 1
    max_input_tokens: int = 80_000
    concurrent_extractions: int = 4


@dataclass
class Phase2Config:
    model: str = "anthropic/claude-sonnet-4-6-20250514"
    max_memories_for_consolidation: int = 200
    run_after_phase1: bool = True


@dataclass
class RedactionConfig:
    extra_patterns: list[str] = field(default_factory=list)
    placeholder: str = "[REDACTED]"


@dataclass
class ProjectsConfig:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass
class ClawtexConfig:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    phase1: Phase1Config = field(default_factory=Phase1Config)
    phase2: Phase2Config = field(default_factory=Phase2Config)
    redaction: RedactionConfig = field(default_factory=RedactionConfig)
    projects: ProjectsConfig = field(default_factory=ProjectsConfig)


def _expand_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _merge_section(dataclass_instance: object, overrides: dict) -> None:
    for key, value in overrides.items():
        if hasattr(dataclass_instance, key):
            field_value = getattr(dataclass_instance, key)
            if isinstance(field_value, Path):
                setattr(dataclass_instance, key, _expand_path(value))
            else:
                setattr(dataclass_instance, key, value)


def load_config(config_path: Path | None = None) -> ClawtexConfig:
    """Load config from TOML file, falling back to defaults for missing values."""
    cfg = ClawtexConfig()

    if config_path is None:
        config_path = Path.home() / ".config" / "cerebral-clawtex" / "config.toml"

    if config_path.exists():
        with open(config_path, "rb") as f:
            raw = tomllib.load(f)

        section_map = {
            "general": cfg.general,
            "phase1": cfg.phase1,
            "phase2": cfg.phase2,
            "redaction": cfg.redaction,
            "projects": cfg.projects,
        }
        for section_name, section_obj in section_map.items():
            if section_name in raw:
                _merge_section(section_obj, raw[section_name])

    # Ensure paths are always expanded
    cfg.general.claude_home = cfg.general.claude_home.expanduser().resolve()
    cfg.general.data_dir = cfg.general.data_dir.expanduser().resolve()

    return cfg
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_config.py -v`
Expected: All tests PASS

**Step 5: Lint and format**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run ruff check . && uv run ruff format .`
Expected: Clean

**Step 6: Commit**

```bash
git add src/cerebral_clawtex/config.py tests/test_config.py
git commit -m "feat: configuration module with TOML loading and defaults"
```

---

## Task 2: Database Module

**Files:**
- Create: `src/cerebral_clawtex/db.py`
- Create: `tests/test_db.py`

**Step 1: Write failing tests**

```python
# tests/test_db.py
import time
from pathlib import Path

from cerebral_clawtex.db import ClawtexDB


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
        db.store_phase1_output("s2", "-proj", "mem2", "sum2", "slug2", "success", 0, 0)
        # Get outputs after the first one
        first = db.get_phase1_outputs(project_path="-proj")
        watermark = first[0]["generated_at"]
        newer = db.get_phase1_outputs(project_path="-proj", since_watermark=watermark)
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
        db.record_consolidation_run("-proj", "completed", 3, 2000, 0, 0)
        watermark = db.get_last_watermark("-proj")
        assert watermark == 2000
        db.close()
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_db.py -v`
Expected: FAIL — `cannot import name 'ClawtexDB'`

**Step 3: Implement database module**

```python
# src/cerebral_clawtex/db.py
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
        return self.conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()

    def get_pending_sessions(
        self, project_path: str | None = None, limit: int = 100
    ) -> list[sqlite3.Row]:
        if project_path:
            return self.conn.execute(
                "SELECT * FROM sessions WHERE status = 'pending' AND project_path = ? "
                "ORDER BY file_modified_at DESC LIMIT ?",
                (project_path, limit),
            ).fetchall()
        return self.conn.execute(
            "SELECT * FROM sessions WHERE status = 'pending' "
            "ORDER BY file_modified_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    def update_session_status(
        self, session_id: str, status: str, error_message: str | None = None
    ) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE sessions SET status = ?, error_message = ?, updated_at = ? WHERE session_id = ?",
            (status, error_message, now, session_id),
        )
        self.conn.commit()

    def claim_session(
        self, session_id: str, worker_id: str, stale_threshold: int = 600
    ) -> bool:
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

    def release_session(
        self, session_id: str, status: str = "pending", error_message: str | None = None
    ) -> None:
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
            (session_id, project_path, raw_memory, rollout_summary, rollout_slug,
             task_outcome, token_usage_input, token_usage_output, now),
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

    def acquire_consolidation_lock(
        self, scope: str, worker_id: str, stale_threshold: int = 600
    ) -> bool:
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
            "UPDATE consolidation_lock SET locked_by = ?, locked_at = ? "
            "WHERE scope = ? AND locked_at < ?",
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
            (scope, status, phase1_count, input_watermark,
             token_usage_input, token_usage_output, error_message, now, now),
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
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_db.py -v`
Expected: All tests PASS

**Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add src/cerebral_clawtex/db.py tests/test_db.py
git commit -m "feat: SQLite database with optimistic locking and consolidation tracking"
```

---

## Task 3: Secret Redaction Module

**Files:**
- Create: `src/cerebral_clawtex/redact.py`
- Create: `tests/test_redact.py`

**Step 1: Write failing tests**

```python
# tests/test_redact.py
from cerebral_clawtex.redact import Redactor


class TestAPIKeyRedaction:
    def test_openai_key(self):
        r = Redactor()
        text = 'OPENAI_API_KEY="sk-proj-abc123def456ghi789jkl012mno"'
        result = r.redact(text)
        assert "sk-proj-" not in result
        assert "[REDACTED:api_key]" in result

    def test_aws_key(self):
        r = Redactor()
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLE"
        result = r.redact(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "[REDACTED:api_key]" in result

    def test_github_token(self):
        r = Redactor()
        text = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = r.redact(text)
        assert "ghp_" not in result
        assert "[REDACTED:api_key]" in result

    def test_anthropic_key(self):
        r = Redactor()
        text = 'api_key = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz"'
        result = r.redact(text)
        assert "sk-ant-" not in result
        assert "[REDACTED:api_key]" in result


class TestTokenRedaction:
    def test_bearer_token(self):
        r = Redactor()
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
        result = r.redact(text)
        assert "eyJhbG" not in result
        assert "[REDACTED:token]" in result


class TestConnectionStringRedaction:
    def test_postgres_url(self):
        r = Redactor()
        text = 'DATABASE_URL="postgres://admin:secretpass@db.example.com:5432/mydb"'
        result = r.redact(text)
        assert "secretpass" not in result
        assert "[REDACTED:connection_string]" in result

    def test_redis_url(self):
        r = Redactor()
        text = "REDIS_URL=redis://default:mypassword@redis.host:6379/0"
        result = r.redact(text)
        assert "mypassword" not in result
        assert "[REDACTED:connection_string]" in result


class TestPrivateKeyRedaction:
    def test_rsa_private_key(self):
        r = Redactor()
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
        result = r.redact(text)
        assert "MIIEpAIBAAKCAQEA" not in result
        assert "[REDACTED:private_key]" in result


class TestGenericSecretRedaction:
    def test_secret_key_assignment(self):
        r = Redactor()
        text = 'DJANGO_SECRET_KEY="super-secret-value-12345678"'
        result = r.redact(text)
        assert "super-secret-value" not in result
        assert "[REDACTED:generic_secret]" in result

    def test_password_assignment(self):
        r = Redactor()
        text = 'password = "MyP@ssw0rd123!"'
        result = r.redact(text)
        assert "MyP@ssw0rd" not in result
        assert "[REDACTED:password]" in result


class TestFalsePositives:
    def test_normal_code_not_redacted(self):
        r = Redactor()
        text = "def calculate_token_count(text: str) -> int:"
        result = r.redact(text)
        assert result == text

    def test_short_values_not_redacted(self):
        r = Redactor()
        text = 'secret = "short"'
        result = r.redact(text)
        # "short" is only 5 chars, below the 8-char threshold
        assert result == text

    def test_import_statements_not_redacted(self):
        r = Redactor()
        text = "from secret_module import secret_function"
        result = r.redact(text)
        assert result == text


class TestCustomPatterns:
    def test_extra_pattern(self):
        r = Redactor(extra_patterns=["CORP_TOKEN_[A-Za-z0-9]+"])
        text = "Using CORP_TOKEN_abc123xyz for auth"
        result = r.redact(text)
        assert "CORP_TOKEN_abc123xyz" not in result
        assert "[REDACTED:custom]" in result


class TestPlaceholder:
    def test_custom_placeholder(self):
        r = Redactor(placeholder="***")
        text = "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        result = r.redact(text)
        assert "***" in result
        assert "ghp_" not in result
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_redact.py -v`
Expected: FAIL — `cannot import name 'Redactor'`

**Step 3: Implement redaction module**

```python
# src/cerebral_clawtex/redact.py
from __future__ import annotations

import re


_BUILTIN_PATTERNS: list[tuple[str, str]] = [
    # API keys
    (r"sk-(?:proj-|ant-api\d{2}-)?[a-zA-Z0-9_-]{20,}", "api_key"),
    (r"AKIA[0-9A-Z]{16}", "api_key"),
    (r"ghp_[a-zA-Z0-9]{36}", "api_key"),
    (r"gho_[a-zA-Z0-9]{36}", "api_key"),
    (r"github_pat_[a-zA-Z0-9_]{22,}", "api_key"),
    (r"glpat-[a-zA-Z0-9_-]{20,}", "api_key"),
    (r"xox[bpors]-[a-zA-Z0-9-]{10,}", "api_key"),
    # Bearer tokens
    (r"Bearer\s+[a-zA-Z0-9._-]{20,}", "token"),
    # Connection strings
    (r"(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?|amqp)://[^\s\"']+@[^\s\"']+", "connection_string"),
    # Private keys
    (r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----", "private_key"),
    # Passwords in config-like contexts
    (r"""(?i)password\s*[=:]\s*["']?([^\s"']{8,})["']?""", "password"),
    # Generic secret/key assignments
    (r"""(?i)(?:secret|_key|_token|api_key)\s*[=:]\s*["']?([^\s"']{8,})["']?""", "generic_secret"),
]


class Redactor:
    def __init__(
        self,
        extra_patterns: list[str] | None = None,
        placeholder: str = "[REDACTED]",
    ):
        self.placeholder = placeholder
        self._compiled: list[tuple[re.Pattern, str]] = []
        for pattern, category in _BUILTIN_PATTERNS:
            self._compiled.append((re.compile(pattern), category))
        for pattern in extra_patterns or []:
            self._compiled.append((re.compile(pattern), "custom"))

    def _replacement(self, category: str) -> str:
        if self.placeholder == "[REDACTED]":
            return f"[REDACTED:{category}]"
        return self.placeholder

    def redact(self, text: str) -> str:
        result = text
        for pattern, category in self._compiled:
            replacement = self._replacement(category)
            if pattern.groups > 0:
                # Pattern has capture group — redact only the captured portion
                def _sub(m: re.Match, cat: str = category) -> str:
                    full = m.group(0)
                    captured = m.group(1)
                    return full.replace(captured, self._replacement(cat))
                result = pattern.sub(_sub, result)
            else:
                result = pattern.sub(replacement, result)
        return result
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_redact.py -v`
Expected: All tests PASS

**Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add src/cerebral_clawtex/redact.py tests/test_redact.py
git commit -m "feat: regex-based secret redaction with extensible patterns"
```

---

## Task 4: Session Discovery and Parsing

**Files:**
- Create: `src/cerebral_clawtex/sessions.py`
- Create: `tests/test_sessions.py`
- Create: `tests/fixtures/` (sample JSONL files)

**Step 1: Create test fixtures**

Create `tests/fixtures/sample_session.jsonl` with representative records covering user messages, assistant responses, tool calls, tool results, progress events, and system records. Use the exact JSONL schema documented above. The fixture should be ~20 lines representing a short but complete session.

Create `tests/fixtures/empty_session.jsonl` — a file with only system/progress records and no meaningful conversation.

**Step 2: Write failing tests**

```python
# tests/test_sessions.py
import json
import time
from pathlib import Path

from cerebral_clawtex.sessions import (
    discover_sessions,
    parse_session,
    truncate_content,
)


def _write_session(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _make_user_record(content: str, uuid: str = "u1", parent: str | None = None) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:00:00Z",
        "isSidechain": False,
        "message": {"role": "user", "content": content},
    }


def _make_assistant_record(
    text: str, uuid: str = "a1", parent: str = "u1", tool_use: dict | None = None,
) -> dict:
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if tool_use:
        content.append({"type": "tool_use", **tool_use})
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:01:00Z",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-6",
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }


def _make_tool_result_record(
    tool_use_id: str, content: str, uuid: str = "tr1", parent: str = "a1",
) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:02:00Z",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": content},
            ],
        },
    }


def _make_progress_record(uuid: str = "p1") -> dict:
    return {
        "type": "progress",
        "uuid": uuid,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:01:30Z",
        "data": {"type": "bash_progress", "output": "running..."},
    }


class TestDiscoverSessions:
    def test_finds_jsonl_files(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-home-user-project"
        proj.mkdir(parents=True)
        (proj / "session-1.jsonl").write_text("{}\n")
        (proj / "session-2.jsonl").write_text("{}\n")
        (proj / "not-a-session.txt").write_text("nope")
        sessions = discover_sessions(tmp_claude_home)
        assert len(sessions) == 2

    def test_extracts_project_path(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-home-user-myproject"
        proj.mkdir(parents=True)
        (proj / "abc.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home)
        assert sessions[0]["project_path"] == "-home-user-myproject"
        assert sessions[0]["session_id"] == "abc"

    def test_skips_subagent_sessions(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-proj"
        proj.mkdir(parents=True)
        (proj / "main.jsonl").write_text("{}\n")
        subagent_dir = proj / "main" / "subagents"
        subagent_dir.mkdir(parents=True)
        (subagent_dir / "agent-1.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "main"

    def test_filters_by_age(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-proj"
        proj.mkdir(parents=True)
        recent = proj / "recent.jsonl"
        recent.write_text("{}\n")
        old = proj / "old.jsonl"
        old.write_text("{}\n")
        # Backdate the old file
        import os
        old_time = time.time() - (60 * 60 * 24 * 45)  # 45 days ago
        os.utime(old, (old_time, old_time))
        sessions = discover_sessions(tmp_claude_home, max_age_days=30)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "recent"

    def test_filters_by_idle_hours(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-proj"
        proj.mkdir(parents=True)
        active = proj / "active.jsonl"
        active.write_text("{}\n")
        # File was just modified — still "active"
        sessions = discover_sessions(tmp_claude_home, min_idle_hours=1)
        assert len(sessions) == 0

    def test_project_include_filter(self, tmp_claude_home: Path):
        for name in ["-proj-a", "-proj-b"]:
            p = tmp_claude_home / "projects" / name
            p.mkdir(parents=True)
            (p / "s1.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home, include_projects=["proj-a"])
        assert len(sessions) == 1
        assert "proj-a" in sessions[0]["project_path"]

    def test_project_exclude_filter(self, tmp_claude_home: Path):
        for name in ["-proj-a", "-proj-b"]:
            p = tmp_claude_home / "projects" / name
            p.mkdir(parents=True)
            (p / "s1.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home, exclude_projects=["proj-b"])
        assert len(sessions) == 1
        assert "proj-a" in sessions[0]["project_path"]


class TestParseSession:
    def test_extracts_user_messages(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(f, [_make_user_record("Hello Claude")])
        messages = parse_session(f)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Hello Claude" in messages[0]["content"]

    def test_extracts_assistant_text(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(f, [
            _make_user_record("Hi"),
            _make_assistant_record("Hello! How can I help?"),
        ])
        messages = parse_session(f)
        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert "Hello! How can I help?" in messages[1]["content"]

    def test_extracts_tool_calls(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(f, [
            _make_user_record("List files"),
            _make_assistant_record(
                "Let me check.",
                tool_use={"id": "t1", "name": "Bash", "input": {"command": "ls"}},
            ),
            _make_tool_result_record("t1", "file1.py\nfile2.py"),
        ])
        messages = parse_session(f)
        assert len(messages) == 3
        assert "Bash" in messages[1]["content"]
        assert "file1.py" in messages[2]["content"]

    def test_drops_progress_records(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(f, [
            _make_user_record("Hi"),
            _make_progress_record(),
            _make_assistant_record("Hello"),
        ])
        messages = parse_session(f)
        assert len(messages) == 2  # progress dropped

    def test_handles_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        messages = parse_session(f)
        assert messages == []

    def test_handles_corrupt_line(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text('{"type":"user","message":{"role":"user","content":"ok"}}\nnot-json\n')
        messages = parse_session(f)
        assert len(messages) == 1  # corrupt line skipped


class TestTruncateContent:
    def test_short_content_unchanged(self):
        messages = [{"role": "user", "content": "short"}]
        result = truncate_content(messages, max_tokens=80000)
        assert len(result) == 1

    def test_long_content_truncated(self):
        # Create messages that exceed token budget
        messages = [
            {"role": "user", "content": "start " * 100},
            *[{"role": "assistant", "content": "middle " * 1000} for _ in range(20)],
            {"role": "user", "content": "end " * 100},
        ]
        result = truncate_content(messages, max_tokens=1000)
        # Should keep start and end, trim middle
        assert len(result) < len(messages)
        assert "start" in result[0]["content"]
        assert "end" in result[-1]["content"]
```

**Step 3: Implement session module**

```python
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

        for jsonl_file in project_dir.glob("*.jsonl"):
            # Skip files in subdirectories (subagent sessions)
            if jsonl_file.parent != project_dir:
                continue

            stat = jsonl_file.stat()
            age = now - stat.st_mtime

            if age > max_age_seconds:
                continue
            if age < min_idle_seconds:
                continue

            results.append({
                "session_id": jsonl_file.stem,
                "project_path": project_path,
                "session_file": str(jsonl_file),
                "file_modified_at": int(stat.st_mtime),
                "file_size_bytes": stat.st_size,
            })

    return results


def _extract_content_from_message(message: dict) -> str:
    """Extract readable text from a message's content field."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content

    parts = []
    for block in content:
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
                    b.get("text", "") for b in result_content if b.get("type") == "text"
                )
            parts.append(f"[Tool Result] {result_content}")
        elif block_type == "thinking":
            parts.append(f"[Thinking] {block.get('thinking', '')}")
    return "\n".join(parts)


def parse_session(session_file: Path) -> list[dict]:
    """Parse a session JSONL file into a list of conversation messages."""
    messages = []

    try:
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

        record_type = record.get("type", "")

        if record_type == "user" and "message" in record:
            msg = record["message"]
            content = _extract_content_from_message(msg)
            if content.strip():
                messages.append({
                    "role": "user",
                    "content": content,
                    "timestamp": record.get("timestamp", ""),
                })

        elif record_type == "assistant" and "message" in record:
            msg = record["message"]
            content = _extract_content_from_message(msg)
            if content.strip():
                messages.append({
                    "role": "assistant",
                    "content": content,
                    "timestamp": record.get("timestamp", ""),
                })

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

    # Reserve 30% for start, 30% for end, drop middle
    start_budget = int(max_tokens * 0.3)
    end_budget = int(max_tokens * 0.3)

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

    return start_messages + [
        {"role": "system", "content": f"[... {len(messages) - len(start_messages) - len(end_messages)} messages truncated ...]"}
    ] + end_messages
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_sessions.py -v`
Expected: All tests PASS

**Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add src/cerebral_clawtex/sessions.py tests/test_sessions.py
git commit -m "feat: session discovery with JSONL parsing and truncation"
```

---

## Task 5: Storage Module

**Files:**
- Create: `src/cerebral_clawtex/storage.py`
- Create: `tests/test_storage.py`

**Step 1: Write failing tests**

```python
# tests/test_storage.py
from pathlib import Path

from cerebral_clawtex.storage import MemoryStore


class TestProjectPaths:
    def test_project_dir(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        path = store.project_dir("-home-user-pinion")
        assert path == tmp_data_dir / "projects" / "-home-user-pinion"

    def test_global_dir(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        assert store.global_dir == tmp_data_dir / "global"


class TestWriteRolloutSummary:
    def test_writes_file(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_rollout_summary(
            project_path="-proj",
            slug="fix-the-bug",
            content="## Session: Fix the Bug\n\nDetails here.",
        )
        path = tmp_data_dir / "projects" / "-proj" / "rollout_summaries" / "fix-the-bug.md"
        assert path.exists()
        assert "Fix the Bug" in path.read_text()

    def test_sanitizes_slug(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_rollout_summary("-proj", "bad/slug with spaces!", "content")
        files = list((tmp_data_dir / "projects" / "-proj" / "rollout_summaries").iterdir())
        assert len(files) == 1
        assert "/" not in files[0].name
        assert " " not in files[0].name


class TestWriteMemoryFiles:
    def test_write_memory_summary(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_memory_summary("-proj", "# Summary\n\nUser profile here.")
        path = tmp_data_dir / "projects" / "-proj" / "memory_summary.md"
        assert path.exists()
        assert "User profile" in path.read_text()

    def test_write_memory_md(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_memory_md("-proj", "# Memory\n\n- Lesson one")
        path = tmp_data_dir / "projects" / "-proj" / "MEMORY.md"
        assert path.exists()

    def test_write_global_memory_summary(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_memory_summary(None, "# Global Summary")
        path = tmp_data_dir / "global" / "memory_summary.md"
        assert path.exists()

    def test_write_global_memory_md(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_memory_md(None, "# Global Memory")
        path = tmp_data_dir / "global" / "MEMORY.md"
        assert path.exists()


class TestWriteSkill:
    def test_writes_skill_file(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_skill("-proj", "django-migration", "---\nname: django-migration\n---\n## Procedure")
        path = tmp_data_dir / "projects" / "-proj" / "skills" / "django-migration" / "SKILL.md"
        assert path.exists()
        assert "Procedure" in path.read_text()


class TestReadMemoryFiles:
    def test_read_existing(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_memory_summary("-proj", "content here")
        result = store.read_memory_summary("-proj")
        assert result == "content here"

    def test_read_missing_returns_none(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        result = store.read_memory_summary("-nonexistent")
        assert result is None


class TestAtomicWrite:
    def test_no_partial_writes(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        store.write_memory_summary("-proj", "first version")
        # Verify no .tmp files left behind
        proj_dir = tmp_data_dir / "projects" / "-proj"
        tmp_files = list(proj_dir.glob("*.tmp*"))
        assert len(tmp_files) == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_storage.py -v`
Expected: FAIL — `cannot import name 'MemoryStore'`

**Step 3: Implement storage module**

```python
# src/cerebral_clawtex/storage.py
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def _sanitize_slug(slug: str) -> str:
    """Make a string safe for use as a filename."""
    slug = re.sub(r"[^\w\-.]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    return slug.strip("-")[:120]


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically via tmp + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class MemoryStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    @property
    def global_dir(self) -> Path:
        return self.data_dir / "global"

    def project_dir(self, project_path: str) -> Path:
        return self.data_dir / "projects" / project_path

    def _scope_dir(self, project_path: str | None) -> Path:
        if project_path is None:
            return self.global_dir
        return self.project_dir(project_path)

    # --- Rollout Summaries ---

    def write_rollout_summary(self, project_path: str, slug: str, content: str) -> Path:
        safe_slug = _sanitize_slug(slug)
        path = self.project_dir(project_path) / "rollout_summaries" / f"{safe_slug}.md"
        _atomic_write(path, content)
        return path

    # --- Memory Files ---

    def write_memory_summary(self, project_path: str | None, content: str) -> Path:
        path = self._scope_dir(project_path) / "memory_summary.md"
        _atomic_write(path, content)
        return path

    def write_memory_md(self, project_path: str | None, content: str) -> Path:
        path = self._scope_dir(project_path) / "MEMORY.md"
        _atomic_write(path, content)
        return path

    def read_memory_summary(self, project_path: str | None) -> str | None:
        path = self._scope_dir(project_path) / "memory_summary.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def read_memory_md(self, project_path: str | None) -> str | None:
        path = self._scope_dir(project_path) / "MEMORY.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    # --- Skills ---

    def write_skill(self, project_path: str, skill_name: str, content: str) -> Path:
        safe_name = _sanitize_slug(skill_name)
        path = self.project_dir(project_path) / "skills" / safe_name / "SKILL.md"
        _atomic_write(path, content)
        return path

    # --- Listing ---

    def list_rollout_summaries(self, project_path: str) -> list[Path]:
        d = self.project_dir(project_path) / "rollout_summaries"
        if not d.exists():
            return []
        return sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    def list_skills(self, project_path: str) -> list[Path]:
        d = self.project_dir(project_path) / "skills"
        if not d.exists():
            return []
        return sorted(p / "SKILL.md" for p in d.iterdir() if (p / "SKILL.md").exists())

    def list_projects(self) -> list[str]:
        projects_dir = self.data_dir / "projects"
        if not projects_dir.exists():
            return []
        return sorted(p.name for p in projects_dir.iterdir() if p.is_dir())
```

**Step 4: Run tests to verify they pass**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_storage.py -v`
Expected: All tests PASS

**Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add src/cerebral_clawtex/storage.py tests/test_storage.py
git commit -m "feat: filesystem storage with atomic writes and progressive disclosure hierarchy"
```

---

## Task 6: Phase 1 Prompts

**Files:**
- Create: `src/cerebral_clawtex/prompts/phase1_system.md`
- Create: `src/cerebral_clawtex/prompts/phase1_user.md`

**Step 1: Write Phase 1 system prompt**

The system prompt must include: role definition, no-op gate, task outcome classification rules, extraction guidelines (what to extract, what not to), secret handling instructions, and strict JSON output schema with examples. See design doc Section "Prompt Design — Phase 1 System Prompt" for requirements.

**Step 2: Write Phase 1 user prompt template**

Jinja2-style template with placeholders: `{{ project_name }}`, `{{ project_path }}`, `{{ session_id }}`, `{{ session_date }}`, `{{ redacted_session_content }}`.

**Step 3: Commit**

```bash
git add src/cerebral_clawtex/prompts/
git commit -m "feat: Phase 1 extraction prompt templates"
```

---

## Task 7: Phase 1 Extraction Pipeline

**Files:**
- Create: `src/cerebral_clawtex/phase1.py`
- Create: `tests/test_phase1.py`

**Step 1: Write failing tests**

Tests use a mock LiteLLM response (monkeypatch `litellm.completion`). Test the full pipeline: session parsing → redaction → LLM call → JSON validation → DB write → rollout summary file creation. Test error cases: invalid JSON response, empty/no-op response, LLM failure.

**Step 2: Implement Phase 1**

```python
# src/cerebral_clawtex/phase1.py — key function signature:
async def extract_session(
    session_id: str,
    session_file: Path,
    project_path: str,
    db: ClawtexDB,
    store: MemoryStore,
    redactor: Redactor,
    config: Phase1Config,
    worker_id: str,
) -> str:  # returns status: "extracted" | "skipped" | "failed"
```

The function:
1. Claims the session via `db.claim_session()`
2. Parses the JSONL via `parse_session()`
3. Redacts via `redactor.redact()`
4. Truncates via `truncate_content()`
5. Builds the prompt from templates (read via `importlib.resources`)
6. Calls `litellm.completion()` with `response_format={"type": "json_object"}`
7. Validates the JSON schema
8. Runs post-scan redaction on output
9. Writes rollout summary via `store.write_rollout_summary()`
10. Stores in DB via `db.store_phase1_output()`
11. Releases session via `db.release_session()`

```python
async def run_phase1(
    config: ClawtexConfig,
    project_path: str | None = None,
    retry_failed: bool = False,
) -> dict:  # returns {"extracted": N, "skipped": N, "failed": N}
```

Top-level orchestrator: discovers sessions, registers in DB, claims and extracts with `asyncio.Semaphore(config.phase1.concurrent_extractions)`.

**Step 3: Run tests**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_phase1.py -v`
Expected: All PASS

**Step 4: Lint and commit**

```bash
git add src/cerebral_clawtex/phase1.py tests/test_phase1.py
git commit -m "feat: Phase 1 extraction pipeline with LiteLLM and async concurrency"
```

---

## Task 8: Phase 2 Prompts

**Files:**
- Create: `src/cerebral_clawtex/prompts/phase2_system.md`
- Create: `src/cerebral_clawtex/prompts/phase2_user.md`
- Create: `src/cerebral_clawtex/prompts/phase2_global_system.md`
- Create: `src/cerebral_clawtex/prompts/phase2_global_user.md`

**Step 1: Write Phase 2 system prompt**

Must include: role definition, INIT vs INCREMENTAL mode instructions, `memory_summary.md` format spec (user profile max 300 words, general tips max 80 items, routing index, total under 5000 tokens), `MEMORY.md` format spec (topic clusters with YAML headers, keyword tags, deduplication/pruning rules), skills creation trigger (3+ occurrences), JSON output schema.

**Step 2: Write Phase 2 user prompt template**

Template with: `{{ mode }}` (INIT/INCREMENTAL), `{{ project_name }}`, existing files (conditional), Phase 1 outputs list.

**Step 3: Write global consolidation prompts**

Separate system/user prompts that instruct: extract only cross-project transferable patterns, not project-specific details.

**Step 4: Commit**

```bash
git add src/cerebral_clawtex/prompts/
git commit -m "feat: Phase 2 consolidation and global prompt templates"
```

---

## Task 9: Phase 2 Consolidation Pipeline

**Files:**
- Create: `src/cerebral_clawtex/phase2.py`
- Create: `tests/test_phase2.py`

**Step 1: Write failing tests**

Test both INIT and INCREMENTAL modes. Mock LiteLLM. Verify:
- `memory_summary.md` is written
- `MEMORY.md` is written
- Skills are created when returned by model
- Consolidation run is recorded in DB
- Watermark advances
- Consolidation lock is acquired and released
- Global consolidation merges project summaries

**Step 2: Implement Phase 2**

```python
# src/cerebral_clawtex/phase2.py — key function signatures:
async def consolidate_project(
    project_path: str,
    db: ClawtexDB,
    store: MemoryStore,
    config: ClawtexConfig,
    worker_id: str,
) -> bool:  # returns True if consolidation ran

async def consolidate_global(
    db: ClawtexDB,
    store: MemoryStore,
    config: ClawtexConfig,
    worker_id: str,
) -> bool:

async def run_phase2(
    config: ClawtexConfig,
    project_path: str | None = None,
) -> dict:  # returns {"projects_consolidated": N, "global": bool}
```

Flow: acquire lock → detect mode → load inputs → build prompt → call Sonnet → parse JSON → write files → record run → release lock.

**Step 3: Run tests**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_phase2.py -v`
Expected: All PASS

**Step 4: Lint and commit**

```bash
git add src/cerebral_clawtex/phase2.py tests/test_phase2.py
git commit -m "feat: Phase 2 consolidation with per-project and global scopes"
```

---

## Task 10: Hook Integration

**Files:**
- Create: `src/cerebral_clawtex/hooks.py`
- Create: `tests/test_hooks.py`

**Step 1: Write failing tests**

Test `session_start_hook()`:
- Returns valid JSON with `additional_context` when memory files exist
- Returns empty/minimal JSON when no memory files exist
- Truncates combined content to ~5000 tokens
- Includes navigation instructions in output

**Step 2: Implement hooks**

```python
# src/cerebral_clawtex/hooks.py
import json
import os
import sys

from cerebral_clawtex.config import load_config
from cerebral_clawtex.storage import MemoryStore


def session_start_hook() -> None:
    """Entry point for SessionStart hook. Prints JSON to stdout."""
    config = load_config()
    store = MemoryStore(config.general.data_dir)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
    project_path = _resolve_project_path(project_dir, config)

    context_parts = []

    # Project memory
    if project_path:
        project_summary = store.read_memory_summary(project_path)
        if project_summary:
            project_name = project_path.split("-")[-1] or project_path
            context_parts.append(f"### Project Memory ({project_name})\n\n{project_summary}")

    # Global memory
    global_summary = store.read_memory_summary(None)
    if global_summary:
        context_parts.append(f"### Global Memory\n\n{global_summary}")

    if not context_parts:
        # No memories yet — just trigger background extraction
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
```

The `_spawn_background_extraction` function uses `os.fork()` + `os.setsid()` to detach a child process that runs Phase 1.

**Step 3: Run tests**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_hooks.py -v`
Expected: All PASS

**Step 4: Lint and commit**

```bash
git add src/cerebral_clawtex/hooks.py tests/test_hooks.py
git commit -m "feat: SessionStart hook with context injection and background extraction"
```

---

## Task 11: CLI Commands

**Files:**
- Modify: `src/cerebral_clawtex/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write failing tests**

Test all CLI commands via `typer.testing.CliRunner`. Test: `status`, `extract`, `consolidate`, `sessions`, `memories`, `config`, `install`, `uninstall`, `reset`.

**Step 2: Implement full CLI**

Wire all commands to the underlying modules. Each command:
- Loads config
- Creates DB connection
- Creates MemoryStore
- Calls the relevant function
- Formats output with `rich`

Key commands:

```python
@app.command()
def extract(
    project: str | None = None,
    retry_failed: bool = False,
    json_output: bool = typer.Option(False, "--json"),
):
    """Run Phase 1 extraction on pending sessions."""

@app.command()
def consolidate(
    project: str | None = None,
    json_output: bool = typer.Option(False, "--json"),
):
    """Run Phase 2 consolidation."""

@app.command()
def status(
    project: str | None = None,
    json_output: bool = typer.Option(False, "--json"),
):
    """Show extraction status summary."""

@app.command()
def sessions(
    failed: bool = False,
    json_output: bool = typer.Option(False, "--json"),
):
    """List recent sessions with extraction status."""

@app.command()
def memories(
    full: bool = False,
    global_: bool = typer.Option(False, "--global"),
):
    """Print memory files for current project."""

@app.command()
def install():
    """Register SessionStart hook in Claude Code settings."""

@app.command()
def uninstall(purge: bool = False):
    """Remove hooks. --purge also removes all data."""

@app.command()
def reset(
    project: str | None = None,
    all_: bool = typer.Option(False, "--all"),
):
    """Clear data and re-extract from scratch."""

@app.command()
def config(edit: bool = False):
    """Print resolved config or open in editor."""
```

**Step 3: Run tests**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_cli.py -v`
Expected: All PASS

**Step 4: Lint and commit**

```bash
git add src/cerebral_clawtex/cli.py tests/test_cli.py
git commit -m "feat: full CLI with extract, consolidate, status, install, and memory commands"
```

---

## Task 12: Install/Uninstall Hook Registration

**Files:**
- Modify: `src/cerebral_clawtex/cli.py` (install/uninstall commands)

**Step 1: Write failing tests for install/uninstall**

Test that `clawtex install`:
- Creates config dir if missing
- Creates data dir if missing
- Initializes SQLite schema
- Merges SessionStart hook into `~/.claude/settings.json` (mock the path)
- Preserves existing hooks

Test that `clawtex uninstall`:
- Removes only the clawtex hook entry
- Preserves other hooks
- `--purge` removes data directory

**Step 2: Implement**

The install logic reads `settings.json`, parses JSON, adds the hook entry under `hooks.SessionStart`, writes back. Must handle: file doesn't exist yet, file exists but no `hooks` key, file exists with other hooks already.

**Step 3: Run tests**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_cli.py -v -k install`
Expected: All PASS

**Step 4: Lint and commit**

```bash
git add src/cerebral_clawtex/cli.py tests/test_cli.py
git commit -m "feat: install/uninstall with Claude Code settings.json hook registration"
```

---

## Task 13: End-to-End Test

**Files:**
- Create: `tests/test_e2e.py`

**Step 1: Write E2E test (gated behind --e2e marker)**

```python
# tests/test_e2e.py
import pytest

pytestmark = pytest.mark.e2e


class TestEndToEnd:
    def test_full_pipeline(self, tmp_path):
        """Seeds a fake session, runs Phase 1 + Phase 2, validates output."""
        # 1. Create fake Claude home with a session JSONL
        # 2. Create config pointing to tmp dirs
        # 3. Run Phase 1 extraction (real Haiku call)
        # 4. Assert: session marked extracted, rollout summary file exists
        # 5. Run Phase 2 consolidation (real Sonnet call)
        # 6. Assert: memory_summary.md exists, MEMORY.md exists
        # 7. Assert: no secrets in any output file
        # 8. Run hook and verify JSON output contains memory content
```

Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = ["e2e: end-to-end tests requiring real LLM API calls"]
```

**Step 2: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end test with real LLM calls (gated behind --e2e marker)"
```

---

## Task 14: Final Integration and Polish

**Step 1: Run full test suite**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run pytest -v --ignore=tests/test_e2e.py`
Expected: All PASS

**Step 2: Run linting**

Run: `cd ~/dev/repos/cerebral-clawtex && uv run ruff check . && uv run ruff format --check .`
Expected: Clean

**Step 3: Test the CLI manually**

```bash
clawtex config
clawtex install
clawtex status
clawtex extract
clawtex consolidate
clawtex memories
clawtex status
```

**Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final integration polish"
```
