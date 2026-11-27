"""Explicit SQLite initialization; importing this module creates no files."""

import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("config.json")


def initialize_database(config_path=DEFAULT_CONFIG):
    """Create the configured database if absent; preserve an existing database.

    Relative database paths are resolved from the project root, not the current
    working directory. No observation tables are defined at this stage.
    """
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    settings = config["database"]
    if settings.get("type") != "sqlite":
        raise ValueError("Observation requires a SQLite database")
    location = settings.get("path")
    if not isinstance(location, str) or not location.strip():
        raise ValueError("A non-empty SQLite database path is required")
    path = Path(location).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA schema_version").fetchone()
    finally:
        connection.close()
    return path


if __name__ == "__main__":
    print(initialize_database())
