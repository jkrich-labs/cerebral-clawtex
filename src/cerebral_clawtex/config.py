# src/cerebral_clawtex/config.py
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
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
    session_lock_stale_seconds: int = 600


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


_POSITIVE_INT_FIELDS = {
    ("phase1", "max_sessions_per_run"),
    ("phase1", "max_session_age_days"),
    ("phase1", "max_input_tokens"),
    ("phase1", "concurrent_extractions"),
    ("phase1", "session_lock_stale_seconds"),
    ("phase2", "max_memories_for_consolidation"),
}

_NON_NEGATIVE_INT_FIELDS = {
    ("phase1", "min_session_idle_hours"),
}

_LIST_STR_FIELDS = {
    ("redaction", "extra_patterns"),
    ("projects", "include"),
    ("projects", "exclude"),
}


def _coerce_and_validate_value(section_name: str, key: str, field_value: object, value: object) -> object:
    if isinstance(field_value, Path):
        if not isinstance(value, str):
            raise TypeError(f"Invalid type for {section_name}.{key}: expected str path, got {type(value).__name__}")
        return _expand_path(value)

    if isinstance(field_value, bool):
        if not isinstance(value, bool):
            raise TypeError(f"Invalid type for {section_name}.{key}: expected bool, got {type(value).__name__}")
        return value

    if isinstance(field_value, int):
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"Invalid type for {section_name}.{key}: expected int, got {type(value).__name__}")
        if (section_name, key) in _POSITIVE_INT_FIELDS and value <= 0:
            raise ValueError(f"{section_name}.{key} must be > 0")
        if (section_name, key) in _NON_NEGATIVE_INT_FIELDS and value < 0:
            raise ValueError(f"{section_name}.{key} must be >= 0")
        return value

    if isinstance(field_value, str):
        if not isinstance(value, str):
            raise TypeError(f"Invalid type for {section_name}.{key}: expected str, got {type(value).__name__}")
        return value

    if isinstance(field_value, list):
        if not isinstance(value, list):
            raise TypeError(f"Invalid type for {section_name}.{key}: expected list, got {type(value).__name__}")
        if (section_name, key) in _LIST_STR_FIELDS and any(not isinstance(v, str) for v in value):
            raise TypeError(f"Invalid type for {section_name}.{key}: expected list[str]")
        return value

    return value


def _merge_section(section_name: str, dataclass_instance: object, overrides: dict) -> None:
    valid_fields = {f.name for f in fields(dataclass_instance)}
    for key, value in overrides.items():
        if key not in valid_fields:
            raise ValueError(f"Unknown config key: {section_name}.{key}")
        field_value = getattr(dataclass_instance, key)
        coerced_value = _coerce_and_validate_value(section_name, key, field_value, value)
        setattr(dataclass_instance, key, coerced_value)


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
        for section_name in raw:
            if section_name not in section_map:
                raise ValueError(f"Unknown config section: {section_name}")
        for section_name, section_obj in section_map.items():
            if section_name in raw:
                section_overrides = raw[section_name]
                if not isinstance(section_overrides, dict):
                    raise TypeError(
                        f"Invalid config section {section_name}: expected table/object, got {type(section_overrides).__name__}"
                    )
                _merge_section(section_name, section_obj, section_overrides)

    # Ensure paths are always expanded
    cfg.general.claude_home = cfg.general.claude_home.expanduser().resolve()
    cfg.general.data_dir = cfg.general.data_dir.expanduser().resolve()

    return cfg
