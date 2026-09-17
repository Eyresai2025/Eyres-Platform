"""Qt thread-pool adapter for non-UI work.

Widgets must still be created and changed on the GUI thread. Use ``BackgroundTask``
for filesystem, database, validation, and model metadata operations.
"""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PyQt5 import QtCore


class TaskSignals(QtCore.QObject):
    succeeded = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()


class BackgroundTask(QtCore.QRunnable):
    def __init__(self, operation: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.operation = operation
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            result = self.operation(*self.args, **self.kwargs)
        except Exception:
            self.signals.failed.emit(traceback.format_exc())
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()
