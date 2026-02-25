# tests/test_hooks.py
"""Tests for the SessionStart hook integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from cerebral_clawtex.config import ClawtexConfig, GeneralConfig
from cerebral_clawtex.storage import MemoryStore


class TestSessionStartHook:
    """Tests for session_start_hook()."""

    def test_valid_json_with_memory_files(self, tmp_data_dir: Path, capsys, monkeypatch):
        """When project and global memory summaries exist, output valid JSON with additional_context."""
        store = MemoryStore(tmp_data_dir)
        project_path = "-home-user-myproject"

        # Write project and global memory summaries
        store.write_memory_summary(project_path, "# Project Memory\n\nSome project learnings.")
        store.write_memory_summary(None, "# Global Memory\n\nSome global learnings.")

        # Create a config pointing to our tmp dir
        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        # Set CLAUDE_PROJECT_DIR env var
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/user/myproject")

        # Mock load_config and _spawn_background_extraction
        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch("cerebral_clawtex.hooks._resolve_project_path", return_value=project_path),
            patch("cerebral_clawtex.hooks._spawn_background_extraction"),
        ):
            from cerebral_clawtex.hooks import session_start_hook

            session_start_hook()

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert "additional_context" in output
        assert "## Cerebral Clawtex Memory" in output["additional_context"]
        assert "Project Memory" in output["additional_context"]
        assert "Global Memory" in output["additional_context"]

    def test_no_memory_files_outputs_empty_context_json(self, tmp_data_dir: Path, capsys, monkeypatch):
        """When no memory files exist, output valid JSON with empty additional_context."""
        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/user/myproject")

        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch("cerebral_clawtex.hooks._resolve_project_path", return_value="-home-user-myproject"),
            patch("cerebral_clawtex.hooks._spawn_background_extraction") as mock_spawn,
        ):
            from cerebral_clawtex.hooks import session_start_hook

            session_start_hook()

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["additional_context"] == ""
        # But background extraction is still spawned
        mock_spawn.assert_called_once()

    def test_only_project_memory(self, tmp_data_dir: Path, capsys, monkeypatch):
        """When only project memory exists (no global), include just the project summary."""
        store = MemoryStore(tmp_data_dir)
        project_path = "-home-user-myproject"
        store.write_memory_summary(project_path, "# Project Only\n\nJust project learnings.")

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/user/myproject")

        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch("cerebral_clawtex.hooks._resolve_project_path", return_value=project_path),
            patch("cerebral_clawtex.hooks._spawn_background_extraction"),
        ):
            from cerebral_clawtex.hooks import session_start_hook

            session_start_hook()

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert "additional_context" in output
        assert "Project Only" in output["additional_context"]
        assert "Global Memory" not in output["additional_context"]

    def test_only_global_memory(self, tmp_data_dir: Path, capsys, monkeypatch):
        """When only global memory exists (no project), include just the global summary."""
        store = MemoryStore(tmp_data_dir)
        store.write_memory_summary(None, "# Global Only\n\nJust global learnings.")

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        # No project dir set
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch("cerebral_clawtex.hooks._resolve_project_path", return_value=""),
            patch("cerebral_clawtex.hooks._spawn_background_extraction"),
        ):
            from cerebral_clawtex.hooks import session_start_hook

            session_start_hook()

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        assert "additional_context" in output
        assert "Global Only" in output["additional_context"]

    def test_content_truncation(self, tmp_data_dir: Path, capsys, monkeypatch):
        """Combined content exceeding ~20000 chars is truncated."""
        store = MemoryStore(tmp_data_dir)
        project_path = "-home-user-myproject"

        # Write a very large project memory summary (25000 chars)
        large_content = "x" * 25000
        store.write_memory_summary(project_path, large_content)

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/user/myproject")

        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch("cerebral_clawtex.hooks._resolve_project_path", return_value=project_path),
            patch("cerebral_clawtex.hooks._spawn_background_extraction"),
        ):
            from cerebral_clawtex.hooks import session_start_hook

            session_start_hook()

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        context = output["additional_context"]
        # The context should be truncated to around 20000 chars + truncation marker
        assert len(context) <= 20100  # 20000 + truncation marker length
        assert "[... truncated ...]" in context

    def test_navigation_instructions_included(self, tmp_data_dir: Path, capsys, monkeypatch):
        """Navigation instructions for MEMORY.md, rollout summaries, and skills are included."""
        store = MemoryStore(tmp_data_dir)
        project_path = "-home-user-myproject"
        store.write_memory_summary(project_path, "# Project Memory\n\nSome learnings.")

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/user/myproject")

        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch("cerebral_clawtex.hooks._resolve_project_path", return_value=project_path),
            patch("cerebral_clawtex.hooks._spawn_background_extraction"),
        ):
            from cerebral_clawtex.hooks import session_start_hook

            session_start_hook()

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())

        context = output["additional_context"]
        # Navigation instructions should reference how to access detailed memory
        assert "MEMORY.md" in context
        assert "rollout_summaries" in context or "rollout" in context.lower()
        assert "skill" in context.lower()

    def test_background_extraction_spawning(self, tmp_data_dir: Path, capsys, monkeypatch):
        """Background extraction is spawned via _spawn_background_extraction."""
        store = MemoryStore(tmp_data_dir)
        project_path = "-home-user-myproject"
        store.write_memory_summary(project_path, "# Project Memory\n\nSome learnings.")

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/user/myproject")

        with (
            patch("cerebral_clawtex.hooks.load_config", return_value=config),
            patch("cerebral_clawtex.hooks._resolve_project_path", return_value=project_path),
            patch("cerebral_clawtex.hooks._spawn_background_extraction") as mock_spawn,
        ):
            from cerebral_clawtex.hooks import session_start_hook

            session_start_hook()

        mock_spawn.assert_called_once_with(config)


class TestResolveProjectPath:
    """Tests for _resolve_project_path()."""

    def test_resolves_from_env_var(self, tmp_data_dir: Path):
        """Converts a project dir to the encoded project path used in storage."""
        from cerebral_clawtex.hooks import _resolve_project_path

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))
        result = _resolve_project_path("/home/user/myproject", config)
        # Claude encodes paths by replacing / with -
        assert result == "-home-user-myproject"

    def test_empty_project_dir(self, tmp_data_dir: Path):
        """Empty project dir returns empty string."""
        from cerebral_clawtex.hooks import _resolve_project_path

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))
        result = _resolve_project_path("", config)
        assert result == ""

    def test_normalizes_windows_backslashes(self, tmp_data_dir: Path):
        from cerebral_clawtex.hooks import _resolve_project_path

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))
        result = _resolve_project_path(r"C:\Users\me\repo", config)
        assert result == "C:-Users-me-repo"


class TestBuildNavigationInstructions:
    """Tests for _build_navigation_instructions()."""

    def test_includes_memory_md_reference(self, tmp_data_dir: Path):
        """Navigation instructions mention MEMORY.md for detailed learnings."""
        from cerebral_clawtex.hooks import _build_navigation_instructions

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))
        nav = _build_navigation_instructions("-home-user-myproject", config)
        assert "MEMORY.md" in nav

    def test_includes_rollout_reference(self, tmp_data_dir: Path):
        """Navigation instructions mention rollout summaries."""
        from cerebral_clawtex.hooks import _build_navigation_instructions

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))
        nav = _build_navigation_instructions("-home-user-myproject", config)
        assert "rollout" in nav.lower()

    def test_includes_skills_reference(self, tmp_data_dir: Path):
        """Navigation instructions mention skills."""
        from cerebral_clawtex.hooks import _build_navigation_instructions

        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))
        nav = _build_navigation_instructions("-home-user-myproject", config)
        assert "skill" in nav.lower()


class TestSpawnBackgroundExtraction:
    """Tests for _spawn_background_extraction()."""

    def test_spawn_uses_subprocess_popen(self, tmp_data_dir: Path, monkeypatch):
        """Background extraction uses subprocess.Popen to spawn a detached process."""
        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        popen_called = False
        popen_kwargs: dict = {}

        class MockPopen:
            def __init__(self, cmd, **kwargs):
                nonlocal popen_called, popen_kwargs
                popen_called = True
                popen_kwargs = kwargs

        monkeypatch.setattr("cerebral_clawtex.hooks.subprocess.Popen", MockPopen)

        from cerebral_clawtex.hooks import _spawn_background_extraction

        _spawn_background_extraction(config)

        assert popen_called
        import subprocess

        assert popen_kwargs.get("stdin") == subprocess.DEVNULL
        assert popen_kwargs.get("stdout") == subprocess.DEVNULL
        assert popen_kwargs.get("stderr") == subprocess.DEVNULL

    def test_spawn_handles_os_error(self, tmp_data_dir: Path, monkeypatch):
        """Background extraction handles OSError gracefully."""
        config = ClawtexConfig(general=GeneralConfig(data_dir=tmp_data_dir))

        def mock_popen(*args, **kwargs):
            raise OSError("spawn failed")

        monkeypatch.setattr("cerebral_clawtex.hooks.subprocess.Popen", mock_popen)

        from cerebral_clawtex.hooks import _spawn_background_extraction

        # Should not raise
        _spawn_background_extraction(config)
