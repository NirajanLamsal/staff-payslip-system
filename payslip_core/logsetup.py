"""Local error log. It records what went wrong and where, never salary figures or employee names."""
from __future__ import annotations

import logging
import traceback
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR

_logger = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    lg = logging.getLogger("payslip_manager")
    lg.setLevel(logging.INFO)
    lg.propagate = False
    if not lg.handlers:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            h = RotatingFileHandler(LOG_DIR / "payslip_manager.log", maxBytes=500_000, backupCount=2,
                                    encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            lg.addHandler(h)
        except OSError:
            lg.addHandler(logging.NullHandler())
    _logger = lg
    return lg


def log_error(context: str, exc: BaseException) -> None:
    """Log the exception TYPE and code location only (the message may contain cell values)."""
    frames = traceback.extract_tb(exc.__traceback__)
    where = " <- ".join(f"{f.filename.split('/')[-1]}:{f.lineno}" for f in reversed(frames[-4:]))
    get_logger().error("%s: %s at %s", context, type(exc).__name__, where)


def log_info(message: str) -> None:
    get_logger().info(message)
