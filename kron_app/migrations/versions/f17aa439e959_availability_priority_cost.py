"""Availability priority -> cost.

Revision ID: f17aa439e959
Revises: a95e71f5c27b
Create Date: 2023-06-12 15:06:28.192378

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f17aa439e959'
down_revision = 'a95e71f5c27b'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column('availability_events', 'priority', new_column_name='cost')


def downgrade():
    op.alter_column('availability_events', 'cost', new_column_name='priority')
