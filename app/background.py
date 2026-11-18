"""Timed jobs that run inside the app (HLD 9.1: "a sweeper job releases expired holds").

One place runs every timed job, so later ones (stuck-order recovery 2.5, automatic replenishment 3.4) are added
here as another loop next to the ones below, and started in `start_all`. Set BACKGROUND_JOBS=off to run none of
them (the tests do).
With several app instances each one runs its own jobs. That is safe: releasing a hold is a conditional update (see
inventory.service._release), and an expired batch has nothing left to write off the second time.
"""
import asyncio
import logging
from collections.abc import Callable

from . import config
from .db import SessionLocal
from .modules.fulfilment import service as fulfilment
from .modules.inventory import service as inventory

log = logging.getLogger("darkstore.background")


def sweep_once() -> int:
    """Release every expired hold once. Returns how many were released."""
    with SessionLocal() as db:
        return inventory.sweep_expired(db)


def expiry_once() -> dict:
    """Write off expired batches in every store, then flag the ones about to expire."""
    with SessionLocal() as db:
        return {"units_written_off": inventory.expire_stock(db),
                "near_expiry_flagged": inventory.flag_near_expiry(db, config.NEAR_EXPIRY_DAYS)}


def recover_once() -> dict | None:
    """Hand idle orders back to the queue in every store (task 2.5). Returns what changed, or None if nothing did."""
    with SessionLocal() as db:
        result = fulfilment.recover_stalled(db)
    return result if result["released"] or result["needs_attention"] else None


async def _repeat(name: str, job: Callable[[], object], seconds: Callable[[], float], first_run_now: bool) -> None:
    """Run `job` every `seconds()` seconds until cancelled. A failed run is logged and retried next time."""
    if not first_run_now:
        await asyncio.sleep(seconds())
    while True:
        try:
            result = await asyncio.to_thread(job)     # database calls block; keep them off the event loop
            if result:
                log.info("%s: %s", name, result)
        except Exception:
            log.exception("%s failed; will retry", name)
        await asyncio.sleep(seconds())


def sweep_loop():
    return _repeat("released expired holds", sweep_once, lambda: config.SWEEP_INTERVAL_SECONDS, first_run_now=False)


def expiry_loop():
    # Runs once at start-up too, so stock that expired while the app was down is never sold.
    return _repeat("expiry check", expiry_once, lambda: config.EXPIRY_INTERVAL_SECONDS, first_run_now=True)


def stall_loop():
    return _repeat("stalled orders", recover_once, lambda: config.STALL_CHECK_SECONDS, first_run_now=False)


def start_all() -> list[asyncio.Task]:
    """Start every timed job; main.py cancels them on shutdown."""
    return [asyncio.create_task(loop()) for loop in (sweep_loop, expiry_loop, stall_loop)]
