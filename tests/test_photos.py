from datetime import datetime, timezone
from io import BytesIO

from PIL import Image

from traffic_tracking.photos import PhotoStore
from traffic_tracking.preprocessing import preprocess_bytes


def test_dev_photo_store_saves_original_and_annotation(tmp_path) -> None:
    source = BytesIO()
    Image.new("RGB", (20, 10), "white").save(source, "JPEG")
    store = PhotoStore(tmp_path, "run-id")

    annotated = store.render_existing(source.getvalue(), [{
        "class_name": "car", "confidence": 0.9, "bbox_xyxy": [1, 1, 10, 8],
    }])
    original_path, annotated_path = store.save(
        "camera/id", datetime(2026, 8, 28, tzinfo=timezone.utc), source.getvalue(), annotated,
    )

    assert (tmp_path / "run-id" / "camera_id_20260828T000000.000000Z_original.jpg").exists()
    assert (tmp_path / "run-id" / "camera_id_20260828T000000.000000Z_annotated.jpg").exists()
    assert original_path.endswith("_original.jpg")
    assert annotated_path.endswith("_annotated.jpg")


def test_duplicate_annotation_uses_recorded_crop(tmp_path) -> None:
    source = BytesIO()
    image = Image.new("RGB", (300, 200), "black")
    from PIL import ImageDraw
    ImageDraw.Draw(image).rectangle((50, 50, 249, 149), fill="white")
    image.save(source, "JPEG")
    metadata = preprocess_bytes(source.getvalue()).metadata
    store = PhotoStore(tmp_path, "run-id")

    annotated = store.render_existing(source.getvalue(), [], metadata)

    assert Image.open(BytesIO(annotated)).size == (200, 100)
