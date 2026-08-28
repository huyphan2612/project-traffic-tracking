-- Current PostgreSQL/PostGIS schema for the traffic-tracking application.
-- This file is forward-only and safe to run repeatedly.

DO $block$
BEGIN
    IF to_regtype('public.geometry') IS NULL THEN
        RAISE EXCEPTION 'PostGIS geometry type is unavailable; install PostGIS before applying this schema';
    END IF;
END
$block$;

CREATE SCHEMA IF NOT EXISTS traffic_tracking;

CREATE TABLE IF NOT EXISTS traffic_tracking.cameras (
    camera_id VARCHAR PRIMARY KEY,
    title TEXT,
    description TEXT,
    code VARCHAR,
    display_name TEXT,
    longitude DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    location public.geometry(Point, 4326),
    snapshot_url TEXT,
    camera_type VARCHAR,
    district VARCHAR,
    published BOOLEAN NOT NULL,
    management_unit TEXT,
    status VARCHAR,
    ptz BOOLEAN,
    angle DOUBLE PRECISION,
    video_url TEXT,
    video_streaming BOOLEAN,
    data_id VARCHAR,
    node_id VARCHAR,
    path TEXT,
    source_created_at TIMESTAMPTZ,
    source_modified_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    raw_metadata JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS traffic_tracking.runs (
    id UUID PRIMARY KEY,
    run_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    config JSONB NOT NULL,
    discovered_count INTEGER NOT NULL,
    up_count INTEGER NOT NULL,
    skipped_count INTEGER NOT NULL,
    succeeded_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS traffic_tracking.observations (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES traffic_tracking.runs(id),
    camera_id VARCHAR NOT NULL REFERENCES traffic_tracking.cameras(camera_id),
    observed_at TIMESTAMPTZ NOT NULL,
    status VARCHAR NOT NULL,
    http_status INTEGER,
    source_http_date TIMESTAMPTZ,
    checksum_sha256 VARCHAR(64),
    byte_size INTEGER,
    content_type VARCHAR,
    requested_width INTEGER,
    requested_height INTEGER,
    actual_width INTEGER,
    actual_height INTEGER,
    fetch_ms DOUBLE PRECISION,
    inference_ms DOUBLE PRECISION,
    model_name VARCHAR,
    model_device VARCHAR,
    model_imgsz INTEGER,
    model_confidence DOUBLE PRECISION,
    inference_signature VARCHAR(64),
    inference_config JSONB,
    preprocessing JSONB,
    bicycle_count INTEGER,
    car_count INTEGER,
    motorcycle_count INTEGER,
    bus_count INTEGER,
    truck_count INTEGER,
    other_vehicle_count INTEGER,
    total_vehicle_count INTEGER,
    detections JSONB,
    duplicate_of_id BIGINT REFERENCES traffic_tracking.observations(id),
    original_photo_path TEXT,
    annotated_photo_path TEXT,
    error_code VARCHAR,
    error_message TEXT,
    CONSTRAINT uq_observations_run_camera UNIQUE (run_id, camera_id)
);

-- These ALTER statements upgrade databases created before inference metadata
-- became part of the current schema. They are no-ops on new/current databases.
ALTER TABLE traffic_tracking.observations
    ADD COLUMN IF NOT EXISTS inference_signature VARCHAR(64);
ALTER TABLE traffic_tracking.observations
    ADD COLUMN IF NOT EXISTS inference_config JSONB;
ALTER TABLE traffic_tracking.observations
    ADD COLUMN IF NOT EXISTS preprocessing JSONB;

CREATE TABLE IF NOT EXISTS traffic_tracking.benchmarks (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES traffic_tracking.runs(id),
    scenario_type VARCHAR NOT NULL,
    model_name VARCHAR,
    device VARCHAR,
    image_size INTEGER,
    batch_size INTEGER,
    concurrency INTEGER,
    sample_camera_ids JSONB NOT NULL,
    host_info JSONB NOT NULL,
    metrics JSONB NOT NULL,
    status VARCHAR NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cameras_location
    ON traffic_tracking.cameras USING GIST (location);
CREATE INDEX IF NOT EXISTS ix_observations_camera_observed
    ON traffic_tracking.observations (camera_id, observed_at);
CREATE INDEX IF NOT EXISTS ix_observations_observed_brin
    ON traffic_tracking.observations USING BRIN (observed_at);
CREATE INDEX IF NOT EXISTS ix_traffic_tracking_observations_run_id
    ON traffic_tracking.observations (run_id);
CREATE INDEX IF NOT EXISTS ix_traffic_tracking_observations_status
    ON traffic_tracking.observations (status);
CREATE INDEX IF NOT EXISTS ix_traffic_tracking_benchmarks_run_id
    ON traffic_tracking.benchmarks (run_id);
