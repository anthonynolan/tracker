"""Logging setup: timestamped entries for uvicorn + the tracker app."""

import json
import logging.config
from pathlib import Path

LOG_CONFIG_PATH = Path(__file__).resolve().parent / "log_config.json"

with open(LOG_CONFIG_PATH, encoding="utf-8") as _fh:
    LOGGING_CONFIG = json.load(_fh)


def configure_logging() -> None:
    logging.config.dictConfig(LOGGING_CONFIG)
