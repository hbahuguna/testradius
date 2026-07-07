import logging
import sys
import time
from contextlib import contextmanager
from typing import Optional

_LOG_FORMAT = "%(asctime)s | %(name)s | %(levelname)-5s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    root = logging.getLogger("testradius")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler: logging.Handler
    if log_file:
        handler = logging.FileHandler(log_file)
    else:
        handler = logging.StreamHandler(sys.stdout)

    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"testradius.{name}")


@contextmanager
def log_duration(logger: logging.Logger, label: str, **extra: str):
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed = (time.perf_counter() - start) * 1000
        logger.warning("%s failed after %.0fms: %s", label, elapsed, exc)
        raise
    else:
        elapsed = (time.perf_counter() - start) * 1000
        extras = ", ".join(f"{k}={v}" for k, v in extra.items())
        logger.info("%s → ok (%.0fms)%s", label, elapsed, f" [{extras}]" if extras else "")
