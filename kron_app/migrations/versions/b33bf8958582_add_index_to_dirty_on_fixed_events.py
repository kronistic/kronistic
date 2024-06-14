"""Add index to dirty on fixed_events.

Revision ID: b33bf8958582
Revises: d70140580678
Create Date: 2022-08-24 14:24:18.847501

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b33bf8958582'
down_revision = 'd70140580678'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index(op.f('ix_fixed_events_dirty'), 'fixed_events', ['dirty'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_fixed_events_dirty'), table_name='fixed_events')
    # ### end Alembic commands ###