"""Database tables. They mirror the core entities in HLD section 7.1.

One deliberate simplification: the HLD keeps `qty_reserved` on every StockItem row.
The prototype splits stock into two tables instead:

* StockLevel  - one row per (store, SKU). Holds on-hand and reserved totals. All checkout
                holds are made here with a single conditional UPDATE, which is what
                prevents overselling.
* StockItem   - one row per (store, SKU, bin, batch). Says where the units physically sit
                and when they expire. Used for pick paths, FEFO and putaway.

Rule that must always hold:  StockLevel.qty_on_hand == sum(StockItem.qty) for that store + SKU.
Only app/modules/inventory/service.py is allowed to change either table.
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp (SQLite does not store time zones)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- stores

class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float, default=3.0)
    status: Mapped[str] = mapped_column(String(10), default="open")   # open | busy | closed
    hub_name: Mapped[str] = mapped_column(String(80), default="City Mother Hub")


class Bin(Base):
    """Smallest storage address in a store. `walk_seq` is its position on the picker's walking route:
    low numbers are closest to the packing desk."""
    __tablename__ = "bins"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))                     # e.g. A-01-02 = zone A, rack 1, shelf 2
    zone: Mapped[str] = mapped_column(String(10))                     # ambient | chilled | frozen
    walk_seq: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("store_id", "code"),)


class SKU(Base):
    __tablename__ = "skus"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40))
    barcode: Mapped[str] = mapped_column(String(20), unique=True)
    storage_type: Mapped[str] = mapped_column(String(10))             # ambient | chilled | frozen
    shelf_life_days: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)


# --------------------------------------------------------------------------- stock

class StockLevel(Base):
    """Totals per store + SKU. ATP (available to promise) = qty_on_hand - qty_reserved."""
    __tablename__ = "stock_levels"
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), primary_key=True)
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    qty_reserved: Mapped[int] = mapped_column(Integer, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, default=10)
    target_stock: Mapped[int] = mapped_column(Integer, default=40)
    version: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[SKU] = relationship()


class StockItem(Base):
    """Physical stock: units of one SKU batch sitting in one bin."""
    __tablename__ = "stock_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True)
    bin_id: Mapped[int] = mapped_column(ForeignKey("bins.id"))
    batch_no: Mapped[str] = mapped_column(String(30))
    expiry_date: Mapped[date] = mapped_column(Date)
    qty: Mapped[int] = mapped_column(Integer, default=0)
    bin: Mapped[Bin] = relationship()
    sku: Mapped[SKU] = relationship()
    __table_args__ = (UniqueConstraint("store_id", "sku_id", "bin_id", "batch_no"),)


class StockLedger(Base):
    """Append-only history of every stock movement. Never update or delete rows here."""
    __tablename__ = "stock_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(Integer, index=True)
    sku_id: Mapped[int] = mapped_column(Integer, index=True)
    bin_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delta: Mapped[int] = mapped_column(Integer)                       # + stock in, - stock out
    reason: Mapped[str] = mapped_column(String(30))                   # receipt | sale | damage | expiry | theft | count | not_found
    reference: Mapped[str | None] = mapped_column(String(60), nullable=True)
    actor: Mapped[str] = mapped_column(String(40), default="system")
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# --------------------------------------------------------------------------- reservations

class Reservation(Base):
    """A checkout hold on stock. held -> confirmed -> fulfilled, or held -> released / expired."""
    __tablename__ = "reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(60), unique=True)    # also the idempotency key
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="held", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    lines: Mapped[list["ReservationLine"]] = relationship(cascade="all, delete-orphan")


class ReservationLine(Base):
    __tablename__ = "reservation_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    qty: Mapped[int] = mapped_column(Integer)


# --------------------------------------------------------------------------- fulfilment

class FulfilmentJob(Base):
    """One paid order being picked and packed. created -> picking -> packed -> handed_over (or cancelled)."""
    __tablename__ = "fulfilment_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(60), unique=True)
    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    state: Mapped[str] = mapped_column(String(12), default="created", index=True)
    picker_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    crate_slot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    picking_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    packed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tasks: Mapped[list["PickTask"]] = relationship(order_by="PickTask.seq", cascade="all, delete-orphan")


class PickTask(Base):
    """Pick `qty` of one SKU from one bin. pending -> picked | short | reallocated."""
    __tablename__ = "pick_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("fulfilment_jobs.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    stock_item_id: Mapped[int | None] = mapped_column(ForeignKey("stock_items.id"), nullable=True)
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("bins.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer, default=0)              # walking order
    status: Mapped[str] = mapped_column(String(12), default="pending")
    sku: Mapped[SKU] = relationship()
    bin: Mapped[Bin | None] = relationship()
    stock_item: Mapped[StockItem | None] = relationship()


# --------------------------------------------------------------------------- replenishment

class TransferOrder(Base):
    """A restocking request to the mother hub. created -> dispatched -> received."""
    __tablename__ = "transfer_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    status: Mapped[str] = mapped_column(String(12), default="created", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lines: Mapped[list["TransferOrderLine"]] = relationship(cascade="all, delete-orphan")


class TransferOrderLine(Base):
    __tablename__ = "transfer_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_order_id: Mapped[int] = mapped_column(ForeignKey("transfer_orders.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    qty_ordered: Mapped[int] = mapped_column(Integer)
    qty_received: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[SKU] = relationship()


class Forecast(Base):
    """Latest demand forecast per store + SKU (units per day)."""
    __tablename__ = "forecasts"
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), primary_key=True)
    daily_demand: Mapped[float] = mapped_column(Float, default=0.0)
    daily_std: Mapped[float] = mapped_column(Float, default=0.0)
    model: Mapped[str] = mapped_column(String(30), default="moving_average")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- events

class EventLog(Base):
    """Every event published on the in-process bus. Stands in for Kafka in the prototype."""
    __tablename__ = "event_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    store_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
