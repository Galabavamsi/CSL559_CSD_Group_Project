"""App users (customers, farmers, delivery agents) sign in with a six-digit code sent to their email.

The rules these tests pin down are listed at the top of app/modules/accounts/service.py."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from starlette.websockets import WebSocketDisconnect

from app import config, email
from app.main import app
from app.models import LoginCode, RefreshToken, User, utcnow

ASHA = "asha@example.com"


@pytest.fixture()
def anon(fresh_data):
    """A caller with no token, and an empty record of emails sent."""
    email.outbox.clear()
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def no_waiting(monkeypatch):
    """Let an address ask for codes back to back, for tests that need several."""
    monkeypatch.setattr(config, "OTP_RESEND_SECONDS", 0)


def ask(client, address=ASHA, role="customer"):
    return client.post("/v1/auth/otp/request", json={"email": address, "role": role})


def emails_to(address=ASHA) -> list:
    return [message for message in email.outbox if message.to == address]


def code_sent_to(address=ASHA) -> str:
    return re.search(r"\b(\d{6})\b", emails_to(address)[-1].text).group(1)


def check(client, code, address=ASHA):
    return client.post("/v1/auth/otp/verify", json={"email": address, "code": code})


def sign_in(client, address=ASHA, role="customer") -> dict:
    assert ask(client, address, role).status_code == 200
    res = check(client, code_sent_to(address), address)
    assert res.status_code == 200, res.text
    return res.json()


def bearer(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}


def a_wrong_code(right: str) -> str:
    return f"{(int(right) + 1) % 10 ** 6:06d}"


# --------------------------------------------------------------------------- signing in

def test_the_first_sign_in_creates_the_account_and_the_next_one_finds_it(anon, db, no_waiting):
    first = sign_in(anon)

    assert first["is_new"] is True and first["token_type"] == "bearer" and first["expires_in"] == 3600
    assert first["user"] == {"id": first["user"]["id"], "role": "customer", "name": None, "email": ASHA,
                             "phone": None, "city": None}
    assert anon.get("/v1/me", headers=bearer(first)).json() == first["user"]

    again = sign_in(anon)

    assert again["is_new"] is False and again["user"]["id"] == first["user"]["id"]
    assert db.scalar(select(func.count()).select_from(User)) == 1


def test_the_code_goes_out_by_email_and_is_neither_returned_nor_stored(anon, db):
    res = ask(anon)

    assert res.json() == {"sent": True, "expires_in_seconds": 600, "retry_after_seconds": 60}
    (message,) = emails_to()
    code = code_sent_to()
    assert code in message.subject and "expires in 10 minutes" in message.text
    row = db.scalar(select(LoginCode))
    assert code not in (row.code_hash, res.text) and len(row.code_hash) == 64        # a keyed hash, not the code


def test_a_farmer_registers_by_signing_in_as_one(anon):
    assert sign_in(anon, "ravi@example.com", "farmer")["user"]["role"] == "farmer"


def test_the_accounts_own_role_wins_over_the_role_asked_for_later(anon, no_waiting):
    sign_in(anon, role="customer")

    assert sign_in(anon, role="farmer")["user"]["role"] == "customer"


def test_an_address_is_the_same_account_however_it_is_typed(anon, no_waiting):
    first = sign_in(anon, "Asha@Example.com")
    ask(anon, "  ASHA@EXAMPLE.COM ")

    again = check(anon, code_sent_to(ASHA), "asha@EXAMPLE.com")

    assert again.json()["user"]["id"] == first["user"]["id"]


@pytest.mark.parametrize("address", ["not-an-address", "two@@example.com", "no-dot@example", "spa ce@example.com"])
def test_something_that_is_not_an_email_address_is_refused(anon, address):
    res = ask(anon, address)

    assert res.status_code == 422 and res.json()["error"]["code"] == "bad_email"
    assert not email.outbox


# --------------------------------------------------------------------------- what a code is good for

def test_a_wrong_code_is_refused_and_the_right_one_still_works_after_it(anon):
    ask(anon)
    right = code_sent_to()

    wrong = check(anon, a_wrong_code(right))

    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "bad_code"
    assert check(anon, right).status_code == 200


def test_after_five_tries_the_code_is_dead_even_for_the_right_one(anon):
    ask(anon)
    right = code_sent_to()

    wrong = [check(anon, a_wrong_code(right)).status_code for _ in range(5)]
    sixth = check(anon, right)

    assert wrong == [401] * 5
    assert sixth.status_code == 429 and sixth.json()["error"]["code"] == "too_many_attempts"


def test_a_code_works_once(anon):
    ask(anon)
    code = code_sent_to()

    assert check(anon, code).status_code == 200
    assert check(anon, code).json()["error"]["code"] == "bad_code"


def test_two_tries_of_the_right_code_at_once_sign_in_once(anon, db):
    ask(anon)
    code = code_sent_to()

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(res.status_code for res in pool.map(lambda _: check(anon, code), range(2)))

    assert statuses == [200, 401]
    assert db.scalar(select(func.count()).select_from(RefreshToken)) == 1


def test_a_code_expires(anon, db):
    ask(anon)
    db.execute(update(LoginCode).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()

    assert check(anon, code_sent_to()).json()["error"]["code"] == "bad_code"


def test_a_code_for_one_address_is_no_good_for_another(anon):
    ask(anon)
    ask(anon, "ravi@example.com")

    assert check(anon, code_sent_to(ASHA), "ravi@example.com").status_code == 401


# --------------------------------------------------------------------------- how often a code can be asked for

def test_asking_again_at_once_is_refused_and_says_how_long_to_wait(anon):
    ask(anon)

    again = ask(anon)

    assert again.status_code == 429 and again.json()["error"]["code"] == "too_soon"
    assert 0 < again.json()["error"]["details"]["retry_after_seconds"] <= 60
    assert len(emails_to()) == 1


def test_a_new_code_replaces_the_one_before_it(anon, no_waiting):
    ask(anon)
    old = code_sent_to()
    ask(anon)
    new = code_sent_to()

    if old != new:                           # one time in a million they are the same six digits
        assert check(anon, old).status_code == 401
    assert check(anon, new).status_code == 200


def test_an_address_gets_five_codes_an_hour_and_no_more(anon, no_waiting):
    asked = [ask(anon).status_code for _ in range(6)]

    assert asked == [200] * 5 + [429]
    assert ask(anon).json()["error"]["code"] == "too_many_codes"
    assert len(emails_to()) == 5
    assert ask(anon, "ravi@example.com").status_code == 200       # the limit is per address


# --------------------------------------------------------------------------- delivery agents are not self-service

def test_an_unknown_address_asking_to_be_an_agent_is_answered_like_anyone_and_sent_nothing(anon, db):
    res = ask(anon, "stranger@example.com", "agent")

    assert res.status_code == 200 and res.json() == ask(anon, ASHA).json()        # the same answer as a customer gets
    assert emails_to("stranger@example.com") == []
    assert db.scalar(select(func.count()).select_from(User)) == 0
    # and there is no code to guess: the row that was written is already spent
    assert db.scalar(select(LoginCode.used_at).where(LoginCode.email == "stranger@example.com")) is not None


def test_an_agent_signs_in_once_the_platform_team_has_created_the_account(anon, client):
    made = client.post("/v1/admin/users", json={"email": "Kiran@Example.com", "role": "agent", "name": " Kiran "})

    assert made.status_code == 201 and made.json()["email"] == "kiran@example.com" and made.json()["name"] == "Kiran"
    assert sign_in(anon, "kiran@example.com", "customer")["user"]["role"] == "agent"
    assert client.post("/v1/admin/users", json={"email": "kiran@example.com", "role": "agent"}).status_code == 409


def test_only_ops_and_admin_create_accounts(anon, client_as):
    body = {"email": "kiran@example.com", "role": "agent"}

    assert anon.post("/v1/admin/users", json=body).status_code == 401
    with client_as("manager", 1) as manager:
        assert manager.post("/v1/admin/users", json=body).status_code == 403
    with client_as("ops") as ops:
        assert ops.post("/v1/admin/users", json=body).status_code == 201


# --------------------------------------------------------------------------- the account

def test_a_user_reads_and_changes_their_own_name_phone_and_city(anon):
    asha = bearer(sign_in(anon))

    changed = anon.patch("/v1/me", headers=asha, json={"name": "  Asha Rao ", "phone": "+91 98765-43210",
                                                       "city": "bhilai"})

    assert changed.status_code == 200
    assert (changed.json()["name"], changed.json()["phone"], changed.json()["city"]) == ("Asha Rao", "+919876543210",
                                                                                         "bhilai")
    assert anon.patch("/v1/me", headers=asha, json={"phone": None}).json()["phone"] is None
    assert anon.get("/v1/me", headers=asha).json()["name"] == "Asha Rao"         # fields not sent are left alone


def test_a_bad_phone_number_or_an_unknown_city_is_refused(anon):
    asha = bearer(sign_in(anon))

    assert anon.patch("/v1/me", headers=asha, json={"phone": "12ab"}).json()["error"]["code"] == "bad_phone"
    assert anon.patch("/v1/me", headers=asha, json={"city": "atlantis"}).json()["error"]["code"] == "unknown_city"
    assert anon.get("/v1/me").status_code == 401


# --------------------------------------------------------------------------- staff and app users are kept apart

def test_an_app_users_token_opens_no_staff_endpoint(anon):
    asha = bearer(sign_in(anon))

    for path in ("/v1/stores/1/dashboard", "/v1/audit", "/v1/stores/1/ledger"):
        res = anon.get(path, headers=asha)
        assert res.status_code == 403 and res.json()["error"]["code"] == "forbidden", path
    assert anon.post("/v1/admin/reset", headers=asha).status_code == 403


def test_an_app_users_token_does_not_open_the_live_feed(anon):
    session = sign_in(anon)

    with anon.websocket_connect("/v1/ws/events?store_id=1") as ws:
        ws.send_text(session["access_token"])
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1008


def test_a_staff_token_is_not_an_app_users(client):
    res = client.get("/v1/me")                     # `client` is logged in as admin

    assert res.status_code == 403 and res.json()["error"]["code"] == "forbidden"


# --------------------------------------------------------------------------- sessions

def test_a_refresh_token_gives_a_new_session_and_then_is_spent(anon):
    first = sign_in(anon)

    second = anon.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})

    assert second.status_code == 200 and second.json()["refresh_token"] != first["refresh_token"]
    assert second.json()["user"] == first["user"]
    assert anon.get("/v1/me", headers=bearer(second.json())).status_code == 200


def test_a_spent_refresh_token_turning_up_again_ends_every_session(anon):
    first = sign_in(anon)
    second = anon.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).json()

    replay = anon.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})    # a stolen copy

    assert replay.status_code == 401 and replay.json()["error"]["code"] == "bad_refresh_token"
    assert anon.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]}).status_code == 401


def test_signing_out_ends_that_session_only(anon, no_waiting):
    phone, tablet = sign_in(anon), sign_in(anon)

    out = anon.post("/v1/auth/logout", json={"refresh_token": phone["refresh_token"]})

    assert out.json() == {"signed_out": True}
    assert anon.post("/v1/auth/refresh", json={"refresh_token": tablet["refresh_token"]}).status_code == 200
    assert anon.post("/v1/auth/logout", json={"refresh_token": "x" * 43}).status_code == 200    # unknown: no error


def test_a_refresh_token_expires_and_an_unknown_one_is_refused(anon, db):
    session = sign_in(anon)
    db.execute(update(RefreshToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    db.commit()

    assert anon.post("/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}).status_code == 401
    assert anon.post("/v1/auth/refresh", json={"refresh_token": "y" * 43}).status_code == 401


def test_the_refresh_token_itself_is_not_in_the_database(anon, db):
    session = sign_in(anon)

    stored = db.scalar(select(RefreshToken.token_hash))

    assert stored != session["refresh_token"] and len(stored) == 64


# --------------------------------------------------------------------------- when the email cannot be sent

def test_an_email_that_cannot_be_sent_does_not_fail_the_request_or_reach_the_log(anon, monkeypatch, caplog):
    def broken(to, subject, text):
        raise email.EmailError("Amazon SES refused or could not be reached: ClientError")
    monkeypatch.setattr(email, "send", broken)

    with caplog.at_level("ERROR", logger="darkstore.email"):
        res = ask(anon)

    assert res.status_code == 200                  # the answer never depends on the send: it gives nothing away
    assert "Could not send an email" in caplog.text and not re.search(r"\b\d{6}\b", caplog.text)
