"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-26 16:54:42.094095
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('email', name=op.f('uq_users_email'))
    )
    op.create_table('audit_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('endpoint_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_events_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_endpoint_id'), 'audit_events', ['endpoint_id'], unique=False)
    op.create_index(op.f('ix_audit_events_user_id'), 'audit_events', ['user_id'], unique=False)

    op.create_table('endpoints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('owner_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('url', sa.String(length=2048), nullable=False),
    sa.Column('method', sa.String(length=10), nullable=False),
    sa.Column('expected_status', sa.Integer(), nullable=False),
    sa.Column('interval_seconds', sa.Integer(), nullable=False),
    sa.Column('timeout_seconds', sa.Float(), nullable=False),
    sa.Column('headers', sa.JSON(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_outcome', sa.String(length=32), nullable=True),
    sa.Column('last_status_code', sa.Integer(), nullable=True),
    sa.Column('last_latency_ms', sa.Float(), nullable=True),
    sa.Column('health_status', sa.String(length=16), nullable=False),
    sa.Column('schema_status', sa.String(length=32), nullable=False),
    sa.Column('schema_checked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('latest_schema_hash', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_endpoints_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_endpoints')),
    sa.UniqueConstraint('owner_id', 'name', name='uq_endpoints_owner_name')
    )
    op.create_index(op.f('ix_endpoints_is_active'), 'endpoints', ['is_active'], unique=False)
    op.create_index(op.f('ix_endpoints_owner_id'), 'endpoints', ['owner_id'], unique=False)

    op.create_table('check_results',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('outcome', sa.String(length=32), nullable=False),
    sa.Column('is_healthy', sa.Boolean(), nullable=False),
    sa.Column('status_code', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Float(), nullable=True),
    sa.Column('response_size_bytes', sa.Integer(), nullable=True),
    sa.Column('content_type', sa.String(length=255), nullable=True),
    sa.Column('error_message', sa.String(length=500), nullable=True),
    sa.Column('schema_status', sa.String(length=32), nullable=False),
    sa.Column('schema_hash', sa.String(length=64), nullable=True),
    sa.Column('drift_severity', sa.String(length=16), nullable=True),
    sa.Column('change_count', sa.Integer(), nullable=False),
    sa.Column('baseline_id', sa.Uuid(), nullable=True),
    sa.Column('incident_id', sa.Uuid(), nullable=True),
    sa.Column('snapshot_id', sa.String(length=64), nullable=True),
    sa.Column('diff_id', sa.String(length=200), nullable=True),
    sa.ForeignKeyConstraint(['endpoint_id'], ['endpoints.id'], name=op.f('fk_check_results_endpoint_id_endpoints'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_check_results'))
    )
    op.create_index('ix_check_results_endpoint_checked', 'check_results', ['endpoint_id', 'checked_at'], unique=False)

    op.create_table('baselines',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('schema_hash', sa.String(length=64), nullable=False),
    sa.Column('is_current', sa.Boolean(), nullable=False),
    sa.Column('source_check_id', sa.Uuid(), nullable=True),
    sa.Column('approved_by_id', sa.Uuid(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('replaced_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['approved_by_id'], ['users.id'], name=op.f('fk_baselines_approved_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['endpoint_id'], ['endpoints.id'], name=op.f('fk_baselines_endpoint_id_endpoints'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_check_id'], ['check_results.id'], name=op.f('fk_baselines_source_check_id_check_results'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_baselines')),
    sa.UniqueConstraint('endpoint_id', 'version', name='uq_baselines_endpoint_version')
    )
    op.create_index('uq_baselines_one_current', 'baselines', ['endpoint_id'], unique=True, postgresql_where=sa.text('is_current'), sqlite_where=sa.text('is_current'))

    op.create_table('incidents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('endpoint_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.String(length=1000), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=True),
    sa.Column('baseline_id', sa.Uuid(), nullable=True),
    sa.Column('latest_diff_id', sa.String(length=200), nullable=True),
    sa.Column('occurrence_count', sa.Integer(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolution', sa.String(length=32), nullable=True),
    sa.Column('resolved_by_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['baseline_id'], ['baselines.id'], name=op.f('fk_incidents_baseline_id_baselines'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['endpoint_id'], ['endpoints.id'], name=op.f('fk_incidents_endpoint_id_endpoints'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], name=op.f('fk_incidents_resolved_by_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incidents'))
    )
    op.create_index('ix_incidents_endpoint_status', 'incidents', ['endpoint_id', 'status'], unique=False)
    op.create_index('ix_incidents_last_seen', 'incidents', ['last_seen_at'], unique=False)
    op.create_index('uq_incidents_one_open', 'incidents', ['endpoint_id', 'type'], unique=True, postgresql_where=sa.text("status = 'open'"), sqlite_where=sa.text("status = 'open'"))

    op.create_table('incident_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('event_type', sa.String(length=32), nullable=False),
    sa.Column('message', sa.String(length=500), nullable=False),
    sa.Column('actor_id', sa.Uuid(), nullable=True),
    sa.Column('details', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_incident_events_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], name=op.f('fk_incident_events_incident_id_incidents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_incident_events'))
    )
    op.create_index(op.f('ix_incident_events_incident_id'), 'incident_events', ['incident_id'], unique=False)
    # check_results <-> baselines/incidents reference each other; add these FKs last.
    op.create_foreign_key(op.f('fk_check_results_baseline_id_baselines'), 'check_results', 'baselines',
                          ['baseline_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key(op.f('fk_check_results_incident_id_incidents'), 'check_results', 'incidents',
                          ['incident_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(op.f('fk_check_results_incident_id_incidents'), 'check_results', type_='foreignkey')
    op.drop_constraint(op.f('fk_check_results_baseline_id_baselines'), 'check_results', type_='foreignkey')
    for table in ('incident_events', 'incidents', 'baselines', 'check_results', 'endpoints', 'audit_events', 'users'):
        op.drop_table(table)
