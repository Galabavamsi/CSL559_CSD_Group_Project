from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, require_role, require_user_role
from ...db import get_db
from ..accounts import service as accounts
from . import service

router = APIRouter(tags=["delivery"])
Agent = Depends(require_user_role("agent"))
OrderId = Annotated[str, Path(min_length=1, max_length=60)]
StoreId = Annotated[int, Path(ge=1, le=2_147_483_647)]


class HubIn(BaseModel):
    store_id: int = Field(ge=1, le=2_147_483_647)


class DutyIn(BaseModel):
    on_duty: bool


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{4}$", description="The four digits the customer reads out")


class FailIn(BaseModel):
    reason: Literal["nobody_home", "refused", "not_found"]


class AgentIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=80, pattern=r"\S")
    store_id: int = Field(ge=1, le=2_147_483_647)


@router.get("/v1/agent", summary="The agent's hub, whether they are on duty, and their trip")
def read_agent(user: dict = Agent, db: Session = Depends(get_db)):
    return service.me(db, user["user_id"])


@router.post("/v1/agent/hub", summary="Say which hub the agent works from")
def choose_hub(body: HubIn, user: dict = Agent, db: Session = Depends(get_db)):
    """Only while off duty (`409 on_duty`)."""
    return service.choose_hub(db, user["user_id"], body.store_id)


@router.post("/v1/agent/duty", summary="Go on or off duty")
def set_duty(body: DutyIn, user: dict = Agent, db: Session = Depends(get_db)):
    """On duty, the agent free longest at a hub is given the next trip, at once if orders have waited long enough.
    `409 no_hub` before a hub is chosen; `409 on_a_trip` when going off duty during a trip."""
    return service.set_duty(db, user["user_id"], body.on_duty)


@router.post("/v1/agent/trip/bags/{order_id}/load", summary="Confirm one bag of the trip at the hub")
def load_bag(order_id: OrderId, user: dict = Agent, db: Session = Depends(get_db)):
    """The order leaves the hub's hands for the agent's. When every bag of the trip is confirmed, the trip is out
    and its customers are told. Safe to repeat."""
    return service.load_bag(db, user["user_id"], order_id)


@router.post("/v1/agent/trip/stops/{order_id}/deliver", summary="Hand an order over against the customer's code")
def deliver(order_id: OrderId, body: CodeIn, user: dict = Agent, db: Session = Depends(get_db)):
    """`422 wrong_code` with `tries_left`; `409 code_locked` after too many; `409 not_left` before every bag is
    checked out of the hub."""
    return service.deliver(db, user["user_id"], order_id, body.code)


@router.post("/v1/agent/trip/stops/{order_id}/fail", summary="Report that an order could not be handed over")
def fail(order_id: OrderId, body: FailIn, user: dict = Agent, db: Session = Depends(get_db)):
    """The bag comes back to the hub with the agent."""
    return service.fail(db, user["user_id"], order_id, body.reason)


@router.post("/v1/admin/agents", status_code=201, summary="Make a delivery agent's account",
             dependencies=[Depends(require_role("admin"))])
def add_agent(body: AgentIn, db: Session = Depends(get_db)):
    """The agent then signs in to the app with a code sent to that address. `409 email_taken`."""
    return service.add_agent(db, accounts.normalise_email(body.email), body.name, body.store_id)


@router.get("/v1/stores/{store_id}/dispatch", summary="Bags waiting, trips forming and out, agents on duty")
def dispatch(store_id: StoreId, staff: dict = Depends(require_role("manager", "ops")),
             db: Session = Depends(get_db)):
    check_store(staff, store_id)
    return service.dispatch(db, store_id)
