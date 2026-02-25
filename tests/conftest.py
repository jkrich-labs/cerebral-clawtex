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
