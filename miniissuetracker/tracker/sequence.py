"""Human-readable ticket numbers (MIT-1, MIT-2, ...), unique even under concurrent requests."""
import threading


class TicketSequence:
    def __init__(self, start=1):
        self._next = start
        self._lock = threading.Lock()
        self.issued = []

    def _store(self, value):
        """Persist the next value. Separate method so tests can observe interleavings."""
        self._next = value

    def next(self):
        with self._lock:
            current = self._next
            self._store(current + 1)
            self.issued.append(current)
            return current

    def peek(self):
        return self._next
