"""Run a source-derived pipeline proof off the GUI thread."""
from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from ..experiments.pipeline_proof import verify


class ProofSignals(QObject):
    finished = Signal(str, str)


class ProofWorker(QRunnable):
    def __init__(self, candidate, output, key):
        super().__init__()
        self.candidate = candidate
        self.output = output
        self.key = key
        self.signals = ProofSignals()

    @Slot()
    def run(self):
        try:
            path = verify(self.candidate, self.output)
            message = f"Equivalence passed after {self.candidate.model.stages} clock edges. Candidate and proof saved in {path.parent}."
        except Exception as error:
            message = f"Verification did not finish successfully. {error}"
        self.signals.finished.emit(self.key, message)
