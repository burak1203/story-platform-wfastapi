"""add events story importance index

DB denetim raporu (Faz 2.0 sonrasi) bulgusu: pinned cekirdek her uretimde
`select(Event).where(Event.story_id == ...).order_by(Event.importance.desc(), Event.id)`
calistiriyor (retrieval.py, PINNED_CANDIDATE_POOL adaylarini secmek icin). Mevcut index
yalnizca story_id'de; importance sirasi icin ayrica sort gerekiyordu. Hikaye basina olay
sayisi buyudukce (bkz. "~1000 bolum/hikaye" yumusak tavani, bolum basina 3-7 olay) bu her
uretimde tekrar eden bir maliyet. Composite index sorguyu tek index taramasina indirir.

Revision ID: 1183dcd3dc65
Revises: 15f3b2b7daa1
Create Date: 2026-08-03 00:58:19.426152

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1183dcd3dc65'
down_revision: Union[str, Sequence[str], None] = '15f3b2b7daa1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # id de eklendi: uygulama sorgusu esitlikte Event.id ile deterministik sonuclaniyor
    # (retrieval.py order_by(Event.importance.desc(), Event.id)); index bunu da karsilasin.
    op.create_index(
        "ix_events_story_importance",
        "events",
        ["story_id", sa.text("importance DESC"), "id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_events_story_importance", table_name="events")
