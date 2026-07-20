#!/usr/bin/env python3
"""Upgrade an empty database and idempotently create required system data."""

import os
import sys

from alembic import command
from alembic.config import Config


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def main() -> int:
    config = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    command.upgrade(config, "head")

    from app.database import SessionLocal
    from app.services.system_bootstrap import bootstrap_system_data

    with SessionLocal() as db:
        try:
            result = bootstrap_system_data(db)
            db.commit()
        except Exception:
            db.rollback()
            raise

    command.check(config)
    print(
        "Database bootstrap complete: "
        f"rubric_version_id={result['rubric_version_id']}, "
        f"prompt_template_ids={result['prompt_template_ids']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
