"""shared_links 생성(SDD 5.2, FR-011 읽기 전용 공유 링크).

token 열에는 토큰 원문 대신 SHA-256 해시를 저장한다(app/db/models.py SharedLinkRow).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-28 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('shared_links',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('trip_id', sa.Uuid(), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], name=op.f('fk_shared_links_trip_id_trips'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_shared_links')),
    sa.UniqueConstraint('token', name=op.f('uq_shared_links_token'))
    )
    op.create_index(op.f('ix_shared_links_trip_id'), 'shared_links', ['trip_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_shared_links_trip_id'), table_name='shared_links')
    op.drop_table('shared_links')
