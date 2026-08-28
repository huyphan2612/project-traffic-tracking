from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
import re
from typing import Any

from PIL import Image, ImageDraw

from .preprocessing import apply_recorded_crop


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


class PhotoStore:
    def __init__(self, root: Path, run_id: str):
        self.run_dir = root / _safe(run_id)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def paths(self, camera_id: str, observed_at: datetime) -> tuple[Path, Path]:
        timestamp = observed_at.strftime("%Y%m%dT%H%M%S.%fZ")
        stem = f"{_safe(camera_id)}_{timestamp}"
        return self.run_dir / f"{stem}_original.jpg", self.run_dir / f"{stem}_annotated.jpg"

    def save(self, camera_id: str, observed_at: datetime, original: bytes, annotated: bytes) -> tuple[str, str]:
        original_path, annotated_path = self.paths(camera_id, observed_at)
        original_path.write_bytes(original)
        annotated_path.write_bytes(annotated)
        return str(original_path), str(annotated_path)

    def render_existing(
        self,
        original: bytes,
        detections: list[dict[str, Any]] | None,
        preprocessing: dict[str, Any] | None = None,
    ) -> bytes:
        image = apply_recorded_crop(original, preprocessing)
        draw = ImageDraw.Draw(image)
        for detection in detections or []:
            bbox = detection.get("bbox_xyxy")
            if not isinstance(bbox, list) or len(bbox) != 4:
                continue
            label = f"{detection.get('class_name', '?')} {float(detection.get('confidence', 0)):.2f}"
            draw.rectangle(tuple(bbox), outline="red", width=3)
            draw.text((bbox[0] + 2, max(0, bbox[1] - 12)), label, fill="red")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=92)
        return buffer.getvalue()
