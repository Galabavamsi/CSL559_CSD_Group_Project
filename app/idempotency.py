"""Idempotency keys (HLD 8): "a retried request never reserves or moves stock twice".

A client sends `Idempotency-Key: <any unique string>` with a write. The first request does the write and saves its
answer in the *same* transaction, so the two can never be separated: if the process dies before the commit, neither
is saved and a retry simply does the write. A later request with the same key gets the saved answer back without
touching stock. If two copies arrive at the same instant, both do the work but only one can save the record (it is the
table's primary key); the other rolls back its whole write and returns the winner's answer.

Reusing a key for a *different* request is a client bug, so it is refused rather than silently answered.
"""
import hashlib
import json
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .errors import DomainError
from .models import IdempotencyRecord


def _fingerprint(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()


def _replay(record: IdempotencyRecord, request_hash: str) -> dict:
    if record.request_hash != request_hash:
        raise DomainError(422, "idempotency_key_reused",
                          "This Idempotency-Key was already used for a different request; send a new key")
    return record.response


def run_once(db: Session, scope: str, key: str | None, request: dict, action: Callable[[], dict]) -> dict:
    """Run `action()` once per (scope, key) and commit. `action` must not commit itself, so its changes and the
    record land together. `request` is the request body, used to spot a key reused for something else.
    Without a key the action just runs and commits, as before."""
    if key is None:
        result = action()
        db.commit()
        return result
    request_hash = _fingerprint(request)
    seen = db.get(IdempotencyRecord, (scope, key))
    if seen is not None:
        return _replay(seen, request_hash)
    result = action()
    db.add(IdempotencyRecord(scope=scope, key=key, request_hash=request_hash, response=result))
    try:
        db.commit()
    except IntegrityError:                       # another copy of this request committed first
        db.rollback()                            # throws our write away with it
        return _replay(db.get(IdempotencyRecord, (scope, key), populate_existing=True), request_hash)
    return result
