"""One worker mechanism; result handlers run in the GUI thread."""
import logging
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class WorkerSignals(QObject):
    completed = Signal(object, object)


class Worker(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.operation()
        except Exception as error:
            logging.getLogger(__name__).exception('Desktop operation failed')
            self.signals.completed.emit(None, error)
        else:
            self.signals.completed.emit(result, None)


class TaskRunner(QObject):
    busy_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.busy = False

    def start(self, operation, success, failure):
        if self.busy:
            return
        self.busy = True
        self.success, self.failure = success, failure
        self.worker = Worker(operation)
        self.worker.signals.completed.connect(self._completed)
        self.busy_changed.emit(True)
        QThreadPool.globalInstance().start(self.worker)

    @Slot(object, object)
    def _completed(self, result, error):
        success, failure = self.success, self.failure
        self.worker = None
        self.busy = False
        self.busy_changed.emit(False)
        if error is None:
            success(result)
        else:
            failure(error)
