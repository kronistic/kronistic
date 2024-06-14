"""Add attendances table.

Revision ID: f5956d420688
Revises: af435a3f3c06
Create Date: 2022-11-23 15:15:31.206088

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f5956d420688'
down_revision = 'af435a3f3c06'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('attendances',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('email_id', sa.Integer(), nullable=False),
    sa.Column('optional', sa.Boolean(), nullable=False),
    sa.Column('deleted', sa.Boolean(), nullable=False),
    sa.Column('response', sa.Integer(), nullable=False),
    sa.Column('creator_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['creator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['email_id'], ['emails.id'], ),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id', 'email_id')
    )
    op.create_index(op.f('ix_attendances_email_id'), 'attendances', ['email_id'], unique=False)
    op.alter_column('events', 'attendees', new_column_name='_attendees')
    op.alter_column('events', 'optionalattendees', new_column_name='_optionalattendees')
    op.alter_column('events', 'invitees', new_column_name='_invitees')
    op.alter_column('events', 'optionalinvitees', new_column_name='_optionalinvitees')
    op.execute('INSERT INTO attendances (event_id, creator_id, email_id, optional, deleted, response, created_at) '
               'SELECT t.id, t.creator_id, users.primary_email_id, false, false, 0, now() FROM '
               '(SELECT id, creator_id, unnest(_attendees) AS user_id FROM events) t '
               'JOIN users ON t.user_id = users.id;')
    op.execute('INSERT INTO attendances (event_id, creator_id, email_id, optional, deleted, response, created_at) '
               'SELECT t.id, t.creator_id, users.primary_email_id, true, false, 0, now() FROM '
               '(SELECT id, creator_id, unnest(_optionalattendees) AS user_id FROM events) t '
               'JOIN users ON t.user_id = users.id;')
    op.execute('INSERT INTO attendances (event_id, creator_id, email_id, optional, deleted, response, created_at) '
               'SELECT id, creator_id, unnest(events._invitees), false, false, 0, now() FROM events;')
    op.execute('INSERT INTO attendances (event_id, creator_id, email_id, optional, deleted, response, created_at) '
               'SELECT id, creator_id, unnest(events._optionalinvitees), true, false, 0, now() FROM events;')
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('events', '_attendees', new_column_name='attendees')
    op.alter_column('events', '_optionalattendees', new_column_name='optionalattendees')
    op.alter_column('events', '_invitees', new_column_name='invitees')
    op.alter_column('events', '_optionalinvitees', new_column_name='optionalinvitees')
    op.drop_index(op.f('ix_attendances_email_id'), table_name='attendances')
    op.drop_table('attendances')
    # ### end Alembic commands ###
