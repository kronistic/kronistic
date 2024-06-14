"""Add costs / groups.

Revision ID: d70140580678
Revises: 74f48e237545
Create Date: 2022-08-16 12:14:41.689402

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd70140580678'
down_revision = '74f48e237545'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('fixed_events', sa.Column('jsoncosts', sa.Text(), nullable=True))
    op.execute("UPDATE fixed_events SET jsoncosts = '{\"everyone\": 0}'::TEXT WHERE kron_duty = true AND priority IS NULL;")
    op.execute("UPDATE fixed_events SET jsoncosts = '{\"everyone\": '||(priority::TEXT)||'}' WHERE kron_duty = true AND priority IS NOT NULL;")
    op.add_column('users', sa.Column('jsongroups', sa.Text(), nullable=True))
    op.execute("UPDATE users SET jsongroups = '{}';")
    op.alter_column('users', 'jsongroups', nullable=False)
    op.drop_column('fixed_events', 'priority')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('fixed_events', sa.Column('priority', sa.Integer(), nullable=True))
    # Simple downgrade step to repopulate `priority`, assuming that
    # all @kron events still have `jsoncosts` in the format
    # `{"everyone": n}`.
    op.execute("UPDATE fixed_events SET priority = NULL WHERE kron_duty = true AND (jsoncosts::JSON->>'everyone')::INT = 0;");
    op.execute("UPDATE fixed_events SET priority = (jsoncosts::JSON->>'everyone')::INT WHERE kron_duty = true AND (jsoncosts::JSON->>'everyone')::INT > 0;");
    op.drop_column('users', 'jsongroups')
    op.drop_column('fixed_events', 'jsoncosts')
    # ### end Alembic commands ###