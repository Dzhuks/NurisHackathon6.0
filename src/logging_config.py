"""Centralized logging configuration.

Usage in any script::

    from src.logging_config import setup_logger
    log = setup_logger("script_name")
    log.info("hello")

Default behaviour:
  * Writes to both console and `outputs/logs/<script_name>.log`
  * INFO level by default; override via env LOG_LEVEL=DEBUG
  * Format: HH:MM:SS LEVEL [module] message
  * Each call to setup_logger appends a fresh timestamped header
"""
from __future__ import annotations
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%H:%M:%S"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _PROJECT_ROOT / "outputs" / "logs"


def setup_logger(name: str, *, level: Optional[str] = None,
                 logfile: Optional[Path | str] = None) -> logging.Logger:
    """Return a logger that writes to console and (optionally) a file.

    name        : logger name. By convention pass the script stem.
    level       : log level (default: env LOG_LEVEL or INFO).
    logfile     : explicit path. If None, defaults to outputs/logs/<name>.log.
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    log = logging.getLogger(name)
    log.setLevel(level)
    # Avoid duplicate handlers if setup is called twice in same process
    if log.handlers:
        return log
    log.propagate = False  # don't double-log via root
    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # Console
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    log.addHandler(ch)

    # File
    if logfile is None:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        logfile = _LOG_DIR / f"{name}.log"
    fh = logging.FileHandler(logfile, mode="a", encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)

    log.info("=== run started %s ===", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return log
