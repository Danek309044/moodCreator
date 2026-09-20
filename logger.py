"""Centralised logging. Writes to data/app.log with rotation, and to stderr."""

import logging
import logging.handlers
import os

from config import DATA_DIR


LOG_FILE = os.path.join(DATA_DIR, "app.log")

_configured = False


def setup() -> None:
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        fh = logging.handlers.RotatingFileHandler(
            LOG_FILE,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setLevel(logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(ch)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup()
    return logging.getLogger(name)