from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import UUID, uuid4

from geoalchemy2.elements import WKTElement
from sqlalchemy import desc, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .db import BenchmarkRecord, CameraRecord, ObservationRecord, RunRecord
from .domain import Camera, InferenceResult, Snapshot


ADVISORY_LOCK_KEY = 824_026_082


class Repository:
    def __init__(self, session: Session):
        self.session = session

    def try_pipeline_lock(self) -> bool:
        return bool(self.session.execute(select(func.pg_try_advisory_lock(ADVISORY_LOCK_KEY))).scalar_one())

    def unlock_pipeline(self) -> None:
        self.session.execute(select(func.pg_advisory_unlock(ADVISORY_LOCK_KEY)))

    def create_run(self, run_type: str, config: dict[str, Any]) -> RunRecord:
        record = RunRecord(
            id=uuid4(),
            run_type=run_type,
            status="running",
            started_at=datetime.now(timezone.utc),
            config=config,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def finish_run(self, run: RunRecord, status: str, **counts: Any) -> None:
        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        for key, value in counts.items():
            if hasattr(run, key):
                setattr(run, key, value)
        self.session.flush()

    def upsert_cameras(self, cameras: Iterable[Camera], seen_at: datetime | None = None) -> None:
        now = seen_at or datetime.now(timezone.utc)
        for camera in cameras:
            location = None
            if camera.longitude is not None and camera.latitude is not None:
                location = WKTElement(f"POINT({camera.longitude} {camera.latitude})", srid=4326)
            values = {
                "camera_id": camera.camera_id,
                "title": camera.title,
                "description": camera.description,
                "code": camera.code,
                "display_name": camera.display_name,
                "longitude": camera.longitude,
                "latitude": camera.latitude,
                "location": location,
                "snapshot_url": camera.snapshot_url,
                "camera_type": camera.camera_type,
                "district": camera.district,
                "published": camera.published,
                "management_unit": camera.management_unit,
                "status": camera.status,
                "ptz": camera.ptz,
                "angle": camera.angle,
                "video_url": camera.video_url,
                "video_streaming": camera.video_streaming,
                "data_id": camera.data_id,
                "node_id": camera.node_id,
                "path": camera.path,
                "source_created_at": camera.source_created_at,
                "source_modified_at": camera.source_modified_at,
                "first_seen_at": now,
                "last_seen_at": now,
                "raw_metadata": camera.raw_metadata,
            }
            statement = insert(CameraRecord).values(**values)
            update_values = {key: value for key, value in values.items() if key not in {"camera_id", "first_seen_at"}}
            self.session.execute(statement.on_conflict_do_update(index_elements=[CameraRecord.camera_id], set_=update_values))
        self.session.flush()

    def list_up_cameras(self) -> list[CameraRecord]:
        return list(self.session.scalars(select(CameraRecord).where(CameraRecord.status == "UP").order_by(CameraRecord.camera_id)))

    def latest_successes(self, camera_ids: Iterable[str]) -> dict[str, ObservationRecord]:
        ids = list(camera_ids)
        if not ids:
            return {}
        ranked = (
            select(
                ObservationRecord.id.label("id"),
                func.row_number().over(
                    partition_by=ObservationRecord.camera_id,
                    order_by=ObservationRecord.observed_at.desc(),
                ).label("rank"),
            )
            .where(
                ObservationRecord.camera_id.in_(ids),
                ObservationRecord.status.in_(["succeeded", "duplicate"]),
            )
            .subquery()
        )
        query = select(ObservationRecord).join(ranked, ranked.c.id == ObservationRecord.id).where(ranked.c.rank == 1)
        return {record.camera_id: record for record in self.session.scalars(query)}

    def add_skipped_observation(self, run_id: UUID, camera: Camera, observed_at: datetime) -> ObservationRecord:
        record = ObservationRecord(
            run_id=run_id,
            camera_id=camera.camera_id,
            observed_at=observed_at,
            status="skipped_not_up",
            error_code="camera_not_up",
            error_message=f"Upstream status is {camera.status!r}",
        )
        self.session.add(record)
        self.session.flush()
        return record

    def add_fetch_error(self, run_id: UUID, snapshot: Snapshot, observed_at: datetime) -> ObservationRecord:
        record = self._snapshot_record(run_id, snapshot, observed_at, "fetch_error")
        self.session.add(record)
        self.session.flush()
        return record

    def add_inference(
        self,
        run_id: UUID,
        snapshot: Snapshot,
        observed_at: datetime,
        result: InferenceResult,
        model_name: str,
        device: str,
        image_size: int,
        confidence: float,
        inference_signature: str,
        inference_config: dict[str, Any],
        original_path: str | None = None,
        annotated_path: str | None = None,
    ) -> ObservationRecord:
        counts = result.counts
        record = self._snapshot_record(run_id, snapshot, observed_at, "succeeded")
        record.inference_ms = result.inference_ms
        record.model_name = model_name
        record.model_device = device
        record.model_imgsz = image_size
        record.model_confidence = confidence
        record.inference_signature = inference_signature
        record.inference_config = inference_config
        record.preprocessing = result.preprocessing
        record.bicycle_count = counts["bicycle"]
        record.car_count = counts["car"]
        record.motorcycle_count = counts["motorcycle"]
        record.bus_count = counts["bus"]
        record.truck_count = counts["truck"]
        record.other_vehicle_count = counts["other_vehicle"]
        record.total_vehicle_count = counts["total_vehicle"]
        record.detections = [item.as_dict() for item in result.detections]
        record.original_photo_path = original_path
        record.annotated_photo_path = annotated_path
        self.session.add(record)
        self.session.flush()
        return record

    def add_duplicate(
        self,
        run_id: UUID,
        snapshot: Snapshot,
        observed_at: datetime,
        previous: ObservationRecord,
        original_path: str | None = None,
        annotated_path: str | None = None,
    ) -> ObservationRecord:
        record = self._snapshot_record(run_id, snapshot, observed_at, "duplicate")
        for field in (
            "model_name", "model_device", "model_imgsz", "model_confidence",
            "inference_signature", "inference_config", "preprocessing",
            "bicycle_count", "car_count", "motorcycle_count", "bus_count", "truck_count",
            "other_vehicle_count", "total_vehicle_count", "detections",
        ):
            setattr(record, field, getattr(previous, field))
        record.duplicate_of_id = previous.id
        record.original_photo_path = original_path
        record.annotated_photo_path = annotated_path
        self.session.add(record)
        self.session.flush()
        return record

    def add_inference_error(self, run_id: UUID, snapshot: Snapshot, observed_at: datetime, error: Exception) -> ObservationRecord:
        record = self._snapshot_record(run_id, snapshot, observed_at, "inference_error")
        record.error_code = "inference_error"
        record.error_message = str(error)[:2000]
        self.session.add(record)
        self.session.flush()
        return record

    def add_benchmark(self, **values: Any) -> BenchmarkRecord:
        record = BenchmarkRecord(**values)
        self.session.add(record)
        self.session.flush()
        return record

    @staticmethod
    def _snapshot_record(run_id: UUID, snapshot: Snapshot, observed_at: datetime, status: str) -> ObservationRecord:
        return ObservationRecord(
            run_id=run_id,
            camera_id=snapshot.camera.camera_id,
            observed_at=observed_at,
            status=status,
            http_status=snapshot.http_status,
            source_http_date=snapshot.source_http_date,
            checksum_sha256=snapshot.checksum_sha256,
            byte_size=snapshot.byte_size,
            content_type=snapshot.content_type,
            requested_width=snapshot.requested_width,
            requested_height=snapshot.requested_height,
            actual_width=snapshot.actual_width,
            actual_height=snapshot.actual_height,
            fetch_ms=snapshot.fetch_ms,
            error_code=snapshot.error_code,
            error_message=snapshot.error_message,
        )
