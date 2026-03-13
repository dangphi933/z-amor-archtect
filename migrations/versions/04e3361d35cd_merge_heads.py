"""merge_heads

Revision ID: 04e3361d35cd
Revises: init_trading_schema, ed3572c9ca19
Create Date: 2026-03-13 08:33:03.300576+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04e3361d35cd'
down_revision: Union[str, None] = ('init_trading_schema', 'ed3572c9ca19')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
