"""Packaged-safe application logging setup."""

import logging
import logging.handlers
import os
from typing import Optional


_LOG_HANDLER_MARKER = "_petrophyter_log_handler"
_LOG_PATH_MARKER = "_petrophyter_log_path"
_LOG_FILENAME = "petrophyter.log"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 3


def _default_log_directory() -> str:
    """Return the per-user application-data directory used by packaged Qt apps."""
    from PyQt6.QtCore import QStandardPaths

    return QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )


def configure_logging(log_directory: Optional[os.PathLike | str] = None):
    """Install one UTF-8 rotating file handler on the root logger.

    ``log_directory`` is injectable for deterministic tests. In the packaged
    application it defaults to Qt's per-user ``AppLocalDataLocation``. Any
    filesystem/handler failure is logged as a warning when possible and
    returns ``None`` so logging setup never prevents the application starting.
    Repeated calls for the same directory return the existing handler.
    """
    directory = os.fspath(log_directory) if log_directory is not None else _default_log_directory()
    if not directory:
        logging.getLogger(__name__).warning(
            "Application log directory is unavailable; file logging disabled"
        )
        return None

    log_path = os.path.abspath(os.path.join(directory, _LOG_FILENAME))
    root = logging.getLogger()

    for handler in root.handlers:
        if (
            getattr(handler, _LOG_HANDLER_MARKER, False)
            and getattr(handler, _LOG_PATH_MARKER, None) == log_path
        ):
            return handler

    try:
        os.makedirs(directory, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s"
            )
        )
        setattr(handler, _LOG_HANDLER_MARKER, True)
        setattr(handler, _LOG_PATH_MARKER, log_path)
        root.addHandler(handler)
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)
        return handler
    except (OSError, ValueError) as exc:
        logging.getLogger(__name__).warning(
            "Could not initialize application file logging: %s", exc
        )
        return None
