"""A small TTL cache used for task lookups and statistics."""
import threading


class TTLCache:
    def __init__(self, ttl_seconds, clock):
        self.ttl = ttl_seconds
        self.clock = clock
        self._data = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def _now(self):
        return self.clock.now().timestamp()

    def get(self, key):
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            value, expires = entry
            if self._now() >= expires:
                del self._data[key]
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key, value):
        with self._lock:
            self._data[key] = (value, self._now() + self.ttl)

    def invalidate(self, key):
        with self._lock:
            self._data.pop(key, None)

    def invalidate_prefix(self, prefix):
        with self._lock:
            for key in [k for k in self._data if k.startswith(prefix)]:
                del self._data[key]

    def clear(self):
        with self._lock:
            self._data.clear()
