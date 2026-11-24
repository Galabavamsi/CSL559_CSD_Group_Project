"""A demo hub's hands: orders nobody has started are picked and packed, so a demo run from phones alone reaches
delivery.

Between a customer's payment and an agent's trip stands the hub: someone claims the order on the picker's screen,
scans each line and packs the bag. A demo given by one person with a phone has nobody at the hub, and the order
would wait at Confirmed for ever. With DEMO_AUTOPACK on, an order that has waited DEMO_AUTOPACK_SECONDS with no
picker is taken by this module instead.

It does what a picker does, with the same functions: the guarded claim, a scan of every line against its barcode,
"not on shelf" for a line that cannot be scanned (an expired batch), and packing into a free crate slot. So the
stock, the bill, the hold and the events are exactly a person's. A person is never raced: an order they have
claimed is no longer waiting, and the claim here is the same guarded update theirs is.
"""
import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .errors import DomainError
from .models import FulfilmentJob, utcnow
from .modules.pickpack import service as pickpack

log = logging.getLogger("darkstore.demo_hub")

PICKER = "demo-picker"
SLOTS = [f"S-{n:02d}" for n in range(1, 25)]


def _free_slot(db: Session, store_id: int) -> str:
    """A crate slot no packed bag is waiting in at this hub; the last one if, somehow, all are taken."""
    taken = set(db.scalars(select(FulfilmentJob.crate_slot)
                           .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state == "packed")).all())
    return next((slot for slot in SLOTS if slot not in taken), SLOTS[-1])


def _pick_and_pack(db: Session, job: FulfilmentJob) -> FulfilmentJob:
    """Scan every line of an order this module has claimed, and pack it. Commits (the functions it calls do)."""
    for _ in range(40):             # a line that is not on its shelf can be moved to another bin: look again
        db.refresh(job)
        task = next((task for task in job.tasks if task.status == "pending"), None)
        if task is None:
            break
        scanned = pickpack.scan(db, task.id, task.sku.barcode, task.qty - task.scanned_qty, PICKER)
        if not scanned["match"]:
            pickpack.report_short(db, task.id, actor=PICKER, picker_id=PICKER)
    return pickpack.pack(db, job.id, _free_slot(db, job.store_id), actor=PICKER, picker_id=PICKER)


def pack_waiting(db: Session) -> list[str]:
    """Pick and pack every order that has waited long enough with no picker, at every hub, and any this module
    had claimed and not finished. Returns the ids of the orders packed."""
    cutoff = utcnow() - timedelta(seconds=config.DEMO_AUTOPACK_SECONDS)
    waiting = db.scalars(select(FulfilmentJob)
                         .where(FulfilmentJob.state == "created", FulfilmentJob.created_at <= cutoff)
                         .order_by(FulfilmentJob.created_at, FulfilmentJob.id)).all()
    mine = db.scalars(select(FulfilmentJob).where(FulfilmentJob.state == "picking",
                                                  FulfilmentJob.picker_id == PICKER)).all()
    packed = []
    for job in [*mine, *waiting]:
        if job.state == "created":
            if not pickpack.claim(db, job, PICKER):
                db.rollback()       # a person, or another app instance, took it a moment ago
                continue
            db.commit()
        try:
            job = _pick_and_pack(db, job)
        except DomainError as error:
            db.rollback()
            log.warning("order %s was not packed by the demo hub: %s", job.order_id, error.message)
            continue
        if job.state == "packed":
            packed.append(job.order_id)
    return packed
