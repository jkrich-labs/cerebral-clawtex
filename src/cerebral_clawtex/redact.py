# src/cerebral_clawtex/redact.py
from __future__ import annotations

import re


_BUILTIN_PATTERNS: list[tuple[str, str]] = [
    # API keys
    (r"sk-(?:proj-|ant-api\d{2}-)?[a-zA-Z0-9_-]{20,}", "api_key"),
    (r"AKIA[0-9A-Z]{16}", "api_key"),
    (r"ghp_[a-zA-Z0-9]{30,}", "api_key"),
    (r"gho_[a-zA-Z0-9]{30,}", "api_key"),
    (r"github_pat_[a-zA-Z0-9_]{22,}", "api_key"),
    (r"glpat-[a-zA-Z0-9_-]{20,}", "api_key"),
    (r"xox[bpors]-[a-zA-Z0-9-]{10,}", "api_key"),
    # Bearer tokens
    (r"Bearer\s+[a-zA-Z0-9._-]{20,}", "token"),
    # Connection strings
    (
        r"(?:postgres(?:ql)?|mysql|redis|mongodb(?:\+srv)?|amqp)"
        r"://[^\s\"']+@[^\s\"']+",
        "connection_string",
    ),
    # Private keys
    (
        r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?"
        r"-----END [A-Z ]+PRIVATE KEY-----",
        "private_key",
    ),
    # Passwords in config-like contexts
    (r"""(?i)password\s*[=:]\s*["']?([^\s"'\[\]]{8,})["']?""", "password"),
    # Generic secret/key assignments
    (
        r"""(?i)(?:secret|_key|_token|api_key)\s*[=:]\s*["']?([^\s"'\[\]]{8,})["']?""",
        "generic_secret",
    ),
]


class Redactor:
    def __init__(
        self,
        extra_patterns: list[str] | None = None,
        placeholder: str = "[REDACTED]",
    ):
        self.placeholder = placeholder
        self._compiled: list[tuple[re.Pattern[str], str]] = []
        for pattern, category in _BUILTIN_PATTERNS:
            self._compiled.append((re.compile(pattern), category))
        for pattern in extra_patterns or []:
            self._compiled.append((re.compile(pattern), "custom"))

    def _replacement(self, category: str) -> str:
        if self.placeholder == "[REDACTED]":
            return f"[REDACTED:{category}]"
        return self.placeholder

    def redact(self, text: str) -> str:
        result = text
        for pattern, category in self._compiled:
            if pattern.groups > 0:
                # Pattern has capture group -- redact only the captured portion
                def _sub(m: re.Match[str], cat: str = category) -> str:
                    full = m.group(0)
                    captured = m.group(1)
                    return full.replace(captured, self._replacement(cat))

                result = pattern.sub(_sub, result)
            else:
                replacement = self._replacement(category)
                result = pattern.sub(replacement, result)
        return result
