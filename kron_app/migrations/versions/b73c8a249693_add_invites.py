"""Add invites.

Revision ID: b73c8a249693
Revises: 98e2ba75bc33
Create Date: 2022-04-29 21:34:51.208421

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b73c8a249693'
down_revision = '98e2ba75bc33'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('invites',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=100), nullable=False),
    sa.Column('sent', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=True))
    op.execute('UPDATE users SET is_admin = false')
    op.alter_column('users', 'is_admin', nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('users', 'is_admin')
    op.drop_table('invites')
    # ### end Alembic commands ###
