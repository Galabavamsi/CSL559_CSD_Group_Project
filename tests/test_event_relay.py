"""Live event feed (HLD 8.2, 9.2): the outbox relay, its sinks and the WebSocket feed."""
from datetime import timedelta

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app import auth, events
from app.models import EventLog, utcnow
from app.modules.dashboard import service as dashboard

from .conftest import place_paid_order


@pytest.fixture()
def sink(monkeypatch):
    """Replace the real sinks with a list that records what the relay hands over."""
    received: list[dict] = []
    monkeypatch.setattr(events, "sinks", [received.append])
    return received


def publish(db, event_type="test.happened", store_id=1, **payload):
    events.publish(db, event_type, store_id, payload)
    db.commit()


def test_relay_hands_each_event_to_the_sink_once_and_marks_it_published(db, sink):
    events.relay_once(db)                      # clear whatever the seed left in the outbox
    sink.clear()
    publish(db, n=1)

    sent = events.relay_once(db)
    again = events.relay_once(db)

    assert sent == 1 and again == 0
    assert [(e["type"], e["store_id"], e["payload"]) for e in sink] == [("test.happened", 1, {"n": 1})]
    row = db.scalar(select(EventLog).order_by(EventLog.id.desc()))
    assert row.published_at is not None


def test_failing_sink_leaves_the_event_unpublished_and_it_is_retried_in_order(db, monkeypatch):
    events.relay_once(db)
    delivered: list[int] = []
    broker_is_up = False

    def flaky_sink(event: dict) -> None:
        if not broker_is_up:
            raise ConnectionError("broker is down")
        delivered.append(event["payload"]["n"])

    monkeypatch.setattr(events, "sinks", [flaky_sink])
    publish(db, n=1)
    publish(db, n=2)

    assert events.relay_once(db) == 0
    unpublished = db.scalars(select(EventLog).where(EventLog.published_at.is_(None))).all()
    assert len(unpublished) == 2 and delivered == []

    broker_is_up = True
    assert events.relay_once(db) == 2
    assert delivered == [1, 2]


def test_dashboard_reports_how_far_the_relay_is_behind(db, sink):
    events.relay_once(db)
    assert dashboard.store_dashboard(db, 1)["outbox_lag_seconds"] == 0

    db.add(EventLog(type="test.old", store_id=1, payload={}, ts=utcnow() - timedelta(seconds=40)))
    db.commit()
    assert dashboard.store_dashboard(db, 1)["outbox_lag_seconds"] >= 40

    events.relay_once(db)
    assert dashboard.store_dashboard(db, 1)["outbox_lag_seconds"] == 0


def test_websocket_pushes_a_stores_events_to_its_staff(client, sku):
    token = auth.make_token("manager1", "manager", 1)
    with client.websocket_connect("/v1/ws/events?store_id=1") as ws:
        ws.send_text(token)
        assert ws.receive_json() == {"type": "connected", "store_id": 1}

        place_paid_order(client, "live-1", 1, [(sku("Tea"), 1)])

        event = ws.receive_json()          # pushed by the relay running in the app, no polling
        while event["type"] != "order.paid":
            event = ws.receive_json()
        assert event["store_id"] == 1 and event["payload"]["order_id"] == "live-1"


def test_websocket_refuses_a_bad_token_and_another_stores_staff(client):
    with client.websocket_connect("/v1/ws/events?store_id=1") as ws:
        ws.send_text("not-a-token")
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()

    with client.websocket_connect("/v1/ws/events?store_id=2") as ws:
        ws.send_text(auth.make_token("picker1", "picker", 1))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_websocket_accepts_city_wide_ops_for_any_store(client):
    with client.websocket_connect("/v1/ws/events?store_id=2") as ws:
        ws.send_text(auth.make_token("ops", "ops", None))
        assert ws.receive_json() == {"type": "connected", "store_id": 2}


def test_websocket_closes_when_the_token_expires(client):
    with client.websocket_connect("/v1/ws/events?store_id=1") as ws:
        ws.send_text(auth.make_token("manager1", "manager", 1, minutes=1 / 60))   # valid for one second
        assert ws.receive_json()["type"] == "connected"
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
        assert closed.value.code == 1008


def test_websocket_refuses_a_binary_first_message(client):
    with client.websocket_connect("/v1/ws/events?store_id=1") as ws:
        ws.send_bytes(b"\x00")
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
        assert closed.value.code == 1008
