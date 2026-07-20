#!/usr/bin/env python3
"""Create or update an initial admin account.

Run this after Alembic has initialized the database:

    python scripts/init_admin.py \
        --name "Teacher Name" \
        --student-id admin001 \
        --email admin@example.com
"""

import argparse
import os
import sys
from getpass import getpass


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update the initial admin user")
    parser.add_argument("--name", required=True, help="Admin display name")
    parser.add_argument("--student-id", required=True, dest="student_id", help="Admin login ID")
    parser.add_argument("--email", required=True, help="Admin email address")
    parser.add_argument("--password", help="Admin password. If omitted, you will be prompted.")
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update name, email, password, and reactivate the admin if the student ID already exists.",
    )
    parser.add_argument(
        "--must-change-password",
        action="store_true",
        help="Require this admin to change the password on first login.",
    )
    return parser.parse_args()


def _get_password(password: str | None) -> str:
    if password is None:
        password = getpass("Admin password: ")
        confirm = getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: passwords do not match.", file=sys.stderr)
            sys.exit(1)
    from app.schemas import validate_password

    try:
        validate_password(password)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    return password


def main() -> int:
    args = _parse_args()
    password = _get_password(args.password)

    from app.auth import hash_password
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.student_id == args.student_id).first()
        if user is not None and not args.update_existing:
            print(
                f"ERROR: user with student_id '{args.student_id}' already exists. "
                "Use --update-existing to update it.",
                file=sys.stderr,
            )
            return 1

        if user is None:
            user = User(
                student_id=args.student_id,
                name=args.name,
                email=args.email,
                hashed_password=hash_password(password),
                role="admin",
                course_num=None,
                is_active=True,
                must_change_password=args.must_change_password,
            )
            db.add(user)
            action = "created"
        else:
            user.name = args.name
            user.email = args.email
            user.hashed_password = hash_password(password)
            user.role = "admin"
            user.course_num = None
            user.is_active = True
            user.must_change_password = args.must_change_password
            action = "updated"

        db.commit()
        db.refresh(user)
    except Exception as exc:
        db.rollback()
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(f"Admin user {action} successfully.")
    print(f"  ID:         {user.id}")
    print(f"  Student ID: {user.student_id}")
    print(f"  Name:       {user.name}")
    print(f"  Email:      {user.email}")
    print(f"  Role:       {user.role}")
    print(f"  is_active:  {user.is_active}")
    print(f"  must_change_password: {user.must_change_password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
