"""Add send_freeze_notifications flag to users.

Revision ID: 98e2ba75bc33
Revises: df6728bf3d0e
Create Date: 2022-04-28 11:12:08.672224

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '98e2ba75bc33'
down_revision = 'df6728bf3d0e'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('send_freeze_notifications', sa.Boolean(), nullable=True))
    op.execute('UPDATE users SET send_freeze_notifications = false')
    op.alter_column('users', 'send_freeze_notifications', nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'send_freeze_notifications')
    # ### end Alembic commands ###