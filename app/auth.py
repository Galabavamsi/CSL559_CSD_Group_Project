"""Login and roles (HLD 10): who is calling, and may they do this for this store?

Routers use three things from here:

    staff: dict = Depends(current_staff)               # any logged-in staff
    staff: dict = Depends(require_role("manager"))     # only these roles (admin always passes)
    check_store(staff, store_id)                       # and only for their own store

`staff` is the decoded token: {"sub": username, "role": ..., "store_id": ... or None, "exp": ...}.
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .db import get_db
from .errors import DomainError
from .models import Staff

ROLES = ("picker", "packer", "receiver", "manager", "ops", "admin")
ALGORITHM = "HS256"

router = APIRouter(tags=["auth"])
_bearer = HTTPBearer(auto_error=False, description="Token from POST /v1/auth/login")


# --------------------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    """Salted scrypt hash, stored as 'salt:digest' in hex. Passwords are never stored as typed."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return salt.hex() + ":" + digest.hex()


def check_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split(":")
        again = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    except ValueError:   # a stored hash that is not 'salt:digest' matches nothing
        return False
    return hmac.compare_digest(again.hex(), digest)


# --------------------------------------------------------------------------- tokens

def make_token(username: str, role: str, store_id: int | None, minutes: float | None = None) -> str:
    """Signed token that says who the caller is. Readable by anyone, so it carries no secrets."""
    lifetime = timedelta(minutes=config.TOKEN_MINUTES if minutes is None else minutes)
    claims = {"sub": username, "role": role, "store_id": store_id,
              "exp": datetime.now(timezone.utc) + lifetime}
    return jwt.encode(claims, config.JWT_SECRET, algorithm=ALGORITHM)


def login(db: Session, username: str, password: str) -> dict:
    """Check a username and password and return a token. Does not write to the database."""
    staff = db.scalar(select(Staff).where(Staff.username == username))
    if staff is None:
        hash_password(password)   # spend the same time as a real check, so timing does not reveal usernames
    if staff is None or not check_password(password, staff.password_hash):
        raise DomainError(401, "bad_credentials", "Wrong username or password")
    return {"access_token": make_token(staff.username, staff.role, staff.store_id),
            "role": staff.role, "store_id": staff.store_id}


# --------------------------------------------------------------------------- dependencies

def decode_token(token: str) -> dict:
    """Check a token's signature and expiry and return its contents, or raise 401."""
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=[ALGORITHM],
                          options={"require": ["exp", "sub", "role"]})
    except jwt.PyJWTError:
        raise DomainError(401, "bad_token", "The token is invalid or has expired; log in again") from None


def current_staff(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """Decode the bearer token or raise 401. The caller is kept on the request for the audit log."""
    if credentials is None:
        raise DomainError(401, "not_logged_in", "Log in and send the token as 'Authorization: Bearer <token>'")
    request.state.staff = decode_token(credentials.credentials)
    return request.state.staff


def require_role(*roles: str):
    """Dependency: 403 unless the caller has one of these roles (admin always passes)."""
    def dependency(staff: dict = Depends(current_staff)) -> dict:
        if staff["role"] != "admin" and staff["role"] not in roles:
            raise DomainError(403, "forbidden", f"A {staff['role']} may not do this")
        return staff
    return dependency


def check_store(staff: dict, store_id: int | None) -> None:
    """403 if the caller is tied to a different store. City-wide staff (no store) may act on any store;
    `store_id=None` means "all stores", which only city-wide staff may ask for."""
    own_store = staff.get("store_id")
    if own_store is not None and own_store != store_id:
        raise DomainError(403, "wrong_store", "You can only act on your own store")


# --------------------------------------------------------------------------- endpoint

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


@router.post("/v1/auth/login", summary="Log in and get a bearer token")
def login_endpoint(body: LoginIn, db: Session = Depends(get_db)):
    return login(db, body.username, body.password)
