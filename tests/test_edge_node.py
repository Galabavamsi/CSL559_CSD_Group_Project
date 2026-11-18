"""Edge-node experiment (Member 4 guide, section 7; the design is in docs/EDGE_NODE.md).

The store's own copy of the app keeps working while its link to the central copy is down. Its events wait in
the outbox and reach central afterwards, oldest first. Central is stood in for by a sink: the same hook a real
HTTP forwarder would use. No app code is changed for this; it runs the relay as it is.
"""
import pytest
from sqlalchemy import select

from app import events
from app.models import EventLog

from .conftest import place_paid_order


class Central:
    """The central copy's ingest: reachable or not, and keeping each event id once, as an ingest table with a
    unique (store_id, event_id) key would."""

    def __init__(self) -> None:
        self.up = False
        self.deliveries: list[int] = []
        self.kept: dict[int, dict] = {}

    def __call__(self, event: dict) -> None:
        if not self.up:
            raise ConnectionError("central is unreachable")
        self.deliveries.append(event["id"])
        self.kept.setdefault(event["id"], event)


@pytest.fixture()
def central(db, monkeypatch) -> Central:
    events.relay_once(db)                        # anything from before the test is already out
    stand_in = Central()
    monkeypatch.setattr(events, "sinks", [stand_in])
    return stand_in


def relay_until_empty(db) -> None:
    while events.relay_once(db):
        pass


def test_the_store_keeps_working_offline_and_central_gets_every_event_in_order_afterwards(client, db, sku, central):
    place_paid_order(client, "edge-1", 1, [(sku("Toned milk"), 2)])
    place_paid_order(client, "edge-2", 1, [(sku("Basmati rice"), 1)])
    claimed = client.get("/v1/pickers/picker1/next-task", params={"store_id": 1})
    assert claimed.status_code == 200 and claimed.json()["job"] is not None

    for _ in range(3):                           # the relay keeps trying while the link is down
        assert events.relay_once(db) == 0
    queued = db.scalars(select(EventLog.id).where(EventLog.published_at.is_(None)).order_by(EventLog.id)).all()
    assert len(queued) >= 3 and central.deliveries == []

    central.up = True
    relay_until_empty(db)

    assert central.deliveries == queued          # every one, oldest first, once


def test_a_crash_after_sending_resends_the_batch_so_central_must_drop_duplicates(client, db, sku, central,
                                                                                monkeypatch):
    place_paid_order(client, "edge-3", 1, [(sku("Toned milk"), 1)])
    central.up = True

    def power_cut():
        raise RuntimeError("power cut before the outbox was marked")
    commit = db.commit
    monkeypatch.setattr(db, "commit", power_cut)
    with pytest.raises(RuntimeError):
        events.relay_once(db)
    monkeypatch.setattr(db, "commit", commit)
    db.rollback()                                # what the restarted edge sees: nothing marked as sent
    sent_before_the_crash = list(central.deliveries)

    relay_until_empty(db)

    assert sent_before_the_crash and central.deliveries == sent_before_the_crash * 2   # all sent twice...
    assert list(central.kept) == sent_before_the_crash                                 # ...kept once, in order
