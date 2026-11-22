from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ... import email
from ...auth import current_user, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["accounts"])

Role = Literal["customer", "farmer", "agent"]


class CodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Role = "customer"


class CodeCheck(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(pattern=r"^[0-9]{6}$")


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class ProfileChanges(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=24)
    city: str | None = Field(default=None, max_length=40, description="A city's slug, for example bhilai")


class NewUser(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Role
    name: str | None = Field(default=None, max_length=80)


@router.post("/v1/auth/otp/request", summary="Email a sign-in code")
def request_code(body: CodeRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    """The answer is the same whether or not the address has an account. `role` matters only the first time an
    address signs in; after that the account's own role is used."""
    answer, message = service.request_code(db, body.email, body.role)
    if message is not None:
        background.add_task(email.send_quietly, *message)      # after the answer, so its time gives nothing away
    return answer


@router.post("/v1/auth/otp/verify", summary="Exchange a sign-in code for a session")
def verify_code(body: CodeCheck, db: Session = Depends(get_db)):
    return service.verify_code(db, body.email, body.code)


@router.post("/v1/auth/refresh", summary="Exchange a refresh token for a new session")
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    return service.refresh(db, body.refresh_token)


@router.post("/v1/auth/logout", summary="End a session")
def sign_out(body: RefreshIn, db: Session = Depends(get_db)):
    return service.sign_out(db, body.refresh_token)


@router.get("/v1/me", summary="The signed-in app user's own account")
def me(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.me(db, user["user_id"])


@router.patch("/v1/me", summary="Change your name, phone or city")
def update_me(body: ProfileChanges, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    return service.update_me(db, user["user_id"], body.model_dump(exclude_unset=True))


@router.post("/v1/admin/users", status_code=201, summary="Create an app account ahead of its first sign-in",
             dependencies=[Depends(require_role("ops"))])
def create_user(body: NewUser, db: Session = Depends(get_db)):
    """How a delivery agent gets an account: agents cannot register themselves."""
    return service.create(db, body.email, body.role, body.name)
