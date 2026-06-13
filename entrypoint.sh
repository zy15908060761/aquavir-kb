#!/usr/bin/env bash
# AquaVir-KB Uvicorn entrypoint — tuned for 2C/4GB cloud hosts
set -e

WORKERS=${UVICORN_WORKERS:-1}
THREADS=${UVICORN_THREADS:-4}
MAX_CONN=${UVICORN_MAX_CONNECTIONS:-1000}
KEEP_ALIVE=${UVICORN_TIMEOUT_KEEP_ALIVE:-5}
LIMIT_CONCURRENCY=${UVICORN_LIMIT_CONCURRENCY:-100}

echo "[entrypoint] Starting Uvicorn: workers=$WORKERS threads=$THREADS keep-alive=$KEEP_ALIVE limit-concurrency=$LIMIT_CONCURRENCY"

exec uvicorn backend:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "$WORKERS" \
    --loop uvloop \
    --http h11 \
    --timeout-keep-alive "$KEEP_ALIVE" \
    --limit-concurrency "$LIMIT_CONCURRENCY"
