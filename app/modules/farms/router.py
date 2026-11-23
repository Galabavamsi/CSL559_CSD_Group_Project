from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ... import config
from ...auth import check_store, require_role, require_user_role
from ...db import get_db
from ...idempotency import run_once
from ...ids import Id, PathId
from . import service

router = APIRouter(tags=["farm supply"])

IdempotencyKey = Annotated[str | None, Header(
    min_length=1, max_length=80,
    description="Any unique string. A retry with the same key is not done again; it returns the first answer.")]
Farmer = Annotated[dict, Depends(require_user_role("farmer"))]
Kg = Annotated[float, Field(gt=0, le=config.LISTING_MAX_KG, allow_inf_nan=False)]


class FarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, allow_inf_nan=False,
                                     description="How sure the phone is of this location, in metres. Leave it out "
                                                 "for a pin placed by hand.")
    area_acres: float | None = Field(default=None, gt=0, le=10_000, allow_inf_nan=False)


class ListingIn(BaseModel):
    farm_id: Id
    item_id: Id
    qty_kg: Kg
    price_per_kg: float = Field(gt=0, le=100_000, allow_inf_nan=False)
    harvest_date: date


class PackIn(BaseModel):
    sku_id: Id
    units: int = Field(ge=0, le=100_000)


class IntakeIn(BaseModel):
    received_kg: Kg
    rejected_kg: float = Field(default=0, ge=0, le=config.LISTING_MAX_KG * 2, allow_inf_nan=False)
    grade: Literal["A", "B", "C", "reject"]
    remarks: str | None = Field(default=None, max_length=200)
    packs: list[PackIn] | None = Field(default=None, max_length=20,
                                       description="How to pack what was accepted. Left out: all of it into the "
                                                   "item's smallest unit.")


@router.get("/v1/produce-items", summary="What a farmer can list, and the units customers buy it in")
def produce_items(db: Session = Depends(get_db)):
    return service.items(db)


@router.post("/v1/farms", status_code=201, summary="Register a farm at its location")
def create_farm(body: FarmIn, farmer: Farmer, db: Session = Depends(get_db)):
    return service.create_farm(db, farmer["user_id"], body.name, body.lat, body.lng, body.accuracy_m, body.area_acres)


@router.get("/v1/farms", summary="Your farms")
def list_farms(farmer: Farmer, db: Session = Depends(get_db)):
    return service.list_farms(db, farmer["user_id"])


@router.post("/v1/listings", status_code=201, summary="List produce; the answer names the hub and the drop slot")
def create_listing(body: ListingIn, farmer: Farmer, idempotency_key: IdempotencyKey = None,
                   db: Session = Depends(get_db)):
    return run_once(db, f"listing:{farmer['user_id']}", idempotency_key, body.model_dump(mode="json"),
                    lambda: service.create_listing(db, farmer["user_id"], body.farm_id, body.item_id, body.qty_kg,
                                                   body.price_per_kg, body.harvest_date))


@router.get("/v1/listings", summary="Your listings, newest first, with each one's quality check")
def list_listings(farmer: Farmer, db: Session = Depends(get_db)):
    return service.list_listings(db, farmer["user_id"])


@router.post("/v1/listings/{listing_id}/cancel", summary="Withdraw a listing that has not been dropped yet")
def cancel_listing(listing_id: PathId, farmer: Farmer, db: Session = Depends(get_db)):
    return service.cancel_listing(db, farmer["user_id"], listing_id)


@router.get("/v1/stores/{store_id}/expected-drops", summary="Lots on their way to this hub")
def expected_drops(store_id: PathId, db: Session = Depends(get_db),
                   staff: dict = Depends(require_role("receiver", "manager", "ops"))):
    check_store(staff, store_id)
    return service.expected_drops(db, store_id)


@router.get("/v1/stores/{store_id}/lots-on-dock", summary="Lots weighed here whose packs are not all put away yet")
def lots_on_dock(store_id: PathId, db: Session = Depends(get_db),
                 staff: dict = Depends(require_role("receiver", "manager", "ops"))):
    """Each has `quality_check.receipt_id`: carry on with that goods receipt's putaway tasks."""
    check_store(staff, store_id)
    return service.lots_on_dock(db, store_id)


@router.post("/v1/listings/{listing_id}/intake", summary="Weigh and grade a lot at the hub, and pack what is accepted")
def intake(listing_id: PathId, body: IntakeIn, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db),
           staff: dict = Depends(require_role("receiver", "manager"))):
    """The packed units wait on a new goods receipt. Put them away with the receiving steps
    (`/v1/goods-receipts/{id}/putaway-tasks`, `/putaway`, `/close`); each line is sellable once it is in its bin."""
    listing = service.get_listing(db, listing_id)
    check_store(staff, listing.store_id)
    packs = [pack.model_dump() for pack in body.packs] if body.packs is not None else None
    return run_once(db, f"intake:{listing_id}", idempotency_key, body.model_dump(mode="json"),
                    lambda: service.intake(db, listing, body.received_kg, body.rejected_kg, body.grade, body.remarks,
                                           packs, staff["sub"]))
