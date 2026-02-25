# tests/test_storage.py
from pathlib import Path

import pytest

from cerebral_clawtex.storage import MemoryStore, _sanitize_slug


class TestSanitizeSlug:
    def test_empty_string_returns_unnamed(self):
        assert _sanitize_slug("") == "unnamed"

    def test_all_special_chars_returns_unnamed(self):
        assert _sanitize_slug("!!!") == "unnamed"

    def test_dots_are_stripped(self):
        result = _sanitize_slug("some..path")
        assert "." not in result

    def test_normal_slug_preserved(self):
        result = _sanitize_slug("fix-the-bug")
        assert result == "fix-the-bug"


class TestProjectPathTraversal:
    def test_path_traversal_raises_value_error(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        with pytest.raises(ValueError, match="escape data directory"):
            store.project_dir("../../etc")

    def test_prefix_collision_escape_raises_value_error(self, tmp_data_dir: Path):
        store = MemoryStore(tmp_data_dir)
        with pytest.raises(ValueError, match="escape data directory"):
            store.project_dir("../projects_evil")


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
