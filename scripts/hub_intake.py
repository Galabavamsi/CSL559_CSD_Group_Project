"""Take in a farm lot at a hub from the command line: weigh it, grade it, and put the packed units away.

A stopgap for demos until the hub has an intake screen. It makes the same calls that screen will:

    GET  /v1/stores/{store}/expected-drops                     the lots on their way to the hub
    POST /v1/listings/{listing}/intake                         weight received, weight rejected, grade
    GET  /v1/goods-receipts/{receipt}/putaway-tasks            which bin each pack goes to
    POST /v1/goods-receipts/{receipt}/putaway                  one call per task: sellable from that moment
    POST /v1/goods-receipts/{receipt}/close

Usage:
    python scripts/hub_intake.py --received 39.5 --rejected 1.5 --grade A
    python scripts/hub_intake.py --url https://staging.example.com --store 1 --listing 12 --received 20 --grade B

With no --listing it takes the lot that has waited longest. The receiver's password is read from STAFF_PASSWORD
(a hosted site refuses the built-in demo password); nothing else is needed, only the standard library.
"""
import argparse
import json
import os
import urllib.error
import urllib.request
import uuid


def call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None) -> dict | list:
    headers = {"Content-Type": "application/json", "Idempotency-Key": uuid.uuid4().hex}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{method} {path} was refused ({error.code}): {error.read().decode(errors='replace')[:400]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Weigh, grade and put away one farm lot at a hub.")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="base URL of the API")
    parser.add_argument("--store", type=int, default=1, help="the hub's id (default: 1)")
    parser.add_argument("--listing", type=int, help="the listing to take in (default: the one that waited longest)")
    parser.add_argument("--received", type=float, required=True, help="kilograms that arrived")
    parser.add_argument("--rejected", type=float, default=0, help="kilograms turned away (default: 0)")
    parser.add_argument("--grade", choices=["A", "B", "C", "reject"], default="A")
    parser.add_argument("--remarks", default=None)
    parser.add_argument("--user", default=None, help="staff username (default: receiver<store>)")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    token = call(base, "POST", "/v1/auth/login", {"username": args.user or f"receiver{args.store}",
                                                  "password": os.getenv("STAFF_PASSWORD", "demo")})["access_token"]
    listing = args.listing
    if listing is None:
        drops = call(base, "GET", f"/v1/stores/{args.store}/expected-drops", token=token)
        if not drops:
            raise SystemExit(f"No lots are on their way to hub {args.store}.")
        listing = drops[0]["listing_id"]

    intake = call(base, "POST", f"/v1/listings/{listing}/intake",
                  {"received_kg": args.received, "rejected_kg": args.rejected, "grade": args.grade,
                   "remarks": args.remarks}, token)
    receipt = (intake.get("receipt") or {}).get("receipt_id")
    check = intake["quality_check"]
    packed = ", ".join(f"{line['units']} x {line['sku']}" for line in intake.get("packed", []))
    print(f"Listing {listing}, {intake['item']} from {intake['farm']}: grade {check['grade']}, "
          f"{check['received_kg']:g} kg received, {check['rejected_kg']:g} kg rejected, {check['accepted_kg']:g} kg "
          f"accepted, {check['trim_kg']:g} kg trim. Packed as batch {check['batch_no']}: {packed or 'nothing'}.")
    if not receipt:
        return
    for task in call(base, "GET", f"/v1/goods-receipts/{receipt}/putaway-tasks", token=token):
        call(base, "POST", f"/v1/goods-receipts/{receipt}/putaway",
             {"sku_id": task["sku_id"], "batch_no": task["batch_no"], "bin_code": task["bin_code"], "qty": task["qty"]},
             token)
        print(f"  {task['qty']} units of batch {task['batch_no']} into bin {task['bin_code']}: on sale")
    call(base, "POST", f"/v1/goods-receipts/{receipt}/close", token=token)
    print(f"Goods receipt {receipt} closed.")


if __name__ == "__main__":
    main()
