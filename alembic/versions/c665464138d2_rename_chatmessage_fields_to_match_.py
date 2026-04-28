"""rename ChatMessage fields to match Phase 3-A design

Revision ID: c665464138d2
Revises: 6c6bec064039
Create Date: 2026-04-28 10:27:37.179714

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c665464138d2'
down_revision: Union[str, Sequence[str], None] = '6c6bec064039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.alter_column('competency_key', new_column_name='probe_type_used')
        batch_op.alter_column('msg_type', new_column_name='instruction_used')


def downgrade() -> None:
    with op.batch_alter_table('chat_messages', schema=None) as batch_op:
        batch_op.alter_column('probe_type_used', new_column_name='competency_key')
        batch_op.alter_column('instruction_used', new_column_name='msg_type')
