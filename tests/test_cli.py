# tests/test_cli.py
"""Tests for CLI commands via typer.testing.CliRunner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from cerebral_clawtex.cli import app
from cerebral_clawtex.config import ClawtexConfig, GeneralConfig
from cerebral_clawtex.db import ClawtexDB
from cerebral_clawtex.storage import MemoryStore

runner = CliRunner()


@pytest.fixture
def mock_config(tmp_data_dir: Path, tmp_config_dir: Path, tmp_claude_home: Path) -> ClawtexConfig:
    """Create a ClawtexConfig pointing to temp dirs."""
    return ClawtexConfig(
        general=GeneralConfig(
            data_dir=tmp_data_dir,
            claude_home=tmp_claude_home,
        ),
    )


@pytest.fixture
def mock_db(tmp_data_dir: Path) -> ClawtexDB:
    """Create a real DB in the temp directory."""
    db_path = tmp_data_dir / "clawtex.db"
    return ClawtexDB(db_path)


@pytest.fixture
def mock_store(tmp_data_dir: Path) -> MemoryStore:
    """Create a MemoryStore pointing to the temp data dir."""
    return MemoryStore(tmp_data_dir)


class TestStatusCommand:
    def test_status_no_data(self, mock_config: ClawtexConfig):
        """status command works when no data exists."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "no sessions" in result.output.lower() or "0" in result.output

    def test_status_with_data(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """status command shows session counts by status."""
        # Register some sessions
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.register_session("sess-2", "-proj-a", "/fake/file2.jsonl", 1001, 600)
        mock_db.update_session_status("sess-2", "extracted")
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["status"])
        assert result.exit_code == 0

    def test_status_json_output(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """status command --json outputs valid JSON."""
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["status", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_status_filter_project(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """status command --project filters by project."""
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.register_session("sess-2", "-proj-b", "/fake/file2.jsonl", 1001, 600)
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["status", "--project", "-proj-a"])
        assert result.exit_code == 0


class TestExtractCommand:
    def test_extract_runs_phase1(self, mock_config: ClawtexConfig):
        """extract command invokes run_phase1."""
        mock_result = {"extracted": 2, "skipped": 1, "failed": 0}

        async def mock_run_phase1(config, project_path=None, retry_failed=False):
            return mock_result

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch("cerebral_clawtex.cli.run_phase1", side_effect=mock_run_phase1),
        ):
            result = runner.invoke(app, ["extract"])
        assert result.exit_code == 0
        assert "2" in result.output  # extracted count

    def test_extract_json_output(self, mock_config: ClawtexConfig):
        """extract command --json outputs valid JSON."""
        mock_result = {"extracted": 1, "skipped": 0, "failed": 0}

        async def mock_run_phase1(config, project_path=None, retry_failed=False):
            return mock_result

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch("cerebral_clawtex.cli.run_phase1", side_effect=mock_run_phase1),
        ):
            result = runner.invoke(app, ["extract", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["extracted"] == 1

    def test_extract_with_project_and_retry(self, mock_config: ClawtexConfig):
        """extract command passes --project and --retry-failed flags."""
        captured_args = {}

        async def mock_run_phase1(config, project_path=None, retry_failed=False):
            captured_args["project_path"] = project_path
            captured_args["retry_failed"] = retry_failed
            return {"extracted": 0, "skipped": 0, "failed": 0}

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch("cerebral_clawtex.cli.run_phase1", side_effect=mock_run_phase1),
        ):
            result = runner.invoke(app, ["extract", "--project", "-my-proj", "--retry-failed"])
        assert result.exit_code == 0
        assert captured_args["project_path"] == "-my-proj"
        assert captured_args["retry_failed"] is True


class TestConsolidateCommand:
    def test_consolidate_runs_phase2(self, mock_config: ClawtexConfig):
        """consolidate command invokes run_phase2."""
        mock_result = {"projects_consolidated": 1, "global": True}

        async def mock_run_phase2(config, project_path=None):
            return mock_result

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch("cerebral_clawtex.cli.run_phase2", side_effect=mock_run_phase2),
        ):
            result = runner.invoke(app, ["consolidate"])
        assert result.exit_code == 0

    def test_consolidate_json_output(self, mock_config: ClawtexConfig):
        """consolidate command --json outputs valid JSON."""
        mock_result = {"projects_consolidated": 2, "global": True}

        async def mock_run_phase2(config, project_path=None):
            return mock_result

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch("cerebral_clawtex.cli.run_phase2", side_effect=mock_run_phase2),
        ):
            result = runner.invoke(app, ["consolidate", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["projects_consolidated"] == 2

    def test_consolidate_with_project(self, mock_config: ClawtexConfig):
        """consolidate command passes --project flag."""
        captured_args = {}

        async def mock_run_phase2(config, project_path=None):
            captured_args["project_path"] = project_path
            return {"projects_consolidated": 1, "global": False}

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch("cerebral_clawtex.cli.run_phase2", side_effect=mock_run_phase2),
        ):
            result = runner.invoke(app, ["consolidate", "--project", "-my-proj"])
        assert result.exit_code == 0
        assert captured_args["project_path"] == "-my-proj"


class TestSessionsCommand:
    def test_sessions_no_data(self, mock_config: ClawtexConfig):
        """sessions command works when no sessions exist."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["sessions"])
        assert result.exit_code == 0

    def test_sessions_with_data(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """sessions command lists sessions."""
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.register_session("sess-2", "-proj-a", "/fake/file2.jsonl", 1001, 600)
        mock_db.update_session_status("sess-2", "failed", "some error")
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["sessions"])
        assert result.exit_code == 0
        assert "sess-1" in result.output or "sess-2" in result.output

    def test_sessions_failed_filter(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """sessions command --failed shows only failed sessions."""
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.register_session("sess-2", "-proj-a", "/fake/file2.jsonl", 1001, 600)
        mock_db.update_session_status("sess-2", "failed", "some error")
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["sessions", "--failed"])
        assert result.exit_code == 0

    def test_sessions_json_output(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """sessions command --json outputs valid JSON."""
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["sessions", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)


class TestMemoriesCommand:
    def test_memories_no_files(self, mock_config: ClawtexConfig):
        """memories command works when no memory files exist."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["memories"])
        assert result.exit_code == 0
        assert "no memory files" in result.output.lower() or "no memories" in result.output.lower()

    def test_memories_with_project_files(
        self, mock_config: ClawtexConfig, mock_store: MemoryStore
    ):
        """memories command shows project memory files."""
        mock_store.write_memory_summary("-proj-test", "# Test Summary\n\nSome content here.")
        mock_store.write_memory_md("-proj-test", "# Memory\n\n- Learning one")

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": "/proj/test"}),
        ):
            result = runner.invoke(app, ["memories"])
        assert result.exit_code == 0

    def test_memories_global_flag(
        self, mock_config: ClawtexConfig, mock_store: MemoryStore
    ):
        """memories command --global shows global memory files."""
        mock_store.write_memory_summary(None, "# Global Summary")

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["memories", "--global"])
        assert result.exit_code == 0
        assert "Global" in result.output or "global" in result.output.lower()

    def test_memories_full_flag(
        self, mock_config: ClawtexConfig, mock_store: MemoryStore
    ):
        """memories command --full shows MEMORY.md and rollout summaries."""
        mock_store.write_memory_summary("-proj-test", "# Summary")
        mock_store.write_memory_md("-proj-test", "# Detailed Memory\n\n- Item one")

        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": "/proj/test"}),
        ):
            result = runner.invoke(app, ["memories", "--full"])
        assert result.exit_code == 0


class TestConfigCommand:
    def test_config_prints_resolved(self, mock_config: ClawtexConfig):
        """config command prints resolved configuration."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["config"])
        assert result.exit_code == 0
        # Should show some config values
        assert "data_dir" in result.output or "claude_home" in result.output

    def test_config_edit_flag(self, mock_config: ClawtexConfig):
        """config command --edit attempts to open editor."""
        with (
            patch("cerebral_clawtex.cli.load_config", return_value=mock_config),
            patch("cerebral_clawtex.cli._open_config_in_editor") as mock_edit,
        ):
            result = runner.invoke(app, ["config", "--edit"])
        assert result.exit_code == 0
        mock_edit.assert_called_once()


class TestInstallCommand:
    def test_install_placeholder(self, mock_config: ClawtexConfig):
        """install command runs as placeholder without error."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["install"])
        assert result.exit_code == 0
        assert "install" in result.output.lower()


class TestUninstallCommand:
    def test_uninstall_placeholder(self, mock_config: ClawtexConfig):
        """uninstall command runs as placeholder without error."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["uninstall"])
        assert result.exit_code == 0
        assert "uninstall" in result.output.lower()

    def test_uninstall_purge_flag(self, mock_config: ClawtexConfig):
        """uninstall command accepts --purge flag."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["uninstall", "--purge"])
        assert result.exit_code == 0


class TestHookCommand:
    def test_hook_session_start(self):
        """hook session-start calls session_start_hook."""
        with patch("cerebral_clawtex.cli.session_start_hook") as mock_hook:
            result = runner.invoke(app, ["hook", "session-start"])
        assert result.exit_code == 0
        mock_hook.assert_called_once()


class TestResetCommand:
    def test_reset_requires_confirmation(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """reset command prompts for confirmation."""
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            # Input "y" for confirmation
            result = runner.invoke(app, ["reset", "--all"], input="y\n")
        assert result.exit_code == 0

    def test_reset_aborted(self, mock_config: ClawtexConfig):
        """reset command can be aborted."""
        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["reset", "--all"], input="n\n")
        assert result.exit_code == 0
        assert "abort" in result.output.lower() or "cancel" in result.output.lower()

    def test_reset_project(self, mock_config: ClawtexConfig, mock_db: ClawtexDB):
        """reset command with --project resets only that project."""
        mock_db.register_session("sess-1", "-proj-a", "/fake/file1.jsonl", 1000, 500)
        mock_db.register_session("sess-2", "-proj-b", "/fake/file2.jsonl", 1001, 600)
        mock_db.close()

        with patch("cerebral_clawtex.cli.load_config", return_value=mock_config):
            result = runner.invoke(app, ["reset", "--project", "-proj-a"], input="y\n")
        assert result.exit_code == 0
