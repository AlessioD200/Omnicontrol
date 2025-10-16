#!/usr/bin/env bash
set -euo pipefail

# Registers or updates a camera device with the Omnicontrol backend via REST.
# Usage:
#   ./register_camera.sh \
#       --hub http://localhost:8000 \
#       --id c200 \
#       --name "Tapo C200" \
#       --ip 192.168.0.236 \
#       --username alessio \
#       --password ALEdpr11 \
#       --path stream1
#
# The script percent-encodes the password for embedding in the RTSP URL.

HUB="http://localhost:8000"
DEVICE_ID=""
DEVICE_NAME=""
DEVICE_IP=""
USERNAME=""
PASSWORD=""
RTSP_PATH="stream1"

urlencode() {
  python3 -c "import urllib.parse, sys; print(urllib.parse.quote(sys.argv[1]))" "$1"
}

usage() {
  grep '^#' "$0" | cut -c 4-
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hub)
      HUB="$2"; shift 2 ;;
    --id)
      DEVICE_ID="$2"; shift 2 ;;
    --name)
      DEVICE_NAME="$2"; shift 2 ;;
    --ip)
      DEVICE_IP="$2"; shift 2 ;;
    --username)
      USERNAME="$2"; shift 2 ;;
    --password)
      PASSWORD="$2"; shift 2 ;;
    --path)
      RTSP_PATH="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1 ;;
  esac
done

if [[ -z "$DEVICE_ID" || -z "$DEVICE_IP" || -z "$USERNAME" || -z "$PASSWORD" ]]; then
  echo "Missing required arguments." >&2
  usage
  exit 1
fi

ENCODED_PASS=$(urlencode "$PASSWORD")

PAYLOAD=$(cat <<JSON
{
  "id": "${DEVICE_ID}",
  "name": "${DEVICE_NAME:-$DEVICE_ID}",
  "ip": "${DEVICE_IP}",
  "type": "Camera",
  "metadata": {
    "rtsp_url": "rtsp://${USERNAME}:${ENCODED_PASS}@${DEVICE_IP}:554/${RTSP_PATH}",
    "snapshot_auth": {
      "user": "${USERNAME}",
      "pass": "${PASSWORD}"
    }
  }
}
JSON
)

echo "Registering camera ${DEVICE_ID} with hub ${HUB}"

curl -sS -X POST "${HUB}/api/tapo/devices" \
  -H "Content-Type: application/json" \
  -d "${PAYLOAD}" | jq .
