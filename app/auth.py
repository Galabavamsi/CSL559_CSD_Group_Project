"""Login and roles (HLD 10): who is calling, and may they do this for this store?

Routers use three things from here:

    staff: dict = Depends(current_staff)               # any logged-in staff
    staff: dict = Depends(require_role("manager"))     # only these roles (admin always passes)
    check_store(staff, store_id)                       # and only for their own store

`staff` is the decoded token: {"sub": username, "role": ..., "store_id": ... or None, "exp": ...}.

People who use the phone app (customers, farmers, delivery agents) are a second kind of caller, with their own
roles and their own dependencies:

    user: dict = Depends(current_user)                 # any signed-in app user
    user: dict = Depends(require_user_role("farmer"))  # only these roles

`user` is {"sub": "user:<id>", "user_id": ..., "role": ..., "exp": ...}. The two kinds never pass for each other:
a staff endpoint refuses an app user's token, and the other way round.
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

ROLES = ("picker", "packer", "receiver", "manager", "ops", "admin")      # hub and platform staff
USER_ROLES = ("customer", "farmer", "agent")                              # people who use the phone app
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


def make_user_token(user_id: int, role: str) -> str:
    """Access token of an app user. Short-lived: the app renews it with its refresh token (accounts.service)."""
    claims = {"sub": f"user:{user_id}", "user_id": user_id, "role": role, "store_id": None,
              "exp": datetime.now(timezone.utc) + timedelta(minutes=config.USER_TOKEN_MINUTES)}
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


def decode_staff_token(token: str) -> dict:
    """`decode_token`, for the staff side: 403 for a valid token that belongs to an app user. Without this check a
    customer's token would pass every endpoint that asks only for "any logged-in staff", and, having no store,
    would count as city-wide."""
    claims = decode_token(token)
    if claims["role"] not in ROLES:
        raise DomainError(403, "forbidden", "This is for hub staff")
    return claims


def current_staff(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """Decode the bearer token or raise 401. The caller is kept on the request for the audit log."""
    if credentials is None:
        raise DomainError(401, "not_logged_in", "Log in and send the token as 'Authorization: Bearer <token>'")
    request.state.staff = decode_staff_token(credentials.credentials)
    return request.state.staff


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    """The signed-in app user's token contents, or 401; 403 for a staff token."""
    if credentials is None:
        raise DomainError(401, "not_logged_in", "Sign in and send the token as 'Authorization: Bearer <token>'")
    claims = decode_token(credentials.credentials)
    if claims["role"] not in USER_ROLES or "user_id" not in claims:
        raise DomainError(403, "forbidden", "This is for people signed in to the app")
    return claims


def require_user_role(*roles: str):
    """Dependency: 403 unless the app user has one of these roles."""
    def dependency(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise DomainError(403, "forbidden", f"A {user['role']} may not do this")
        return user
    return dependency


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
