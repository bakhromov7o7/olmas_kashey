from dataclasses import dataclass
from time import monotonic
from typing import Dict, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float, max_items: int = 10000) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._data: Dict[str, CacheEntry[T]] = {}

    def get(self, key: str) -> Optional[T]:
        entry = self._data.get(key)
        if not entry:
            return None
        if entry.expires_at < monotonic():
            self._data.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: T, ttl_seconds: Optional[float] = None) -> None:
        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        if len(self._data) >= self.max_items:
            self._evict_one()
        self._data[key] = CacheEntry(value=value, expires_at=monotonic() + ttl)

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def _evict_one(self) -> None:
        if not self._data:
            return
        oldest_key = min(self._data.items(), key=lambda kv: kv[1].expires_at)[0]
        self._data.pop(oldest_key, None)
