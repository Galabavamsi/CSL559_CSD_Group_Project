"""The load-test script (task 4.8): its percentile method, and a one-second run against the app in-process."""
from fastapi.testclient import TestClient

from app.main import app
from scripts.load_test import percentile, run, summarise


def test_percentile_takes_the_value_at_index_q_times_n_minus_one():
    assert percentile([5, 1, 4, 2, 3], 0.5) == 3
    assert percentile(list(range(1, 101)), 0.99) == 99


def test_a_short_run_times_every_kind_of_call_without_server_errors(fresh_data):
    results = run(lambda: TestClient(app), seconds=1, workers=2)

    rows = {row["endpoint"]: row for row in summarise(results, seconds=1)}

    assert {"availability", "serviceability", "hold"} <= rows.keys()
    assert all(row["errors"] == 0 and row["limited"] == 0 and row["p99_ms"] >= row["p50_ms"] > 0
               for row in rows.values())
