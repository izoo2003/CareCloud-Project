"""Gemini API key rotation with cooldowns. Failover only — not quota evasion."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.core.logging import mask_secret

logger = logging.getLogger(__name__)

DEFAULT_RATE_LIMIT_COOLDOWN_S = 60.0
SERVER_ERROR_COOLDOWN_S = 10.0


@dataclass(frozen=True)
class KeyLease:
    """A key the caller may use for one attempt. Report the outcome afterward."""

    index: int
    key: str
    masked: str


@dataclass
class _KeyState:
    index: int
    key: str
    masked: str
    cooldown_until: float = 0.0
    disabled: bool = False
    last_used: float = 0.0


class KeyPool:
    """In-process key pool. Least-recently-used among keys that are not cooling or disabled."""

    def __init__(
        self,
        keys: list[str],
        *,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._now = time_fn or time.monotonic
        self._lock = asyncio.Lock()
        self._keys: list[_KeyState] = [
            _KeyState(index=i, key=raw, masked=mask_secret(raw))
            for i, raw in enumerate(keys)
            if raw
        ]

    @property
    def size(self) -> int:
        """Number of configured keys (including disabled / cooling)."""
        return len(self._keys)

    async def acquire(self) -> KeyLease | None:
        """Return the least-recently-used available key, or None if none can be used."""
        async with self._lock:
            now = self._now()
            available = [
                state
                for state in self._keys
                if not state.disabled and state.cooldown_until <= now
            ]
            if not available:
                return None
            available.sort(key=lambda state: (state.last_used, state.index))
            chosen = available[0]
            chosen.last_used = now
            return KeyLease(index=chosen.index, key=chosen.key, masked=chosen.masked)

    async def report_success(self, index: int) -> None:
        """Clear a transient cooldown after a good response."""
        async with self._lock:
            state = self._by_index(index)
            if state is None or state.disabled:
                return
            state.cooldown_until = 0.0

    async def report_rate_limit(self, index: int, retry_after: float | None = None) -> None:
        """Cool a key after HTTP 429. Uses Retry-After when present, else 60s."""
        seconds = (
            retry_after
            if retry_after is not None and retry_after > 0
            else DEFAULT_RATE_LIMIT_COOLDOWN_S
        )
        await self._cooldown(index, seconds, reason="rate_limited")

    async def report_server_error(self, index: int) -> None:
        """Cool a key for 10s after 5xx, timeout, or connection failure."""
        await self._cooldown(index, SERVER_ERROR_COOLDOWN_S, reason="server_error")

    async def report_auth_error(self, index: int) -> None:
        """Disable a key for the process lifetime after 401/403."""
        async with self._lock:
            state = self._by_index(index)
            if state is None:
                return
            state.disabled = True
            logger.error(
                "gemini_key_disabled",
                extra={"key_index": state.index, "key": state.masked, "reason": "auth"},
            )

    def status(self) -> dict[str, Any]:
        """Masked snapshot for GET /health. Never includes raw keys."""
        now = self._now()
        available = 0
        cooling_down = 0
        disabled = 0
        for state in self._keys:
            if state.disabled:
                disabled += 1
            elif state.cooldown_until > now:
                cooling_down += 1
            else:
                available += 1
        return {
            "configured": bool(self._keys),
            "keys": [state.masked for state in self._keys],
            "available": available,
            "cooling_down": cooling_down,
            "disabled": disabled,
        }

    async def _cooldown(self, index: int, seconds: float, *, reason: str) -> None:
        async with self._lock:
            state = self._by_index(index)
            if state is None or state.disabled:
                return
            state.cooldown_until = self._now() + seconds
            logger.warning(
                "gemini_key_failover",
                extra={
                    "key_index": state.index,
                    "key": state.masked,
                    "reason": reason,
                    "cooldown_s": seconds,
                },
            )

    def _by_index(self, index: int) -> _KeyState | None:
        if 0 <= index < len(self._keys):
            return self._keys[index]
        return None


_pool: KeyPool | None = None


def get_key_pool() -> KeyPool:
    """Process-wide pool, created from GEMINI_API_KEYS on first use."""
    global _pool
    if _pool is None:
        _pool = KeyPool(get_settings().gemini_key_list)
    return _pool


def reset_key_pool(pool: KeyPool | None = None) -> None:
    """Replace or clear the singleton. Used at startup and in tests."""
    global _pool
    _pool = pool
