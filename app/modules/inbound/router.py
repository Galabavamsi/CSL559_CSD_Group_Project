from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import check_store, require_role
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


@router.post("/v1/goods-receipts", status_code=201)
def create_goods_receipt(body: GoodsReceiptIn, db: Session = Depends(get_db),
                         staff: dict = Depends(require_role("receiver", "manager"))):
    check_store(staff, body.store_id)
    return service.receive_goods(db, body.store_id, [line.model_dump() for line in body.lines],
                                 body.transfer_order_id, body.actor)
