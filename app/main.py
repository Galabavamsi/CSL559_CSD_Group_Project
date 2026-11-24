"""Application entry point: builds the FastAPI app and plugs in every module.

Run it with:   uvicorn app.main:app --reload
Then open:     http://localhost:8000        (demo screens)
               http://localhost:8000/docs   (interactive API reference)
"""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import auth, background, config, demo_supply, events, monitoring, rate_limit, seed
from .db import SessionLocal, get_db, init_db
from .errors import DomainError
from .modules.accounts.router import router as accounts_router
from .modules.assortment.router import router as assortment_router
from .modules.catalogue.router import router as catalogue_router
from .modules.dashboard.router import router as dashboard_router
from .modules.delivery.router import router as delivery_router
from .modules.farms.router import router as farms_router
from .modules.forecasting.router import router as forecasting_router
from .modules.fulfilment.router import router as fulfilment_router
from .modules.inbound.router import router as inbound_router
from .modules.inventory.router import router as inventory_router
from .modules.network_planning.router import router as network_planning_router
from .modules.orders.router import router as orders_router
from .modules.pickpack.router import router as pickpack_router
from .modules.replenishment.router import router as replenishment_router
from .modules.serviceability.router import router as serviceability_router
from .modules.slotting.router import router as slotting_router

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
monitoring.setup_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.JWT_SECRET == config.DEFAULT_JWT_SECRET:
        logging.getLogger("uvicorn.error").warning(
            "JWT_SECRET is not set: tokens are signed with the public development secret.")
    init_db()
    with SessionLocal() as db:
        seed.seed_if_empty(db)
    relay = asyncio.create_task(events.run_relay())
    jobs = background.start_all() if config.BACKGROUND_JOBS else []
    yield
    for task in (relay, *jobs):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="Dark Store Prototype",
    version="0.1.0",
    description="Micro-warehousing module of a quick-commerce app. One module per service in the HLD.",
    lifespan=lifespan,
)


app.middleware("http")(rate_limit.limit)     # added first, so it runs inside observe: a 429 is logged and timed too
app.middleware("http")(monitoring.observe)   # request ids, timing and one JSON log line per request


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status,
                        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})


for router in (
    auth.router, accounts_router, monitoring.router, serviceability_router, inventory_router, fulfilment_router, pickpack_router, inbound_router,
    replenishment_router, forecasting_router, slotting_router, assortment_router,
    network_planning_router, dashboard_router, farms_router, orders_router, catalogue_router, delivery_router,
):
    app.include_router(router)


@app.get("/health", tags=["admin"])
def health():
    return {"status": "ok"}


@app.post("/v1/admin/reset", tags=["admin"], dependencies=[Depends(auth.require_role("admin"))])
def reset_demo_data():
    """Wipe everything and reload the demo data. For demos and local testing only."""
    seed.reset()
    return {"status": "reset"}


@app.post("/v1/admin/demo-supply", tags=["admin"], dependencies=[Depends(auth.require_role("admin"))],
          summary="Have the demo farms deliver to every hub that is nearly out, now")
def bring_demo_supply(db: Session = Depends(get_db)):
    """What the timed job does when DEMO_SUPPLY is on, on request (app/demo_supply.py). Answers with the lots that
    arrived; an empty list when every hub has enough, or when another top-up is running."""
    return {"arrived": demo_supply.top_up(db)}


# The demo screens. Mounted last so the API routes above take priority.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
