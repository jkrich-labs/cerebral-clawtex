# src/cerebral_clawtex/redact.py
from __future__ import annotations

import re


_BUILTIN_PATTERNS: list[tuple[str, str]] = [
    # API keys — Anthropic / OpenAI
    (r"sk-(?:proj-|ant-api\d{2}-)?[a-zA-Z0-9_-]{20,}", "api_key"),
    # AWS access key IDs
    (r"AKIA[0-9A-Z]{16}", "api_key"),
    # GitHub tokens (PAT, OAuth, fine-grained)
    (r"ghp_[a-zA-Z0-9]{30,}", "api_key"),
    (r"gho_[a-zA-Z0-9]{30,}", "api_key"),
    (r"ghs_[a-zA-Z0-9]{30,}", "api_key"),
    (r"ghr_[a-zA-Z0-9]{30,}", "api_key"),
    (r"github_pat_[a-zA-Z0-9_]{22,}", "api_key"),
    # GitLab personal access tokens
    (r"glpat-[a-zA-Z0-9_-]{20,}", "api_key"),
    # Slack tokens
    (r"xox[bpors]-[a-zA-Z0-9-]{10,}", "api_key"),
    # Slack webhook URLs
    (r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[a-zA-Z0-9]+", "webhook"),
    # npm tokens
    (r"npm_[a-zA-Z0-9]{36}", "api_key"),
    # PyPI tokens
    (r"pypi-[a-zA-Z0-9_-]{100,}", "api_key"),
    # Google API keys
    (r"AIza[a-zA-Z0-9_-]{35}", "api_key"),
    # Stripe keys
    (r"(?:sk|pk)_(?:test|live)_[a-zA-Z0-9]{20,}", "api_key"),
    # Twilio keys
    (r"SK[a-f0-9]{32}", "api_key"),
    # SendGrid keys
    (r"SG\.[a-zA-Z0-9_-]{22,}\.[a-zA-Z0-9_-]{22,}", "api_key"),
    # Azure storage keys (base64, typically 88 chars)
    (r"""(?i)(?:AccountKey|azure[_-]?(?:storage[_-]?)?key)\s*[=:]\s*["']?([a-zA-Z0-9+/=]{44,})["']?""", "api_key"),
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
                    start, end = m.span(1)
                    rel_start = start - m.start(0)
                    rel_end = end - m.start(0)
                    return full[:rel_start] + self._replacement(cat) + full[rel_end:]

                result = pattern.sub(_sub, result)
            else:
                replacement = self._replacement(category)
                result = pattern.sub(replacement, result)
        return result
