"""Technical monitoring (HLD 12): request timing, request ids, JSON logs and GET /metrics.

Every request gets an id: the caller's X-Request-ID if it is safe to log, otherwise a new one. It is sent
back in the response and written on every log line made while the request is handled, so one request
can be followed through the logs.
"""
import contextvars
import hmac
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import config, metrics
from .auth import require_role
from .db import SessionLocal, get_db
from .errors import DomainError
from .models import AuditEntry, EventLog, Reservation, utcnow
from .modules.dashboard.service import outbox_lag_seconds

log = logging.getLogger("app.requests")
request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
KNOWN_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}   # anything else is labelled "other"

router = APIRouter(tags=["admin"])


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with the id of the request being handled ("-" outside a request)."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {"ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
                 "level": record.levelname, "logger": record.name, "message": record.getMessage(),
                 "request_id": request_id.get(), **getattr(record, "fields", {})}
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging() -> None:
    """Write the app's own log lines (loggers named "app...") to stderr as JSON. Uvicorn keeps its format."""
    app_log = logging.getLogger("app")
    if not any(isinstance(handler.formatter, JsonFormatter) for handler in app_log.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        app_log.addHandler(handler)
    app_log.setLevel(logging.INFO)
    app_log.propagate = False        # written once, as JSON, even if the root logger has a handler too


async def observe(request: Request, call_next):
    """HTTP middleware: give the request an id, time it under its route template, and log one line for it."""
    incoming = request.headers.get("x-request-id", "")
    rid = incoming if SAFE_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
    token = request_id.set(rid)
    started = time.perf_counter()
    status = 500                                 # what the caller gets if the handler raises
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        seconds = time.perf_counter() - started
        # The template (/v1/stores/{store_id}/...), not the raw path, or every store gets its own series.
        route = getattr(request.scope.get("route"), "path", "other")
        method = request.method if request.method in KNOWN_METHODS else "other"   # callers can invent methods
        metrics.REQUEST_SECONDS.labels(method, route, str(status)).observe(seconds)
        log.info("request", extra={"fields": {"method": request.method, "route": route, "status": status,
                                              "ms": round(seconds * 1000, 1)}})
        await run_in_threadpool(_audit, request, route, status, rid)   # a slow or locked database must not stall other requests
        request_id.reset(token)


def _audit(request: Request, route: str, status: int, rid: str) -> None:
    """Record a call by a logged-in staff member (current_staff put them on the request). Calls that need no
    login, or had no valid token, have nobody to name and are not recorded. A failed write is logged, and the
    caller still gets their answer."""
    staff = getattr(request.state, "staff", None)
    if staff is None:
        return
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    try:
        with SessionLocal() as db:
            db.add(AuditEntry(username=staff["sub"], role=staff["role"], store_id=staff.get("store_id"),
                              method=request.method[:10], route=route, path=path[:300], status=status,
                              request_id=rid))
            db.commit()
    except Exception:   # whatever goes wrong here, the caller still gets the answer they were given
        log.exception("audit write failed")


@router.get("/v1/audit", summary="Who called which protected endpoint, newest first (admin only)")
def audit_log(username: str | None = None, limit: int = Query(100, ge=1, le=500),
              db: Session = Depends(get_db), staff: dict = Depends(require_role("admin"))) -> list[dict]:
    query = select(AuditEntry)
    if username is not None:
        query = query.where(AuditEntry.username == username)
    rows = db.scalars(query.order_by(AuditEntry.id.desc()).limit(limit))
    return [{"ts": e.ts.isoformat() + "Z", "username": e.username, "role": e.role, "store_id": e.store_id,
             "method": e.method, "route": e.route, "path": e.path, "status": e.status, "request_id": e.request_id}
            for e in rows]


@router.get("/metrics", include_in_schema=False)
def metrics_endpoint(request: Request, db: Session = Depends(get_db)) -> Response:
    """Prometheus scrape target. The gauges are read from the database at scrape time."""
    expected = f"Bearer {config.METRICS_TOKEN}".encode()
    if config.METRICS_TOKEN and not hmac.compare_digest(request.headers.get("authorization", "").encode(), expected):
        raise DomainError(401, "bad_scrape_token", "Send the scrape token as 'Authorization: Bearer <METRICS_TOKEN>'")
    metrics.HOLDS_IN_PROGRESS.set(
        db.scalar(select(func.count()).select_from(Reservation).where(Reservation.status == "held")))
    metrics.OUTBOX_LAG.set(outbox_lag_seconds(db))
    now = utcnow()
    metrics.STORE_SILENCE.clear()    # so a store that has gone (after a reset) does not keep its old value
    for store_id, last in db.execute(select(EventLog.store_id, func.max(EventLog.ts))
                                     .where(EventLog.store_id.is_not(None)).group_by(EventLog.store_id)):
        metrics.STORE_SILENCE.labels(str(store_id)).set((now - last).total_seconds())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
