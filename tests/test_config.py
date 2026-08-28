from pathlib import Path

import pytest

from traffic_tracking.config import Settings


DB_ENV = {
    "DB_USERNAME": "user@local",
    "DB_PASSWORD": "value" + chr(64) + "with/slash",
    "DB_SERVER": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "traffic",
}


def test_default_model_is_yolo26m() -> None:
    assert Settings.__dataclass_fields__["yolo_model"].default == "yolo26m.pt"


def test_settings_parse_runtime_options(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key, value in DB_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("SAVE_IMAGES", "true")
    monkeypatch.setenv("SNAPSHOT_SIZES", "1280x720,640x360")
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path / "photo"))

    settings = Settings.from_env(tmp_path / "missing.env")

    assert settings.save_images is True
    assert settings.snapshot_sizes == ((1280, 720), (640, 360))
    assert "user%40local:value%40with%2Fslash" in settings.database_url


def test_settings_reject_invalid_confidence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key, value in DB_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("YOLO_CONFIDENCE", "1.5")

    with pytest.raises(ValueError, match="between 0 and 1"):
        Settings.from_env(tmp_path / "missing.env")
