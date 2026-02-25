# Phase 2: Global Memory Consolidation — User Prompt

**Mode:** {{ mode }}
**Scope:** Global (cross-project)

---

{% if mode == "INCREMENTAL" %}
## Existing Global Memory Summary

The current global `memory_summary.md`:

```markdown
{{ existing_memory_summary }}
```

## Existing Global MEMORY.md

The current global `MEMORY.md`:

```markdown
{{ existing_memory_md }}
```

Merge the per-project summaries below into these existing global files. Extract only cross-project transferable patterns. Deduplicate, prune contradicted entries, and reorganize as needed. Return the complete updated files.

{% else %}
## No Existing Global Memory Files

This is an INIT consolidation — build the global memory files from scratch using the per-project summaries below.

{% endif %}
---

## Per-Project Memory Summaries

The following are `memory_summary.md` contents from each project. Extract only the patterns that transfer across projects.

{% for project in project_summaries %}
### Project: {{ project.name }}

```markdown
{{ project.summary }}
```

{% endfor %}
---

Consolidate cross-project transferable patterns into the structured output format described in your instructions. Return valid JSON with `memory_summary`, `memory_md`, and `skills` fields.
