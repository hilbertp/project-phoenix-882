"""Structured logging for the bot.

Console gets a compact human-readable line; the file handler gets JSON-per-line.
All log records may carry structured fields via the `extra` dict; these are
flattened into the JSON output alongside the standard fields.

Use it like:

    from apps.bot.logging_setup import configure_logging, get_logger

    configure_logging(log_dir, level="INFO")
    log = get_logger(__name__)
    log.info("setup detected", extra={"asset": "BTC", "setup_key": "..."})
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_STD_RECORD_FIELDS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "taskName",
}

# Any extra field whose name matches this pattern has its value scrubbed in
# both formatters. Defence in depth -- the API key is loaded on demand and
# kept off the BotConfig object, but if anything ever passes a secret-like
# value through logger.extra= it must not reach the log file.
_SECRET_KEY_RE = re.compile(
    r"(private|secret|passw(or)?d|token|api[_-]?key|wallet[_-]?key|"
    r"signing[_-]?key|mnemonic|seed)",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"


def _maybe_redact(key: str, value: object) -> object:
    return _REDACTED if _SECRET_KEY_RE.search(key) else value


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STD_RECORD_FIELDS or key.startswith("_"):
                continue
            payload[key] = _maybe_redact(key, value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        extras = {
            k: _maybe_redact(k, v) for k, v in record.__dict__.items()
            if k not in _STD_RECORD_FIELDS and not k.startswith("_")
        }
        suffix = ""
        if extras:
            suffix = " " + " ".join(f"{k}={v}" for k, v in extras.items())
        return f"{ts} {record.levelname:<5} {record.name} {record.getMessage()}{suffix}"


_configured = False


def configure_logging(
    log_dir: str | Path | None = None,
    level: str | int = "INFO",
    *,
    filename: str = "bot.log",
) -> None:
    """Wire root handlers once. Idempotent: a second call is a no-op."""
    global _configured
    if _configured:
        return
    root = logging.getLogger()
    root.setLevel(level)
    # Remove default handlers so we control the format.
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(level)
    console.setFormatter(_ConsoleFormatter())
    root.addHandler(console)

    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / filename, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(_JsonFormatter())
        root.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
