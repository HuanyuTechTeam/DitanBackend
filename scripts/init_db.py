"""Upgrade database schema using Alembic (preserves existing data)."""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def main() -> None:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
