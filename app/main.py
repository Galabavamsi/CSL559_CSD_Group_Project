"""Application entry point: builds the FastAPI app and plugs in every module.

Run it with:   uvicorn app.main:app --reload
Then open:     http://localhost:8000        (demo screens)
               http://localhost:8000/docs   (interactive API reference)
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, seed
from .db import SessionLocal, init_db
from .errors import DomainError
from .modules.assortment.router import router as assortment_router
from .modules.dashboard.router import router as dashboard_router
from .modules.forecasting.router import router as forecasting_router
from .modules.fulfilment.router import router as fulfilment_router
from .modules.inbound.router import router as inbound_router
from .modules.inventory.router import router as inventory_router
from .modules.network_planning.router import router as network_planning_router
from .modules.pickpack.router import router as pickpack_router
from .modules.replenishment.router import router as replenishment_router
from .modules.serviceability.router import router as serviceability_router
from .modules.slotting.router import router as slotting_router

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if config.JWT_SECRET == config.DEFAULT_JWT_SECRET:
        logging.getLogger("uvicorn.error").warning(
            "JWT_SECRET is not set: tokens are signed with the public development secret.")
    init_db()
    with SessionLocal() as db:
        seed.seed_if_empty(db)
    yield


app = FastAPI(
    title="Dark Store Prototype",
    version="0.1.0",
    description="Micro-warehousing module of a quick-commerce app. One module per service in the HLD.",
    lifespan=lifespan,
)


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.status,
                        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})


for router in (
    auth.router, serviceability_router, inventory_router, fulfilment_router, pickpack_router, inbound_router,
    replenishment_router, forecasting_router, slotting_router, assortment_router,
    network_planning_router, dashboard_router,
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


# The demo screens. Mounted last so the API routes above take priority.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
