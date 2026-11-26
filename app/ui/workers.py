"""Background worker infrastructure using QRunnable and QThreadPool (Non-Blocking UI)."""

from __future__ import annotations

import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    """Signals emitted by AsyncWorker."""

    finished = Signal(object)
    error = Signal(str)
    progress = Signal(str)


class AsyncWorker(QRunnable):
    """Generic QRunnable executing a callable off the main UI thread."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            detail = f"{exc}\n{traceback.format_exc()}"
            self.signals.error.emit(detail)
