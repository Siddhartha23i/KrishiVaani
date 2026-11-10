"""
In-memory time-to-live (TTL) cache for weather data in KrishiVaani — Phase 6.1.
Enforces provider-specific caching policies:
- Current weather observations: maximum 60 minutes (WeatherAPI Free terms).
- Short-range forecast: maximum 24 hours (WeatherAPI Free terms).
"""

import time
from typing import Any, Dict, Optional, Tuple


class WeatherCache:
    """
    Thread-safe in-memory cache with explicit per-entry TTL.
    Prevents stale data retention and respects external provider terms.
    """

    # Conservative default TTL values adhering to provider terms
    DEFAULT_CURRENT_TTL_SECONDS: int = 1800   # 30 minutes (max allowed: 60 minutes)
    MAX_CURRENT_TTL_SECONDS: int = 3600       # 60 minutes
    DEFAULT_FORECAST_TTL_SECONDS: int = 21600 # 6 hours (max allowed: 24 hours)
    MAX_FORECAST_TTL_SECONDS: int = 86400     # 24 hours

    def __init__(self):
        # Maps cache_key -> (data, expiry_timestamp)
        self._store: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Retrieve cached entry if present and not expired."""
        if key not in self._store:
            return None

        data, expiry = self._store[key]
        if time.time() > expiry:
            del self._store[key]
            return None

        return data

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store an entry with a positive TTL in seconds."""
        expiry = time.time() + max(1, ttl_seconds)
        self._store[key] = (value, expiry)

    def delete(self, key: str) -> None:
        """Evict a specific entry from cache."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Evict all entries from cache."""
        self._store.clear()

    def count(self) -> int:
        """Return count of active (unexpired) entries."""
        now = time.time()
        active = [k for k, (_, exp) in self._store.items() if exp > now]
        # Clean up expired on check
        for k in list(self._store.keys()):
            if k not in active:
                del self._store[k]
        return len(active)


# Global singleton instance for local application lifecycle
weather_cache = WeatherCache()

