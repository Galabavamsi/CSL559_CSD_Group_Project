"""A tiny in-process event bus that stands in for Kafka (HLD section 8.2).

publish() does two things inside the caller's database transaction:
  1. writes the event to the event_log table (so it commits or rolls back with the stock change
     that caused it - this is the "transactional outbox" idea from HLD 9.2), and
  2. calls every handler subscribed to that event type.

A relay (relay_once, run forever by run_relay) then reads event_log rows that are not yet published,
in id order, and hands each to every *sink*: today the WebSocket feed, later a Kafka producer.
Delivery is at least once: an event is marked published only after every sink took it, so a sink
that fails gets it again on the next pass, and so may the sinks before it. Consumers must cope with
duplicates, for example by remembering the event id.
"""
import asyncio
import logging
from collections import defaultdict
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import SessionLocal
from .models import EventLog, utcnow

log = logging.getLogger(__name__)

Handler = Callable[[Session, int | None, dict], None]
_handlers: dict[str, list[Handler]] = defaultdict(list)

Sink = Callable[[dict], None]
sinks: list[Sink] = []      # modules add themselves with add_sink


def subscribe(event_type: str):
    """Decorator: register a function to run whenever `event_type` is published."""
    def register(fn: Handler) -> Handler:
        if fn not in _handlers[event_type]:
            _handlers[event_type].append(fn)
        return fn
    return register


def add_sink(sink: Sink) -> Sink:
    """Decorator: register a function that receives every event the relay sends out."""
    if sink not in sinks:
        sinks.append(sink)
    return sink


def event_view(event: EventLog) -> dict:
    return {"id": event.id, "type": event.type, "store_id": event.store_id, "payload": event.payload,
            "ts": event.ts.isoformat() + "Z"}


def relay_once(db: Session) -> int:
    """Hand unpublished events to every sink, oldest first, and mark them published. Commits.

    Stops at the first event a sink rejects, so that event and the ones after it are retried on the
    next pass, still in order. Returns how many events were published.
    """
    rows = db.scalars(select(EventLog).where(EventLog.published_at.is_(None))
                      .order_by(EventLog.id).limit(config.RELAY_BATCH_SIZE)).all()
    sent = 0
    for row in rows:
        message = event_view(row)
        try:
            for sink in sinks:
                sink(message)
        except Exception:
            log.exception("Event %s was not delivered; it will be retried", row.id)
            break
        row.published_at = utcnow()
        sent += 1
    db.commit()
    return sent


async def run_relay() -> None:
    """Background task started by main.lifespan: relay new events a few times a second."""
    while True:
        try:
            # shortcut: the database call blocks the event loop for a moment; move it to a thread or a
            # separate process once passes take more than a few milliseconds.
            with SessionLocal() as db:
                relay_once(db)
        except Exception:
            log.exception("Event relay pass failed")
        await asyncio.sleep(config.RELAY_INTERVAL_SECONDS)


def publish(db: Session, event_type: str, store_id: int | None, payload: dict) -> None:
    db.add(EventLog(type=event_type, store_id=store_id, payload=payload))
    db.flush()
    for handler in _handlers[event_type]:
        handler(db, store_id, payload)
