"""Ops dashboard (task 4.6, FR-13): city overview, what needs action, and every HLD 12 KPI beside its target."""
import importlib
import sys
import types
from datetime import timedelta

from sqlalchemy import select

from app import config
from app.models import FulfilmentJob, StockLevel, utcnow
from app.modules.fulfilment import service as fulfilment
from app.modules.replenishment import service as replenishment

from .conftest import place_paid_order
from .test_fulfilment_metrics import pick_and_pack

HLD_12_KPIS = {"seconds_to_pack_p90", "fill_rate", "items_per_picker_hour", "inventory_accuracy", "stock_out_rate",
               "days_of_cover", "wastage_rate", "replenishment_on_time", "forecast_wape", "outbox_lag_seconds"}
# Not an HLD 12 KPI: Member 2's task 2.7 measures it, judged against the rider-wait alert.
OPS_KPIS = HLD_12_KPIS | {"seconds_packed_to_handover_p90"}


def kpis(client, store_id=1) -> dict:
    res = client.get(f"/v1/stores/{store_id}/kpis")
    assert res.status_code == 200, res.text
    return {kpi["key"]: kpi for kpi in res.json()["kpis"]}


def test_overview_has_a_row_per_store_for_city_wide_staff(client, client_as, sku):
    place_paid_order(client, "ov-1", 1, [(sku("Tea"), 1)])

    rows = client_as("ops").get("/v1/dashboard/overview").json()

    assert [row["store_id"] for row in rows] == [1, 2]
    assert rows[0]["waiting_orders"] == 1 and rows[1]["waiting_orders"] == 0
    assert {"store", "status", "waiting_for_rider", "low_stock", "out_of_stock"} <= rows[0].keys()
    assert client_as("manager", 1).get("/v1/dashboard/overview").status_code == 403


def test_every_kpi_is_listed_with_its_hld_target(client):
    board = kpis(client)

    assert set(board) == OPS_KPIS
    assert all(kpi["target"] and kpi["name"] for kpi in board.values())
    assert board["stock_out_rate"]["available"] is True                  # Member 3's KPIs are merged
    assert board["outbox_lag_seconds"]["available"] is True and board["outbox_lag_seconds"]["target"] == "≤ 30 s"


def test_teammates_numbers_are_judged_against_the_targets(client, monkeypatch):
    def metrics(db, store_id):
        return {"seconds_to_pack_p90": 100, "fill_rate": 0.98, "items_per_picker_hour": 120,
                "seconds_packed_to_handover_p90": config.RIDER_WAIT_MINUTES * 60 + 1}

    def inventory_accuracy(db, store_id):
        return {"value": 0.999}

    monkeypatch.setattr(fulfilment, "metrics", metrics, raising=False)
    monkeypatch.setitem(sys.modules, "app.modules.inventory.counts",
                        types.SimpleNamespace(inventory_accuracy=inventory_accuracy))

    board = kpis(client)

    assert (board["seconds_to_pack_p90"]["value"], board["seconds_to_pack_p90"]["met"]) == (100, True)
    assert board["fill_rate"]["met"] is False and board["items_per_picker_hour"]["met"] is True
    assert board["inventory_accuracy"]["met"] is True
    assert board["seconds_packed_to_handover_p90"]["met"] is False             # a second past the rider-wait alert


def test_a_bag_handed_to_its_rider_shows_the_packed_to_rider_time(client, sku):
    place_paid_order(client, "r-1", 1, [(sku("Tea"), 1)])
    packed = pick_and_pack(client)
    rider = packed["rider"]["rider_id"]
    assert client.post(f"/v1/riders/{rider}/arrive", json={"order_id": "r-1"}).status_code == 200
    handed = client.post(f"/v1/fulfilment-jobs/{packed['job_id']}/handover",
                         json={"rider_id": rider, "scanned_order_id": "r-1"})
    assert handed.status_code == 200, handed.text

    kpi = kpis(client)["seconds_packed_to_handover_p90"]

    assert (kpi["available"], kpi["met"]) == (True, True) and kpi["value"] >= 0
    assert kpi["unit"] == "seconds" and kpi["target"] == "≤ 300 s"


def test_a_missing_teammate_function_shows_not_available_and_the_rest_still_loads(client, monkeypatch):
    monkeypatch.delattr(replenishment, "kpis")

    board = kpis(client)

    assert board["stock_out_rate"]["available"] is False and board["stock_out_rate"]["note"] == "not built yet"
    assert board["outbox_lag_seconds"]["available"] is True


def test_a_failing_teammate_function_shows_not_available(client, monkeypatch):
    def broken(db, store_id):
        raise RuntimeError("a bug in a teammate's code")

    monkeypatch.setattr(replenishment, "kpis", broken)

    board = kpis(client)

    assert board["wastage_rate"]["available"] is False and "failed" in board["wastage_rate"]["note"]
    assert board["outbox_lag_seconds"]["available"] is True


def test_a_teammate_module_that_breaks_on_import_shows_failed_not_missing(client, monkeypatch):
    def broken_import(name, *args, **kwargs):
        if name == "app.modules.inventory.counts":
            raise ModuleNotFoundError("No module named 'scipy'", name="scipy")   # its own dependency is missing
        return real_import(name, *args, **kwargs)

    real_import = importlib.import_module
    monkeypatch.setattr(importlib, "import_module", broken_import)

    assert "failed" in kpis(client)["inventory_accuracy"]["note"]


def test_needs_action_lists_bags_waiting_too_long_for_a_rider_and_stock_outs(client, db, sku):
    waits = {"bag-0": 9, "bag-1": 4, "bag-2": 6}
    for order_id in waits:                                   # every API write first: SQLite has one writer
        place_paid_order(client, order_id, 1, [(sku("Tea"), 1)])
    for order_id, minutes in waits.items():
        job = db.scalar(select(FulfilmentJob).where(FulfilmentJob.order_id == order_id))
        job.state, job.packed_at = "packed", utcnow() - timedelta(minutes=minutes, seconds=10)
    milk = db.scalar(select(StockLevel).where(StockLevel.store_id == 1, StockLevel.sku_id == sku("Toned milk")))
    milk.qty_reserved = milk.qty_on_hand                                   # nothing left to sell
    db.commit()

    action = client.get("/v1/stores/1/kpis").json()["needs_action"]

    # Fulfilment's list (task 2.5): only bags packed more than RIDER_WAIT_MINUTES (5) ago, longest wait first.
    assert action["waiting_for_rider"] == [{"order_id": "bag-0", "minutes_waiting": 9},
                                           {"order_id": "bag-2", "minutes_waiting": 6}]
    assert "Toned milk 500 ml" in action["out_of_stock"]


def test_needs_action_shows_fulfilments_stalled_orders(client, monkeypatch):
    monkeypatch.setattr(fulfilment, "attention",
                        lambda db, store_id: {"stalled": [{"order_id": "late-1"}], "waiting_for_rider": []})

    action = client.get("/v1/stores/1/kpis").json()["needs_action"]

    assert (action["stalled_orders"], action["waiting_for_rider"]) == (["late-1"], [])


def test_stalled_orders_and_late_bags_are_not_available_without_fulfilments_list(client, monkeypatch):
    monkeypatch.delattr(fulfilment, "attention", raising=False)

    action = client.get("/v1/stores/1/kpis").json()["needs_action"]

    assert (action["stalled_orders"], action["waiting_for_rider"]) == (None, None)
    assert action["stalled_note"] == "not built yet"


def test_orders_per_hour_counts_paid_orders_over_the_last_12_hours(client, sku):
    def total():
        chart = client.get("/v1/stores/1/kpis").json()["orders_per_hour"]
        assert len(chart) == 12
        return sum(hour["orders"] for hour in chart)

    before = total()
    for n in range(2):
        place_paid_order(client, f"hour-{n}", 1, [(sku("Tea"), 1)])

    assert total() == before + 2


def test_kpis_are_per_store_except_for_ops(client_as):
    assert client_as("picker", 1).get("/v1/stores/2/kpis").status_code == 403
    assert client_as("manager", 1).get("/v1/stores/1/kpis").status_code == 200
    assert client_as("ops").get("/v1/stores/2/kpis").status_code == 200
