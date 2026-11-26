"""places·place_hours·data_sources·ingestion_runs 생성과 data_sources 시드(SDD 5.2, FR-016).

SDD 와 다른 점은 app/db/models.py 의 모듈 설명에 적었다.
data_sources 시드 행(tourapi·data06·data07)은 여기서만 넣는다. 다른 소스가 생기면 새 마이그레이션으로 넣는다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('places',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('lat', sa.Double(), nullable=False),
    sa.Column('lng', sa.Double(), nullable=False),
    sa.Column('category', sa.String(length=50), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=100), nullable=True),
    sa.Column('address', sa.String(length=300), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('closed_days_text', sa.String(length=200), nullable=True),
    sa.Column('default_stay_min', sa.SmallInteger(), nullable=True),
    sa.Column('indoor_outdoor', sa.String(length=10), nullable=True),
    sa.Column('adm_dong_code', sa.String(length=20), nullable=True),
    sa.Column('source_org', sa.String(length=200), nullable=True),
    sa.Column('ref_date', sa.Date(), nullable=True),
    sa.Column('collected_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_places'))
    )
    op.create_table('place_hours',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('place_id', sa.String(length=64), nullable=False),
    sa.Column('day_type', sa.String(length=10), nullable=False),
    sa.Column('open_time', sa.Time(), nullable=True),
    sa.Column('close_time', sa.Time(), nullable=True),
    sa.Column('break_start', sa.Time(), nullable=True),
    sa.Column('break_end', sa.Time(), nullable=True),
    sa.Column('is_closed', sa.Boolean(), nullable=False),
    sa.Column('origin', sa.String(length=10), nullable=False),
    sa.ForeignKeyConstraint(['place_id'], ['places.id'], name=op.f('fk_place_hours_place_id_places'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_place_hours')),
    sa.UniqueConstraint('place_id', 'day_type', name=op.f('uq_place_hours_place_id_day_type'))
    )
    data_sources = op.create_table('data_sources',
    sa.Column('id', sa.String(length=30), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('refresh_cycle', sa.String(length=20), nullable=False),
    sa.Column('daily_call_limit', sa.Integer(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_sources'))
    )
    op.create_table('ingestion_runs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('source_id', sa.String(length=30), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('record_count', sa.Integer(), nullable=True),
    sa.Column('rejected_count', sa.Integer(), nullable=True),
    sa.Column('call_count', sa.Integer(), nullable=True),
    sa.Column('as_of', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('alerted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['source_id'], ['data_sources.id'], name=op.f('fk_ingestion_runs_source_id_data_sources')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingestion_runs'))
    )
    op.create_index(op.f('ix_ingestion_runs_source_id_started_at'), 'ingestion_runs', ['source_id', 'started_at'], unique=False)

    # daily_call_limit 은 잠정값이다(TourAPI 개발 계정 일 1000건 기준, 운영 승인 후 조정).
    # 키가 필요한 data06·data07 은 꺼 둔다. 키를 받으면 enabled 를 켠다.
    op.bulk_insert(data_sources, [
        {'id': 'tourapi', 'name': 'TourAPI 국문 관광정보', 'kind': 'API', 'refresh_cycle': 'MONTH', 'daily_call_limit': 1000, 'enabled': True},
        {'id': 'data06', 'name': '지역별 방문자수', 'kind': 'API', 'refresh_cycle': 'DAY', 'daily_call_limit': None, 'enabled': False},
        {'id': 'data07', 'name': '관광지 집중률 예측', 'kind': 'API', 'refresh_cycle': 'DAY', 'daily_call_limit': None, 'enabled': False},
    ])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_ingestion_runs_source_id_started_at'), table_name='ingestion_runs')
    op.drop_table('ingestion_runs')
    op.drop_table('data_sources')
    op.drop_table('place_hours')
    op.drop_table('places')
