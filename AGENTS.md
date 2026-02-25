# Repository Guidelines

## Project Structure & Module Organization
Code follows a `src/` layout:
- `src/cerebral_clawtex/`: core package and CLI (`cli.py`), extraction/consolidation phases (`phase1.py`, `phase2.py`), storage/DB/config modules, and hook integration.
- `src/cerebral_clawtex/prompts/`: prompt templates used by phase pipelines.
- `tests/`: pytest suite (`test_*.py`) covering CLI, hooks, config, DB, storage, and end-to-end flows.
- `docs/plans/`: implementation/design plan artifacts.

## Build, Test, and Development Commands
- `uv sync --extra dev`: install runtime + dev dependencies.
- `uv run pytest`: run full test suite.
- `uv run pytest -m e2e`: run end-to-end tests only.
- `uv run pytest -k cli -v`: run a focused subset while iterating.
- `uv run ruff check src tests`: lint for style/issues.
- `uv run ruff format src tests`: apply formatting.
- `uv run clawtex --help`: inspect CLI commands locally.

## Coding Style & Naming Conventions
- Python 3.12+, 4-space indentation, and explicit type hints for public functions.
- Ruff is the style gate (`line-length = 120` in `pyproject.toml`).
- Modules/files: `snake_case.py`; classes: `PascalCase`; functions/variables: `snake_case`.
- Keep CLI behaviors in `cli.py`, domain logic in phase/storage/config modules, and avoid cross-module duplication.

## Testing Guidelines
- Frameworks: `pytest`, `pytest-asyncio`, optional `pytest-cov`.
- Naming is enforced by config: files `test_*.py`, functions `test_*`.
- Mark full-pipeline tests with `@pytest.mark.e2e`.
- Prefer fast unit tests with mocked external calls; add/adjust e2e tests only for full workflow behavior.

## Commit & Pull Request Guidelines
- Follow Conventional Commit prefixes seen in history: `feat:`, `fix:`, `test:`, `chore:` (automation commits may use `swarm:`).
- Keep commit scope narrow and messages actionable, e.g. `fix: handle missing session metadata in phase2`.
- PRs should include:
  - concise problem/solution summary,
  - linked issue/task,
  - test evidence (`uv run pytest ...` output),
  - CLI output snippets for user-visible command changes.

## Security & Configuration Tips
- Do not commit local config, tokens, or generated user data.
- Default config path: `~/.config/cerebral-clawtex/config.toml`.
- Validate hook/install flows with tests before shipping changes touching `install`/`uninstall` behavior.
