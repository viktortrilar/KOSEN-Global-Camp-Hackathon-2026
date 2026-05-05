#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

detected_ip="$(hostname -I | awk 'NF {print $1; exit}')"
LAN_IP="${LAN_IP:-$detected_ip}"

if [[ -z "${LAN_IP}" ]]; then
  echo "Could not detect a LAN IP. Set LAN_IP manually and retry." >&2
  exit 1
fi

export LAN_IP
export CV_STREAM_URL="${CV_STREAM_URL:-http://host.docker.internal:8001/stream}"

printf 'Using LAN_IP=%s\n' "$LAN_IP"
printf 'Starting Docker stack...\n'
sudo docker compose up -d --build

if command -v flutter >/dev/null 2>&1; then
  if [[ "${RUN_FLUTTER:-false}" == "true" ]]; then
    printf 'Starting Flutter with dart-defines...\n'
    flutter run "$@" \
      --dart-define=MQTT_BROKER_HOST="$LAN_IP" \
      --dart-define=API_BASE_URL="http://$LAN_IP:8000"
  else
    printf 'Flutter is installed. Run manually with:\n'
    printf '  flutter run %s --dart-define=MQTT_BROKER_HOST=%s --dart-define=API_BASE_URL=http://%s:8000\n' "$*" "$LAN_IP" "$LAN_IP"
  fi
else
  printf 'Flutter is not installed on this machine.\n'
fi
