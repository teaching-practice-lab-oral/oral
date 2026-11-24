"""drop worker routing events (audio offload removed)

Revision ID: 002
Revises: 001
Create Date: 2026-11-24
"""

from alembic import op
import sqlalchemy as sa


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(sa.text("DROP TABLE IF EXISTS worker_routing_events"))


def downgrade():
    op.execute(sa.text("""
        CREATE TABLE worker_routing_events (
            id SERIAL NOT NULL,
            user_id INTEGER,
            student_id VARCHAR(64) NOT NULL,
            submission_id INTEGER,
            stage INTEGER,
            operation VARCHAR(64) NOT NULL,
            route_status VARCHAR(32) NOT NULL,
            worker_url VARCHAR(512),
            detail VARCHAR(256),
            duration_ms INTEGER,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            PRIMARY KEY (id),
            CONSTRAINT ck_worker_routing_events_status CHECK (route_status IN ('worker_success', 'fallback_error', 'local_weight', 'local_cooldown', 'local_disabled')),
            CONSTRAINT ck_worker_routing_events_stage CHECK (stage IS NULL OR stage BETWEEN 1 AND 8),
            CONSTRAINT ck_worker_routing_events_duration CHECK (duration_ms IS NULL OR duration_ms >= 0),
            FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL,
            FOREIGN KEY(submission_id) REFERENCES submissions (id) ON DELETE SET NULL
        )
    """))
    for statement in (
        "CREATE INDEX ix_worker_routing_events_created_at ON worker_routing_events (created_at)",
        "CREATE INDEX ix_worker_routing_events_created_id_desc ON worker_routing_events (created_at DESC, id DESC)",
        "CREATE INDEX ix_worker_routing_events_route_status ON worker_routing_events (route_status)",
        "CREATE INDEX ix_worker_routing_events_status_created ON worker_routing_events (route_status, created_at DESC)",
        "CREATE INDEX ix_worker_routing_events_student_id ON worker_routing_events (student_id)",
        "CREATE INDEX ix_worker_routing_events_submission_id ON worker_routing_events (submission_id)",
        "CREATE INDEX ix_worker_routing_events_user_created ON worker_routing_events (user_id, created_at DESC)",
        "CREATE INDEX ix_worker_routing_events_user_id ON worker_routing_events (user_id)",
    ):
        op.execute(sa.text(statement))
