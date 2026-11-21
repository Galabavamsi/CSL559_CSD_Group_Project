from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from ...idempotency import run_once
from ...ids import Id, PathId
from ..inventory.router import MAX_BIN_UNITS      # Inventory's cap on one quantity (PR 50): 10**20 was a 500 here
from . import service

router = APIRouter(tags=["inbound"])

# Every receiving write takes one (task 3.5 with Member 1's task 1.4): a retried scan or putaway does not count twice.
IdempotencyKey = Annotated[str | None, Header(
    min_length=1, max_length=80,
    description="Any unique string. A retry with the same key is not done again; it returns the first answer.")]


class ReceiptLineIn(BaseModel):
    sku_id: Id
    qty: int = Field(gt=0, le=MAX_BIN_UNITS)
    batch_no: str | None = Field(None, max_length=30)
    expiry_date: date | None = None
    bin_id: Id | None = None


class GoodsReceiptIn(BaseModel):
    store_id: Id
    transfer_order_id: Id | None = None
    lines: list[ReceiptLineIn] = Field(min_length=1)


class OpenReceiptIn(BaseModel):
    store_id: Id
    transfer_order_id: Id | None = None


class ScanIn(BaseModel):
    barcode: str = Field(min_length=1, max_length=20)
    qty: int = Field(gt=0, le=MAX_BIN_UNITS)
    batch_no: str = Field(min_length=1, max_length=30)          # both printed on the case: the shelf-life check
    expiry_date: date                                           # and first-expiry-first-out picking rely on them
    damaged: bool = False


class PutawayIn(BaseModel):
    sku_id: Id
    batch_no: str = Field(min_length=1, max_length=30)
    bin_code: str = Field(min_length=1, max_length=20)
    qty: int = Field(gt=0, le=MAX_BIN_UNITS)


@router.post("/v1/goods-receipts", status_code=201, summary="Receive a whole truck in one call")
def create_goods_receipt(body: GoodsReceiptIn, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db),
                         staff: dict = Depends(require_role("receiver", "manager"))):
    """Runs the five receiving steps in order and saves the receipt. A batch with less than half its shelf life left
    is listed under `rejected`."""
    check_store(staff, body.store_id)
    return run_once(db, "goods-receipt", idempotency_key, {**body.model_dump(), "by": staff["sub"]},
                    lambda: service.receive_goods(db, body.store_id, [line.model_dump() for line in body.lines],
                                                  body.transfer_order_id, actor=staff["sub"], commit=False))


@router.post("/v1/goods-receipts/open", status_code=201, summary="Start receiving a truck (no stock changes yet)")
def open_receipt(body: OpenReceiptIn, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db),
                 staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, body.store_id)
    return run_once(db, "goods-receipt-open", idempotency_key, {**body.model_dump(), "by": staff["sub"]},
                    lambda: service.open_receipt(db, body.store_id, body.transfer_order_id, commit=False))


@router.post("/v1/goods-receipts/{receipt_id}/scans", summary="Scan units off the truck onto the dock")
def scan(receipt_id: PathId, body: ScanIn, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db),
         staff: dict = Depends(require_role("receiver", "manager"))):
    """Good units wait on the dock, not yet sellable. Damaged units (`damaged: true`) and a batch with less than half
    its shelf life left are recorded on the receipt and never stocked."""
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return run_once(db, "goods-receipt-scan", idempotency_key,
                    {"receipt_id": receipt_id, "by": staff["sub"], **body.model_dump()},
                    lambda: service.scan(db, receipt_id, body.barcode, body.qty, body.batch_no, body.expiry_date,
                                         body.damaged, commit=False))


@router.get("/v1/goods-receipts/{receipt_id}/putaway-tasks", summary="Where to put what waits on the dock")
def putaway_tasks(receipt_id: PathId, db: Session = Depends(get_db),
                  staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return service.putaway_tasks(db, receipt_id)


@router.post("/v1/goods-receipts/{receipt_id}/putaway", summary="Put units from the dock into a bin: sellable at once")
def put_away(receipt_id: PathId, body: PutawayIn, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db),
             staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return run_once(db, "goods-receipt-putaway", idempotency_key,
                    {"receipt_id": receipt_id, "by": staff["sub"], **body.model_dump()},
                    lambda: service.put_away(db, receipt_id, body.sku_id, body.batch_no, body.bin_code, body.qty,
                                             actor=staff["sub"], commit=False))


@router.post("/v1/goods-receipts/{receipt_id}/close", summary="Finish a receipt: order received, shortfalls reported")
def close_receipt(receipt_id: PathId, idempotency_key: IdempotencyKey = None,
                  send_back: bool = Query(False, description="Return what is still on the dock to the hub "
                                                             "(a miscount, or no room) instead of refusing to close"),
                  db: Session = Depends(get_db), staff: dict = Depends(require_role("receiver", "manager"))):
    """Refused while good units wait on the dock, unless `send_back`, and for a receipt with nothing scanned on it
    (`409 nothing_scanned`: cancel it instead). Reports ordered versus received (with damaged, rejected and sent-back
    units) for every SKU ordered or scanned, marks the transfer order received and publishes goods.received."""
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return run_once(db, "goods-receipt-close", idempotency_key,
                    {"receipt_id": receipt_id, "send_back": send_back, "by": staff["sub"]},
                    lambda: service.close_receipt(db, receipt_id, send_back, commit=False))


@router.post("/v1/goods-receipts/{receipt_id}/cancel", summary="Drop a receipt opened by mistake, before any scan")
def cancel_receipt(receipt_id: PathId, idempotency_key: IdempotencyKey = None, db: Session = Depends(get_db),
                   staff: dict = Depends(require_role("receiver", "manager"))):
    """Only while nothing is scanned on it (`409 receipt_not_empty`). The transfer order is left as it was, so the
    real truck can still be received."""
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return run_once(db, "goods-receipt-cancel", idempotency_key, {"receipt_id": receipt_id, "by": staff["sub"]},
                    lambda: service.cancel_receipt(db, receipt_id, commit=False))


@router.get("/v1/goods-receipts/{receipt_id}", summary="A goods receipt and its lines")
def read_receipt(receipt_id: PathId, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    receipt = service.get_receipt(db, receipt_id)
    check_store(staff, receipt.store_id)
    return service.receipt_view(receipt)
