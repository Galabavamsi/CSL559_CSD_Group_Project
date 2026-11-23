from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import require_user_role
from ...db import get_db
from . import service

router = APIRouter(tags=["orders"])
Customer = Depends(require_user_role("customer"))


class AddressIn(BaseModel):
    label: str = Field(min_length=1, max_length=120, pattern=r"\S", description="The area, e.g. Supela, Bhilai")
    line: str = Field(min_length=3, max_length=120, pattern=r"\S", description="House or flat, and street")
    landmark: str | None = Field(default=None, max_length=80)
    lat: float = Field(ge=-90, le=90, allow_inf_nan=False)
    lng: float = Field(ge=-180, le=180, allow_inf_nan=False)


class OrderIn(BaseModel):
    hold_id: str = Field(min_length=1, max_length=36, description="The id of the checkout hold being paid for")
    address: AddressIn


@router.post("/v1/orders", status_code=201, summary="Pay for a held cart and make it an order")
def place_order(body: OrderIn, user: dict = Customer, db: Session = Depends(get_db)):
    """Confirms the hold and writes the order in one step: who it is for, where it goes, and the price of each
    unit. Payment is a stand-in: no money moves. Asking again for the same hold returns the same order. The address
    must be one the hold's hub delivers to (`422 address_outside_zone`); a hold that ran out is refused
    (`409 hold_expired`)."""
    address = body.address.model_dump()
    address["label"], address["line"] = " ".join(address["label"].split()), " ".join(address["line"].split())
    address["landmark"] = " ".join((address["landmark"] or "").split()) or None
    return service.place(db, user["user_id"], body.hold_id, address)


@router.get("/v1/orders", summary="My orders, newest first")
def my_orders(user: dict = Customer, db: Session = Depends(get_db)):
    return service.mine(db, user["user_id"])


@router.get("/v1/orders/{order_id}", summary="One of my orders, with its timeline")
def read_order(order_id: str, user: dict = Customer, db: Session = Depends(get_db)):
    return service.view(db, service.get(db, user["user_id"], order_id))


@router.post("/v1/orders/{order_id}/cancel", summary="Cancel an order the hub has not packed yet")
def cancel_order(order_id: str, user: dict = Customer, db: Session = Depends(get_db)):
    """The items go back on sale. Safe to repeat. `409 too_late` once the hub has packed it."""
    return service.cancel(db, user["user_id"], order_id)
