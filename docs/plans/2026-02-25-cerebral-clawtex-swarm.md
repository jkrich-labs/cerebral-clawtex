# Swarm Plan: Cerebral Clawtex Implementation

> **For Claude:** REQUIRED SUB-SKILL: Use swarm-skills:swarm-executor to implement this plan.

**Generated**: 2026-02-25
**Goal**: Build a Claude Code memory plugin that automatically extracts learnings from past sessions and consolidates them into a progressive-disclosure memory hierarchy.
**Architecture**: Two-phase LLM pipeline (Haiku 4.5 extraction, Sonnet 4.6 consolidation) triggered by SessionStart hook or CLI. SQLite for job tracking with row-level optimistic locking. Filesystem storage with markdown files in progressive-disclosure hierarchy.
**Tech Stack**: Python 3.12, uv, typer, LiteLLM, SQLite3, rich, tomli/tomllib

---

## Overview

Cerebral Clawtex is a Claude Code plugin that auto-distills reusable knowledge from every coding session. It uses a two-phase LLM pipeline: Phase 1 (Haiku) extracts per-session learnings, Phase 2 (Sonnet) consolidates them into a searchable memory hierarchy. The system integrates via Claude Code's SessionStart hook for automatic context injection.

The source implementation plan with **complete, verbatim code** for every module is at:
`docs/plans/2026-02-25-cerebral-clawtex-implementation.md`

Each task in this swarm plan references a corresponding task in that document. Agents MUST read the referenced task section for complete code listings.

## Prerequisites

- Python 3.12 installed
- `uv` package manager installed
- Git configured

## Dependency Graph

```
T0 ──┬── T1 ──┐
     ├── T2 ──┤
     ├── T3 ──┤
     ├── T4 ──┼── T7 ──┬── T9 ──── T10 ──── T11 ──── T12 ── T13 ── T14
     ├── T5 ──┤         │
     ├── T6 ──┘         │
     └── T8 ────────────┘
          (T1,T2,T5 also → T9)
          (T1 also → T10)
          (T1,T2,T5,T10 also → T11)
```

## Tasks

### T0: Project Scaffolding
- **depends_on**: []
- **files**:
  - Create: `pyproject.toml`
  - Create: `src/cerebral_clawtex/__init__.py`
  - Create: `src/cerebral_clawtex/cli.py`
  - Create: `src/cerebral_clawtex/prompts/__init__.py`
  - Create: `tests/__init__.py`
  - Create: `tests/conftest.py`
  - Create: `.gitignore`
  - Create: `.python-version`
- **description**: Set up the project skeleton. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 0: Project Scaffolding" for exact file contents. Create all files exactly as specified. **Additionally**: create `src/cerebral_clawtex/prompts/__init__.py` as an empty file (makes prompts a package for T6/T8), and add `asyncio_mode = "auto"` to `[tool.pytest.ini_options]` in `pyproject.toml` (required for async tests in T7/T9). Then run `uv sync --extra dev` to install dependencies, `uv run clawtex status` to verify CLI works (should print "Cerebral Clawtex v0.1.0 — no data yet"), and `uv run pytest` to verify test infrastructure (0 tests collected, exits 0). Commit with message "feat: project scaffolding with uv, typer CLI, and pytest".
- **acceptance_criteria**:
  - `pyproject.toml` exists with correct project metadata, dependencies (typer>=0.15, rich>=13.0, litellm>=1.60, tomli>=2.0), dev deps (pytest, ruff), tool configs, and `asyncio_mode = "auto"`
  - `src/cerebral_clawtex/prompts/__init__.py` exists (empty file)
  - `uv sync --extra dev` succeeds
  - `uv run clawtex status` prints version message
  - `uv run pytest` exits 0
  - All files committed to git
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv sync --extra dev && uv run clawtex status && uv run pytest`
- **status**: completed
- **log**: ["Created all scaffold files: pyproject.toml (with build-system, dependencies, asyncio_mode=auto), src/cerebral_clawtex/__init__.py, cli.py (with Typer callback for subcommand support), prompts/__init__.py (empty), tests/__init__.py, tests/conftest.py, .gitignore, .python-version. Added hatchling build-system to enable entry point installation. Verified: uv sync --extra dev succeeds, clawtex status prints expected message, pytest collects 0 tests (exit 5, standard for no tests)."]
- **files_edited**: ["pyproject.toml", "src/cerebral_clawtex/__init__.py", "src/cerebral_clawtex/cli.py", "src/cerebral_clawtex/prompts/__init__.py", "tests/__init__.py", "tests/conftest.py", ".gitignore", ".python-version"]

---

### T1: Configuration Module
- **depends_on**: [T0]
- **files**:
  - Create: `src/cerebral_clawtex/config.py`
  - Create: `tests/test_config.py`
- **description**: Implement the TOML-based configuration system. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 1: Configuration Module" for exact code. TDD approach: write failing tests first, then implement. The module uses Python dataclasses for config sections (GeneralConfig, Phase1Config, Phase2Config, RedactionConfig, ProjectsConfig, ClawtexConfig) and a `load_config()` function that reads TOML via `tomllib` (stdlib), falls back to defaults for missing values, and expands `~` in paths. Default models: `anthropic/claude-haiku-4-5-20251001` (phase1), `anthropic/claude-sonnet-4-6-20250514` (phase2). Default data_dir: `~/.local/share/cerebral-clawtex`. Tests cover: default values, TOML override, tilde expansion, missing file fallback, project include/exclude, extra redaction patterns. Commit with "feat: configuration module with TOML loading and defaults".
- **acceptance_criteria**:
  - `ClawtexConfig` dataclass with all sections
  - `load_config()` loads from TOML with defaults fallback
  - All 12 tests pass in `tests/test_config.py`
  - `ruff check` and `ruff format` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_config.py -v && uv run ruff check src/cerebral_clawtex/config.py tests/test_config.py`
- **status**: completed
- **log**: ["TDD approach: wrote 12 tests first (7 default config tests, 5 TOML loading tests), verified import failure, then implemented config.py with 6 dataclasses (GeneralConfig, Phase1Config, Phase2Config, RedactionConfig, ProjectsConfig, ClawtexConfig) and load_config() with TOML loading via tomllib, section merging, path expansion. All 12 tests pass. ruff check and ruff format clean."]
- **files_edited**: ["src/cerebral_clawtex/config.py", "tests/test_config.py"]

---

### T2: Database Module
- **depends_on**: [T0]
- **files**:
  - Create: `src/cerebral_clawtex/db.py`
  - Create: `tests/test_db.py`
- **description**: Implement SQLite database with optimistic locking. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 2: Database Module" for exact code. TDD approach. The `ClawtexDB` class manages a SQLite database with WAL mode, foreign keys, and 5 tables: `schema_version`, `sessions`, `phase1_outputs`, `consolidation_runs`, `consolidation_lock`. Key features: session registration with upsert, status tracking (pending/extracted/skipped/failed), optimistic row-level locking with stale lock expiry (600s default), phase1 output storage with watermark-based retrieval, consolidation scope-level locking, and consolidation run recording. Tests cover: schema creation, session CRUD, optimistic locking (claim/release/stale), phase1 output storage and watermark queries, consolidation lock acquire/release, and consolidation run recording. Commit with "feat: SQLite database with optimistic locking and consolidation tracking".
- **acceptance_criteria**:
  - `ClawtexDB` class with all CRUD methods
  - 5 SQLite tables created with correct schema
  - Optimistic locking works (claim, conflict, stale reclaim)
  - All 15 tests pass in `tests/test_db.py`
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_db.py -v && uv run ruff check src/cerebral_clawtex/db.py tests/test_db.py`
- **status**: completed
- **log**: ["Implemented ClawtexDB class with SQLite WAL mode, foreign keys, 5 tables (schema_version, sessions, phase1_outputs, consolidation_runs, consolidation_lock), 4 indexes, session CRUD with upsert, optimistic row-level locking with stale lock expiry, phase1 output storage with watermark-based retrieval, consolidation scope-level locking, and consolidation run recording. TDD approach: wrote 17 tests first (red), then implemented db.py (green). Fixed 2 watermark tests that had same-second timestamp collisions by backdating earlier records. All 17 tests pass, ruff check clean."]
- **files_edited**: ["src/cerebral_clawtex/db.py", "tests/test_db.py"]

---

### T3: Secret Redaction Module
- **depends_on**: [T0]
- **files**:
  - Create: `src/cerebral_clawtex/redact.py`
  - Create: `tests/test_redact.py`
- **description**: Implement regex-based secret redaction. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 3: Secret Redaction Module" for exact code. TDD approach. The `Redactor` class compiles regex patterns for: API keys (OpenAI sk-proj, AWS AKIA, GitHub ghp_/gho_/github_pat_, GitLab glpat-, Slack xox, Anthropic sk-ant-), Bearer tokens, connection strings (postgres/mysql/redis/mongodb/amqp with credentials), private keys (PEM blocks), passwords in config contexts, and generic secret/key/token assignments. Patterns with capture groups redact only the captured portion. Short values (<8 chars) are not redacted to avoid false positives. Supports custom extra patterns and configurable placeholder text. Tests cover: each secret category, false positives (normal code, short values, imports), custom patterns, and custom placeholders. Commit with "feat: regex-based secret redaction with extensible patterns".
- **acceptance_criteria**:
  - `Redactor` class with compiled regex patterns
  - All 7 secret categories detected
  - False positives avoided (normal code, short values, imports)
  - Custom patterns and placeholders work
  - All 14 tests pass in `tests/test_redact.py`
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_redact.py -v && uv run ruff check src/cerebral_clawtex/redact.py tests/test_redact.py`
- **status**: completed
- **log**: ["Implemented Redactor class with compiled regex patterns for 7 secret categories (API keys, bearer tokens, connection strings, private keys, passwords, generic secrets, custom). TDD approach: wrote 15 tests first, verified they failed, then implemented. Fixed two issues from reference code: (1) ghp_/gho_ patterns needed {30,} instead of {36} to match test token lengths; (2) password/generic_secret capture groups needed [^\\s\"'\\[\\]] to exclude brackets and avoid re-matching already-redacted placeholders. All 15 tests pass, ruff check and format clean."]
- **files_edited**: ["src/cerebral_clawtex/redact.py", "tests/test_redact.py"]

---

### T4: Session Discovery and Parsing
- **depends_on**: [T0]
- **files**:
  - Create: `src/cerebral_clawtex/sessions.py`
  - Create: `tests/test_sessions.py`
- **description**: Implement session JSONL discovery and parsing. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 4: Session Discovery and Parsing" for exact code. TDD approach. Three main functions: (1) `discover_sessions(claude_home, ...)` scans `~/.claude/projects/*/` for `*.jsonl` files, filtering by age, idle time, project include/exclude lists, and skipping subagent session directories. (2) `parse_session(session_file)` reads JSONL line-by-line, extracts user messages (plain text), assistant messages (text + tool_use blocks formatted as `[Tool: name] {json}`), tool results (formatted as `[Tool Result] content`), and drops progress/system/snapshot records. Handles corrupt lines gracefully. (3) `truncate_content(messages, max_tokens)` trims messages to fit within a token budget (~4 chars/token estimate), preserving the beginning (30%) and end (30%), dropping the middle with a truncation marker. Tests use helper functions to create fake JSONL records. Commit with "feat: session discovery with JSONL parsing and truncation".
- **acceptance_criteria**:
  - `discover_sessions()` finds JSONL files with correct filtering
  - `parse_session()` extracts user/assistant messages, tool calls/results
  - Progress records dropped, corrupt lines skipped
  - `truncate_content()` preserves start/end, trims middle
  - All 16 tests pass in `tests/test_sessions.py`
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_sessions.py -v && uv run ruff check src/cerebral_clawtex/sessions.py tests/test_sessions.py`
- **status**: completed
- **log**: ["Implemented TDD: wrote tests first (15 tests across TestDiscoverSessions, TestParseSession, TestTruncateContent), then implemented sessions.py with discover_sessions(), parse_session(), truncate_content(). Fixed test min_idle_hours defaults so freshly-created test files are discoverable. All 15 tests pass, ruff check clean."]
- **files_edited**: ["src/cerebral_clawtex/sessions.py", "tests/test_sessions.py"]

---

### T5: Storage Module
- **depends_on**: [T0]
- **files**:
  - Create: `src/cerebral_clawtex/storage.py`
  - Create: `tests/test_storage.py`
- **description**: Implement filesystem storage with atomic writes. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 5: Storage Module" for exact code. TDD approach. The `MemoryStore` class manages the progressive-disclosure hierarchy under `data_dir/`: `projects/<path>/memory_summary.md`, `projects/<path>/MEMORY.md`, `projects/<path>/rollout_summaries/<slug>.md`, `projects/<path>/skills/<name>/SKILL.md`, and `global/` equivalents. Uses `_atomic_write()` via `tempfile.mkstemp()` + `os.replace()` to prevent partial writes. The `_sanitize_slug()` function makes strings filename-safe. Supports: writing/reading rollout summaries, memory summaries, MEMORY.md, skills; listing rollout summaries, skills, and projects. Tests cover: path construction, rollout summary writing with slug sanitization, memory file reading/writing (project and global scope), skill writing, missing file returns None, and no leftover .tmp files. Commit with "feat: filesystem storage with atomic writes and progressive disclosure hierarchy".
- **acceptance_criteria**:
  - `MemoryStore` class with all read/write/list methods
  - Atomic writes via tempfile + os.replace
  - Slug sanitization removes unsafe characters
  - All 10 tests pass in `tests/test_storage.py`
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_storage.py -v && uv run ruff check src/cerebral_clawtex/storage.py tests/test_storage.py`
- **status**: completed
- **log**: ["Implemented MemoryStore class with progressive-disclosure hierarchy (projects/<path>/memory_summary.md, MEMORY.md, rollout_summaries/<slug>.md, skills/<name>/SKILL.md, and global/ equivalents). Atomic writes via tempfile.mkstemp() + os.replace(). Slug sanitization via regex. TDD: wrote 12 tests first (path construction, rollout summary write/sanitize, memory file read/write for project and global scope, skill write, missing file returns None, no leftover .tmp files), all 12 pass. ruff check and ruff format clean."]
- **files_edited**: ["src/cerebral_clawtex/storage.py", "tests/test_storage.py"]

---

### T6: Phase 1 Prompts
- **depends_on**: [T0]
- **files**:
  - Create: `src/cerebral_clawtex/prompts/phase1_system.md`
  - Create: `src/cerebral_clawtex/prompts/phase1_user.md`
- **description**: Write Phase 1 extraction prompt templates. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 6: Phase 1 Prompts" and the design document at `docs/plans/2026-02-25-cerebral-clawtex-design.md` (Section "Prompt Design — Phase 1") for requirements.

  **Phase 1 System Prompt** (`phase1_system.md`) must include:
  - Role definition: "You are a memory extraction agent that distills reusable learnings from Claude Code sessions"
  - No-op gate: "Before extracting, ask: Will a future agent plausibly act better because of this information? If no, return empty fields."
  - Task outcome classification rules: success (explicit completion evidence), partial (some goals met), fail (explicit errors/abandonment), uncertain (no clear signal)
  - Extraction guidelines — EXTRACT: multi-attempt debugging decisions, working commands/configs confirmed by tool output, failed approaches and WHY they failed, project conventions, user preferences/style, environment-specific quirks. DO NOT EXTRACT: temporary state, information already in standard docs, secrets/credentials, speculation/unconfirmed info
  - Secret handling: "NEVER include API keys, passwords, tokens, or connection strings. Describe the role of a secret (e.g., 'requires an API key for service X') but never its value."
  - Strict JSON output schema with example:
    ```json
    {
      "task_outcome": "success | partial | fail | uncertain",
      "rollout_slug": "kebab-case-slug-describing-session",
      "rollout_summary": "## Session: Title\n\n**Goal:** ...\n**Approach:** ...\n**Outcome:** ...\n**Key Learnings:** ...",
      "raw_memory": "---\nrollout_summary_file: rollout_summaries/<slug>.md\ndescription: one-line description\nkeywords: [keyword1, keyword2]\n---\n- Bullet point learnings..."
    }
    ```
  - For no-op/skipped sessions, return: `{"task_outcome": "uncertain", "rollout_slug": "", "rollout_summary": "", "raw_memory": ""}`

  **Phase 1 User Prompt** (`phase1_user.md`) is a Jinja2-style template with placeholders:
  - `{{ project_name }}` — human-readable project name
  - `{{ project_path }}` — encoded project path
  - `{{ session_id }}` — session UUID
  - `{{ session_date }}` — ISO date string
  - `{{ redacted_session_content }}` — the full redacted session transcript

  Note: `src/cerebral_clawtex/prompts/__init__.py` is already created by T0. Do NOT create it again.

  Commit with "feat: Phase 1 extraction prompt templates".
- **acceptance_criteria**:
  - `phase1_system.md` contains role definition, no-op gate, extraction guidelines, JSON schema
  - `phase1_user.md` contains Jinja2 template with all required placeholders
  - Prompts are well-structured, clear, and follow the design doc requirements
- **validation**: `test -f src/cerebral_clawtex/prompts/phase1_system.md && test -f src/cerebral_clawtex/prompts/phase1_user.md && echo "All prompt files exist"`
- **status**: completed
- **log**: ["Created phase1_system.md with all required sections: role definition (memory extraction agent), no-op gate (future agent benefit test), task outcome classification (success/partial/fail/uncertain with evidence-based rules), extraction guidelines (EXTRACT: debugging decisions, working commands, failed approaches, conventions, preferences, env quirks; DO NOT EXTRACT: temporary state, standard docs info, secrets, speculation), secret handling (never include values, describe roles only), strict JSON output schema with full example, and no-op empty-fields response format. Created phase1_user.md as Jinja2 template with all required placeholders: project_name, project_path, session_id, session_date, redacted_session_content. Template includes metadata section and session transcript wrapped in XML tags."]
- **files_edited**: ["src/cerebral_clawtex/prompts/phase1_system.md", "src/cerebral_clawtex/prompts/phase1_user.md"]

---

### T7: Phase 1 Extraction Pipeline
- **depends_on**: [T1, T2, T3, T4, T5, T6]
- **files**:
  - Create: `src/cerebral_clawtex/phase1.py`
  - Create: `tests/test_phase1.py`
- **description**: Implement the Phase 1 per-session extraction pipeline. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 7: Phase 1 Extraction Pipeline" for function signatures and flow.

  **Key function: `extract_session()`** (async) — the core extraction for a single session:
  1. Claims session via `db.claim_session()`
  2. Parses JSONL via `parse_session()`
  3. Redacts via `redactor.redact()`
  4. Truncates via `truncate_content()`
  5. Builds prompt from templates (read via `importlib.resources`)
  6. Calls `litellm.acompletion()` with `response_format={"type": "json_object"}`
  7. Validates the JSON response schema (must have task_outcome, rollout_slug, rollout_summary, raw_memory). **On invalid JSON: retry once** by appending a user message: "Your response was not valid JSON. Please respond with only valid JSON matching the schema." If retry also fails, mark session as failed.
  8. Runs post-scan redaction on output
  9. Writes rollout summary via `store.write_rollout_summary()`
  10. Stores in DB via `db.store_phase1_output()`
  11. Releases session via `db.release_session(status="extracted")`
  Returns status: "extracted" | "skipped" | "failed"

  **Key function: `run_phase1()`** (async) — top-level orchestrator:
  - Discovers sessions, registers in DB
  - Claims and extracts with `asyncio.Semaphore(config.phase1.concurrent_extractions)`
  - Returns `{"extracted": N, "skipped": N, "failed": N}`

  **LiteLLM API usage** (from Context7 docs):
  ```python
  from litellm import acompletion
  response = await acompletion(
      model=config.phase1.model,
      messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
      response_format={"type": "json_object"},
      timeout=120,
  )
  content = response.choices[0].message.content
  ```

  **Tests** use monkeypatch on `litellm.acompletion` to mock LLM responses. Test cases: successful extraction pipeline, empty/no-op response handling, invalid JSON response, LLM call failure, and concurrent extraction. Commit with "feat: Phase 1 extraction pipeline with LiteLLM and async concurrency".
- **acceptance_criteria**:
  - `extract_session()` implements full 11-step pipeline
  - `run_phase1()` orchestrates with semaphore-based concurrency
  - JSON response validation with retry on invalid JSON
  - Post-extraction redaction safety net
  - All tests pass with mocked LiteLLM
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_phase1.py -v && uv run ruff check src/cerebral_clawtex/phase1.py tests/test_phase1.py`
- **status**: pending
- **log**: []
- **files_edited**: []

---

### T8: Phase 2 Prompts
- **depends_on**: [T0]
- **files**:
  - Create: `src/cerebral_clawtex/prompts/phase2_system.md`
  - Create: `src/cerebral_clawtex/prompts/phase2_user.md`
  - Create: `src/cerebral_clawtex/prompts/phase2_global_system.md`
  - Create: `src/cerebral_clawtex/prompts/phase2_global_user.md`
- **description**: Write Phase 2 consolidation prompt templates. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 8: Phase 2 Prompts" and the design document at `docs/plans/2026-02-25-cerebral-clawtex-design.md` (Section "Prompt Design — Phase 2") for requirements.

  **Phase 2 System Prompt** (`phase2_system.md`) must include:
  - Role: "You are a memory consolidation agent that merges per-session learnings into organized, searchable memory files"
  - INIT vs INCREMENTAL mode instructions: INIT builds from scratch, INCREMENTAL merges new learnings into existing files while deduplicating and pruning contradicted entries
  - `memory_summary.md` format spec: user profile section (max 300 words), general tips section (max 80 items), routing index pointing to MEMORY.md sections and skill files. Total under 5,000 tokens.
  - `MEMORY.md` format spec: topic clusters with YAML frontmatter headers (rollout files list, keywords), bullet-point learnings under each topic. Deduplication and pruning rules.
  - Skills creation trigger: when a procedure appears 3+ times across sessions, create a skill with `name` and full `skill_md` content in SKILL.md format
  - JSON output schema:
    ```json
    {
      "memory_summary": "...markdown content for memory_summary.md...",
      "memory_md": "...markdown content for MEMORY.md...",
      "skills": [{"name": "skill-name", "skill_md": "---\nname: skill-name\n---\n## Procedure\n..."}]
    }
    ```

  **Phase 2 User Prompt** (`phase2_user.md`) — template with:
  - `{{ mode }}` (INIT/INCREMENTAL)
  - `{{ project_name }}`
  - `{{ existing_memory_summary }}` (conditional, only in INCREMENTAL mode)
  - `{{ existing_memory_md }}` (conditional, only in INCREMENTAL mode)
  - `{{ phase1_outputs }}` — list of Phase 1 raw_memory entries

  **Global System Prompt** (`phase2_global_system.md`) — same structure but instructs: extract only cross-project transferable patterns, not project-specific details.

  **Global User Prompt** (`phase2_global_user.md`) — template with per-project summaries and existing global files.

  Note: `src/cerebral_clawtex/prompts/__init__.py` is already created by T0. Do NOT create it again.

  Commit with "feat: Phase 2 consolidation and global prompt templates".
- **acceptance_criteria**:
  - All 4 prompt files created with correct structure and content
  - Phase 2 system prompt covers INIT/INCREMENTAL modes, memory_summary format, MEMORY.md format, skills trigger
  - Global prompts focus on cross-project transferable patterns
  - Templates use Jinja2 placeholders correctly
- **validation**: `test -f src/cerebral_clawtex/prompts/phase2_system.md && test -f src/cerebral_clawtex/prompts/phase2_user.md && test -f src/cerebral_clawtex/prompts/phase2_global_system.md && test -f src/cerebral_clawtex/prompts/phase2_global_user.md && echo "All Phase 2 prompt files exist"`
- **status**: pending
- **log**: []
- **files_edited**: []

---

### T9: Phase 2 Consolidation Pipeline
- **depends_on**: [T1, T2, T3, T5, T7, T8]
- **files**:
  - Create: `src/cerebral_clawtex/phase2.py`
  - Create: `tests/test_phase2.py`
- **description**: Implement the Phase 2 consolidation pipeline. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 9: Phase 2 Consolidation Pipeline" for function signatures and flow.

  **Key function: `consolidate_project()`** (async):
  1. Acquire consolidation lock via `db.acquire_consolidation_lock()`
  2. Detect mode: INIT (no existing files) or INCREMENTAL (existing files present)
  3. Load Phase 1 outputs from DB (since last watermark for INCREMENTAL)
  4. Load existing memory files from store (for INCREMENTAL)
  5. Build prompt from templates
  6. Call `litellm.acompletion()` with Sonnet model
  7. Parse JSON response
  7a. **Post-scan redaction**: Run `Redactor.redact()` on all output strings (memory_summary, memory_md, skill content) before writing to disk — this is the Layer 3 safety net from the design doc
  8. Write `memory_summary.md`, `MEMORY.md`, and any skills via store
  9. Record consolidation run in DB with watermark
  10. Release consolidation lock

  **Key function: `consolidate_global()`** (async):
  - Loads each project's `memory_summary.md`
  - Uses global prompt templates
  - Extracts only cross-project transferable patterns
  - Writes to `global/` directory

  **Key function: `run_phase2()`** (async):
  - Consolidates each project with new Phase 1 outputs
  - Then runs global consolidation
  - Returns `{"projects_consolidated": N, "global": bool}`

  **Tests** mock `litellm.acompletion`. Test both INIT and INCREMENTAL modes. Verify: memory files written, skills created, consolidation run recorded, watermark advances, lock acquired/released, global consolidation merges project summaries. Commit with "feat: Phase 2 consolidation with per-project and global scopes".
- **acceptance_criteria**:
  - `consolidate_project()` handles INIT and INCREMENTAL modes
  - `consolidate_global()` extracts cross-project patterns
  - `run_phase2()` orchestrates project + global consolidation
  - Post-scan redaction applied to all LLM output before writing to disk
  - Memory files, skills, and consolidation runs properly recorded
  - All tests pass with mocked LiteLLM
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_phase2.py -v && uv run ruff check src/cerebral_clawtex/phase2.py tests/test_phase2.py`
- **status**: pending
- **log**: []
- **files_edited**: []

---

### T10: Hook Integration
- **depends_on**: [T1, T5, T7, T9]
- **files**:
  - Create: `src/cerebral_clawtex/hooks.py`
  - Create: `tests/test_hooks.py`
- **description**: Implement the SessionStart hook for context injection. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 10: Hook Integration" for code.

  **`session_start_hook()`** — entry point for the SessionStart hook:
  1. Loads config via `load_config()`
  2. Creates `MemoryStore` from config
  3. Resolves project path from `CLAUDE_PROJECT_DIR` env var
  4. Reads project `memory_summary.md` and global `memory_summary.md`
  5. Combines with navigation instructions (how to grep/read MEMORY.md, rollout summaries, skills)
  6. Truncates combined content to ~5,000 tokens (~20,000 chars)
  7. Prints JSON to stdout: `{"additional_context": "## Cerebral Clawtex Memory\n\n..."}`
  8. Spawns background extraction via `_spawn_background_extraction()` using `os.fork()` + `os.setsid()` to detach child process

  Tests verify: valid JSON output with `additional_context` when memory files exist, empty/minimal JSON when no memory files exist, content truncation to ~5,000 tokens, navigation instructions included. Commit with "feat: SessionStart hook with context injection and background extraction".
- **acceptance_criteria**:
  - `session_start_hook()` outputs valid JSON with `additional_context`
  - Combines project + global memory summaries
  - Truncates to token budget
  - Background extraction spawning (testable via mock)
  - All tests pass
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_hooks.py -v && uv run ruff check src/cerebral_clawtex/hooks.py tests/test_hooks.py`
- **status**: pending
- **log**: []
- **files_edited**: []

---

### T11: CLI Commands
- **depends_on**: [T1, T2, T5, T7, T9, T10]
- **files**:
  - Modify: `src/cerebral_clawtex/cli.py`
  - Create: `tests/test_cli.py`
- **description**: Implement the full CLI with all commands. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 11: CLI Commands" for command signatures.

  Replace the minimal `cli.py` (from T0) with the full implementation. Wire all commands to underlying modules. Each command: loads config, creates DB connection, creates MemoryStore, calls the relevant function, formats output with `rich`.

  **Commands to implement:**
  - `clawtex status [--project] [--json]` — Show extraction status summary (counts by status per project)
  - `clawtex extract [--project] [--retry-failed] [--json]` — Run Phase 1 extraction on pending sessions
  - `clawtex consolidate [--project] [--json]` — Run Phase 2 consolidation
  - `clawtex sessions [--failed] [--json]` — List recent sessions with extraction status
  - `clawtex memories [--full] [--global]` — Print memory files for current/specified project
  - `clawtex config [--edit]` — Print resolved config or open in editor
  - `clawtex install` — Register SessionStart hook (placeholder — full implementation in T12)
  - `clawtex uninstall [--purge]` — Remove hooks (placeholder — full implementation in T12)
  - `clawtex hook session-start` — **Entry point for the SessionStart hook** (calls `session_start_hook()` from hooks.py). This is what gets registered in `~/.claude/settings.json` by `clawtex install`. Implement as a typer command group or subcommand.
  - `clawtex reset [--project] [--all]` — Clear data and re-extract from scratch

  **Typer usage** (from Context7 docs): Use `@app.command()` decorators, `typer.Option()` for flags, `typer.testing.CliRunner` for tests.

  Tests use `CliRunner` to invoke each command. Commit with "feat: full CLI with extract, consolidate, status, install, and memory commands".
- **acceptance_criteria**:
  - All 9 CLI commands implemented
  - Each command loads config, creates dependencies, calls underlying modules
  - `--json` output option on key commands
  - Tests cover each command via CliRunner
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_cli.py -v && uv run ruff check src/cerebral_clawtex/cli.py tests/test_cli.py`
- **status**: pending
- **log**: []
- **files_edited**: []

---

### T12: Install/Uninstall Hook Registration
- **depends_on**: [T10, T11]
- **files**:
  - Modify: `src/cerebral_clawtex/cli.py`
  - Modify: `tests/test_cli.py`
- **description**: Implement the install/uninstall commands that register the SessionStart hook in Claude Code settings. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 12: Install/Uninstall Hook Registration" for details.

  **`clawtex install`** must:
  - Create config dir if missing
  - Create data dir if missing
  - Initialize SQLite schema
  - Read `~/.claude/settings.json` (or create if missing)
  - Merge SessionStart hook entry: `{"matcher": "startup", "hooks": [{"type": "command", "command": "clawtex hook session-start", "timeout": 10}]}`
  - Preserve existing hooks
  - Write back settings.json

  **`clawtex uninstall`** must:
  - Remove only the clawtex hook entry from settings.json
  - Preserve other hooks
  - `--purge` flag: also remove data directory

  Tests mock the settings.json path. Test scenarios: fresh install (no settings.json), install with existing hooks, uninstall preserves other hooks, purge removes data. Commit with "feat: install/uninstall with Claude Code settings.json hook registration".
- **acceptance_criteria**:
  - `install` creates dirs, inits DB, registers hook in settings.json
  - `uninstall` removes only clawtex hook, preserves others
  - `--purge` removes data directory
  - Handles missing settings.json gracefully
  - Install tests pass
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_cli.py -v -k install && uv run ruff check src/cerebral_clawtex/cli.py`
- **status**: pending
- **log**: []
- **files_edited**: []

---

### T13: End-to-End Test
- **depends_on**: [T7, T9, T10, T11, T12]
- **files**:
  - Create: `tests/test_e2e.py`
  - Modify: `pyproject.toml` (add e2e marker)
- **description**: Create an end-to-end test gated behind `--e2e` marker. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 13: End-to-End Test" for structure.

  The E2E test seeds a fake Claude home with a realistic session JSONL, creates a config pointing to tmp dirs, runs Phase 1 extraction (with real Haiku API call), verifies session marked extracted and rollout summary file exists, runs Phase 2 consolidation (with real Sonnet API call), verifies memory_summary.md and MEMORY.md exist, checks no secrets in any output file, and runs the hook to verify JSON output contains memory content.

  Add pytest marker to `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  markers = ["e2e: end-to-end tests requiring real LLM API calls"]
  ```

  The test class should be decorated with `@pytest.mark.e2e` so it's skipped by default and only runs with `pytest -m e2e`.

  Commit with "test: end-to-end test with real LLM calls (gated behind --e2e marker)".
- **acceptance_criteria**:
  - E2E test file created with full pipeline test
  - pytest e2e marker configured in pyproject.toml
  - Test is skipped by default (only runs with `-m e2e`)
  - Test covers Phase 1, Phase 2, hook output, and secret scanning
  - `ruff check` clean
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest tests/test_e2e.py --collect-only && uv run ruff check tests/test_e2e.py`
- **status**: pending
- **log**: []
- **files_edited**: []

---

### T14: Final Integration and Polish
- **depends_on**: [T13]
- **files**:
  - Potentially modify: any file (integration fixes)
- **description**: Run the full test suite and linting, fix any integration issues. Read `docs/plans/2026-02-25-cerebral-clawtex-implementation.md`, "Task 14: Final Integration and Polish" for validation steps.

  1. Run full test suite: `uv run pytest -v --ignore=tests/test_e2e.py` — all must pass
  2. Run linting: `uv run ruff check . && uv run ruff format --check .` — must be clean
  3. Fix any issues discovered
  4. Test CLI manually: `clawtex config`, `clawtex status`
  5. Commit any fixes with "chore: final integration polish"
- **acceptance_criteria**:
  - All non-E2E tests pass
  - `ruff check` and `ruff format --check` clean
  - CLI commands work without errors
  - No import errors or missing dependencies
- **validation**: `cd ~/dev/repos/cerebral-clawtex && uv run pytest -v --ignore=tests/test_e2e.py && uv run ruff check . && uv run ruff format --check .`
- **status**: pending
- **log**: []
- **files_edited**: []

---

## Parallel Execution Waves

| Wave | Tasks | Can Start When | Files Touched |
|------|-------|----------------|---------------|
| 1 | T0 | Immediately | pyproject.toml, __init__.py, cli.py, prompts/__init__.py, tests/__init__.py, conftest.py, .gitignore, .python-version |
| 2 | T1, T2, T3, T4, T5, T6, T8 | T0 complete | T1: config.py, test_config.py; T2: db.py, test_db.py; T3: redact.py, test_redact.py; T4: sessions.py, test_sessions.py; T5: storage.py, test_storage.py; T6: prompts/phase1_*.md; T8: prompts/phase2_*.md |
| 3 | T7 | T1,T2,T3,T4,T5,T6 complete | phase1.py, test_phase1.py |
| 4 | T9 | T1,T2,T3,T5,T7,T8 complete | phase2.py, test_phase2.py |
| 5 | T10 | T1,T5,T7,T9 complete | hooks.py, test_hooks.py |
| 6 | T11 | T1,T2,T5,T7,T9,T10 complete | cli.py (modify), test_cli.py |
| 7 | T12 | T10,T11 complete | cli.py (modify), test_cli.py (modify) |
| 8 | T13 | T12 complete | test_e2e.py, pyproject.toml (modify) |
| 9 | T14 | T13 complete | any (integration fixes) |

**File isolation verified**: No two tasks in the same wave touch the same files. The `prompts/__init__.py` potential conflict between T6/T8 is eliminated by creating it in T0.

## Testing Strategy

- Each task runs its own tests after implementation
- Full test suite (excluding E2E): `uv run pytest -v --ignore=tests/test_e2e.py`
- E2E test (requires API keys): `uv run pytest -m e2e -v`
- Linting: `uv run ruff check . && uv run ruff format --check .`

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| T7/T9 have complex LLM integration | Mock-based tests eliminate flakiness; E2E test in T13 covers real API |
| T7 invalid JSON from LLM | Retry once with nudge message, then mark failed (retryable via CLI) |
| T9 secret leakage from Phase 2 LLM | Post-scan redaction (Layer 3) applied before writing any files |
| T11 replaces cli.py created by T0 | T11 depends on T0 and writes a complete replacement — no merge conflict |
| T12 modifies files from T11 | T12 depends on T11 — serial execution ensures clean base |
| Wave 2 has 7 parallel tasks | All create distinct files — merge is safe |
| `os.fork()` not available on Windows | Acceptable — project targets Linux/macOS per design doc |
| Async tests need pytest-asyncio config | `asyncio_mode = "auto"` added to pyproject.toml in T0 |
