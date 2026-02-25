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


def derive_project_name(encoded_path: str) -> str:
    """Derive a human-readable project name from an encoded project path.

    The encoded path format is like '-home-user-my-project'. We extract
    the last path component by splitting on the original path separator pattern.
    """
    if not encoded_path:
        return encoded_path
    # The encoded path was created by replacing '/' with '-', so we need
    # to find the last real path component. Split by '-' and find the last
    # non-empty segment that would have been a directory name.
    # Since paths like /home/user/my-project become -home-user-my-project,
    # the safest approach is to take the original dir name from the end.
    # Remove the leading '-' (which was the leading '/'), then take
    # everything after the last '/' equivalent.
    parts = encoded_path.lstrip("-").split("-")
    # For paths like 'home-user-my-project', the project dir was the last
    # component after the last '/' in the original path. However, we can't
    # perfectly reconstruct this since hyphens in dir names are ambiguous.
    # Use the last segment as a reasonable approximation.
    return parts[-1] if parts else encoded_path


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
