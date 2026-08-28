from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from traffic_tracking.config import Settings
from traffic_tracking.sql_migrate import SchemaMigrationError, apply_schema


def settings() -> Settings:
    return Settings(
        db_username="traffic-user",
        db_password="secret-password",
        db_server="database.internal",
        db_port=5432,
        db_name="traffic",
    )


def test_schema_sql_is_current_and_non_destructive() -> None:
    source = (Path(__file__).parents[1] / "migrations" / "schema.sql").read_text()
    tables = set(re.findall(
        r"CREATE TABLE IF NOT EXISTS traffic_tracking\.([a-z_]+)", source, flags=re.IGNORECASE,
    ))

    assert tables == {"cameras", "runs", "observations", "benchmarks"}
    assert {"inference_signature", "inference_config", "preprocessing"} <= set(
        re.findall(r"^\s*([a-z_]+)\s+(?:VARCHAR|JSONB)", source, flags=re.IGNORECASE | re.MULTILINE)
    )
    assert not re.search(r"^\s*(?:DROP|TRUNCATE|DELETE)\b", source, flags=re.IGNORECASE | re.MULTILINE)
    assert "alembic" not in source.lower()


def test_apply_schema_calls_psql_without_password_in_argv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT 1;")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("traffic_tracking.sql_migrate.shutil.which", lambda _name: "/usr/bin/psql")
    monkeypatch.setattr("traffic_tracking.sql_migrate.subprocess.run", fake_run)

    apply_schema(settings(), schema)

    command = captured["command"]
    assert command[0] == "/usr/bin/psql"
    assert {"-X", "ON_ERROR_STOP=1", "--single-transaction"} <= set(command)
    assert command[-2:] == ["--file", str(schema)]
    assert "secret-password" not in command
    assert captured["environment"]["PGPASSWORD"] == "secret-password"
    assert "shell" not in captured["kwargs"]


def test_apply_schema_reports_missing_psql(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("traffic_tracking.sql_migrate.shutil.which", lambda _name: None)

    with pytest.raises(SchemaMigrationError, match="psql was not found"):
        apply_schema(settings(), tmp_path / "schema.sql")


def test_apply_schema_surfaces_psql_error_without_password(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    schema = tmp_path / "schema.sql"
    schema.write_text("SELECT broken;")
    monkeypatch.setattr("traffic_tracking.sql_migrate.shutil.which", lambda _name: "/usr/bin/psql")
    monkeypatch.setattr(
        "traffic_tracking.sql_migrate.subprocess.run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=3, stdout="", stderr="syntax error"),
    )

    with pytest.raises(SchemaMigrationError, match="syntax error") as error:
        apply_schema(settings(), schema)

    assert "secret-password" not in str(error.value)
