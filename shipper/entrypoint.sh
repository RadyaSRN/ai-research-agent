#!/usr/bin/env bash
set -euo pipefail

: "${SHIPPER_SLEEP_SECONDS:=60}"
: "${SHIPPER_BATCH_LIMIT:=500}"
: "${SHIPPER_CHECKPOINT_DIR:=/data}"

mkdir -p "${SHIPPER_CHECKPOINT_DIR}"
export CHECKPOINT_FILE="${SHIPPER_CHECKPOINT_DIR}/.shipper_checkpoint"

echo "[shipper] starting loop: sleep=${SHIPPER_SLEEP_SECONDS}s, batch=${SHIPPER_BATCH_LIMIT}, checkpoint=${CHECKPOINT_FILE}"

while true; do
    echo "[shipper] tick $(date -u +%FT%TZ)"
    if ! n8n-shipper shipper --limit "${SHIPPER_BATCH_LIMIT}" --no-dry-run; then
        echo "[shipper] run failed, sleeping and retrying"
    fi
    sleep "${SHIPPER_SLEEP_SECONDS}"
done
