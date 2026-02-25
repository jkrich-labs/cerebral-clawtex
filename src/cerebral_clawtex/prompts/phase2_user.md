# Phase 2: Memory Consolidation — User Prompt

**Mode:** {{ mode }}
**Project:** {{ project_name }}

---

{% if mode == "INCREMENTAL" %}
## Existing Memory Summary

The current `memory_summary.md` for this project:

```markdown
{{ existing_memory_summary }}
```

## Existing MEMORY.md

The current `MEMORY.md` for this project:

```markdown
{{ existing_memory_md }}
```

Merge the new Phase 1 outputs below into these existing files. Deduplicate, prune contradicted entries, and reorganize as needed. Return the complete updated files.

{% else %}
## No Existing Memory Files

This is an INIT consolidation — build the memory files from scratch using the Phase 1 outputs below.

{% endif %}
---

## Phase 1 Outputs

The following are raw_memory entries extracted from individual coding sessions. Each entry contains bullet-point learnings from a single session, with YAML frontmatter linking to the rollout summary file.

{% for output in phase1_outputs %}
### Session {{ loop.index }}

```markdown
{{ output }}
```

{% endfor %}
---

Consolidate these learnings into the structured output format described in your instructions. Return valid JSON with `memory_summary`, `memory_md`, and `skills` fields.
