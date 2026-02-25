# tests/test_sessions.py
import json
import time
from pathlib import Path

from cerebral_clawtex.sessions import (
    discover_sessions,
    parse_session,
    truncate_content,
)


def _write_session(path: Path, records: list[dict]) -> None:
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def _make_user_record(content: str, uuid: str = "u1", parent: str | None = None) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:00:00Z",
        "isSidechain": False,
        "message": {"role": "user", "content": content},
    }


def _make_assistant_record(
    text: str,
    uuid: str = "a1",
    parent: str = "u1",
    tool_use: dict | None = None,
) -> dict:
    content = []
    if text:
        content.append({"type": "text", "text": text})
    if tool_use:
        content.append({"type": "tool_use", **tool_use})
    return {
        "type": "assistant",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:01:00Z",
        "isSidechain": False,
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-6",
            "content": content,
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }


def _make_tool_result_record(
    tool_use_id: str,
    content: str,
    uuid: str = "tr1",
    parent: str = "a1",
) -> dict:
    return {
        "type": "user",
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:02:00Z",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": content},
            ],
        },
    }


def _make_progress_record(uuid: str = "p1") -> dict:
    return {
        "type": "progress",
        "uuid": uuid,
        "sessionId": "sess-1",
        "timestamp": "2026-02-25T10:01:30Z",
        "data": {"type": "bash_progress", "output": "running..."},
    }


class TestDiscoverSessions:
    def test_finds_jsonl_files(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-home-user-project"
        proj.mkdir(parents=True)
        (proj / "session-1.jsonl").write_text("{}\n")
        (proj / "session-2.jsonl").write_text("{}\n")
        (proj / "not-a-session.txt").write_text("nope")
        sessions = discover_sessions(tmp_claude_home, min_idle_hours=0)
        assert len(sessions) == 2

    def test_extracts_project_path(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-home-user-myproject"
        proj.mkdir(parents=True)
        (proj / "abc.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home, min_idle_hours=0)
        assert sessions[0]["project_path"] == "-home-user-myproject"
        assert sessions[0]["session_id"] == "-home-user-myproject:abc"

    def test_skips_subagent_sessions(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-proj"
        proj.mkdir(parents=True)
        (proj / "main.jsonl").write_text("{}\n")
        subagent_dir = proj / "main" / "subagents"
        subagent_dir.mkdir(parents=True)
        (subagent_dir / "agent-1.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home, min_idle_hours=0)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "-proj:main"

    def test_session_id_is_project_scoped(self, tmp_claude_home: Path):
        for project in ["-proj-a", "-proj-b"]:
            proj_dir = tmp_claude_home / "projects" / project
            proj_dir.mkdir(parents=True)
            (proj_dir / "same-id.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home, min_idle_hours=0)
        session_ids = {s["session_id"] for s in sessions}
        assert len(session_ids) == 2
        assert "-proj-a:same-id" in session_ids
        assert "-proj-b:same-id" in session_ids

    def test_stat_race_is_skipped(self, tmp_claude_home: Path, monkeypatch):
        proj = tmp_claude_home / "projects" / "-proj"
        proj.mkdir(parents=True)
        good = proj / "good.jsonl"
        bad = proj / "bad.jsonl"
        good.write_text("{}\n")
        bad.write_text("{}\n")

        orig_stat = Path.stat

        def flaky_stat(path: Path, *args, **kwargs):
            if path.name == "bad.jsonl":
                raise FileNotFoundError("simulated race")
            return orig_stat(path, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky_stat)
        sessions = discover_sessions(tmp_claude_home, min_idle_hours=0)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "-proj:good"

    def test_filters_by_age(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-proj"
        proj.mkdir(parents=True)
        recent = proj / "recent.jsonl"
        recent.write_text("{}\n")
        old = proj / "old.jsonl"
        old.write_text("{}\n")
        # Backdate the old file
        import os

        old_time = time.time() - (60 * 60 * 24 * 45)  # 45 days ago
        os.utime(old, (old_time, old_time))
        sessions = discover_sessions(tmp_claude_home, max_age_days=30, min_idle_hours=0)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "-proj:recent"

    def test_filters_by_idle_hours(self, tmp_claude_home: Path):
        proj = tmp_claude_home / "projects" / "-proj"
        proj.mkdir(parents=True)
        active = proj / "active.jsonl"
        active.write_text("{}\n")
        # File was just modified — still "active"
        sessions = discover_sessions(tmp_claude_home, min_idle_hours=1)
        assert len(sessions) == 0

    def test_project_include_filter(self, tmp_claude_home: Path):
        for name in ["-proj-a", "-proj-b"]:
            p = tmp_claude_home / "projects" / name
            p.mkdir(parents=True)
            (p / "s1.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home, include_projects=["proj-a"], min_idle_hours=0)
        assert len(sessions) == 1
        assert "proj-a" in sessions[0]["project_path"]

    def test_project_exclude_filter(self, tmp_claude_home: Path):
        for name in ["-proj-a", "-proj-b"]:
            p = tmp_claude_home / "projects" / name
            p.mkdir(parents=True)
            (p / "s1.jsonl").write_text("{}\n")
        sessions = discover_sessions(tmp_claude_home, exclude_projects=["proj-b"], min_idle_hours=0)
        assert len(sessions) == 1
        assert "proj-a" in sessions[0]["project_path"]


class TestParseSession:
    def test_extracts_user_messages(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(f, [_make_user_record("Hello Claude")])
        messages = parse_session(f)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Hello Claude" in messages[0]["content"]

    def test_extracts_assistant_text(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(
            f,
            [
                _make_user_record("Hi"),
                _make_assistant_record("Hello! How can I help?"),
            ],
        )
        messages = parse_session(f)
        assert len(messages) == 2
        assert messages[1]["role"] == "assistant"
        assert "Hello! How can I help?" in messages[1]["content"]

    def test_extracts_tool_calls(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(
            f,
            [
                _make_user_record("List files"),
                _make_assistant_record(
                    "Let me check.",
                    tool_use={"id": "t1", "name": "Bash", "input": {"command": "ls"}},
                ),
                _make_tool_result_record("t1", "file1.py\nfile2.py"),
            ],
        )
        messages = parse_session(f)
        assert len(messages) == 3
        assert "Bash" in messages[1]["content"]
        assert "file1.py" in messages[2]["content"]

    def test_drops_progress_records(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        _write_session(
            f,
            [
                _make_user_record("Hi"),
                _make_progress_record(),
                _make_assistant_record("Hello"),
            ],
        )
        messages = parse_session(f)
        assert len(messages) == 2  # progress dropped

    def test_handles_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        messages = parse_session(f)
        assert messages == []

    def test_handles_corrupt_line(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        f.write_text('{"type":"user","message":{"role":"user","content":"ok"}}\nnot-json\n')
        messages = parse_session(f)
        assert len(messages) == 1  # corrupt line skipped

    def test_handles_unexpected_content_shapes(self, tmp_path: Path):
        f = tmp_path / "session.jsonl"
        records = [
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": {"not": "a-list"}},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": ["bad-block", {"type": "text", "text": "safe text"}],
                },
            },
        ]
        _write_session(f, records)
        messages = parse_session(f)
        assert len(messages) == 1
        assert "safe text" in messages[0]["content"]


class TestTruncateContent:
    def test_short_content_unchanged(self):
        messages = [{"role": "user", "content": "short"}]
        result = truncate_content(messages, max_tokens=80000)
        assert len(result) == 1

    def test_long_content_truncated(self):
        # Create messages that exceed token budget
        messages = [
            {"role": "user", "content": "start " * 100},
            *[{"role": "assistant", "content": "middle " * 1000} for _ in range(20)],
            {"role": "user", "content": "end " * 100},
        ]
        result = truncate_content(messages, max_tokens=1000)
        # Should keep start and end, trim middle
        assert len(result) < len(messages)
        assert "start" in result[0]["content"]
        assert "end" in result[-1]["content"]
