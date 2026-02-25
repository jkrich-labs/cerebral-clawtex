# Cerebral Clawtex — Design Document

**Date:** 2026-02-25
**Status:** Approved

## Overview

Cerebral Clawtex is a Claude Code plugin that automatically extracts learnings from past coding sessions and consolidates them into a searchable, progressive-disclosure memory hierarchy. It is a feature-parity equivalent of OpenAI Codex's `memory_tool`, adapted to Claude Code's extension points (hooks, MCP, sessions, skills).

## Goals

- Automatically distill reusable knowledge from every Claude Code session
- Organize memories in a progressive-disclosure hierarchy (summary → registry → per-session details → skills)
- Inject relevant memory context into new sessions without manual effort
- Support both per-project and cross-project memory consolidation
- Provide CLI tools for manual control, inspection, and maintenance

## Non-Goals

- Replacing Claude Code's native MEMORY.md (coexists, doesn't touch it)
- Vector database or semantic search (grep over markdown is sufficient)
- Multi-user or distributed operation (single user, single machine)
- Real-time memory updates during a session (batch processing between sessions)

## Architecture

### Deployment Model

Claude Code plugin: Python package installed via `uv`, integrates through Claude Code's `SessionStart` hook for context injection and background extraction triggering. CLI (`clawtex`) for manual operations.

### LLM Backend

LiteLLM for model abstraction. Default models:

| Phase | Model | Reasoning | Purpose |
|-------|-------|-----------|---------|
| Phase 1 | `anthropic/claude-haiku-4-5-20251001` | Low | Per-session extraction |
| Phase 2 | `anthropic/claude-sonnet-4-6-20250514` | Medium | Global consolidation |

Configurable via `config.toml`. Any LiteLLM-supported model can be substituted.

### Pipeline Overview

```
Session ends
     │
     ▼ (next session start, or manual `clawtex extract`)
     │
Phase 1: Per-Session Extraction (Haiku 4.5)
     │  - Parse session JSONL
     │  - Redact secrets (regex)
     │  - Truncate to token budget
     │  - Extract structured memory + rollout summary
     │  - Post-scan redaction safety net
     │  - Write rollout_summaries/<slug>.md
     │  - Store in SQLite
     │
     ▼
Phase 2: Consolidation (Sonnet 4.6)
     │  - Per-project: merge Phase 1 outputs → MEMORY.md + memory_summary.md + skills
     │  - Global: merge project summaries → global memory_summary.md + MEMORY.md
     │
     ▼
SessionStart Hook
     │  - Read memory_summary.md (project + global)
     │  - Inject via additional_context
     │  - Spawn background extraction for pending sessions
```

## Project Structure

```
~/dev/repos/cerebral-clawtex/
├── pyproject.toml
├── src/
│   └── cerebral_clawtex/
│       ├── __init__.py
│       ├── cli.py              # typer CLI
│       ├── config.py           # TOML config loading
│       ├── db.py               # SQLite operations
│       ├── sessions.py         # JSONL discovery + parsing
│       ├── redact.py           # Regex secret redaction
│       ├── phase1.py           # Per-session extraction
│       ├── phase2.py           # Consolidation
│       ├── storage.py          # Memory filesystem operations
│       ├── hooks.py            # SessionStart hook entry point
│       └── prompts/
│           ├── phase1_system.md
│           ├── phase1_user.md
│           ├── phase2_system.md
│           └── phase2_user.md
├── tests/
│   ├── test_sessions.py
│   ├── test_redact.py
│   ├── test_db.py
│   ├── test_storage.py
│   ├── test_config.py
│   ├── test_phase1.py
│   ├── test_phase2.py
│   ├── test_hooks.py
│   └── test_cli.py
├── hooks/
│   └── session-start.sh
└── docs/
    └── plans/
        └── 2026-02-25-cerebral-clawtex-design.md
```

## Configuration

```toml
# ~/.config/cerebral-clawtex/config.toml

[general]
claude_home = "~/.claude"
data_dir = "~/.local/share/cerebral-clawtex"

[phase1]
model = "anthropic/claude-haiku-4-5-20251001"
max_sessions_per_run = 20
max_session_age_days = 30
min_session_idle_hours = 1
max_input_tokens = 80000
concurrent_extractions = 4

[phase2]
model = "anthropic/claude-sonnet-4-6-20250514"
max_memories_for_consolidation = 200
run_after_phase1 = true

[redaction]
extra_patterns = []
placeholder = "[REDACTED]"

[projects]
include = []
exclude = []
```

All paths support `~` expansion. Config file is optional — sensible defaults work out of the box.

## SQLite Schema

```sql
-- ~/.local/share/cerebral-clawtex/clawtex.db

CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    session_file TEXT NOT NULL,
    file_modified_at INTEGER NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    locked_by TEXT,
    locked_at INTEGER,
    error_message TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE phase1_outputs (
    session_id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    raw_memory TEXT NOT NULL,
    rollout_summary TEXT NOT NULL,
    rollout_slug TEXT NOT NULL,
    task_outcome TEXT NOT NULL,
    token_usage_input INTEGER,
    token_usage_output INTEGER,
    generated_at INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE consolidation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    phase1_count INTEGER,
    input_watermark INTEGER,
    token_usage_input INTEGER,
    token_usage_output INTEGER,
    error_message TEXT,
    started_at INTEGER NOT NULL,
    completed_at INTEGER
);

CREATE TABLE consolidation_lock (
    scope TEXT PRIMARY KEY,
    locked_by TEXT,
    locked_at INTEGER
);

CREATE INDEX idx_sessions_status ON sessions(status, file_modified_at DESC);
CREATE INDEX idx_sessions_project ON sessions(project_path, status);
CREATE INDEX idx_phase1_project ON phase1_outputs(project_path, generated_at DESC);
CREATE INDEX idx_consolidation_scope ON consolidation_runs(scope, started_at DESC);
```

### Concurrency Model

- **Phase 1 extraction:** Row-level optimistic locking on `sessions` table. Workers claim sessions via `UPDATE ... WHERE locked_by IS NULL OR locked_at < stale_threshold`. Multiple processes can extract different sessions simultaneously.
- **Phase 2 consolidation:** Scope-level locking via `consolidation_lock` table. One writer per project/global scope at a time.
- **Stale lock timeout:** 600 seconds (configurable). Crashed workers' locks expire automatically.

## Session Discovery & Parsing

### Discovery

Scans `~/.claude/projects/*/` for `*.jsonl` files. Filters by:
- Project include/exclude config
- `max_session_age_days` (file mtime)
- `min_session_idle_hours` (file mtime vs now)
- Already-tracked status in DB

### JSONL Parsing

Extracts from each session file:
- User messages (what was asked)
- Assistant messages (what Claude said and did)
- Tool results (command outputs, file reads — the evidence)

Drops: `progress` events (streaming deltas), large binary/base64 content.

### Truncation

Sessions can exceed 8MB. Content is truncated to `max_input_tokens` (default 80K), preserving the beginning (context setup) and end (final results/outcomes), trimming middle exploration.

## Secret Redaction

Three layers, applied sequentially:

### Layer 1: Regex Pre-filter (before LLM call)

Applied to parsed session content before sending to extraction model.

| Category | Patterns |
|----------|----------|
| API keys | `sk-[a-zA-Z0-9]{20,}`, `AKIA[0-9A-Z]{16}`, `ghp_[a-zA-Z0-9]{36}` |
| Tokens | `Bearer [a-zA-Z0-9._-]{20,}`, `token[=: ]["']?[a-zA-Z0-9._-]{20,}` |
| Connection strings | `postgres://.*@.*`, `redis://.*@.*`, `mongodb+srv://.*@.*` |
| Passwords | `password[=: ]["']?[^\s"']{8,}` |
| Private keys | `-----BEGIN [A-Z ]+ PRIVATE KEY-----` blocks |
| Base64 blobs | Long base64 strings (>64 chars) in value positions |
| Generic secrets | `secret[=: ]["']?[^\s"']{8,}`, `_KEY[=: ]["']?[^\s"']{8,}` |

Matches replaced with `[REDACTED:<category>]`. User-extensible via `extra_patterns` in config.

### Layer 2: Prompt Instructions (during LLM call)

Phase 1 system prompt explicitly instructs: never include credentials in output, describe the role of a secret not its value.

### Layer 3: Post-extraction Scan

Same regex patterns run over LLM output before writing to disk.

## Phase 1: Per-Session Extraction

**Model:** Haiku 4.5 via LiteLLM
**Trigger:** SessionStart hook (background) or `clawtex extract` (manual)

### Flow

1. Discover pending sessions, register in DB
2. Claim sessions via optimistic row lock
3. Parse JSONL, redact (Layer 1), truncate
4. Call Haiku via LiteLLM (up to 4 concurrent per process)
5. Validate structured JSON output
6. Post-scan redaction (Layer 3)
7. Write rollout summary to filesystem
8. Store phase1_output in DB, mark session `extracted`

### Structured Output Schema

```json
{
  "task_outcome": "success | partial | fail | uncertain",
  "rollout_slug": "fix-typesense-sync-tests",
  "rollout_summary": "## Session: Fix Typesense Sync Tests\n\nthread_id: ...\n...",
  "raw_memory": "---\nrollout_summary_file: ...\ndescription: ...\nkeywords: ...\n---\n- Bullet point learnings..."
}
```

### No-op Gate

System prompt instructs model: "Will a future agent plausibly act better because of this?" If no → return empty fields → session marked `skipped`.

### Error Handling

- LLM failure → mark `failed`, reprocessable via `clawtex extract --retry-failed`
- Invalid JSON → one retry with nudge, then fail
- Empty response → mark `skipped` (legitimate no-op)
- Timeouts: 120s for Haiku

## Phase 2: Global Consolidation

**Model:** Sonnet 4.6 via LiteLLM
**Trigger:** After Phase 1 (if `run_after_phase1 = true`) or `clawtex consolidate` (manual)

### Two Scopes, Sequential

**Per-project consolidation:**
1. Load all Phase 1 outputs for the project
2. Load existing project `MEMORY.md` and `memory_summary.md` (if any)
3. Send to Sonnet with consolidation prompt
4. Model returns: `memory_summary`, `memory_md`, `skills[]`
5. Write to project memory directory

**Global consolidation:**
1. Load each project's `memory_summary.md`
2. Load existing global files
3. Sonnet extracts cross-project transferable patterns only
4. Write global `memory_summary.md` and `MEMORY.md`

### Mode Detection

- No existing files → INIT mode (build from scratch)
- Existing files → INCREMENTAL mode (merge, deduplicate, prune stale)

### Context Window Management

If Phase 1 outputs exceed `max_memories_for_consolidation` (200), take most recent by `generated_at`. Older outputs are already represented in existing `MEMORY.md` from prior runs.

### Structured Output Schema

```json
{
  "memory_summary": "...markdown (max 5000 tokens)...",
  "memory_md": "...markdown...",
  "skills": [
    {
      "name": "skill-name",
      "skill_md": "...full SKILL.md content..."
    }
  ]
}
```

### Timeout

300s for Sonnet.

## Storage Layout

```
~/.local/share/cerebral-clawtex/
├── clawtex.db
├── projects/
│   ├── -home-johnr-dev-repos-pinion/
│   │   ├── memory_summary.md
│   │   ├── MEMORY.md
│   │   ├── rollout_summaries/
│   │   │   ├── fix-typesense-sync-tests.md
│   │   │   └── add-devcontainer-support.md
│   │   └── skills/
│   │       └── django-migration-workflow/
│   │           └── SKILL.md
│   └── -home-johnr-dev-repos-cerebral-clawtex/
│       └── ...
└── global/
    ├── memory_summary.md
    └── MEMORY.md
```

### Progressive Disclosure Hierarchy

| Layer | Loaded When | Token Budget |
|-------|-------------|--------------|
| `memory_summary.md` | Always (SessionStart hook injection) | ~5,000 tokens |
| `MEMORY.md` | On demand via grep/read | Unbounded |
| `rollout_summaries/*.md` | On demand per file | Unbounded |
| `skills/*/SKILL.md` | On demand per skill | Unbounded |

## SessionStart Hook Integration

### Registration

`clawtex install` adds to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "clawtex hook session-start",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### Hook Behavior

1. Resolve project from `$CLAUDE_PROJECT_DIR`
2. Read project + global `memory_summary.md`
3. Combine, truncate to ~5,000 tokens
4. Output JSON with `additional_context` containing:
   - Memory summary content
   - Navigation instructions for deeper lookup
5. Spawn background extraction (detached process via `os.fork()` + `os.setsid()`)

Hook itself completes within 10s timeout (file reads only). Extraction runs independently.

### Injected Context Format

```markdown
## Cerebral Clawtex Memory

You have access to a learned memory system at ~/.local/share/cerebral-clawtex/.

### Project Memory (pinion)

[contents of project memory_summary.md]

### Global Memory

[contents of global memory_summary.md]

### Deeper Lookup

If you need more detail:
- Search MEMORY.md: `cat ~/.local/share/cerebral-clawtex/projects/<project>/MEMORY.md | grep -i <keyword>`
- Rollout summaries: `ls ~/.local/share/cerebral-clawtex/projects/<project>/rollout_summaries/`
- Skills: `ls ~/.local/share/cerebral-clawtex/projects/<project>/skills/`
- Global memory: `cat ~/.local/share/cerebral-clawtex/global/MEMORY.md`
```

## CLI Commands

```bash
# Installation
clawtex install              # register hooks in Claude Code settings
clawtex uninstall            # remove hooks (data preserved)
clawtex uninstall --purge    # remove hooks + all data

# Pipeline
clawtex extract              # Phase 1 on all pending sessions
clawtex extract --project pinion
clawtex extract --retry-failed
clawtex consolidate          # Phase 2 on all projects + global
clawtex consolidate --project pinion

# Inspection
clawtex status               # summary per project
clawtex status --project pinion
clawtex sessions             # list recent sessions with status
clawtex sessions --failed

# Memory browsing
clawtex memories             # project memory_summary.md for cwd
clawtex memories --global
clawtex memories --full      # full MEMORY.md

# Maintenance
clawtex reset --project pinion
clawtex reset --all
clawtex config
clawtex config --edit
```

All commands support `--json` for scriptability. Project names fuzzy-match against encoded paths.

## Prompt Design

### Phase 1 System Prompt

Key instructions:
1. **Role:** Memory extraction agent distilling sessions into reusable learnings
2. **No-op gate:** "Will a future agent plausibly act better because of this?" → empty if no
3. **Task outcome classification:** success/partial/fail/uncertain based on evidence
4. **Extract:** Multi-attempt decisions, working commands, failed approaches, conventions, user preferences
5. **Don't extract:** Temporary state, info already in docs, secrets, speculation
6. **Output:** Strict JSON schema with `task_outcome`, `rollout_slug`, `rollout_summary`, `raw_memory`

### Phase 2 System Prompt

Key instructions:
1. **Role:** Memory consolidation agent merging per-session learnings
2. **Mode:** INIT (build from scratch) vs INCREMENTAL (merge with existing)
3. **memory_summary.md:** User profile (300 words max) + general tips (80 items max) + routing index. Total under 5,000 tokens.
4. **MEMORY.md:** Topic clusters with YAML headers (rollout files, keywords) + bullet-point learnings. Deduplicate, prune contradicted entries.
5. **Skills creation:** When a procedure appears 3+ times → create `skills/<name>/SKILL.md`
6. **Output:** JSON with `memory_summary`, `memory_md`, `skills[]`

### Global Consolidation Prompt

Same Phase 2 structure, but extracts only cross-project transferable patterns from all project `memory_summary.md` files.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Empty/corrupt JSONL | Mark `skipped` with reason |
| Session still active | Skip, pick up next run |
| LLM network error | Mark `failed`, retry via CLI |
| Invalid JSON response | One retry with nudge, then fail |
| Empty LLM response | Mark `skipped` (legitimate no-op) |
| Lock contention | Skip session/scope, other worker handles it |
| Stale lock (crashed worker) | Auto-expires after 600s |
| Disk full | Catch `OSError`, log, fail gracefully |
| File write | Atomic via `.tmp` + `os.rename()` |

## Testing Strategy

### Unit Tests (no LLM calls)

| Module | Coverage |
|--------|----------|
| `test_sessions.py` | JSONL discovery, parsing, filtering, truncation |
| `test_redact.py` | Every regex pattern, false positive checks |
| `test_db.py` | Schema, status transitions, locking, watermarks |
| `test_storage.py` | Hierarchy creation, atomic writes, naming |
| `test_config.py` | Defaults, TOML parsing, path expansion |

### Integration Tests (mocked LLM)

| Module | Coverage |
|--------|----------|
| `test_phase1.py` | Full pipeline with mock responses |
| `test_phase2.py` | INIT and INCREMENTAL consolidation |
| `test_hooks.py` | Hook output format, background spawn |
| `test_cli.py` | All commands via typer test runner |

### End-to-End Test (real LLM, `--e2e` flag)

Seeds fake session → Phase 1 with real Haiku → Phase 2 with real Sonnet → validates hierarchy and no secret leakage.

## Upgrade Path

- SQLite migrations via `schema_version` table
- New columns added with defaults (no breaking changes)
- Memory files are plain markdown (always backward compatible)
