# syntax=docker/dockerfile:1

FROM pytorch/pytorch:2.13.0-cuda12.6-cudnn9-runtime AS gpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

ARG YOLO_MODEL=yolo26m.pt
ENV YOLO_MODEL=${YOLO_MODEL}
RUN python -c 'import os; from ultralytics import YOLO; YOLO(os.environ["YOLO_MODEL"])'

COPY main.py ./
COPY traffic_tracking/ ./traffic_tracking/

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/photo \
    && chown -R app:app /app

USER app

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]


FROM python:3.10-slim-bookworm AS cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python -m pip install --no-cache-dir \
        torch==2.13.0+cpu torchvision==0.28.0+cpu \
        --extra-index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r requirements.txt

ARG YOLO_MODEL=yolo26m.pt
ENV YOLO_MODEL=${YOLO_MODEL}
RUN python -c 'import os; from ultralytics import YOLO; YOLO(os.environ["YOLO_MODEL"])'

COPY main.py ./
COPY traffic_tracking/ ./traffic_tracking/

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/photo \
    && chown -R app:app /app

USER app

ENTRYPOINT ["python", "main.py"]
CMD ["--help"]
