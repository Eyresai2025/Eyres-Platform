"""Last-resort exception boundary for the Qt event loop."""

from __future__ import annotations

import logging
import sys
import traceback
from typing import Callable


def install_exception_hook(show_error: Callable[[str], None] | None = None) -> None:
    logger = logging.getLogger("eyres.crash")

    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        incident = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("Unhandled application error\n%s", incident)
        if show_error:
            try:
                show_error("An unexpected error occurred. Details were written to the application log.")
            except Exception:
                logger.exception("Unable to show the crash notification")

    sys.excepthook = handle
