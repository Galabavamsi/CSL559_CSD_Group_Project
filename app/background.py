"""Timed jobs that run inside the app (HLD 9.1: "a sweeper job releases expired holds").

One place runs every timed job: each is a loop below, listed in `loops()` and started in `start_all`. Set
BACKGROUND_JOBS=off to run none of them (the tests do).
With several app instances each one runs its own jobs. That is safe: releasing a hold is a conditional update (see
inventory.service._release), and an expired batch has nothing left to write off the second time. Replenishment is
the exception: its lock is per process, so set REPLENISHMENT_INTERVAL_MINUTES=0 on every instance but one.
"""
import asyncio
import logging
from collections.abc import Callable

from . import config, demo_supply
from .db import SessionLocal
from .modules.delivery import service as delivery
from .modules.fulfilment import service as fulfilment
from .modules.inventory import service as inventory
from .modules.replenishment import service as replenishment

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


def replenish_once() -> list[dict] | None:
    """Reorder for every open store (task 3.4). Returns the stores where something was ordered or cut, or None."""
    with SessionLocal() as db:
        changed = [row for row in replenishment.run_all(db) if row["transfer_order_id"] or row["capped"]]
    return changed or None


def delivery_once() -> int | None:
    """Form the trips that have become due because an order has waited long enough (docs/DESIGN.md, section 4.1).
    Packing an order and an agent coming free check at once; only the passing of time needs this. Returns how many
    trips were formed, or None."""
    with SessionLocal() as db:
        return delivery.form_all(db) or None


def demo_supply_once() -> list[dict] | None:
    """Bring demo lots to hubs that are nearly out (app/demo_supply.py). Returns what arrived, or None."""
    with SessionLocal() as db:
        return demo_supply.top_up(db) or None


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


def replenish_loop():
    # The first run waits one interval after the app starts (pressing Reset demo data does not restart it).
    return _repeat("replenishment", replenish_once, lambda: config.REPLENISHMENT_INTERVAL_MINUTES * 60,
                   first_run_now=False)


def delivery_loop():
    return _repeat("trips formed", delivery_once, lambda: config.DELIVERY_CHECK_SECONDS, first_run_now=False)


def demo_supply_loop():
    # Runs at start-up too: a hub opened by this deploy has stock before anyone opens its shop.
    return _repeat("demo farms delivered", demo_supply_once, lambda: config.DEMO_SUPPLY_INTERVAL_MINUTES * 60,
                   first_run_now=True)


def loops() -> list[Callable]:
    """The timed jobs to start. Replenishment is left out when REPLENISHMENT_INTERVAL_MINUTES is 0 or less, and the
    demo farms unless DEMO_SUPPLY is on."""
    jobs = [sweep_loop, expiry_loop, stall_loop, delivery_loop]
    if config.REPLENISHMENT_INTERVAL_MINUTES > 0:
        jobs.append(replenish_loop)
    if config.DEMO_SUPPLY and config.DEMO_SUPPLY_INTERVAL_MINUTES > 0:
        jobs.append(demo_supply_loop)
    return jobs


def start_all() -> list[asyncio.Task]:
    """Start every timed job; main.py cancels them on shutdown."""
    return [asyncio.create_task(loop()) for loop in loops()]
