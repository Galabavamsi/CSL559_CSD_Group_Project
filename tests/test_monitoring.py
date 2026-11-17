"""Monitoring (task 4.7, HLD 12): Prometheus metrics, request ids and JSON logs."""
import json
import logging

from prometheus_client import REGISTRY

from app import monitoring

from .conftest import place_paid_order

AVAILABILITY = "/v1/stores/{store_id}/availability"


def sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0


class KeepLines(logging.Handler):
    """Collects the app's log lines, formatted as they would be written."""

    def __init__(self):
        super().__init__()
        self.lines: list[dict] = []
        self.setFormatter(monitoring.JsonFormatter())

    def emit(self, record):
        self.lines.append(json.loads(self.format(record)))


def test_metrics_time_requests_by_route_template_not_by_raw_path(client):
    before = sample("http_request_duration_seconds_count", method="GET", route=AVAILABILITY, status="200")
    for store_id in (1, 2):
        client.get(f"/v1/stores/{store_id}/availability")

    text = client.get("/metrics").text

    assert sample("http_request_duration_seconds_count", method="GET", route=AVAILABILITY, status="200") == before + 2
    assert 'route="/v1/stores/{store_id}/availability"' in text
    assert "/v1/stores/1/availability" not in text                 # one series per route, not one per store


def test_response_carries_the_request_id_it_was_sent(client):
    assert client.get("/health", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"


def test_a_missing_or_unsafe_request_id_is_replaced_with_a_new_one(client):
    made = client.get("/health").headers["X-Request-ID"]
    unsafe = client.get("/health", headers={"X-Request-ID": "x" * 65}).headers["X-Request-ID"]

    assert len(made) == 32 and len(unsafe) == 32 and made != unsafe


def test_log_lines_are_json_and_carry_the_request_id(client):
    keep = KeepLines()
    logging.getLogger("app").addHandler(keep)
    try:
        client.get("/v1/stores", headers={"X-Request-ID": "trace-me"})
    finally:
        logging.getLogger("app").removeHandler(keep)

    mine = [line for line in keep.lines if line["request_id"] == "trace-me"]
    assert mine and mine[-1]["route"] == "/v1/stores" and mine[-1]["status"] == 200 and "ms" in mine[-1]


def test_counters_for_reservations_events_and_scans(client, sku):
    held, short = sample("reservations_total", result="held"), sample("reservations_total", result="insufficient_stock")
    paid = sample("events_published_total", type="order.paid")
    match, mismatch = sample("scans_total", result="match"), sample("scans_total", result="mismatch")

    place_paid_order(client, "metrics-1", 1, [(sku("Tea"), 1)])
    client.post("/v1/reservations", json={"order_id": "metrics-2", "store_id": 1,
                                          "lines": [{"sku_id": sku("Tea"), "qty": 10_000}]})
    task = client.get("/v1/pickers/p1/next-task", params={"store_id": 1}).json()["job"]["tasks"][0]
    client.post(f"/v1/pick-tasks/{task['task_id']}/scans", json={"barcode": "0000000000000", "qty": task["qty"]})
    client.post(f"/v1/pick-tasks/{task['task_id']}/scans", json={"barcode": task["barcode"], "qty": task["qty"]})

    assert sample("reservations_total", result="held") == held + 1
    assert sample("reservations_total", result="insufficient_stock") == short + 1
    assert sample("events_published_total", type="order.paid") == paid + 1
    assert sample("scans_total", result="mismatch") == mismatch + 1
    assert sample("scans_total", result="match") == match + 1


def test_gauges_show_holds_in_progress_and_relay_lag(client, sku):
    client.post("/v1/reservations", json={"order_id": "gauge-1", "store_id": 1,
                                          "lines": [{"sku_id": sku("Tea"), "qty": 1}]})

    client.get("/metrics")

    assert sample("holds_in_progress") >= 1
    assert REGISTRY.get_sample_value("outbox_lag_seconds") is not None


def test_time_since_each_stores_last_event_is_exposed_for_the_store_offline_alert(client, sku):
    place_paid_order(client, "silence-1", 1, [(sku("Tea"), 1)])

    client.get("/metrics")

    assert 0 <= REGISTRY.get_sample_value("store_seconds_since_last_event", {"store_id": "1"}) < 60
