from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_sizes(value: str) -> tuple[tuple[int, int], ...]:
    sizes: list[tuple[int, int]] = []
    for item in value.split(","):
        width, separator, height = item.strip().lower().partition("x")
        if not separator or not width.isdigit() or not height.isdigit():
            raise ValueError(f"Invalid snapshot size: {item!r}")
        sizes.append((int(width), int(height)))
    if not sizes:
        raise ValueError("SNAPSHOT_SIZES must contain at least one size")
    return tuple(sizes)


@dataclass(frozen=True)
class Settings:
    db_username: str
    db_password: str
    db_server: str
    db_port: int
    db_name: str
    base_url: str = "https://giaothong.hochiminhcity.gov.vn"
    yolo_model: str = "yolo26m.pt"
    yolo_device: str = "auto"
    yolo_confidence: float = 0.15
    yolo_imgsz: int = 1280
    inference_batch_size: int = 1
    download_concurrency: int = 4
    snapshot_sizes: tuple[tuple[int, int], ...] = ((1280, 720), (960, 540), (640, 360), (300, 230))
    auto_crop: bool = True
    save_images: bool = False
    photo_dir: Path = Path("photo")
    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus

        username = quote_plus(self.db_username)
        password = quote_plus(self.db_password)
        return f"postgresql+psycopg://{username}:{password}@{self.db_server}:{self.db_port}/{self.db_name}"

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Settings":
        load_dotenv(env_file)
        required = ["DB_USERNAME", "DB_PASSWORD", "DB_SERVER", "DB_PORT", "DB_NAME"]
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

        confidence = float(os.getenv("YOLO_CONFIDENCE", "0.15"))
        if not 0 <= confidence <= 1:
            raise ValueError("YOLO_CONFIDENCE must be between 0 and 1")

        concurrency = int(os.getenv("DOWNLOAD_CONCURRENCY", "4"))
        if concurrency < 1:
            raise ValueError("DOWNLOAD_CONCURRENCY must be >= 1")

        return cls(
            db_username=os.environ["DB_USERNAME"],
            db_password=os.environ["DB_PASSWORD"],
            db_server=os.environ["DB_SERVER"],
            db_port=int(os.environ["DB_PORT"]),
            db_name=os.environ["DB_NAME"],
            base_url=os.getenv("TRAFFIC_BASE_URL", cls.base_url).rstrip("/"),
            yolo_model=os.getenv("YOLO_MODEL", cls.yolo_model),
            yolo_device=os.getenv("YOLO_DEVICE", cls.yolo_device),
            yolo_confidence=confidence,
            yolo_imgsz=int(os.getenv("YOLO_IMGSZ", "1280")),
            inference_batch_size=max(1, int(os.getenv("INFERENCE_BATCH_SIZE", "1"))),
            download_concurrency=concurrency,
            snapshot_sizes=_as_sizes(os.getenv("SNAPSHOT_SIZES", "1280x720,960x540,640x360,300x230")),
            auto_crop=_as_bool(os.getenv("AUTO_CROP"), default=True),
            save_images=_as_bool(os.getenv("SAVE_IMAGES")),
            photo_dir=Path(os.getenv("PHOTO_DIR", "photo")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def public_config(self) -> dict[str, object]:
        return {
            "base_url": self.base_url,
            "yolo_model": self.yolo_model,
            "yolo_device": self.yolo_device,
            "yolo_confidence": self.yolo_confidence,
            "yolo_imgsz": self.yolo_imgsz,
            "inference_batch_size": self.inference_batch_size,
            "download_concurrency": self.download_concurrency,
            "snapshot_sizes": self.snapshot_sizes,
            "auto_crop": self.auto_crop,
            "save_images": self.save_images,
            "photo_dir": str(self.photo_dir),
        }
