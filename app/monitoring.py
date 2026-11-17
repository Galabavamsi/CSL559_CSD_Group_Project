"""Technical monitoring (HLD 12): request timing, request ids, JSON logs and GET /metrics.

Every request gets an id: the caller's X-Request-ID if it is safe to log, otherwise a new one. It is sent
back in the response and written on every log line made while the request is handled, so one request
can be followed through the logs.
"""
import contextvars
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import metrics
from .db import get_db
from .models import EventLog, Reservation, utcnow
from .modules.dashboard.service import outbox_lag_seconds

log = logging.getLogger("app.requests")
request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

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
        metrics.REQUEST_SECONDS.labels(request.method, route, str(status)).observe(seconds)
        log.info("request", extra={"fields": {"method": request.method, "route": route, "status": status,
                                              "ms": round(seconds * 1000, 1)}})
        request_id.reset(token)


@router.get("/metrics", include_in_schema=False)
def metrics_endpoint(db: Session = Depends(get_db)) -> Response:
    """Prometheus scrape target. The gauges are read from the database at scrape time."""
    metrics.HOLDS_IN_PROGRESS.set(
        db.scalar(select(func.count()).select_from(Reservation).where(Reservation.status == "held")))
    metrics.OUTBOX_LAG.set(outbox_lag_seconds(db))
    now = utcnow()
    for store_id, last in db.execute(select(EventLog.store_id, func.max(EventLog.ts))
                                     .where(EventLog.store_id.is_not(None)).group_by(EventLog.store_id)):
        metrics.STORE_SILENCE.labels(str(store_id)).set((now - last).total_seconds())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
