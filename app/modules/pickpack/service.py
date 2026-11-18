"""Pick & Pack Service (HLD service 5): give pickers work, check every scan, pack the order."""
from string import ascii_uppercase

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ... import config, events, metrics
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
        if _claim(db, candidate, picker_id):
            db.commit()
            return candidate
        db.rollback()   # another picker claimed it first; look for the next one


def _claim(db: Session, job: FulfilmentJob, picker_id: str, tote: str | None = None) -> bool:
    """Give a waiting order to this picker: a conditional UPDATE, so two pickers asking at the same moment can never
    get the same order. Returns False, having changed nothing, if someone else got it first. Does not commit."""
    now = utcnow()
    claimed = db.execute(
        update(FulfilmentJob)
        .where(FulfilmentJob.id == job.id, FulfilmentJob.state == "created")
        .values(state="picking", picker_id=picker_id, picking_at=now, last_activity_at=now, tote=tote)
        .execution_options(synchronize_session=False)
    ).rowcount == 1
    if claimed:
        db.refresh(job)
        events.publish(db, "fulfilment.state_changed", job.store_id,
                       {"job_id": job.id, "order_id": job.order_id, "state": "picking"})
    return claimed


def next_batch(db: Session, picker_id: str, store_id: int) -> list[FulfilmentJob]:
    """Single-order picking off-peak, batch picking at peak (HLD 13.1, task 2.6). Commits.

    A picker who still has orders being picked gets those back. Otherwise: with at least BATCH_PICK_BACKLOG orders
    waiting, claim the oldest BATCH_SIZE, each with the same conditional UPDATE as next_job and its own tote letter
    (A, B, C), so one walk through the store serves them all; with fewer waiting, claim one, so an order never waits
    for a batch to fill. Scanning and packing stay per line and per order."""
    mine = list(db.scalars(
        select(FulfilmentJob)
        .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state == "picking",
               FulfilmentJob.picker_id == picker_id)
        .order_by(FulfilmentJob.tote, FulfilmentJob.id)).all())
    if mine:
        letters = iter(letter for letter in ascii_uppercase if letter not in {job.tote for job in mine})
        for job in mine:
            if job.tote is None:          # claimed one at a time through next-task: give it a tote too
                job.tote = next(letters)
        db.commit()
        return sorted(mine, key=lambda job: job.tote)
    waiting = db.scalars(
        select(FulfilmentJob)
        .where(FulfilmentJob.store_id == store_id, FulfilmentJob.state == "created")
        .order_by(FulfilmentJob.created_at, FulfilmentJob.id)).all()
    wanted = config.BATCH_SIZE if len(waiting) >= config.BATCH_PICK_BACKLOG else 1
    claimed: list[FulfilmentJob] = []
    for candidate in waiting:
        if len(claimed) == wanted:
            break
        if _claim(db, candidate, picker_id, tote=ascii_uppercase[len(claimed)]):
            claimed.append(candidate)     # a lost race changes nothing; try the next oldest
    db.commit()
    return claimed


def batch_view(jobs: list[FulfilmentJob]) -> dict:
    """What a picker's handheld shows for a batch: which order goes in which tote, and one route through the store
    with every line still to pick from all of them, in walking order (task 2.6)."""
    route = [{"tote": job.tote, "job_id": job.id, "order_id": job.order_id, "task_id": task.id, "bin": task.bin.code,
              "walk_seq": task.bin.walk_seq, "sku_id": task.sku_id, "sku": task.sku.name, "barcode": task.sku.barcode,
              "qty": task.qty, "scanned_qty": task.scanned_qty}
             for job in jobs for task in job.tasks if task.status == "pending"]
    route.sort(key=lambda line: (line["walk_seq"], line["tote"], line["task_id"]))
    return {"totes": {job.tote: job.order_id for job in jobs}, "route": route,
            "jobs": [fulfilment.job_view(job) for job in jobs]}


def task_store_id(db: Session, task_id: int) -> int:
    """Which store a pick task belongs to (used for the permission check). Read-only."""
    task = db.get(PickTask, task_id)
    if task is None:
        raise not_found("Pick task", task_id)
    return db.get(FulfilmentJob, task.job_id).store_id


def _check_picker(db: Session, job: FulfilmentJob, picker_id: str | None) -> None:
    """With `picker_id`, refuse to act on an order that now belongs to someone else: it sat idle and another picker
    claimed it (task 2.5), so a handheld that comes back to life cannot scan, report or pack it."""
    if picker_id is not None and job.picker_id != picker_id:
        db.rollback()
        raise DomainError(409, "not_your_order", "This order went to another picker after it sat idle; "
                                                 "ask for your next order")


def _open_task(db: Session, task_id: int, picker_id: str | None = None) -> tuple[PickTask, FulfilmentJob]:
    """The task and its job, taken for a change (fulfilment.hold_if_picking), so a cancel cannot slip in between.
    A job that was cancelled meanwhile answers `job_not_picking`, which the picker station explains. With
    `picker_id`, a job that now belongs to someone else (it sat idle and another picker claimed it, task 2.5)
    answers `not_your_order`, so a handheld that comes back to life cannot scan into another picker's order."""
    task = db.get(PickTask, task_id)
    if task is None:
        raise not_found("Pick task", task_id)
    job = db.get(FulfilmentJob, task.job_id)
    if not fulfilment.hold_if_picking(db, job):
        raise DomainError(409, "job_not_picking", f"Order is {job.state}; ask for your next task first")
    _check_picker(db, job, picker_id)
    if task.status != "pending":
        db.rollback()
        raise DomainError(409, "task_closed", f"This line is already {task.status}")
    return task, job


def scan(db: Session, task_id: int, barcode: str, qty: int = 1, picker_id: str | None = None) -> dict:
    """Check a barcode scan against the pick task (FR-5) and put `qty` units in the tote: one at a time as a picker
    really scans, or the whole line in one call. The line is picked when every unit is scanned. A wrong item, or more
    units than the line still needs, changes nothing."""
    task, job = _open_task(db, task_id, picker_id)
    if barcode != task.sku.barcode:
        db.commit()                   # keeps only last_activity_at: a wrong scan still shows the handheld is alive
        metrics.SCANS.labels("mismatch").inc()
        return {"match": False, "message": f"Wrong item. This line needs {task.sku.name}."}
    # Conditional, like the claim: the units are added only if the line still has room for them.
    added = db.execute(
        update(PickTask)
        .where(PickTask.id == task.id, PickTask.status == "pending", PickTask.scanned_qty + qty <= PickTask.qty)
        .values(scanned_qty=PickTask.scanned_qty + qty)
        .execution_options(synchronize_session=False)
    ).rowcount == 1
    if not added:
        db.commit()                   # keeps only last_activity_at, as above
        metrics.SCANS.labels("mismatch").inc()
        still_needed = task.qty - task.scanned_qty
        return {"match": False, "message": f"Too many. This line needs {still_needed} more, not {qty}."}
    db.refresh(task)
    if task.scanned_qty == task.qty:
        task.status = "picked"
        task.picked_at = utcnow()
    db.commit()
    metrics.SCANS.labels("match").inc()
    pending = sum(1 for t in job.tasks if t.status == "pending")
    message = "Picked." if task.status == "picked" else f"{task.scanned_qty} of {task.qty} scanned."
    return {"match": True, "message": message, "lines_left": pending, "job": fulfilment.job_view(job)}


def find_substitute(db: Session, store_id: int, sku_id: int, qty: int) -> dict | None:
    """Something the customer might take instead of `qty` units that cannot be found (HLD 9.2 saga, task 2.4): same
    category, enough that a customer could buy it (ATP, after the safety buffer), and the nearest price. Only an
    offer: nothing is held. None when nothing fits."""
    wanted = inventory.get_sku(db, sku_id)
    options = [row for row in inventory.availability(db, store_id)
               if row["category"] == wanted.category and row["sku_id"] != sku_id and row["atp"] >= qty]
    if not options:
        return None
    best = min(options, key=lambda row: (abs(row["price"] - wanted.price), row["price"], row["name"]))
    return {"sku_id": best["sku_id"], "name": best["name"], "price": best["price"]}


def report_short(db: Session, task_id: int, found: int | None = None, actor: str = "picker",
                 picker_id: str | None = None) -> dict:
    """The bin holds fewer units than the line needs: `found` of them were there (by default, the ones already
    scanned). The found units become a picked line of their own; for the rest, fix the count, then try another bin;
    if none has spare units, drop them, free their hold, publish order.line_dropped (the Order service refunds from
    it) and offer a substitute (`substitute_offer`, or None)."""
    task, job = _open_task(db, task_id, picker_id)
    found = task.scanned_qty if found is None else found
    if found < task.scanned_qty:
        db.rollback()
        raise DomainError(409, "found_below_scanned",
                          f"{task.scanned_qty} units of this line are already scanned, so at least that many "
                          "were found")
    if found >= task.qty:
        db.rollback()
        raise DomainError(409, "nothing_missing", f"This line needs {task.qty}; if all are there, scan them instead")
    if found:
        db.add(PickTask(job_id=job.id, sku_id=task.sku_id, stock_item_id=task.stock_item_id, bin_id=task.bin_id,
                        qty=found, scanned_qty=found, status="picked", picked_at=utcnow()))
        task.qty -= found             # this line is now only the missing units
        task.scanned_qty = 0
    item = task.stock_item
    inventory.write_off_missing(db, item, task.qty, reference=f"job:{job.id}", actor=actor)

    # After the write-off, units not held by anyone else can cover this line.
    level = inventory.get_level(db, job.store_id, task.sku_id)
    spare = max(0, level.qty_on_hand - (level.qty_reserved - task.qty))
    wanted = min(task.qty, spare)
    task.status = "short"
    db.flush()

    moved = 0
    if wanted:
        picks, _missing = inventory.allocate(db, job.store_id, task.sku_id, wanted, exclude_item_ids=(item.id,))
        for other, take in picks:
            db.add(PickTask(job_id=job.id, sku_id=task.sku_id, stock_item_id=other.id, bin_id=other.bin_id,
                            qty=take, status="pending"))
            moved += take
    lost = task.qty - moved
    if moved:
        task.status = "reallocated"
        if lost:
            db.add(PickTask(job_id=job.id, sku_id=task.sku_id, qty=lost, status="short"))
    offer = None
    if lost:
        inventory.unreserve(db, job.store_id, task.sku_id, lost)
        fulfilment.publish_line_dropped(db, job, task.sku_id, lost)
    db.flush()
    if lost:
        offer = find_substitute(db, job.store_id, task.sku_id, lost)
    fulfilment.resequence(db, job)
    events.publish(db, "stock.changed", job.store_id,
                   {"sku_id": task.sku_id, "cause": "not_found", "bin_id": item.bin_id})   # inventory counts the bin
    db.commit()
    if moved and not lost:
        message = "Count corrected. Pick the rest from another bin."
    elif moved:
        message = f"Count corrected. Only {moved} more found in another bin; {lost} dropped from the order."
    else:
        message = f"Count corrected. No other stock, so {lost} dropped from the order."
    if found:
        message = f"{found} picked. {message}"
    if offer:
        message += f" Possible substitute: {offer['name']} (Rs {offer['price']:g})."
    return {"picked": found, "reallocated": moved, "dropped": lost, "substitute_offer": offer, "message": message,
            "job": fulfilment.job_view(job)}


def pack(db: Session, job_id: int, crate_slot: str, actor: str = "packer",
         picker_id: str | None = None) -> FulfilmentJob:
    """Mark the order packed (FR-6). This is the moment the sale is committed: units leave
    on-hand stock and the hold on them ends."""
    job = fulfilment.get_job(db, job_id)
    if job.state in ("packed", "handed_over"):
        return job
    # Take the job first: a cancel at the same moment either finished before this (and nothing is sold) or waits for
    # it (and is told the order is packed). Selling the units and giving their hold back can never both happen.
    if not fulfilment.hold_if_picking(db, job):
        if job.state in ("packed", "handed_over"):
            return job                                      # packed by a retry of this same call
        raise DomainError(409, "job_not_picking", f"Order is {job.state}; it cannot be packed")
    _check_picker(db, job, picker_id)
    if any(t.status == "pending" for t in job.tasks):
        db.rollback()
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
