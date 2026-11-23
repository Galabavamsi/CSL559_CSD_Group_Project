"""service requests: a customer asking for delivery where no hub serves yet

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-24 03:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'service_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('h3_cell', sa.String(length=16), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('ts', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'h3_cell'),
    )
    op.create_index(op.f('ix_service_requests_h3_cell'), 'service_requests', ['h3_cell'], unique=False)
    op.create_index(op.f('ix_service_requests_ts'), 'service_requests', ['ts'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_service_requests_ts'), table_name='service_requests')
    op.drop_index(op.f('ix_service_requests_h3_cell'), table_name='service_requests')
    op.drop_table('service_requests')
