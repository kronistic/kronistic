"""Add cols to users for refresh token handling.

Revision ID: 1671383aafd8
Revises: 4c73dbc55962
Create Date: 2022-04-21 14:01:14.550885

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1671383aafd8'
down_revision = '4c73dbc55962'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('gcal_api_error_count', sa.Integer(), nullable=True))
    op.execute('UPDATE users SET gcal_api_error_count = 0')
    op.alter_column('users', 'gcal_api_error_count', nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'gcal_api_error_count')
    op.drop_column('users', 'last_login_at')
    # ### end Alembic commands ###