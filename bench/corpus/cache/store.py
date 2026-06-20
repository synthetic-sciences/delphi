"""In-memory cache with LRU-style eviction."""

from collections import OrderedDict


class CacheStore:
    """A bounded key/value cache that evicts the least-recently-used entry."""

    def __init__(self, capacity: int = 128) -> None:
        self.capacity = capacity
        self._data: OrderedDict = OrderedDict()

    def get(self, key: str):
        """Return a value and mark it most-recently-used."""
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def set(self, key: str, value) -> None:
        """Insert/update a value, evicting if over capacity."""
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self.evict()

    def evict(self) -> None:
        """Remove the least-recently-used entry."""
        if self._data:
            self._data.popitem(last=False)
