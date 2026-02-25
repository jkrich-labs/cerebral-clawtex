# tests/test_config.py
from pathlib import Path

import pytest

from cerebral_clawtex.config import ClawtexConfig, derive_project_name, load_config


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


class TestDeriveProjectName:
    def test_extracts_last_segment(self):
        assert derive_project_name("-home-user-myproject") == "myproject"

    def test_empty_string_returns_empty(self):
        assert derive_project_name("") == ""


class TestLoadFromToml:
    def test_load_overrides_model(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text('[phase1]\nmodel = "openai/gpt-4o-mini"\n')
        cfg = load_config(config_path=config_file)
        assert cfg.phase1.model == "openai/gpt-4o-mini"
        # Other fields keep defaults
        assert cfg.phase2.model == "anthropic/claude-sonnet-4-6-20250514"

    def test_load_expands_tilde(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text('[general]\ndata_dir = "~/my-clawtex-data"\n')
        cfg = load_config(config_path=config_file)
        assert "~" not in str(cfg.general.data_dir)
        assert str(cfg.general.data_dir).endswith("my-clawtex-data")

    def test_load_missing_file_uses_defaults(self, tmp_config_dir: Path):
        cfg = load_config(config_path=tmp_config_dir / "nonexistent.toml")
        assert cfg.phase1.model == "anthropic/claude-haiku-4-5-20251001"

    def test_load_project_include_exclude(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text('[projects]\ninclude = ["pinion"]\nexclude = ["tmp-project"]\n')
        cfg = load_config(config_path=config_file)
        assert cfg.projects.include == ["pinion"]
        assert cfg.projects.exclude == ["tmp-project"]

    def test_load_extra_redaction_patterns(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text('[redaction]\nextra_patterns = ["CORP_SECRET_[A-Z]+"]\n')
        cfg = load_config(config_path=config_file)
        assert len(cfg.redaction.extra_patterns) == 1

    def test_unknown_key_raises(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text('[phase1]\nnonexistent = 1\n')
        with pytest.raises(ValueError, match="Unknown config key"):
            load_config(config_path=config_file)

    def test_invalid_type_raises(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text('[phase1]\nconcurrent_extractions = "many"\n')
        with pytest.raises(TypeError, match="Invalid type"):
            load_config(config_path=config_file)

    def test_invalid_range_raises(self, tmp_config_dir: Path):
        config_file = tmp_config_dir / "config.toml"
        config_file.write_text("[phase1]\nmax_sessions_per_run = 0\n")
        with pytest.raises(ValueError, match="must be > 0"):
            load_config(config_path=config_file)
