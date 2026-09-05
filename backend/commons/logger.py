"""Central logging setup for the LRN backend.

Exposes ``logger(__name__)`` used by every module, per Eigi backend standards. Handlers are
attached once to the root ``lrn`` logger so child loggers inherit them without duplicating output.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_ROOT_LOGGER_NAME = "lrn"
_configured = False


def _configure_root_logger() -> logging.Logger:
    """
    Configure the shared ``lrn`` root logger exactly once.

    Attaches a stdout handler always, and a rotating file handler when LOG_DIR is writable, so
    container logs work without a mounted volume but persist when one is present.

    Returns:
        logging.Logger: The configured root logger for the application.
    """
    global _configured
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    if _configured:
        return root

    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    root.propagate = False
    formatter = logging.Formatter(_LOG_FORMAT)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    # File logging is opt-in via LOG_DIR. Containers leave it unset and log to stdout, where the
    # container runtime already handles collection, rotation and retention; writing log files
    # inside a container hides them from `docker logs` and fills the image layer instead.
    log_dir = os.getenv("LOG_DIR")
    if log_dir:
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                Path(log_dir) / "lrn.log", maxBytes=10 * 1024 * 1024, backupCount=5
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as error:
            root.warning(f"File logging disabled, could not use LOG_DIR '{log_dir}': {error}")

    _configured = True
    return root


def logger(name: str) -> logging.Logger:
    """
    Return a module-scoped logger attached to the shared application logger.

    Ensures root configuration has run so every module logs with the same format and level.

    Args:
        name: Module name, normally ``__name__``.

    Returns:
        logging.Logger: Logger namespaced under the application root logger.
    """
    _configure_root_logger()
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
