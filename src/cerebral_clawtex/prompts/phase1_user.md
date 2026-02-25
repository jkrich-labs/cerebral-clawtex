# Session Extraction Request

Extract reusable learnings from the following Claude Code session.

## Session Metadata

- **Project:** {{ project_name }}
- **Project Path:** {{ project_path }}
- **Session ID:** {{ session_id }}
- **Date:** {{ session_date }}

## Session Transcript

The transcript below has been pre-processed: secrets have been redacted (shown as `[REDACTED:<category>]`) and the content may have been truncated to fit within the token budget. A truncation marker `[... middle truncated ...]` indicates that middle portions of the session were removed, preserving the beginning (context setup) and end (final results/outcomes).

<session>
{{ redacted_session_content }}
</session>

Analyze this session and return a JSON object with `task_outcome`, `rollout_slug`, `rollout_summary`, and `raw_memory` as specified in your instructions. If the session contains no extractable learnings, return empty fields.
