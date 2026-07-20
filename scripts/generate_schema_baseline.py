#!/usr/bin/env python3
"""Generate the frozen current-schema Alembic baseline from ORM metadata.

This maintenance tool writes a static migration; the generated migration does
not import live model metadata, so later model changes still require ordinary
incremental Alembic revisions.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from pprint import pformat
import sys

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models import Base


HEADER = '''"""current schema baseline

Revision ID: 001
Revises: None
Create Date: 2026-07-18
"""

from alembic import op
import sqlalchemy as sa


revision = "001"
down_revision = None
branch_labels = None
depends_on = None

'''


def _ddl() -> tuple[list[str], list[str]]:
    dialect = postgresql.dialect()
    statements = [str(CreateTable(table).compile(dialect=dialect)).strip() for table in Base.metadata.sorted_tables]
    for table in Base.metadata.sorted_tables:
        statements.extend(
            str(CreateIndex(index).compile(dialect=dialect)).strip()
            for index in sorted(table.indexes, key=lambda item: item.name or "")
        )
    return statements, [table.name for table in Base.metadata.sorted_tables]


def generate(output: Path) -> None:
    statements, table_names = _ddl()
    body = HEADER
    body += f"SCHEMA_STATEMENTS = {pformat(statements, width=118, sort_dicts=False)}\n\n"
    body += f"TABLE_NAMES = {pformat(table_names, width=118, sort_dicts=False)}\n\n"
    body += '''
def upgrade():
    for statement in SCHEMA_STATEMENTS:
        op.execute(sa.text(statement))
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION prevent_grade_revision_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'submission_grade_revisions is append-only';
        END;
        $$ LANGUAGE plpgsql
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_grade_revisions_append_only
        BEFORE UPDATE OR DELETE ON submission_grade_revisions
        FOR EACH ROW EXECUTE FUNCTION prevent_grade_revision_mutation()
    """))


def downgrade():
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_grade_revisions_append_only ON submission_grade_revisions"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS prevent_grade_revision_mutation()"))
    for table_name in reversed(TABLE_NAMES):
        op.drop_table(table_name)
'''
    output.write_text(body, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
