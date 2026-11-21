"""The two fulfilment experiments run from the command line, as the README tells people to (tasks 2.6 and 2.8).

Their functions are tested in test_batch_picking.py and test_simulate_orders.py; these runs cover the rest: argument
parsing, the throwaway database each one sets up before importing the app, the printed report and the exit code."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, f"scripts/{script}", *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=120, env={**os.environ, **(env or {})})


def test_compare_picking_prints_the_walking_saved():
    done = run("compare_picking.py", "--orders", "8", "--seed", "1")

    assert done.returncode == 0, done.stderr
    assert "8 paid orders in store 1" in done.stdout
    assert "One order per walk" in done.stdout and "Batches of up to 3" in done.stdout
    assert "Batching saves" in done.stdout


def test_simulate_orders_prints_the_kpis_and_a_clean_audit():
    done = run("simulate_orders.py", "--orders", "6", "--pickers", "2", "--step", "0", "--seed", "1")

    assert done.returncode == 0, done.stderr
    assert "6 paid orders, 2 picker(s)" in done.stdout
    assert "Stock audit: clean" in done.stdout
    assert "n/a (compressed time)" in done.stdout                    # time-based targets are never "met"


def test_the_scripts_leave_the_real_database_alone(tmp_path):
    """Each script points DARKSTORE_DB at its own temporary file before the app is imported."""
    before = sorted(p.name for p in ROOT.glob("darkstore.db*"))
    stamps = {p.name: p.stat().st_mtime for p in ROOT.glob("darkstore.db*")}

    assert run("compare_picking.py", "--orders", "4").returncode == 0

    assert sorted(p.name for p in ROOT.glob("darkstore.db*")) == before
    assert {p.name: p.stat().st_mtime for p in ROOT.glob("darkstore.db*")} == stamps


def test_both_scripts_run_on_a_windows_console():
    """A Windows console encodes output as cp1252, which has no "≤": printing one crashed simulate_orders.py there
    (found in the review of #49). Both scripts now print plain ASCII."""
    windows = {"PYTHONIOENCODING": "cp1252"}

    runs = (("simulate_orders.py", ("--orders", "3", "--step", "0")), ("compare_picking.py", ("--orders", "4")))
    for script, args in runs:
        done = run(script, *args, env=windows)
        assert done.returncode == 0, done.stderr
    assert "<= 120 s" in run("simulate_orders.py", "--orders", "3", "--step", "0", env=windows).stdout
