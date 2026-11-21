import asyncio
import time

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ... import config
from ...auth import check_store, current_staff, decode_token
from ...db import get_db
from ...errors import DomainError
from ...ids import MAX_ID, PathId
from . import service

router = APIRouter(tags=["dashboard"])


@router.get("/v1/stores/{store_id}/dashboard")
def dashboard(store_id: PathId, db: Session = Depends(get_db),
              staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.store_dashboard(db, store_id)


@router.get("/v1/dashboard/overview", summary="One row per store, for city-wide staff")
def overview(db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, None)
    return service.city_overview(db)


@router.get("/v1/stores/{store_id}/kpis", summary="What needs action, and every HLD 12 KPI beside its target")
def kpis(store_id: PathId, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.kpi_board(db, store_id)


@router.get("/v1/events")
def events(store_id: int | None = Query(None, ge=1, le=MAX_ID), limit: int = Query(20, ge=1, le=500), db: Session = Depends(get_db),
           staff: dict = Depends(current_staff)):
    check_store(staff, store_id)
    return service.recent_events(db, store_id, limit)


@router.websocket("/v1/ws/events")
async def live_events(websocket: WebSocket, store_id: int = Query(ge=1, le=MAX_ID)):
    """Live feed of one store's events as JSON messages. Browsers cannot put a token in a WebSocket's
    headers, so send the bearer token as the first message. Staff see only their own store."""
    await websocket.accept()
    try:
        staff = decode_token(await asyncio.wait_for(websocket.receive_text(), timeout=5))
        check_store(staff, store_id)
    except WebSocketDisconnect:
        return
    except (DomainError, TimeoutError, KeyError):   # KeyError: the first message was binary, not text
        await websocket.close(code=1008)      # 1008 = policy violation
        return

    queue = service.listen(store_id)
    try:
        await websocket.send_json({"type": "connected", "store_id": store_id})
        while True:
            seconds_left = staff["exp"] - time.time()
            if seconds_left <= 0:
                await websocket.close(code=1008)      # the token has expired: the client must log in again
                return
            try:
                event = await asyncio.wait_for(queue.get(), timeout=min(config.LIVE_PING_SECONDS, seconds_left))
            except TimeoutError:
                event = {"type": "ping"}      # a failed send is how a vanished viewer is noticed
            await websocket.send_json(event)
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass                                  # the viewer went away
    finally:
        service.stop_listening(store_id, queue)
