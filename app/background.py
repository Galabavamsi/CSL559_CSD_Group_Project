"""Timed jobs that run inside the app (HLD 9.1: "a sweeper job releases expired holds").

One place runs every timed job, so later ones (stuck-order recovery 2.5, automatic replenishment 3.4) are added
here as another loop next to `sweep_loop`. Set BACKGROUND_JOBS=off to run none of them (the tests do).
With several app instances each one runs its own sweeper; that is safe because releasing a hold is a conditional
update (see inventory.service._release), so two sweepers never give the same stock back twice.
"""
import asyncio
import logging

from . import config
from .db import SessionLocal
from .modules.inventory import service as inventory

log = logging.getLogger("darkstore.background")


def sweep_once() -> int:
    """Release every expired hold once. Returns how many were released."""
    with SessionLocal() as db:
        return inventory.sweep_expired(db)


async def sweep_loop() -> None:
    while True:
        await asyncio.sleep(config.SWEEP_INTERVAL_SECONDS)
        try:
            released = await asyncio.to_thread(sweep_once)    # database calls block; keep them off the event loop
            if released:
                log.info("released %s expired holds", released)
        except Exception:
            log.exception("sweep failed; will retry")
