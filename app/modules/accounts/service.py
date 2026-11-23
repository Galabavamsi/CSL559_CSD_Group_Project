"""Accounts for the people who use the phone app: customers, farmers and delivery agents.

They sign in with a six-digit code sent to their email; there is no password to forget or to leak. The rules, each
with a test in tests/test_accounts.py (sources in docs/journal/2026-11-23-accounts-and-email-codes.md):

* A code is random, works once, and dies after OTP_TTL_MINUTES or OTP_MAX_ATTEMPTS wrong tries.
* Only a keyed hash of a code is stored. A six-digit code has a million values, so a plain hash could be reversed by
  trying them all; the key (JWT_SECRET) is not in the database.
* Asking for a code gives the same answer whether or not the address has an account, and the email is sent after
  the answer, so neither the words nor the time taken reveal who is registered.
* An address may ask again after OTP_RESEND_SECONDS, and at most OTP_MAX_PER_HOUR times an hour. A new code replaces
  the one before it.
* Customers and farmers register themselves by signing in the first time. A delivery agent's account is created by
  the platform team; an unknown address asking to be an agent is answered like any other and sent nothing.

A session is a short-lived access token plus a refresh token that is exchanged for a new pair before it runs out.
A refresh token works once. If one that was already exchanged turns up again, somebody has a copy, and every
session of that user is ended.
"""
import hashlib
import hmac
import math
import re
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ... import auth, config
from ...errors import DomainError
from ...models import City, LoginCode, RefreshToken, User, utcnow

SELF_SIGNUP_ROLES = ("customer", "farmer")
# Deliberately loose: one @, no spaces, a dot in the domain. The real check is that the code arrives.
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+")
PHONE = re.compile(r"\+?[0-9]{7,15}")
BAD_CODE = (401, "bad_code", "That code is not right, or it has expired. Ask for a new one.")
BAD_REFRESH = (401, "bad_refresh_token", "This session has ended. Sign in again.")


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    # `.invalid` can never receive mail (RFC 2606). Accounts that nobody is meant to sign in to are given such an
    # address (the demo farms), so no code is ever made for one.
    if len(email) > 254 or not EMAIL.fullmatch(email) or email.endswith(".invalid"):
        raise DomainError(422, "bad_email", "That does not look like an email address")
    return email


def _code_hash(email: str, code: str) -> str:
    return hmac.new(config.JWT_SECRET.encode(), f"login-code:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _token_hash(token: str) -> str:
    """Refresh tokens are 32 random bytes, far too many to try, so an unkeyed hash is enough to store."""
    return hashlib.sha256(token.encode()).hexdigest()


def public(user: User, city: City | None = None) -> dict:
    return {"id": user.id, "role": user.role, "name": user.name, "email": user.email, "phone": user.phone,
            "city": city.slug if city else None}


def _with_city(db: Session, user: User) -> dict:
    return public(user, db.get(City, user.city_id) if user.city_id else None)


# --------------------------------------------------------------------------- codes

def request_code(db: Session, email: str, role: str) -> tuple[dict, tuple[str, str, str] | None]:
    """Make a login code for this address. Returns the answer for the caller and, unless nothing is to be sent, the
    (to, subject, text) of the email, which the router sends after answering. Commits."""
    email = normalise_email(email)
    now = utcnow()
    # One request at a time per address: two at once would both pass the checks below and both send a code.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(email))))
    hour = db.scalars(select(LoginCode).where(LoginCode.email == email, LoginCode.created_at > now - timedelta(hours=1))
                      .order_by(LoginCode.id.desc())).all()
    if hour:
        waited = (now - hour[0].created_at).total_seconds()
        if waited < config.OTP_RESEND_SECONDS:
            wait = math.ceil(config.OTP_RESEND_SECONDS - waited)
            raise DomainError(429, "too_soon", f"A code was sent a moment ago. You can ask again in {wait} seconds.",
                              {"retry_after_seconds": wait})
    if len(hour) >= config.OTP_MAX_PER_HOUR:
        raise DomainError(429, "too_many_codes", "Too many codes were asked for this address. Try again in an hour.",
                          {"retry_after_seconds": 3600})

    db.execute(delete(LoginCode).where(LoginCode.email == email, LoginCode.created_at <= now - timedelta(days=1)))
    db.execute(update(LoginCode).where(LoginCode.email == email, LoginCode.used_at.is_(None)).values(used_at=now))
    user = db.scalar(select(User).where(User.email == email))
    may_sign_in = (user is not None or role in SELF_SIGNUP_ROLES
                   or (role == "agent" and config.AGENT_SELF_SIGNUP))
    code = f"{secrets.randbelow(10 ** 6):06d}"
    # An address that may not sign in gets a row too, already spent: it counts towards the limits above, so the
    # answers and their timing stay the same, and no code exists that could be guessed.
    db.add(LoginCode(email=email, role=user.role if user else role, code_hash=_code_hash(email, code),
                     created_at=now, expires_at=now + timedelta(minutes=config.OTP_TTL_MINUTES),
                     used_at=None if may_sign_in else now))
    db.commit()
    answer = {"sent": True, "expires_in_seconds": config.OTP_TTL_MINUTES * 60,
              "retry_after_seconds": config.OTP_RESEND_SECONDS}
    if not may_sign_in:
        return answer, None
    text = (f"Your Farm2Home sign-in code is {code}\n\n"
            f"It works once and expires in {config.OTP_TTL_MINUTES} minutes.\n"
            "If you did not ask for it, ignore this email: nobody can sign in without the code.\n")
    return answer, (email, f"{code} is your Farm2Home sign-in code", text)


def verify_code(db: Session, email: str, code: str) -> dict:
    """Exchange a login code for a session. The first sign-in of an address creates its account. Commits."""
    email = normalise_email(email)
    now = utcnow()
    row = db.scalar(select(LoginCode).where(LoginCode.email == email, LoginCode.used_at.is_(None),
                                            LoginCode.expires_at > now).order_by(LoginCode.id.desc()))
    given = _code_hash(email, code)          # worked out before the row is looked at, so every path takes as long
    if row is None:
        raise DomainError(*BAD_CODE)
    # Count the try first, in its own commit, so that it is counted whatever happens next and two tries at once
    # cannot both be the fifth.
    counted = db.execute(update(LoginCode).where(LoginCode.id == row.id, LoginCode.attempts < config.OTP_MAX_ATTEMPTS)
                         .values(attempts=LoginCode.attempts + 1)).rowcount
    db.commit()
    if not counted:
        raise DomainError(429, "too_many_attempts", "Too many wrong codes. Ask for a new one.")
    if not hmac.compare_digest(given, row.code_hash):
        raise DomainError(*BAD_CODE)
    spent = db.execute(update(LoginCode).where(LoginCode.id == row.id, LoginCode.used_at.is_(None))
                       .values(used_at=now)).rowcount
    if not spent:                            # another request used this code a moment ago: it works once
        db.rollback()
        raise DomainError(*BAD_CODE)
    user = db.scalar(select(User).where(User.email == email))
    is_new = user is None
    if is_new:
        user = User(email=email, role=row.role, created_at=now)
        db.add(user)
    user.last_login_at = now
    db.flush()
    session = _new_session(db, user, now)
    db.commit()
    return {**session, "user": _with_city(db, user), "is_new": is_new}


# --------------------------------------------------------------------------- sessions

def _new_session(db: Session, user: User, now) -> dict:
    refresh_token = secrets.token_urlsafe(32)
    db.add(RefreshToken(user_id=user.id, token_hash=_token_hash(refresh_token), created_at=now,
                        expires_at=now + timedelta(days=config.REFRESH_TOKEN_DAYS)))
    return {"access_token": auth.make_user_token(user.id, user.role), "token_type": "bearer",
            "expires_in": int(config.USER_TOKEN_MINUTES * 60), "refresh_token": refresh_token}


def refresh(db: Session, refresh_token: str) -> dict:
    """Exchange a refresh token for a new access token and a new refresh token. Commits."""
    now = utcnow()
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == _token_hash(refresh_token)))
    if row is None:
        raise DomainError(*BAD_REFRESH)
    if row.revoked_at is not None:
        # It was exchanged or signed out already, and here it is again: a copy exists. End every session.
        db.execute(update(RefreshToken).where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
                   .values(revoked_at=now))
        db.commit()
        raise DomainError(*BAD_REFRESH)
    if row.expires_at <= now:
        raise DomainError(*BAD_REFRESH)
    exchanged = db.execute(update(RefreshToken).where(RefreshToken.id == row.id, RefreshToken.revoked_at.is_(None))
                           .values(revoked_at=now)).rowcount
    if not exchanged:                        # two exchanges at once: one wins, the other signs in again
        db.rollback()
        raise DomainError(*BAD_REFRESH)
    user = db.get(User, row.user_id)
    session = _new_session(db, user, now)
    db.commit()
    return {**session, "user": _with_city(db, user)}


def sign_out(db: Session, refresh_token: str) -> dict:
    """End the session this refresh token belongs to. An unknown token is not an error. Commits."""
    db.execute(update(RefreshToken).where(RefreshToken.token_hash == _token_hash(refresh_token),
                                          RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    db.commit()
    return {"signed_out": True}


# --------------------------------------------------------------------------- the account itself

def get(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:                          # the account was removed after the token was issued
        raise DomainError(401, "bad_token", "This account no longer exists")
    return user


def me(db: Session, user_id: int) -> dict:
    return _with_city(db, get(db, user_id))


def update_me(db: Session, user_id: int, changes: dict) -> dict:
    """Change name, phone or city; only the fields present in `changes`. Commits."""
    user = get(db, user_id)
    if "name" in changes:
        user.name = (changes["name"] or "").strip() or None
    if "phone" in changes:
        phone = re.sub(r"[\s-]", "", changes["phone"] or "")
        if phone and not PHONE.fullmatch(phone):
            raise DomainError(422, "bad_phone", "A phone number is 7 to 15 digits, with an optional + in front")
        user.phone = phone or None
    if "city" in changes:
        if changes["city"] is None:
            user.city_id = None
        else:
            city = db.scalar(select(City).where(City.slug == changes["city"]))
            if city is None:
                raise DomainError(422, "unknown_city", f"There is no city '{changes['city']}'")
            user.city_id = city.id
    db.commit()
    return _with_city(db, user)


def create(db: Session, email: str, role: str, name: str | None) -> dict:
    """Create an account ahead of its first sign-in: how a delivery agent gets one. Commits."""
    email = normalise_email(email)
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise DomainError(409, "email_taken", "That address already has an account")
    user = User(email=email, role=role, name=(name or "").strip() or None, created_at=utcnow())
    db.add(user)
    db.commit()
    return public(user)
