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

from geoalchemy2 import Geography
from sqlalchemy import (JSON, Boolean, Computed, Date, DateTime, Float, ForeignKey, Index, Integer, String,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC timestamp: every DateTime column is UTC without a time zone."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --------------------------------------------------------------------------- cities and stores

# A point on the globe, kept by PostgreSQL itself from the row's lat and lng, so the two can never disagree.
# geography (not geometry): distances come out in metres along the earth's surface. spatial_index=False because
# the GiST index is declared by name below, where Alembic can see it.
POINT_FROM_LAT_LNG = "ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography"


def _location():
    return mapped_column(Geography("POINT", srid=4326, spatial_index=False), Computed(POINT_FROM_LAT_LNG, persisted=True))


class City(Base):
    """A city the service runs in. Everything located (hubs, and later farms, customers and orders) belongs to one,
    so a query, a simulation or a dashboard can be for one city (HLD 12: partition by city)."""
    __tablename__ = "cities"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)        # in URLs and settings, e.g. "bhilai"
    name: Mapped[str] = mapped_column(String(80))
    tier: Mapped[int] = mapped_column(Integer)                        # 1 = metro, 2 and 3 = smaller cities
    lat: Mapped[float] = mapped_column(Float)                         # city centre
    lng: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float)                   # roughly how far the built-up area reaches
    hub_radius_km: Mapped[float] = mapped_column(Float, default=3.0)  # service radius a new hub here starts with
    location = _location()
    __table_args__ = (Index("ix_cities_location", "location", postgresql_using="gist"),)


class Store(Base):
    """A hub: the micro-warehouse that stocks produce and sends out orders. (Still called a store in the code and the
    API paths, from the dark-store prototype this grew out of.)"""
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    radius_km: Mapped[float] = mapped_column(Float, default=3.0)
    status: Mapped[str] = mapped_column(String(10), default="open")   # open | busy | closed
    hub_name: Mapped[str] = mapped_column(String(80), default="City Mother Hub")
    # Produce the hub can hold, in kg: what is on its shelves plus lots farmers are bringing (farms.service).
    capacity_kg: Mapped[int] = mapped_column(Integer, default=5000, server_default="5000")
    location = _location()
    __table_args__ = (Index("ix_stores_location", "location", postgresql_using="gist"),)


class Bin(Base):
    """Smallest storage address in a store. `walk_seq` is its position on the picker's walking route:
    low numbers are closest to the packing desk."""
    __tablename__ = "bins"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))                     # e.g. A-01-02 = zone A, rack 1, shelf 2
    zone: Mapped[str] = mapped_column(String(10))                     # ambient | chilled | frozen
    walk_seq: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer, default=100)       # units it holds; orders and putaway stay within
    __table_args__ = (UniqueConstraint("store_id", "code"),)


class ProduceItem(Base):
    """A kind of produce a farmer can list and a hub can stock, for example Tomato. Farmers deal in kilograms of an
    item; customers buy its SKUs, each a fixed unit of it: a pack, a piece or a bunch."""
    __tablename__ = "produce_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    family: Mapped[str] = mapped_column(String(20))                   # vegetables | leafy | fruits | herbs
    storage_type: Mapped[str] = mapped_column(String(10))             # ambient | chilled | frozen, as bins are
    shelf_life_days: Mapped[int] = mapped_column(Integer)             # counted from the harvest date


class SKU(Base):
    __tablename__ = "skus"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(40))
    barcode: Mapped[str] = mapped_column(String(20), unique=True)
    storage_type: Mapped[str] = mapped_column(String(10))             # ambient | chilled | frozen
    shelf_life_days: Mapped[int] = mapped_column(Integer)
    price: Mapped[float] = mapped_column(Float)
    case_size: Mapped[int] = mapped_column(Integer, default=1)        # units per case; the hub ships whole cases
    # Produce only, empty for anything else: the item this is a unit of, the grams of it one unit takes (how
    # accepted kilograms become units at intake), and what the customer is told one unit is.
    item_id: Mapped[int | None] = mapped_column(ForeignKey("produce_items.id"), nullable=True, index=True)
    unit_grams: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(String(40), nullable=True)   # "500 g", "1 piece (400-600 g)"


class StoreZone(Base):
    """Delivery zones: which store serves each H3 cell. Rebuilt by serviceability.rebuild_zones."""
    __tablename__ = "store_zones"
    h3_cell: Mapped[str] = mapped_column(String(16), primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    distance_km: Mapped[float] = mapped_column(Float)                 # store to the centre of the cell


class ServiceabilityMiss(Base):
    """A lookup no store could serve: the best evidence for a new store (task 4.4). Only the H3 cell and
    the time are kept, never the exact location."""
    __tablename__ = "serviceability_misses"
    id: Mapped[int] = mapped_column(primary_key=True)
    h3_cell: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditEntry(Base):
    """One call by a logged-in staff member to a protected endpoint, refused or not (HLD 10).
    shortcut: entries are never pruned and a demo reset wipes them; add retention before running for weeks."""
    __tablename__ = "audit_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(40), index=True)
    role: Mapped[str] = mapped_column(String(20))
    store_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    method: Mapped[str] = mapped_column(String(10))
    route: Mapped[str] = mapped_column(String(200))     # the template, e.g. /v1/stores/{store_id}/dashboard
    path: Mapped[str] = mapped_column(String(300))      # what was actually asked for, with the query string
    status: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(64))


class Staff(Base):
    """Someone who can log in (HLD 10). `store_id` is empty for city-wide roles (ops, admin)."""
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(10))                     # picker | packer | receiver | manager | ops | admin
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)


# --------------------------------------------------------------------------- people who use the phone app

class User(Base):
    """Someone who signs in to the phone app with a code sent to their email: a customer, a farmer or a delivery
    agent. Hub staff are in `staff`, log in with a password, and are a separate kind of login."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(10))                     # customer | farmer | agent
    email: Mapped[str] = mapped_column(String(254), unique=True)      # lower case; it is the login
    name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LoginCode(Base):
    """A one-time sign-in code emailed to an address. Only a keyed hash of the code is kept (accounts.service).
    `role` is the role the address will have: its account's, or the one asked for at a first sign-in."""
    __tablename__ = "login_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    role: Mapped[str] = mapped_column(String(10))
    code_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)         # tries made against this code, right or wrong
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)   # set when used, replaced or void


class RefreshToken(Base):
    """One session of an app user. The token itself is never stored, only its hash; `revoked_at` is set when it is
    exchanged for a new one or signed out."""
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------- farm supply

class Farm(Base):
    """Where a farmer's produce comes from. The location decides which hub a listing goes to."""
    __tablename__ = "farms"
    id: Mapped[int] = mapped_column(primary_key=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    area_acres: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    location = _location()
    __table_args__ = (Index("ix_farms_location", "location", postgresql_using="gist"),)


class Listing(Base):
    """A lot of one item that a farmer will bring to a hub in a drop slot. listed -> received (weighed and graded at
    the hub) or cancelled. Weights are whole grams."""
    __tablename__ = "listings"
    id: Mapped[int] = mapped_column(primary_key=True)
    farm_id: Mapped[int] = mapped_column(ForeignKey("farms.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("produce_items.id"))
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)        # the hub it was assigned to
    qty_g: Mapped[int] = mapped_column(Integer)
    price_per_kg: Mapped[float] = mapped_column(Float)                                # what the farmer asks
    harvest_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), default="listed", index=True)
    drop_from: Mapped[datetime] = mapped_column(DateTime)                             # the drop slot, UTC
    drop_until: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    farm: Mapped[Farm] = relationship()
    item: Mapped[ProduceItem] = relationship()


class QualityCheck(Base):
    """What the hub found when a lot arrived: its weight, its grade, and how much was accepted. accepted = received
    - rejected; trim is accepted weight that did not fill a last unit. `batch_no` is the batch the packed units
    carry in stock, which is how a pack on a shelf is traced back to its farm and its grade."""
    __tablename__ = "quality_checks"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"), unique=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    batch_no: Mapped[str] = mapped_column(String(30), unique=True)
    grade: Mapped[str] = mapped_column(String(6))                     # A | B | C | reject
    received_g: Mapped[int] = mapped_column(Integer)
    accepted_g: Mapped[int] = mapped_column(Integer)
    rejected_g: Mapped[int] = mapped_column(Integer)
    trim_g: Mapped[int] = mapped_column(Integer, default=0)
    remarks: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checked_by: Mapped[str] = mapped_column(String(40))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    receipt_id: Mapped[int | None] = mapped_column(ForeignKey("goods_receipts.id"), nullable=True)


# --------------------------------------------------------------------------- stock

class StockLevel(Base):
    """Totals per store + SKU. ATP (available to promise) = qty_on_hand - qty_reserved - safety_buffer, never below 0.
    The safety buffer (HLD 7.1) hides a few units from customers so small counting errors do not become failed orders;
    the units are still physically there, so replenishment does not subtract it.
    reorder_stopped: a manager stopped reordering this SKU (to let it run down, e.g. before dropping it), so
    replenishment skips it."""
    __tablename__ = "stock_levels"
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), primary_key=True)
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    qty_reserved: Mapped[int] = mapped_column(Integer, default=0)
    safety_buffer: Mapped[int] = mapped_column(Integer, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, default=10)
    target_stock: Mapped[int] = mapped_column(Integer, default=40)
    reorder_stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[SKU] = relationship()


class StockItem(Base):
    """Physical stock: units of one SKU batch sitting in one bin."""
    __tablename__ = "stock_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), index=True)
    bin_id: Mapped[int] = mapped_column(ForeignKey("bins.id"), index=True)   # slotting sums a bin's units often
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
    reason: Mapped[str] = mapped_column(String(30))                   # receipt | sale | damage | expiry | theft | count | not_found | move
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
    # H3 cell of the delivery address, for network planning (HLD 10: a cell, never the address itself).
    h3_cell: Mapped[str | None] = mapped_column(String(16), nullable=True)
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
    tote: Mapped[str | None] = mapped_column(String(2), nullable=True)      # A, B, C in a picker's batch (task 2.6)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    picking_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The picker's last sign of life on this order: claim, scan or shelf report (task 2.5).
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    packed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tasks: Mapped[list["PickTask"]] = relationship(order_by="PickTask.seq", cascade="all, delete-orphan")
    rider: Mapped["RiderAssignment | None"] = relationship(uselist=False, cascade="all, delete-orphan")


class PickTask(Base):
    """Pick `qty` of one SKU from one bin. pending -> picked | short | reallocated (or cancelled with its order).
    Units are scanned one or more at a time; the line is picked when `scanned_qty` reaches `qty`."""
    __tablename__ = "pick_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("fulfilment_jobs.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    stock_item_id: Mapped[int | None] = mapped_column(ForeignKey("stock_items.id"), nullable=True)
    bin_id: Mapped[int | None] = mapped_column(ForeignKey("bins.id"), nullable=True)
    qty: Mapped[int] = mapped_column(Integer)
    scanned_qty: Mapped[int] = mapped_column(Integer, default=0, server_default="0")   # units already in the tote
    seq: Mapped[int] = mapped_column(Integer, default=0)              # walking order
    status: Mapped[str] = mapped_column(String(12), default="pending")
    picked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)        # when the last unit was scanned
    sku: Mapped[SKU] = relationship()
    bin: Mapped[Bin | None] = relationship()
    stock_item: Mapped[StockItem | None] = relationship()


class RiderAssignment(Base):
    """The rider sent to collect one packed order (HLD service 11, task 2.7).
    assigned -> arrived -> collected; checking in is optional (a handover records the arrival too)."""
    __tablename__ = "rider_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("fulfilment_jobs.id"), unique=True)
    rider_id: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12), default="assigned")
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


class GoodsReceipt(Base):
    """A truck being received (HLD 6.3): opened, scanned onto the dock, put away line by line, then closed.
    open -> closed, or open -> cancelled (opened or scanned by mistake, nothing put away). transfer_order_id is empty
    for a receipt that came without a transfer order."""
    __tablename__ = "goods_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    transfer_order_id: Mapped[int | None] = mapped_column(ForeignKey("transfer_orders.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(10), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lines: Mapped[list["GoodsReceiptLine"]] = relationship(cascade="all, delete-orphan", order_by="GoodsReceiptLine.id")


class GoodsReceiptLine(Base):
    """One SKU and batch off a truck. Good units (qty_scanned) wait on the dock until they are put away; damaged units
    and batches refused for too little shelf life left (qty_rejected) are recorded but never enter stock."""
    __tablename__ = "goods_receipt_lines"
    __table_args__ = (UniqueConstraint("receipt_id", "sku_id", "batch_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("goods_receipts.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    batch_no: Mapped[str] = mapped_column(String(30))
    expiry_date: Mapped[date] = mapped_column(Date)
    qty_scanned: Mapped[int] = mapped_column(Integer, default=0)
    qty_damaged: Mapped[int] = mapped_column(Integer, default=0)
    qty_rejected: Mapped[int] = mapped_column(Integer, default=0)
    qty_put_away: Mapped[int] = mapped_column(Integer, default=0)
    sku: Mapped[SKU] = relationship()


class Forecast(Base):
    """Latest demand forecast per store + SKU (units per day)."""
    __tablename__ = "forecasts"
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), primary_key=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"), primary_key=True)
    daily_demand: Mapped[float] = mapped_column(Float, default=0.0)  # forecast units for the day it was made
    daily_std: Mapped[float] = mapped_column(Float, default=0.0)     # spread of the model's recent daily errors
    model: Mapped[str] = mapped_column(String(30), default="moving_average")   # which model made it
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# --------------------------------------------------------------------------- events

class CycleCount(Base):
    """A blind count of one bin (FR-11). open -> submitted -> approved | rejected; a small difference goes straight
    from open to approved. The counter is told which SKUs to look for, never how many the system expects."""
    __tablename__ = "cycle_counts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    bin_id: Mapped[int] = mapped_column(ForeignKey("bins.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)
    reason: Mapped[str] = mapped_column(String(20), default="manual")         # manual | not_found (a picker found it short)
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    submitted_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    difference_value: Mapped[float | None] = mapped_column(Float, nullable=True)   # sum of |counted - system| x price
    decided_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bin: Mapped[Bin] = relationship()
    lines: Mapped[list["CycleCountLine"]] = relationship(cascade="all, delete-orphan", order_by="CycleCountLine.id")


class CycleCountLine(Base):
    """One SKU in a counted bin. `system_qty` is what the records said at the moment the count was submitted."""
    __tablename__ = "cycle_count_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    count_id: Mapped[int] = mapped_column(ForeignKey("cycle_counts.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    system_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counted_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sku: Mapped[SKU] = relationship()


# --------------------------------------------------------------------------- customers' orders

class Order(Base):
    """A signed-in customer's paid order: who it is for, where it goes, what each unit cost and how far along it is
    (docs/DESIGN.md, section 2). Made when the customer's hold is confirmed; the hold and the pick job go on doing
    the stock work. `order_id` is the hold's, chosen by the app, and is what the customer sees."""
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[str] = mapped_column(String(60), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), index=True)
    reservation_id: Mapped[str] = mapped_column(ForeignKey("reservations.id"), unique=True)
    # confirmed -> packed -> (pooled -> out_for_delivery -> delivered | delivery_failed), or cancelled
    status: Mapped[str] = mapped_column(String(20), default="confirmed", index=True)
    address_label: Mapped[str] = mapped_column(String(120))           # the area, e.g. "Supela, Bhilai"
    address_line: Mapped[str] = mapped_column(String(120))            # house or flat and street
    landmark: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    item_total: Mapped[float] = mapped_column(Float)
    savings: Mapped[float] = mapped_column(Float, default=0)
    delivery_fee: Mapped[float] = mapped_column(Float, default=0)
    total: Mapped[float] = mapped_column(Float)
    payment: Mapped[str] = mapped_column(String(20), default="stand_in")   # no gateway yet: no money moves
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    lines: Mapped[list["OrderLine"]] = relationship(order_by="OrderLine.id", cascade="all, delete-orphan")
    events: Mapped[list["OrderEvent"]] = relationship(order_by="OrderEvent.id", cascade="all, delete-orphan")


class OrderLine(Base):
    """What the customer is charged for: units of one item at the price paid for each."""
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id"))
    name: Mapped[str] = mapped_column(String(120))                    # as shown when it was bought
    unit_label: Mapped[str | None] = mapped_column(String(40), nullable=True)
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float)                  # what was charged for one unit
    list_price: Mapped[float] = mapped_column(Float)                  # the item's full price then; more if rescued


class OrderEvent(Base):
    """Each status an order has reached, and when: the customer's timeline."""
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IdempotencyRecord(Base):
    """The first answer to a write request that carried an Idempotency-Key header (HLD 8). A retry with the same
    key gets this answer back instead of doing the write again. Saved in the same transaction as the write."""
    __tablename__ = "idempotency_records"
    scope: Mapped[str] = mapped_column(String(40), primary_key=True)        # which endpoint, e.g. "stock-adjustment"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))                   # catches one key reused for another request
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EventLog(Base):
    """Every event published on the in-process bus. Stands in for Kafka in the prototype."""
    __tablename__ = "event_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    store_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Set by the relay once every sink has the event; empty means still in the outbox (HLD 9.2).
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
