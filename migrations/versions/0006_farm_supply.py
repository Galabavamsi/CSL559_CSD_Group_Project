"""farm supply: produce items and their units, hub capacity, farms, listings and quality checks

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-23 22:00:00
"""
import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

POINT = "ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography"


def upgrade() -> None:
    op.create_table(
        'produce_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('family', sa.String(length=20), nullable=False),
        sa.Column('storage_type', sa.String(length=10), nullable=False),
        sa.Column('shelf_life_days', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.add_column('skus', sa.Column('item_id', sa.Integer(), nullable=True))
    op.add_column('skus', sa.Column('unit_grams', sa.Integer(), nullable=True))
    op.add_column('skus', sa.Column('unit_label', sa.String(length=40), nullable=True))
    op.create_foreign_key('skus_item_id_fkey', 'skus', 'produce_items', ['item_id'], ['id'])
    op.create_index(op.f('ix_skus_item_id'), 'skus', ['item_id'], unique=False)
    op.add_column('stores', sa.Column('capacity_kg', sa.Integer(), server_default='5000', nullable=False))
    op.create_table(
        'farms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('farmer_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('area_acres', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('location', Geography('POINT', srid=4326, spatial_index=False), sa.Computed(POINT, persisted=True),
                  nullable=True),
        sa.ForeignKeyConstraint(['farmer_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_farms_farmer_id'), 'farms', ['farmer_id'], unique=False)
    op.create_index('ix_farms_location', 'farms', ['location'], unique=False, postgresql_using='gist')
    op.create_table(
        'listings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('farm_id', sa.Integer(), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('qty_g', sa.Integer(), nullable=False),
        sa.Column('price_per_kg', sa.Float(), nullable=False),
        sa.Column('harvest_date', sa.Date(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('drop_from', sa.DateTime(), nullable=False),
        sa.Column('drop_until', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id']),
        sa.ForeignKeyConstraint(['item_id'], ['produce_items.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_listings_farm_id'), 'listings', ['farm_id'], unique=False)
    op.create_index(op.f('ix_listings_store_id'), 'listings', ['store_id'], unique=False)
    op.create_index(op.f('ix_listings_status'), 'listings', ['status'], unique=False)
    op.create_table(
        'quality_checks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('listing_id', sa.Integer(), nullable=False),
        sa.Column('store_id', sa.Integer(), nullable=False),
        sa.Column('batch_no', sa.String(length=30), nullable=False),
        sa.Column('grade', sa.String(length=6), nullable=False),
        sa.Column('received_g', sa.Integer(), nullable=False),
        sa.Column('accepted_g', sa.Integer(), nullable=False),
        sa.Column('rejected_g', sa.Integer(), nullable=False),
        sa.Column('trim_g', sa.Integer(), nullable=False),
        sa.Column('remarks', sa.String(length=200), nullable=True),
        sa.Column('checked_by', sa.String(length=40), nullable=False),
        sa.Column('checked_at', sa.DateTime(), nullable=False),
        sa.Column('receipt_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['listing_id'], ['listings.id']),
        sa.ForeignKeyConstraint(['receipt_id'], ['goods_receipts.id']),
        sa.ForeignKeyConstraint(['store_id'], ['stores.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_no'),
        sa.UniqueConstraint('listing_id'),
    )
    op.create_index(op.f('ix_quality_checks_store_id'), 'quality_checks', ['store_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_quality_checks_store_id'), table_name='quality_checks')
    op.drop_table('quality_checks')
    op.drop_index(op.f('ix_listings_status'), table_name='listings')
    op.drop_index(op.f('ix_listings_store_id'), table_name='listings')
    op.drop_index(op.f('ix_listings_farm_id'), table_name='listings')
    op.drop_table('listings')
    op.drop_index('ix_farms_location', table_name='farms', postgresql_using='gist')
    op.drop_index(op.f('ix_farms_farmer_id'), table_name='farms')
    op.drop_table('farms')
    op.drop_column('stores', 'capacity_kg')
    op.drop_index(op.f('ix_skus_item_id'), table_name='skus')
    op.drop_constraint('skus_item_id_fkey', 'skus', type_='foreignkey')
    op.drop_column('skus', 'unit_label')
    op.drop_column('skus', 'unit_grams')
    op.drop_column('skus', 'item_id')
    op.drop_table('produce_items')
