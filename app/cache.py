"""ATP cache (HLD 9.2: "ATP served from Redis"). Reads outnumber stock writes about 13 to 1 (HLD 3), so a store's
availability list is kept for a couple of seconds instead of being read from the database every time.

The rule that keeps this safe: the cache is only ever used to *show* stock. `inventory.reserve` never reads it; the
hold is a conditional UPDATE on the database. So a stale cache can make a customer see an item that then fails to
hold ("sorry, just sold out"), but it can never make the store promise units it does not have.

How entries are cleared. Every write to a StockLevel row, from any module, is noticed by two SQLAlchemy hooks below:
the store's entry is dropped at once, and dropped again right after the transaction commits. The second drop matters:
between the write and the commit another request can still read the old, committed numbers and put them back in the
cache. Dropping after the commit removes that copy. A request that read before the commit but stores its result just
after the second drop can still leave an old copy; the 2-second expiry is what bounds that.

TTLCache is in-process. With several app instances, each has its own copy and only clears its own; the expiry bounds
how stale another instance can be. A Redis class with the same get / set / delete / clear methods would share one copy.
"""
import time

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.sql import operators, visitors

from . import config
from .models import StockLevel

ALL_STORES = "*"


class TTLCache:
    """A dict whose entries vanish after `ttl` seconds. ttl <= 0 turns it off (every get misses)."""

    def __init__(self, ttl_seconds: float):
        self.ttl, self._data = ttl_seconds, {}

    def get(self, key):
        hit = self._data.get(key)
        return hit[1] if hit and hit[0] > time.monotonic() else None

    def set(self, key, value) -> None:
        if self.ttl > 0:
            self._data[key] = (time.monotonic() + self.ttl, value)

    def delete(self, key) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


atp_cache = TTLCache(ttl_seconds=config.ATP_CACHE_SECONDS)


def _forget(stores: set) -> None:
    if ALL_STORES in stores:
        atp_cache.clear()
    for store_id in stores - {ALL_STORES}:
        atp_cache.delete(store_id)


def _stock_written(session: Session, stores: set) -> None:
    """Drop those stores now, and remember them so they are dropped again after the commit."""
    _forget(stores)
    session.info.setdefault("atp_stores_written", set()).update(stores)


def _store_in_where(statement) -> object:
    """The store id a bulk UPDATE / DELETE of stock_levels is limited to, or ALL_STORES if it cannot be told."""
    where = getattr(statement, "whereclause", None)
    for node in visitors.iterate(where) if where is not None else ():
        left = getattr(node, "left", None)
        if (getattr(node, "operator", None) is operators.eq and getattr(left, "table", None) is StockLevel.__table__
                and getattr(left, "name", None) == "store_id" and hasattr(node.right, "effective_value")):
            return node.right.effective_value
    return ALL_STORES


@event.listens_for(Session, "after_flush")
def _after_flush(session: Session, _flush_context) -> None:
    """StockLevel rows added, changed or deleted as objects (db.add, level.qty_reserved = ..., db.delete)."""
    stores = {obj.store_id for obj in (*session.new, *session.dirty, *session.deleted)
              if isinstance(obj, StockLevel) and (obj in session.new or obj in session.deleted
                                                  or session.is_modified(obj))}
    if stores:
        _stock_written(session, stores)


@event.listens_for(Session, "do_orm_execute")
def _bulk_statement(state) -> None:
    """StockLevel rows changed by a bulk statement: update(StockLevel)... or delete(StockLevel)..."""
    if (state.is_update or state.is_delete) and state.bind_mapper is not None \
            and state.bind_mapper is inspect(StockLevel):
        _stock_written(state.session, {_store_in_where(state.statement)})


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    _forget(session.info.pop("atp_stores_written", set()))


@event.listens_for(Session, "after_rollback")
def _after_rollback(session: Session) -> None:
    session.info.pop("atp_stores_written", None)        # nothing changed; the early drop was harmless
