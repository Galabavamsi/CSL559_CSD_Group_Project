"""index stock_items.bin_id

Slotting sums the units in one bin on every putaway and for every planned move (slotting.room_in), and emptied
batches stay in the table as rows with qty 0, so without an index that read scans a table that only grows (issue #84).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-22 18:10:00
"""
from alembic import op


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('stock_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stock_items_bin_id'), ['bin_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('stock_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stock_items_bin_id'))
