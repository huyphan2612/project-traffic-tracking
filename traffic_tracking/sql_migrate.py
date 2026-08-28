from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

from .config import Settings


DEFAULT_SCHEMA_FILE = Path(__file__).resolve().parent.parent / "migrations" / "schema.sql"


class SchemaMigrationError(RuntimeError):
    pass


def apply_schema(settings: Settings, schema_file: Path = DEFAULT_SCHEMA_FILE) -> None:
    psql = shutil.which("psql")
    if psql is None:
        raise SchemaMigrationError("psql was not found; install the PostgreSQL client")
    if not schema_file.is_file():
        raise SchemaMigrationError(f"Schema file does not exist: {schema_file}")

    command = [
        psql,
        "-X",
        "-v", "ON_ERROR_STOP=1",
        "--single-transaction",
        "--host", settings.db_server,
        "--port", str(settings.db_port),
        "--username", settings.db_username,
        "--dbname", settings.db_name,
        "--file", str(schema_file),
    ]
    environment = os.environ.copy()
    environment["PGPASSWORD"] = settings.db_password
    completed = subprocess.run(
        command,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown psql error"
        raise SchemaMigrationError(f"Could not apply database schema: {message}")
