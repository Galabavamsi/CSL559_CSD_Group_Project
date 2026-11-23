"""cities, and PostGIS locations for cities and stores

The database becomes PostgreSQL with PostGIS only. Every hub belongs to a city (Bhilai and Bangalore to begin with),
and cities and hubs get a `location` point that PostgreSQL keeps from lat and lng, with a GiST index, so "nearest hub"
and "hubs within their radius of this point" are index lookups (HLD 8).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-23 12:00:00
"""
import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

POINT = "ST_SetSRID(ST_MakePoint(lng, lat), 4326)::geography"


def _location() -> sa.Column:
    return sa.Column('location', Geography('POINT', srid=4326, spatial_index=False), sa.Computed(POINT, persisted=True),
                     nullable=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        'cities',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('tier', sa.Integer(), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('radius_km', sa.Float(), nullable=False),
        sa.Column('hub_radius_km', sa.Float(), nullable=False),
        _location(),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_cities_location', 'cities', ['location'], unique=False, postgresql_using='gist')
    op.add_column('stores', sa.Column('city_id', sa.Integer(), nullable=True))
    op.create_foreign_key('stores_city_id_fkey', 'stores', 'cities', ['city_id'], ['id'])
    op.create_index(op.f('ix_stores_city_id'), 'stores', ['city_id'], unique=False)
    op.add_column('stores', _location())
    op.create_index('ix_stores_location', 'stores', ['location'], unique=False, postgresql_using='gist')


def downgrade() -> None:
    op.drop_index('ix_stores_location', table_name='stores', postgresql_using='gist')
    op.drop_column('stores', 'location')
    op.drop_index(op.f('ix_stores_city_id'), table_name='stores')
    op.drop_constraint('stores_city_id_fkey', 'stores', type_='foreignkey')
    op.drop_column('stores', 'city_id')
    op.drop_index('ix_cities_location', table_name='cities', postgresql_using='gist')
    op.drop_table('cities')
