"""The checkout race script (task 1.8), run small and in-process: more buyers than units, never one hold too many."""
from fastapi.testclient import TestClient

from app.main import app
from scripts import load_checkout

from .conftest import assert_stock_is_consistent


def test_forty_buyers_and_ten_units_give_exactly_ten_holds_and_a_clean_audit(client):
    sku_id = load_checkout.prepare(client, store_id=1, units=10)

    results = load_checkout.race(lambda: TestClient(app), buyers=40, store_id=1, sku_id=sku_id)
    summary = load_checkout.check(client, results, units=10, store_id=1, sku_id=sku_id)

    assert summary["problems"] == []
    assert (summary["held"], summary["refused"], summary["other"]) == (10, 30, {})
    assert (summary["on_hand_after"], summary["reserved_after"], summary["atp_after"]) == (10, 10, 0)
    assert summary["p99_ms"] >= summary["p50_ms"] > 0
    assert_stock_is_consistent()


def test_prepare_can_lower_stock_and_clears_a_safety_buffer(client, sku):
    milk = sku("Toned milk")                         # 30 on hand in two batches, safety buffer 2

    load_checkout.prepare(client, store_id=1, units=5, sku_id=milk)

    row = client.get("/v1/stores/1/availability", params={"skus": str(milk)}).json()[0]
    assert (row["on_hand"], row["reserved"], row["safety_buffer"], row["atp"]) == (5, 0, 0, 5)
    assert_stock_is_consistent()


def test_a_run_that_oversells_or_breaks_the_records_is_reported_as_failed(client):
    sku_id = load_checkout.prepare(client, store_id=1, units=3)
    results = load_checkout.race(lambda: TestClient(app), buyers=5, store_id=1, sku_id=sku_id)

    summary = load_checkout.check(client, results, units=2, store_id=1, sku_id=sku_id)   # as if only 2 had existed

    assert any("OVERSOLD" in problem for problem in summary["problems"])


def test_a_url_on_another_machine_is_refused_without_allow_remote(capsys):
    assert load_checkout.main(["--url", "http://10.0.0.5:8000"]) == 2
    assert "wipes" in capsys.readouterr().err
