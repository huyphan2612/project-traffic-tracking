from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_dockerfile_has_cpu_and_gpu_non_root_targets() -> None:
    source = (ROOT / "Dockerfile").read_text()

    assert "AS cpu" in source
    assert "AS gpu" in source
    assert "pytorch/pytorch:2.13.0-cuda12.6-cudnn9-runtime" in source
    assert "torch==2.13.0+cpu" in source
    assert source.count("ARG YOLO_MODEL=yolo26m.pt") == 2
    assert source.count("USER app") == 2
    assert source.count('ENTRYPOINT ["python", "main.py"]') == 2


def test_docker_image_does_not_include_database_migration_tools() -> None:
    source = (ROOT / "Dockerfile").read_text().lower()

    assert "postgresql-client" not in source
    assert "migrations/schema.sql" not in source
    assert "psql" not in source


def test_dockerignore_is_an_allowlist_without_secrets_or_runtime_data() -> None:
    rules = (ROOT / ".dockerignore").read_text().splitlines()

    assert rules[0] == "*"
    assert set(rules[1:]) == {
        "!Dockerfile",
        "!requirements.txt",
        "!main.py",
        "!traffic_tracking/",
        "!traffic_tracking/**",
    }
    assert not any(rule in rules for rule in ("!.env", "!photo/", "!migrations/", "!tests/", "!*.pt"))
