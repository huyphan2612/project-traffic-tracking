from io import BytesIO

from PIL import Image, ImageDraw

from traffic_tracking.preprocessing import apply_recorded_crop, preprocess_bytes, preprocess_image


def padded_image(content_size=(512, 288), canvas_size=(1286, 726)) -> bytes:
    image = Image.new("RGB", canvas_size, "black")
    draw = ImageDraw.Draw(image)
    x = (canvas_size[0] - content_size[0]) // 2
    y = (canvas_size[1] - content_size[1]) // 2
    draw.rectangle((x, y, x + content_size[0] - 1, y + content_size[1] - 1), fill=(90, 120, 150))
    # Reproduce the thin bright border returned by the upstream renderer.
    draw.rectangle((0, 0, canvas_size[0] - 1, canvas_size[1] - 1), outline="white", width=3)
    output = BytesIO()
    image.save(output, "JPEG", quality=95)
    return output.getvalue()


def test_crops_centered_video_from_black_canvas() -> None:
    result = preprocess_bytes(padded_image())

    assert result.image.size == (512, 288)
    assert result.metadata["applied"] is True
    assert result.metadata["crop_box_xyxy"] == [387, 219, 899, 507]
    assert result.metadata["bbox_coordinate_space"] == "preprocessed_image"


def test_supports_larger_upstream_video_region() -> None:
    result = preprocess_bytes(padded_image((800, 450)))

    assert result.image.size == (800, 450)
    assert result.metadata["crop_box_xyxy"] == [243, 138, 1043, 588]


def test_keeps_full_frame_when_content_already_fills_it() -> None:
    image = Image.new("RGB", (640, 360), (80, 100, 120))

    result = preprocess_image(image)

    assert result.image.size == image.size
    assert result.metadata["applied"] is False
    assert result.metadata["reason"] == "content_already_fills_frame"


def test_falls_back_for_black_or_disabled_image() -> None:
    black = Image.new("RGB", (640, 360), "black")

    assert preprocess_image(black).metadata["reason"] == "no_active_rows"
    assert preprocess_image(black, enabled=False).metadata["reason"] == "disabled"


def test_applies_recorded_crop_for_duplicate_annotation() -> None:
    content = padded_image()
    metadata = preprocess_bytes(content).metadata

    assert apply_recorded_crop(content, metadata).size == (512, 288)
    assert apply_recorded_crop(content, None).size == (1286, 726)
