"""delivery: agents on duty, trips, and the stops on them

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24 04:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'agent_profiles',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=True),
        sa.Column('on_duty', sa.Boolean(), nullable=False),
        sa.Column('free_since', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('user_id'),
    )
    op.create_index(op.f('ix_agent_profiles_store_id'), 'agent_profiles', ['store_id'], unique=False)
    op.create_table(
        'trips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('km', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('left_at', sa.DateTime(), nullable=True),
        sa.Column('done_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['users.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_trips_agent_id'), 'trips', ['agent_id'], unique=False)
    op.create_index(op.f('ix_trips_status'), 'trips', ['status'], unique=False)
    op.create_index(op.f('ix_trips_store_id'), 'trips', ['store_id'], unique=False)
    op.create_table(
        'trip_stops',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('order_id', sa.Integer(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('loaded_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('failed_reason', sa.String(length=20), nullable=True),
        sa.Column('code_tries', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id'),
    )
    op.create_index(op.f('ix_trip_stops_trip_id'), 'trip_stops', ['trip_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_trip_stops_trip_id'), table_name='trip_stops')
    op.drop_table('trip_stops')
    op.drop_index(op.f('ix_trips_store_id'), table_name='trips')
    op.drop_index(op.f('ix_trips_status'), table_name='trips')
    op.drop_index(op.f('ix_trips_agent_id'), table_name='trips')
    op.drop_table('trips')
    op.drop_index(op.f('ix_agent_profiles_store_id'), table_name='agent_profiles')
    op.drop_table('agent_profiles')
