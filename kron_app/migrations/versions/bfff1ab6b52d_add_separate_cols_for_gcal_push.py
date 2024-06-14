"""Add separate cols for gcal push.

Revision ID: bfff1ab6b52d
Revises: 2ca505d0d67a
Create Date: 2023-07-10 10:03:48.591666

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'bfff1ab6b52d'
down_revision = '2ca505d0d67a'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('attendances', sa.Column('gcal_push_id', sa.String(length=1024), nullable=True))
    op.drop_constraint('attendances_gcal_calendar_id_fkey', 'attendances', type_='foreignkey')
    op.alter_column('attendances', 'gcal_calendar_id', new_column_name='_gcal_calendar_id')
    op.execute('UPDATE attendances SET gcal_push_id = calendars.gcal_id FROM calendars WHERE attendances._gcal_calendar_id = calendars.id;');

    op.add_column('events', sa.Column('gcal_push_id', sa.String(length=1024), nullable=True))
    op.drop_constraint('events_calendar_id_fkey', 'events', type_='foreignkey')
    op.alter_column('events', 'calendar_id', new_column_name='_calendar_id')
    op.execute('UPDATE events SET gcal_push_id = calendars.gcal_id FROM calendars WHERE events._calendar_id = calendars.id;');

    op.add_column('users', sa.Column('gcal_push_id', sa.String(length=1024), nullable=True))
    op.drop_constraint('users_active_calendar_id_fkey', 'users', type_='foreignkey')
    op.alter_column('users', 'active_calendar_id', new_column_name='_active_calendar_id')
    op.execute('UPDATE users SET gcal_push_id = calendars.gcal_id FROM calendars WHERE users._active_calendar_id = calendars.id;');

    op.add_column('users', sa.Column('gcal_push_state', sa.Integer(), nullable=True))
    op.execute('UPDATE users SET gcal_push_state = 0;') # OFF
    # Enable push only for users with `gcal_push_id` set, ensuring we
    # state in a consistent state. (The upshot is that folks sat in
    # set-up at deploy time will not have push enabled.)
    op.execute('UPDATE users SET gcal_push_state = 2 WHERE gcal_push_id IS NOT NULL') # ON
    op.alter_column('users', 'gcal_push_state', nullable=False)

    op.alter_column('users', 'kalendar_gcal_id', new_column_name='_kalendar_gcal_id')
    op.drop_column('users', 'kalendar_delete_count')

    op.drop_constraint('draft_events_calendar_id_fkey', 'draft_events', type_='foreignkey')
    op.alter_column('draft_events', 'calendar_id', new_column_name='_calendar_id')
    op.add_column('draft_events', sa.Column('user_id', sa.Integer(), nullable=True))
    op.execute('UPDATE draft_events SET user_id = calendars.user_id FROM calendars WHERE draft_events._calendar_id = calendars.id;')
    op.alter_column('draft_events', 'user_id', nullable=False)
    op.create_foreign_key('draft_events_user_id_fkey', 'draft_events', 'users', ['user_id'], ['id'])
    # ### end Alembic commands ###

# NOTE: this is incomplete, and would likely need extending if we were
# to use it to rollback production. e.g. A new sign-up would need a
# new calendar row creating for their `gcal_push_id`. Something
# similar applies to attendances.
def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('draft_events_user_id_fkey', 'draft_events', type_='foreignkey')
    op.drop_column('draft_events', 'user_id')
    op.alter_column('draft_events', '_calendar_id', new_column_name='calendar_id')
    op.create_foreign_key('draft_events_calendar_id_fkey', 'draft_events', 'calendars', ['calendar_id'], ['id'])

    op.add_column('users', sa.Column('kalendar_delete_count', sa.Integer(), nullable=True))
    op.execute('UPDATE users SET kalendar_delete_count = 0;')
    op.alter_column('users', 'kalendar_delete_count', nullable=False);
    op.alter_column('users', '_kalendar_gcal_id', new_column_name='kalendar_gcal_id')

    op.drop_column('users', 'gcal_push_state')

    op.alter_column('users', '_active_calendar_id', new_column_name='active_calendar_id')
    op.create_foreign_key('users_active_calendar_id_fkey', 'users', 'calendars', ['active_calendar_id'], ['id'])
    op.drop_column('users', 'gcal_push_id')

    op.alter_column('events', '_calendar_id', new_column_name='calendar_id')
    op.create_foreign_key('events_calendar_id_fkey', 'events', 'calendars', ['calendar_id'], ['id'])
    op.drop_column('events', 'gcal_push_id')

    op.alter_column('attendances', '_gcal_calendar_id', new_column_name='gcal_calendar_id')
    op.create_foreign_key('attendances_gcal_calendar_id_fkey', 'attendances', 'calendars', ['gcal_calendar_id'], ['id'])
    op.drop_column('attendances', 'gcal_push_id')
    # ### end Alembic commands ###