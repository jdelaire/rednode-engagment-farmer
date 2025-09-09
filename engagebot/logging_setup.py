from __future__ import annotations

import json
import logging
import sys
from typing import Any

_configured = False


def _build_json_formatter() -> logging.Formatter:
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
            payload: dict[str, Any] = {
                "level": record.levelname,
                "name": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exc_info"] = self.formatException(record.exc_info)
            return json.dumps(payload, ensure_ascii=False)

    return JsonFormatter()


def setup_logging(json_logs: bool = False, level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter: logging.Formatter
    if json_logs:
        formatter = _build_json_formatter()
    else:
        formatter = logging.Formatter(
            fmt="%(levelname)s | %(name)s | %(message)s",
        )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

