"""Lengthen gcal_sync_token column.

Revision ID: c6e96448900f
Revises: bfff1ab6b52d
Create Date: 2023-09-18 18:53:08.391701

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c6e96448900f'
down_revision = 'bfff1ab6b52d'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('alter table calendars alter column gcal_sync_token type varchar(64);');


def downgrade():
    # Will fail if we've already stored sync tokens with length > 36.
    op.execute('alter table calendars alter column gcal_sync_token type varchar(36);');
