"""Logging: entries carry timestamps, config holds no secrets."""

import json
import logging

from backend.logging_config import LOGGING_CONFIG, configure_logging


def _renders_with_timestamp(logger_name: str, msg: str = "hello",
                            args=None) -> None:
    configure_logging()
    logger: logging.Logger | None = logging.getLogger(logger_name)
    while logger is not None and not logger.handlers:
        logger = logger.parent
    assert logger is not None and logger.handlers, logger_name
    record = logging.LogRecord(logger_name, logging.INFO, __file__, 1,
                               msg, args, None)
    rendered = logger.handlers[0].format(record)
    assert rendered[:4].isdigit(), rendered


def test_timestamped_entries():
    _renders_with_timestamp("uvicorn.error")
    _renders_with_timestamp("tracker")
    _renders_with_timestamp("uvicorn.access", "%s - \"%s %s HTTP/%s\" %d",
                            ("1.2.3.4:5", "GET", "/health", "1.1", 200))


def test_colors_when_forced():
    from uvicorn.logging import AccessFormatter, DefaultFormatter

    plain = DefaultFormatter("%(levelprefix)s %(message)s", use_colors=True)
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hi", None, None)
    assert "\x1b[" in plain.format(rec)
    access = AccessFormatter("%(client_addr)s %(status_code)s", use_colors=True)
    rec2 = logging.LogRecord("y", logging.INFO, __file__, 1,
                             "%s - \"%s %s HTTP/%s\" %d",
                             ("1.2.3.4:5", "GET", "/health", "1.1", 200), None)
    assert "\x1b[" in access.format(rec2)


def test_config_holds_no_secrets():
    assert "MODEL_API_KEY" not in json.dumps(LOGGING_CONFIG)
