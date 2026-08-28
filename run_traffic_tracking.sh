#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${TRAFFIC_TRACKING_ENV_FILE:-${SCRIPT_DIR}/.env}"
IMAGE="${TRAFFIC_TRACKING_IMAGE:-traffic-tracking:cpu}"
PHOTO_DIR="${SCRIPT_DIR}/photo"

if [[ ! -f "${ENV_FILE}" ]]; then
    echo "Missing environment file: ${ENV_FILE}" >&2
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is not available in PATH" >&2
    exit 1
fi

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
    echo "Docker image ${IMAGE} does not exist; build it before starting PM2" >&2
    exit 1
fi

mkdir -p "${PHOTO_DIR}"
cd "${SCRIPT_DIR}"

exec docker run \
    --rm \
    --init \
    --stop-timeout 60 \
    --env-file "${ENV_FILE}" \
    --env HOME=/tmp \
    --env YOLO_CONFIG_DIR=/tmp/Ultralytics \
    --add-host host.docker.internal:host-gateway \
    --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=${PHOTO_DIR},dst=/app/photo" \
    "${IMAGE}" run
