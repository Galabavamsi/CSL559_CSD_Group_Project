from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, current_staff, require_role
from ...db import get_db
from . import service

router = APIRouter(tags=["inbound"])


class ReceiptLineIn(BaseModel):
    sku_id: int
    qty: int = Field(gt=0)
    batch_no: str | None = None
    expiry_date: date | None = None
    bin_id: int | None = None


class GoodsReceiptIn(BaseModel):
    store_id: int
    transfer_order_id: int | None = None
    lines: list[ReceiptLineIn] = Field(min_length=1)
    actor: str = "receiver"


class OpenReceiptIn(BaseModel):
    store_id: int
    transfer_order_id: int | None = None


class ScanIn(BaseModel):
    barcode: str = Field(min_length=1, max_length=20)
    qty: int = Field(gt=0)
    batch_no: str | None = Field(None, max_length=30)
    expiry_date: date | None = None
    damaged: bool = False


class PutawayIn(BaseModel):
    sku_id: int
    batch_no: str = Field(min_length=1, max_length=30)
    bin_code: str = Field(min_length=1, max_length=20)
    qty: int = Field(gt=0)
    actor: str = "receiver"


@router.post("/v1/goods-receipts", status_code=201)
def create_goods_receipt(body: GoodsReceiptIn, db: Session = Depends(get_db),
                         staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, body.store_id)
    return service.receive_goods(db, body.store_id, [line.model_dump() for line in body.lines],
                                 body.transfer_order_id, body.actor)


@router.post("/v1/goods-receipts/open", status_code=201, summary="Start receiving a truck (no stock changes yet)")
def open_receipt(body: OpenReceiptIn, db: Session = Depends(get_db),
                 staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, body.store_id)
    return service.open_receipt(db, body.store_id, body.transfer_order_id)


@router.post("/v1/goods-receipts/{receipt_id}/scans", summary="Scan units off the truck onto the dock")
def scan(receipt_id: int, body: ScanIn, db: Session = Depends(get_db),
         staff: dict = Depends(require_role("receiver", "manager"))):
    """Good units wait on the dock, not yet sellable. Damaged units (`damaged: true`) and a batch with less than half
    its shelf life left are recorded on the receipt and never stocked."""
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return service.scan(db, receipt_id, body.barcode, body.qty, body.batch_no, body.expiry_date, body.damaged)


@router.get("/v1/goods-receipts/{receipt_id}/putaway-tasks", summary="Where to put what waits on the dock")
def putaway_tasks(receipt_id: int, db: Session = Depends(get_db),
                  staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return service.putaway_tasks(db, receipt_id)


@router.post("/v1/goods-receipts/{receipt_id}/putaway", summary="Put units from the dock into a bin: sellable at once")
def put_away(receipt_id: int, body: PutawayIn, db: Session = Depends(get_db),
             staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, service.get_receipt(db, receipt_id).store_id)
    return service.put_away(db, receipt_id, body.sku_id, body.batch_no, body.bin_code, body.qty, body.actor)


@router.get("/v1/goods-receipts/{receipt_id}", summary="A goods receipt and its lines")
def read_receipt(receipt_id: int, db: Session = Depends(get_db), staff: dict = Depends(current_staff)):
    receipt = service.get_receipt(db, receipt_id)
    check_store(staff, receipt.store_id)
    return service.receipt_view(receipt)
