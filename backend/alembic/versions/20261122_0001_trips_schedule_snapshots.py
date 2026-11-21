"""trips·blocks·legs·schedule_snapshots 생성(SDD 5.2 일정 도메인, FR-006).

SDD 와 다른 점은 app/db/models.py 의 모듈 설명에 적었다. 병합 순서는 마이그레이션 담당이 정한다.

Revision ID: 0001
Revises: 
Create Date: 2026-11-22 04:17:48.149396

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('trips',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('session_key', sa.String(length=64), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('day_start', sa.Time(), nullable=False),
    sa.Column('day_end', sa.Time(), nullable=False),
    sa.Column('transport_mode', sa.String(length=10), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trips'))
    )
    op.create_table('blocks',
    sa.Column('trip_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('position', sa.SmallInteger(), nullable=False),
    sa.Column('day_no', sa.SmallInteger(), nullable=False),
    sa.Column('seq', sa.SmallInteger(), nullable=False),
    sa.Column('place_kind', sa.String(length=10), nullable=False),
    sa.Column('place_id', sa.String(length=64), nullable=True),
    sa.Column('kakao_place_id', sa.String(length=32), nullable=True),
    sa.Column('kakao_place_url', sa.String(length=255), nullable=True),
    sa.Column('is_fixed', sa.Boolean(), nullable=False),
    sa.Column('fixed_start', sa.Time(), nullable=True),
    sa.Column('fixed_end', sa.Time(), nullable=True),
    sa.Column('stay_min', sa.SmallInteger(), nullable=False),
    sa.Column('arrive_at', sa.Time(), nullable=True),
    sa.Column('depart_at', sa.Time(), nullable=True),
    sa.Column('origin', sa.String(length=10), nullable=False),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name=op.f('fk_blocks_trip_id_trips'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('trip_id', 'id', name=op.f('pk_blocks'))
    )
    op.create_table('schedule_snapshots',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('trip_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('reason', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name=op.f('fk_schedule_snapshots_trip_id_trips'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_schedule_snapshots')),
    sa.UniqueConstraint('trip_id', 'version', name=op.f('uq_schedule_snapshots_trip_id_version'))
    )
    op.create_table('legs',
    sa.Column('trip_id', sa.Uuid(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('position', sa.SmallInteger(), nullable=False),
    sa.Column('from_block_id', sa.String(length=64), nullable=False),
    sa.Column('to_block_id', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=10), nullable=False),
    sa.Column('duration_min', sa.SmallInteger(), nullable=True),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('time_semantics', sa.String(length=30), nullable=False),
    sa.Column('lookup_failed', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['trip_id', 'from_block_id'], ['blocks.trip_id', 'blocks.id'], name=op.f('fk_legs_trip_id_from_block_id_blocks'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['trip_id', 'to_block_id'], ['blocks.trip_id', 'blocks.id'], name=op.f('fk_legs_trip_id_to_block_id_blocks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('trip_id', 'id', name=op.f('pk_legs'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('legs')
    op.drop_table('schedule_snapshots')
    op.drop_table('blocks')
    op.drop_table('trips')
