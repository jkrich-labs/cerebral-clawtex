# src/cerebral_clawtex/storage.py
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path


def _sanitize_slug(slug: str) -> str:
    """Make a string safe for use as a filename.

    Strips all characters except word chars and hyphens.
    Dots are excluded to prevent path traversal via '..' sequences.
    """
    slug = re.sub(r"[^\w\-]", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")[:120]
    return slug or "unnamed"


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically via tmp + rename.

    Files are created with 0o600 permissions (owner-only read/write)
    to protect potentially sensitive memory content.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
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
        result = (self.data_dir / "projects" / project_path).resolve()
        # Guard against path traversal via crafted project_path values
        projects_root = (self.data_dir / "projects").resolve()
        if not str(result).startswith(str(projects_root)):
            raise ValueError(f"Invalid project path would escape data directory: {project_path}")
        return result

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
