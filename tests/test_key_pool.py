"""Key pool rotation, cooldowns, and health snapshot. No network."""

from __future__ import annotations

import pytest

from app.core.logging import mask_secret
from app.llm.key_pool import KeyPool


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _pool(clock: _Clock | None = None) -> KeyPool:
    return KeyPool(
        ["AIza_test_key_one_xxxx", "AIza_test_key_two_yyyy"],
        time_fn=clock,
    )


@pytest.mark.asyncio
async def test_acquire_prefers_least_recently_used() -> None:
    pool = _pool()
    first = await pool.acquire()
    second = await pool.acquire()
    assert first is not None and first.index == 0
    assert second is not None and second.index == 1
    third = await pool.acquire()
    assert third is not None and third.index == 0


@pytest.mark.asyncio
async def test_rate_limit_cools_key_and_next_acquire_skips_it() -> None:
    clock = _Clock()
    pool = _pool(clock)
    first = await pool.acquire()
    assert first is not None and first.index == 0
    await pool.report_rate_limit(0)
    nxt = await pool.acquire()
    assert nxt is not None and nxt.index == 1
    status = pool.status()
    assert status["cooling_down"] == 1
    assert status["available"] == 1
    assert status["disabled"] == 0


@pytest.mark.asyncio
async def test_rate_limit_uses_retry_after() -> None:
    clock = _Clock()
    pool = _pool(clock)
    await pool.acquire()
    await pool.report_rate_limit(0, retry_after=5)
    assert (await pool.acquire()).index == 1  # type: ignore[union-attr]
    clock.now += 5.1
    again = await pool.acquire()
    assert again is not None and again.index == 0


@pytest.mark.asyncio
async def test_auth_error_disables_key_for_process() -> None:
    pool = _pool()
    await pool.acquire()
    await pool.report_auth_error(0)
    nxt = await pool.acquire()
    assert nxt is not None and nxt.index == 1
    status = pool.status()
    assert status["disabled"] == 1
    assert status["available"] == 1
    # Success must not resurrect a disabled key.
    await pool.report_success(0)
    still = await pool.acquire()
    assert still is not None and still.index == 1


@pytest.mark.asyncio
async def test_all_unavailable_returns_none() -> None:
    pool = KeyPool(["only-one-key-abcdefgh"])
    lease = await pool.acquire()
    assert lease is not None
    await pool.report_auth_error(0)
    assert await pool.acquire() is None
    status = pool.status()
    assert status["available"] == 0
    assert status["disabled"] == 1


@pytest.mark.asyncio
async def test_success_clears_transient_cooldown() -> None:
    clock = _Clock()
    pool = _pool(clock)
    await pool.acquire()
    await pool.report_rate_limit(0)
    await pool.report_success(0)
    nxt = await pool.acquire()
    # Key 0 is usable again and is LRU vs unused key 1? key 0 was used then
    # cooled then cleared; key 1 never used so last_used=0. Acquire prefers 1.
    assert nxt is not None and nxt.index == 1
    again = await pool.acquire()
    assert again is not None and again.index == 0


def test_status_masks_keys() -> None:
    raw = "AIza_test_key_one_xxxx"
    pool = KeyPool([raw])
    status = pool.status()
    assert status["configured"] is True
    assert status["keys"] == [mask_secret(raw)]
    assert raw not in str(status)
    assert status["available"] == 1
    assert status["cooling_down"] == 0
    assert status["disabled"] == 0


def test_empty_pool_status() -> None:
    pool = KeyPool([])
    status = pool.status()
    assert status == {
        "configured": False,
        "keys": [],
        "available": 0,
        "cooling_down": 0,
        "disabled": 0,
    }
