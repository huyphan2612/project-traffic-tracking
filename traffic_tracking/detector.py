from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path
import time

from PIL import Image

from .domain import Detection, InferenceResult, Snapshot
from .preprocessing import preprocess_bytes, preprocessing_config


ROAD_VEHICLE_CLASS_IDS = [1, 2, 3, 5, 7]


class Detector:
    def __init__(self, model_name: str, device: str, confidence: float, image_size: int, auto_crop: bool = True):
        import ultralytics
        from ultralytics import YOLO

        self.model_name = model_name
        self.requested_device = device
        self.confidence = confidence
        self.image_size = image_size
        self.auto_crop = auto_crop
        self.model = YOLO(model_name)
        self.device = self._resolve_device(device)
        self.inference_config = {
            "model_name": model_name,
            "model_sha256": self._model_sha256(model_name),
            "ultralytics_version": ultralytics.__version__,
            "image_size": image_size,
            "confidence": confidence,
            "class_ids": ROAD_VEHICLE_CLASS_IDS,
            "preprocessing": preprocessing_config(auto_crop),
        }
        encoded = json.dumps(self.inference_config, sort_keys=True, separators=(",", ":")).encode()
        self.inference_signature = hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _model_sha256(model_name: str) -> str | None:
        path = Path(model_name)
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as model_file:
            for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        try:
            import torch

            return "cuda:0" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def infer(self, snapshots: list[Snapshot], render: bool = False) -> list[tuple[InferenceResult, bytes | None]]:
        prepared = [preprocess_bytes(snapshot.content, self.auto_crop) for snapshot in snapshots if snapshot.content]
        if len(prepared) != len(snapshots):
            raise ValueError("Cannot infer a snapshot without image bytes")
        images = [item.image for item in prepared]
        started = time.perf_counter()
        results = self.model.predict(
            source=images,
            conf=self.confidence,
            imgsz=self.image_size,
            classes=ROAD_VEHICLE_CLASS_IDS,
            device=self.device,
            verbose=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        per_image_ms = elapsed_ms / max(1, len(results))
        outputs: list[tuple[InferenceResult, bytes | None]] = []
        for result, prepared_image in zip(results, prepared):
            detections: list[Detection] = []
            boxes = result.boxes
            if boxes is not None:
                for class_id, confidence, coordinates in zip(
                    boxes.cls.detach().cpu().tolist(),
                    boxes.conf.detach().cpu().tolist(),
                    boxes.xyxy.detach().cpu().tolist(),
                ):
                    integer_id = int(class_id)
                    class_name = str(result.names[integer_id])
                    detections.append(Detection(
                        class_id=integer_id,
                        class_name=class_name,
                        confidence=round(float(confidence), 6),
                        bbox_xyxy=[round(float(value), 3) for value in coordinates],
                    ))
            annotated_bytes = None
            if render:
                plotted_bgr = result.plot()
                annotated = Image.fromarray(plotted_bgr[:, :, ::-1])
                buffer = BytesIO()
                annotated.save(buffer, format="JPEG", quality=92)
                annotated_bytes = buffer.getvalue()
            outputs.append((InferenceResult(
                detections=detections,
                inference_ms=per_image_ms,
                preprocessing=prepared_image.metadata,
            ), annotated_bytes))
        return outputs
