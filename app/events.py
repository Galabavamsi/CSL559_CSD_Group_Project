"""A tiny in-process event bus that stands in for Kafka (HLD section 8.2).

publish() does two things inside the caller's database transaction:
  1. writes the event to the event_log table (so it commits or rolls back with the stock change
     that caused it - this is the "transactional outbox" idea from HLD 9.2), and
  2. calls every handler subscribed to that event type.

To move to real Kafka later, keep publish() as it is, drop step 2, and add a relay that reads
event_log and sends the rows to Kafka topics keyed by store_id.
"""
from collections import defaultdict
from typing import Callable

from sqlalchemy.orm import Session

from .models import EventLog

Handler = Callable[[Session, int | None, dict], None]
_handlers: dict[str, list[Handler]] = defaultdict(list)


def subscribe(event_type: str):
    """Decorator: register a function to run whenever `event_type` is published."""
    def register(fn: Handler) -> Handler:
        if fn not in _handlers[event_type]:
            _handlers[event_type].append(fn)
        return fn
    return register


def publish(db: Session, event_type: str, store_id: int | None, payload: dict) -> None:
    db.add(EventLog(type=event_type, store_id=store_id, payload=payload))
    db.flush()
    for handler in _handlers[event_type]:
        handler(db, store_id, payload)
