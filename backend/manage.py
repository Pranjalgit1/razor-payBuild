"""Small operational CLI.

Usage:
    python manage.py init-db     # create tables directly (dev shortcut)
    python manage.py seed        # reset and load demo data
    python manage.py reset       # alias for seed
    python manage.py clear       # delete all data, leaving empty tables

For anything beyond local development, use Alembic to manage the schema:
    python -m alembic upgrade head
"""

from __future__ import annotations

import sys

from app.config import settings
from app.database.base import Base
from app.database.session import SessionLocal, engine
from app.models import entities  # noqa: F401  (registers models on the metadata)
from app.simulations.seed import reset_demo_data, seed_demo_data


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print(f"Schema created on {settings.database_url.split('://', 1)[0]}.")


def seed() -> None:
    with SessionLocal() as db:
        counts = seed_demo_data(db, reset=True)
    print(f"Seeded {counts['customers']} customers, {counts['transactions']} transactions.")


def clear() -> None:
    with SessionLocal() as db:
        reset_demo_data(db)
    print("All data cleared.")


COMMANDS = {"init-db": init_db, "seed": seed, "reset": seed, "clear": clear}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return 1
    COMMANDS[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
