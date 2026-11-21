"""Impossible ids on the fulfilment and pick & pack routes (issue from Member 4's repo audit).

An id like 10**20 overflowed the database integer and came back as a 500. These routes now use the shared limits in
app/ids.py: an impossible id is a 422 before any query runs, while an id that could exist but does not is still each
route's 404 (or an empty answer). Text ids in the URL are limited to their column's 40 characters."""
import pytest

from app.ids import MAX_ID

from .conftest import place_paid_order

HUGE = 10**20
LONG = "p" * 41

ROUTES = [  # (method, path with {id}, body)
    ("GET", "/v1/fulfilment-jobs/{id}", None),
    ("POST", "/v1/fulfilment-jobs/{id}/cancel", {"reason": "x"}),
    ("POST", "/v1/fulfilment-jobs/{id}/handover", {"rider_id": "R-11", "scanned_order_id": "x"}),
    ("POST", "/v1/fulfilment-jobs/{id}/packed", {"crate_slot": "S-01"}),
    ("POST", "/v1/fulfilment-jobs/{id}/substitutions", {"dropped_sku_id": 1, "substitute_sku_id": 2, "qty": 1}),
    ("POST", "/v1/pick-tasks/{id}/scans", {"barcode": "x"}),
    ("POST", "/v1/pick-tasks/{id}/short", None),
    ("GET", "/v1/stores/{id}/fulfilment-metrics", None),
    ("GET", "/v1/stores/{id}/attention", None),
    ("GET", "/v1/fulfilment-jobs?store_id={id}", None),
    ("GET", "/v1/pickers/picker1/next-task?store_id={id}", None),
    ("GET", "/v1/pickers/picker1/next-batch?store_id={id}", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES, ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_an_impossible_id_is_a_422_not_a_500(client, method, path, body):
    for impossible in (HUGE, 0, -1):
        res = client.request(method, path.format(id=impossible), json=body)
        assert res.status_code == 422, (impossible, res.text)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES[:7], ids=[f"{m} {p}" for m, p, _ in ROUTES[:7]])
def test_a_possible_but_unknown_job_or_task_is_still_a_404(client, method, path, body):
    assert client.request(method, path.format(id=MAX_ID), json=body).status_code == 404


def test_a_possible_but_unknown_store_has_nothing_to_show(client):
    assert client.get(f"/v1/fulfilment-jobs?store_id={MAX_ID}").json() == []
    assert client.get(f"/v1/pickers/picker1/next-task?store_id={MAX_ID}").json() == {"job": None}
    assert client.get(f"/v1/stores/{MAX_ID}/attention").json() == {"stalled": [], "waiting_for_rider": []}
    assert client.get(f"/v1/stores/{MAX_ID}/fulfilment-metrics").json()["orders_packed"] == 0


def test_ids_inside_a_substitution_body_are_checked_too(client, sku):
    place_paid_order(client, "i-1", 1, [(sku("Basmati rice"), 1)])
    job = client.get("/v1/pickers/picker1/next-task", params={"store_id": 1}).json()["job"]

    for field in ("dropped_sku_id", "substitute_sku_id"):
        body = {"dropped_sku_id": 1, "substitute_sku_id": 2, "qty": 1, field: HUGE}
        assert client.post(f"/v1/fulfilment-jobs/{job['job_id']}/substitutions", json=body).status_code == 422


def test_a_picker_or_rider_id_longer_than_its_column_is_a_422(client):
    assert client.get(f"/v1/pickers/{LONG}/next-task", params={"store_id": 1}).status_code == 422
    assert client.get(f"/v1/pickers/{LONG}/next-batch", params={"store_id": 1}).status_code == 422
    assert client.post(f"/v1/riders/{'r' * 41}/arrive", json={"order_id": "x"}).status_code == 422
    assert client.get(f"/v1/pickers/{'p' * 40}/next-task", params={"store_id": 1}).status_code == 200
