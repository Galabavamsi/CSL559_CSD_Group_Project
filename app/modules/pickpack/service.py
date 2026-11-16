"""Pick & Pack Service (HLD service 5): give pickers work, check every scan, pack the order."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ... import events
from ...errors import DomainError, not_found
from ...models import FulfilmentJob, PickTask, Reservation, utcnow
from ..fulfilment import service as fulfilment
from ..inventory import service as inventory


def next_job(db: Session, picker_id: str, store_id: int) -> FulfilmentJob | None:
    """Return the picker's current order, or claim the oldest waiting one (FR-4).

    The claim is a conditional UPDATE, so two pickers asking at the same moment can never get
    the same order.
    """
    current = db.scalar(
        select(FulfilmentJob).where(FulfilmentJob.store_id == store_id, FulfilmentJob.state == "picking",
                                    FulfilmentJob.picker_id == picker_id)
    )
    if current is not None:
        return current
    while True:
        candidate = db.scalar(
            select(FulfilmentJob)
            .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state == "created")
            .order_by(FulfilmentJob.created_at, FulfilmentJob.id)
        )
        if candidate is None:
            return None
        claimed = db.execute(
            update(FulfilmentJob)
            .where(FulfilmentJob.id == candidate.id, FulfilmentJob.state == "created")
            .values(state="picking", picker_id=picker_id, picking_at=utcnow())
            .execution_options(synchronize_session=False)
        )
        if claimed.rowcount == 1:
            db.refresh(candidate)
            events.publish(db, "fulfilment.state_changed", candidate.store_id,
                           {"job_id": candidate.id, "order_id": candidate.order_id, "state": "picking"})
            db.commit()
            return candidate
        db.rollback()   # another picker claimed it first; look for the next one


def task_store_id(db: Session, task_id: int) -> int:
    """Which store a pick task belongs to (used for the permission check). Read-only."""
    task = db.get(PickTask, task_id)
    if task is None:
        raise not_found("Pick task", task_id)
    return db.get(FulfilmentJob, task.job_id).store_id


def _open_task(db: Session, task_id: int) -> tuple[PickTask, FulfilmentJob]:
    task = db.get(PickTask, task_id)
    if task is None:
        raise not_found("Pick task", task_id)
    job = db.get(FulfilmentJob, task.job_id)
    if job.state != "picking":
        raise DomainError(409, "job_not_picking", f"Order is {job.state}; ask for your next task first")
    if task.status != "pending":
        raise DomainError(409, "task_closed", f"This line is already {task.status}")
    return task, job


def scan(db: Session, task_id: int, barcode: str, qty: int) -> dict:
    """Check a barcode scan against the pick task (FR-5). A wrong item changes nothing."""
    task, job = _open_task(db, task_id)
    if barcode != task.sku.barcode:
        return {"match": False, "message": f"Wrong item. This line needs {task.sku.name}."}
    if qty != task.qty:
        return {"match": False, "message": f"Pick {task.qty} units for this line, not {qty}."}
    task.status = "picked"
    db.commit()
    pending = sum(1 for t in job.tasks if t.status == "pending")
    return {"match": True, "message": "Picked.", "lines_left": pending, "job": fulfilment.job_view(job)}


def report_short(db: Session, task_id: int, actor: str = "picker") -> dict:
    """The item is not in the bin. Fix the count, then try another bin; if none has spare
    units, drop the line and free its hold (the refund itself belongs to the Order service)."""
    task, job = _open_task(db, task_id)
    item = task.stock_item
    inventory.write_off_missing(db, item, task.qty, reference=f"job:{job.id}", actor=actor)

    # After the write-off, units not held by anyone else can cover this line.
    level = inventory.get_level(db, job.store_id, task.sku_id)
    spare = max(0, level.qty_on_hand - (level.qty_reserved - task.qty))
    wanted = min(task.qty, spare)
    task.status = "short"
    db.flush()

    found = 0
    if wanted:
        picks, _missing = inventory.allocate(db, job.store_id, task.sku_id, wanted, exclude_item_ids=(item.id,))
        for other, take in picks:
            db.add(PickTask(job_id=job.id, sku_id=task.sku_id, stock_item_id=other.id, bin_id=other.bin_id,
                            qty=take, status="pending"))
            found += take
    lost = task.qty - found
    if found:
        task.status = "reallocated"
        if lost:
            db.add(PickTask(job_id=job.id, sku_id=task.sku_id, qty=lost, status="short"))
    if lost:
        inventory.unreserve(db, job.store_id, task.sku_id, lost)
    db.flush()
    fulfilment.resequence(db, job)
    events.publish(db, "stock.changed", job.store_id, {"sku_id": task.sku_id, "cause": "not_found"})
    db.commit()
    if found and not lost:
        message = "Count corrected. Pick this line from another bin."
    elif found:
        message = f"Count corrected. Only {found} more found in another bin; {lost} dropped from the order."
    else:
        message = "Count corrected. No other stock, so this line is dropped from the order."
    return {"reallocated": found, "dropped": lost, "message": message, "job": fulfilment.job_view(job)}


def pack(db: Session, job_id: int, crate_slot: str, actor: str = "packer") -> FulfilmentJob:
    """Mark the order packed (FR-6). This is the moment the sale is committed: units leave
    on-hand stock and the hold on them ends."""
    job = fulfilment.get_job(db, job_id)
    if job.state in ("packed", "handed_over"):
        return job
    if job.state != "picking":
        raise DomainError(409, "job_not_picking", f"Order is {job.state}; it cannot be packed")
    if any(t.status == "pending" for t in job.tasks):
        raise DomainError(409, "lines_pending", "Scan or report every line before packing")

    picked = [t for t in job.tasks if t.status == "picked"]
    for task in picked:
        inventory.commit_sale(db, task, reference=f"order:{job.order_id}", actor=actor)

    reservation = db.get(Reservation, job.reservation_id)
    reservation.status = "fulfilled"
    job.state = "packed" if picked else "cancelled"     # nothing found at all -> nothing to deliver
    job.crate_slot = crate_slot if picked else None
    job.packed_at = utcnow()
    db.flush()

    for sku_id in {t.sku_id for t in picked}:
        events.publish(db, "stock.changed", job.store_id, {"sku_id": sku_id, "cause": "sale"})
    events.publish(db, "fulfilment.state_changed", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "state": job.state})
    if picked:
        events.publish(db, "order.ready_for_pickup", job.store_id,
                       {"job_id": job.id, "order_id": job.order_id, "crate_slot": crate_slot})
    fulfilment.refresh_store_load(db, job.store_id)
    db.commit()
    return job
