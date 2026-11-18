"""Fulfilment Orchestrator (HLD service 4) and Rider Handoff Adapter (service 11).

Turns a paid order into a fulfilment job with pick tasks, and tracks the job until a rider
takes the bag:   created -> picking -> packed -> handed_over   (or cancelled).
"""
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ... import config, events
from ...errors import DomainError, not_found
from ...models import FulfilmentJob, PickTask, Reservation, ReservationLine, Store, utcnow
from ..inventory import service as inventory

ACTIVE_STATES = ("created", "picking")


@events.subscribe("order.paid")
def on_order_paid(db: Session, store_id: int | None, payload: dict) -> None:
    reservation = db.get(Reservation, payload["reservation_id"])
    if reservation is not None:
        create_job(db, reservation)


def create_job(db: Session, reservation: Reservation) -> FulfilmentJob:
    """Create the job and its pick tasks for a paid order. Does not commit."""
    existing = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == reservation.order_id))
    if existing is not None:
        return existing
    job = FulfilmentJob(order_id=reservation.order_id, reservation_id=reservation.id,
                        store_id=reservation.store_id, state="created")
    db.add(job)
    db.flush()
    for line in reservation.lines:
        add_pick_tasks(db, job, line.sku_id, line.qty)
    resequence(db, job)
    events.publish(db, "fulfilment.state_changed", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "state": job.state})
    refresh_store_load(db, job.store_id)
    return job


def add_pick_tasks(db: Session, job: FulfilmentJob, sku_id: int, qty: int,
                   exclude_item_ids: tuple[int, ...] = ()) -> int:
    """Allocate bins for `qty` units and create one pick task per bin.
    Returns the quantity that could not be found anywhere (recorded as a 'short' task)."""
    picks, shortfall = inventory.allocate(db, job.store_id, sku_id, qty, exclude_item_ids)
    for item, take in picks:
        db.add(PickTask(job_id=job.id, sku_id=sku_id, stock_item_id=item.id, bin_id=item.bin_id,
                        qty=take, status="pending"))
    if shortfall:
        db.add(PickTask(job_id=job.id, sku_id=sku_id, qty=shortfall, status="short"))
        inventory.unreserve(db, job.store_id, sku_id, shortfall)
    db.flush()
    return shortfall


def resequence(db: Session, job: FulfilmentJob) -> None:
    """Number the tasks in walking order (nearest bin first) - the pick path from FR-4."""
    tasks = db.scalars(select(PickTask).where(PickTask.job_id == job.id)).all()
    ordered = sorted(tasks, key=lambda t: (t.bin.walk_seq if t.bin else 10**6, t.id))
    for position, task in enumerate(ordered, start=1):
        task.seq = position
    db.flush()
    db.refresh(job)


def refresh_store_load(db: Session, store_id: int) -> None:
    """Mark the store busy when too many orders are waiting, and open again when the queue clears."""
    store = db.get(Store, store_id)
    if store is None or store.status == "closed":
        return
    backlog = db.scalar(
        select(func.count()).select_from(FulfilmentJob)
        .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state.in_(ACTIVE_STATES))
    )
    new_status = "busy" if backlog > config.BUSY_BACKLOG_THRESHOLD else "open"
    if new_status != store.status:
        store.status = new_status
        events.publish(db, "store.status_changed", store_id, {"status": new_status, "backlog": backlog})


def get_job(db: Session, job_id: int) -> FulfilmentJob:
    job = db.get(FulfilmentJob, job_id)
    if job is None:
        raise not_found("Fulfilment job", job_id)
    return job


def list_jobs(db: Session, store_id: int, state: str | None = None) -> list[FulfilmentJob]:
    query = select(FulfilmentJob).where(FulfilmentJob.store_id == store_id)
    if state:
        query = query.where(FulfilmentJob.state == state)
    return list(db.scalars(query.order_by(FulfilmentJob.id.desc()).limit(50)).all())


def hold_if_picking(db: Session, job: FulfilmentJob) -> bool:
    """Before changing a job that is being picked, take it, and read it again as it is now.

    The UPDATE matches only while the job is still `picking`, and keeps the job until this transaction ends, so a
    cancel arriving at the same moment waits for the change and then sees it. Without this, a scan, an empty-shelf
    report or a pack that read the job just before a cancel would act on a cancelled order, and a hold could be
    given back twice. Returns False, having changed nothing, when the job is no longer `picking`.
    Does not commit."""
    taken = db.execute(
        update(FulfilmentJob)
        .where(FulfilmentJob.id == job.id, FulfilmentJob.state == "picking")
        .values(state="picking")      # changes nothing; task 2.5 will set last_activity_at here instead
        .execution_options(synchronize_session=False)
    ).rowcount == 1
    if taken:
        db.expire_all()               # what this session read before the job was ours may be out of date
    else:
        db.rollback()
    db.refresh(job)
    return taken


def cancel(db: Session, job_id: int, reason: str) -> FulfilmentJob:
    """Cancel a paid order before it is packed (task 2.3): the customer changed their mind, or the payment was
    reversed. Commits.

    Nothing leaves `qty_on_hand` until packing, so this only gives the holds back. Units already scanned into a tote
    go back on their shelves, and the books never counted them as gone. The state change is one conditional UPDATE,
    like the claim, so two cancels at once, or a cancel and a pack, cannot both win and no hold is given back twice.
    Cancelling a cancelled order again is safe and returns it; a packed order is a return, which is not built."""
    job = get_job(db, job_id)
    won = db.execute(
        update(FulfilmentJob)
        .where(FulfilmentJob.id == job_id, FulfilmentJob.state.in_(ACTIVE_STATES))
        .values(state="cancelled")
        .execution_options(synchronize_session=False)
    ).rowcount == 1
    if not won:
        db.rollback()
        db.refresh(job)
        if job.state == "cancelled":
            return job                                          # safe to retry
        raise DomainError(409, "too_late", f"This order is already {job.state.replace('_', ' ')}. Taking it back "
                                           "would be a return, which is not built.")
    db.expire_all()                     # read the lines as they are now that the job is ours

    released: dict[int, int] = defaultdict(int)
    for task in job.tasks:
        # A `short` line gave its hold back when it was dropped; a `reallocated` line was replaced by new lines.
        if task.status in ("pending", "picked"):
            inventory.unreserve(db, job.store_id, task.sku_id, task.qty)
            released[task.sku_id] += task.qty
            task.status = "cancelled"
    db.get(Reservation, job.reservation_id).status = "cancelled"
    db.flush()

    for sku_id in released:
        events.publish(db, "stock.changed", job.store_id, {"sku_id": sku_id, "cause": "cancelled"})
    events.publish(db, "fulfilment.state_changed", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "state": "cancelled"})
    events.publish(db, "order.cancelled", job.store_id,           # the Order service refunds from this
                   {"order_id": job.order_id, "job_id": job.id, "reason": reason})
    refresh_store_load(db, job.store_id)
    db.commit()
    return job


def handover(db: Session, job_id: int) -> FulfilmentJob:
    """Rider Handoff: the rider has collected the packed bag."""
    job = get_job(db, job_id)
    if job.state == "handed_over":
        return job
    if job.state != "packed":
        raise DomainError(409, "not_packed", f"Job is {job.state}; only a packed order can be handed to a rider")
    job.state = "handed_over"
    job.handed_at = utcnow()
    events.publish(db, "fulfilment.state_changed", job.store_id,
                   {"job_id": job.id, "order_id": job.order_id, "state": job.state})
    db.commit()
    return job


def job_view(job: FulfilmentJob) -> dict:
    def seconds(start, end):
        return round((end - start).total_seconds(), 1) if start and end else None

    return {
        "job_id": job.id,
        "order_id": job.order_id,
        "store_id": job.store_id,
        "state": job.state,
        "picker_id": job.picker_id,
        "crate_slot": job.crate_slot,
        "created_at": job.created_at.isoformat() + "Z",
        "seconds_to_pack": seconds(job.created_at, job.packed_at),
        "tasks": [
            {
                "task_id": t.id,
                "seq": t.seq,
                "sku_id": t.sku_id,
                "sku": t.sku.name,
                "barcode": t.sku.barcode,
                "bin": t.bin.code if t.bin else None,
                "batch_no": t.stock_item.batch_no if t.stock_item else None,
                "expiry_date": t.stock_item.expiry_date.isoformat() if t.stock_item else None,
                "qty": t.qty,
                "scanned_qty": t.scanned_qty,
                "status": t.status,
                "picked_at": t.picked_at.isoformat() + "Z" if t.picked_at else None,
            }
            for t in sorted(job.tasks, key=lambda t: t.seq)
        ],
    }


# --------------------------------------------------------------------------- KPIs (HLD 12, task 2.1) and attention (2.5)

def percentile(values: list[float], q: float) -> float:
    """The value at index int(q * (n - 1)) of the sorted values: the method the guide asks for (task 2.1)."""
    ordered = sorted(values)
    return ordered[int(q * (len(ordered) - 1))]


def metrics(db: Session, store_id: int) -> dict:
    """Order-to-pack time, fill rate and picker productivity for one store, over the orders that reached the pack
    station in the last KPI_WINDOW_DAYS days. That includes an order packed as `cancelled` because nothing was
    found: it counts as 0 units picked against everything it ordered. Units ordered come from the reservation,
    not the pick tasks, because a re-allocated line is split over two tasks."""
    is_finished = (FulfilmentJob.store_id == store_id,
                   FulfilmentJob.packed_at >= utcnow() - timedelta(days=config.KPI_WINDOW_DAYS))
    finished = db.scalars(select(FulfilmentJob).where(*is_finished)).all()
    packed = [j for j in finished if j.state in ("packed", "handed_over")]
    to_pack = [(j.packed_at - j.created_at).total_seconds() for j in packed]
    claim_to_pack = [(j.packed_at - j.picking_at).total_seconds() for j in packed if j.picking_at]
    units_picked = db.scalar(select(func.coalesce(func.sum(PickTask.qty), 0))
                             .join(FulfilmentJob, FulfilmentJob.id == PickTask.job_id)
                             .where(*is_finished, PickTask.status == "picked"))
    units_ordered = db.scalar(select(func.coalesce(func.sum(ReservationLine.qty), 0))
                              .join(FulfilmentJob, FulfilmentJob.reservation_id == ReservationLine.reservation_id)
                              .where(*is_finished))
    picking_hours = sum((j.packed_at - j.picking_at).total_seconds() for j in finished if j.picking_at) / 3600
    return {
        "orders_packed": len(packed),
        "seconds_to_pack_p50": round(percentile(to_pack, 0.5), 1) if to_pack else None,
        "seconds_to_pack_p90": round(percentile(to_pack, 0.9), 1) if to_pack else None,
        "seconds_claim_to_pack_p90": round(percentile(claim_to_pack, 0.9), 1) if claim_to_pack else None,
        "fill_rate": units_picked / units_ordered if units_ordered else None,
        "items_per_picker_hour": round(units_picked / picking_hours, 1) if picking_hours else None,
    }


def attention(db: Session, store_id: int) -> dict:
    """Orders someone should look at now: still being picked more than PICK_STALL_MINUTES after they were claimed
    (task 2.5). The ops page lists them first.
    shortcut: measured from the claim, not the last scan; task 2.5's last_activity_at would tell a slow picker
    from a dead handheld."""
    now = utcnow()
    jobs = db.scalars(select(FulfilmentJob).where(
        FulfilmentJob.store_id == store_id, FulfilmentJob.state == "picking",
        FulfilmentJob.picking_at < now - timedelta(minutes=config.PICK_STALL_MINUTES))
        .order_by(FulfilmentJob.picking_at)).all()
    return {"stalled": [{"job_id": j.id, "order_id": j.order_id, "picker_id": j.picker_id,
                         "minutes_since_claim": round((now - j.picking_at).total_seconds() / 60, 1)} for j in jobs]}
