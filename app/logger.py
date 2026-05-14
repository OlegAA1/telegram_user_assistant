"""Application logging (stdlib)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(log_file: Path | None = None) -> None:
    root = logging.getLogger()
    if root.handlers:
        return

    fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    root.addHandler(handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        root.addHandler(file_handler)

    root.setLevel(logging.INFO)
