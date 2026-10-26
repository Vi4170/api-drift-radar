"""Logging setup with a redaction filter so secrets never reach log output."""

import logging
import re

_PATTERNS = [
    # Authorization / API key style headers and bearer tokens
    (re.compile(r"(?i)(bearer\s+)[a-z0-9\-._~+/]+=*"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)\b(authorization|x-api-key|api[_-]?key|password|secret|token)(\"?\s*[:=]\s*\"?)[^\s\",}]+"
        ),
        r"\1\2[REDACTED]",
    ),
    # Credentials embedded in connection strings: scheme://user:pass@host
    (re.compile(r"([a-z][a-z0-9+.\-]*://[^:/\s]+:)[^@/\s]+@", re.I), r"\1[REDACTED]@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # httpx logs full request URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors").setLevel(logging.WARNING)  # one line per job run otherwise
