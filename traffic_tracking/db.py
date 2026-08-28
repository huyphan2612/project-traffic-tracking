from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from typing import Iterator
from uuid import UUID

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


SCHEMA = "traffic_tracking"


class Base(DeclarativeBase):
    pass


class CameraRecord(Base):
    __tablename__ = "cameras"
    __table_args__ = ({"schema": SCHEMA},)

    camera_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    code: Mapped[str | None] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(Text)
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    location: Mapped[object | None] = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    snapshot_url: Mapped[str | None] = mapped_column(Text)
    camera_type: Mapped[str | None] = mapped_column(String)
    district: Mapped[str | None] = mapped_column(String)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    management_unit: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String)
    ptz: Mapped[bool | None] = mapped_column(Boolean)
    angle: Mapped[float | None] = mapped_column(Float)
    video_url: Mapped[str | None] = mapped_column(Text)
    video_streaming: Mapped[bool | None] = mapped_column(Boolean)
    data_id: Mapped[str | None] = mapped_column(String)
    node_id: Mapped[str | None] = mapped_column(String)
    path: Mapped[str | None] = mapped_column(Text)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False)


class RunRecord(Base):
    __tablename__ = "runs"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    up_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class ObservationRecord(Base):
    __tablename__ = "observations"
    __table_args__ = (
        UniqueConstraint("run_id", "camera_id", name="uq_observations_run_camera"),
        Index("ix_observations_camera_observed", "camera_id", "observed_at"),
        Index("ix_observations_observed_brin", "observed_at", postgresql_using="brin"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey(f"{SCHEMA}.runs.id"), nullable=False, index=True)
    camera_id: Mapped[str] = mapped_column(String, ForeignKey(f"{SCHEMA}.cameras.camera_id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    http_status: Mapped[int | None] = mapped_column(Integer)
    source_http_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    byte_size: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String)
    requested_width: Mapped[int | None] = mapped_column(Integer)
    requested_height: Mapped[int | None] = mapped_column(Integer)
    actual_width: Mapped[int | None] = mapped_column(Integer)
    actual_height: Mapped[int | None] = mapped_column(Integer)
    fetch_ms: Mapped[float | None] = mapped_column(Float)
    inference_ms: Mapped[float | None] = mapped_column(Float)
    model_name: Mapped[str | None] = mapped_column(String)
    model_device: Mapped[str | None] = mapped_column(String)
    model_imgsz: Mapped[int | None] = mapped_column(Integer)
    model_confidence: Mapped[float | None] = mapped_column(Float)
    inference_signature: Mapped[str | None] = mapped_column(String(64))
    inference_config: Mapped[dict | None] = mapped_column(JSONB)
    preprocessing: Mapped[dict | None] = mapped_column(JSONB)
    bicycle_count: Mapped[int | None] = mapped_column(Integer)
    car_count: Mapped[int | None] = mapped_column(Integer)
    motorcycle_count: Mapped[int | None] = mapped_column(Integer)
    bus_count: Mapped[int | None] = mapped_column(Integer)
    truck_count: Mapped[int | None] = mapped_column(Integer)
    other_vehicle_count: Mapped[int | None] = mapped_column(Integer)
    total_vehicle_count: Mapped[int | None] = mapped_column(Integer)
    detections: Mapped[list | None] = mapped_column(JSONB)
    duplicate_of_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey(f"{SCHEMA}.observations.id"))
    original_photo_path: Mapped[str | None] = mapped_column(Text)
    annotated_photo_path: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String)
    error_message: Mapped[str | None] = mapped_column(Text)


class BenchmarkRecord(Base):
    __tablename__ = "benchmarks"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey(f"{SCHEMA}.runs.id"), nullable=False, index=True)
    scenario_type: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str | None] = mapped_column(String)
    device: Mapped[str | None] = mapped_column(String)
    image_size: Mapped[int | None] = mapped_column(Integer)
    batch_size: Mapped[int | None] = mapped_column(Integer)
    concurrency: Mapped[int | None] = mapped_column(Integer)
    sample_camera_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    host_info: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def make_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


@contextmanager
def session_scope(engine) -> Iterator[Session]:
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
