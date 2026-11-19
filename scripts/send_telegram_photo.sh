#!/usr/bin/env bash
# Send one image to the Hermes Telegram home channel (Bot API sendPhoto). Paper-trading report delivery only.
# Usage: send_telegram_photo.sh <absolute path to PNG> <caption>
# Reads TELEGRAM_BOT_TOKEN, TELEGRAM_HOME_CHANNEL, TELEGRAM_HOME_CHANNEL_THREAD_ID from $TELEGRAM_ENV_FILE
# (default /opt/data/.env) without echoing them. One upload attempt; exits 0 only when Telegram answers ok=true.
set -uo pipefail
png="${1:?usage: send_telegram_photo.sh <png> <caption>}"
caption="${2:-}"
env_file="${TELEGRAM_ENV_FILE:-/opt/data/.env}"

[ -f "$png" ] || { echo "send_telegram_photo: no such file: $png" >&2; exit 1; }
[ -f "$env_file" ] || { echo "send_telegram_photo: env file missing: $env_file" >&2; exit 1; }

key() { grep -m1 "^$1=" "$env_file" | cut -d= -f2- | tr -d '"' | tr -d "'"; }
token="$(key TELEGRAM_BOT_TOKEN)"
chat="$(key TELEGRAM_HOME_CHANNEL)"
thread="$(key TELEGRAM_HOME_CHANNEL_THREAD_ID)"
if [ -z "$token" ] || [ -z "$chat" ]; then
  echo "send_telegram_photo: TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL not set" >&2
  exit 1
fi

args=(-F "chat_id=${chat}" -F "caption=${caption:0:1000}" -F "photo=@${png}")
[ -n "$thread" ] && args+=(-F "message_thread_id=${thread}")

resp="$(curl -s -m 240 "${args[@]}" "https://api.telegram.org/bot${token}/sendPhoto")" || {
  echo "send_telegram_photo: upload failed (network or timeout)" >&2
  exit 1
}
if printf '%s' "$resp" | python3 -c 'import json,sys; sys.exit(0 if json.load(sys.stdin).get("ok") else 1)' 2>/dev/null; then
  mid="$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["message_id"])')"
  echo "send_telegram_photo: sent message_id=${mid}"
  exit 0
fi
echo "send_telegram_photo: Telegram rejected the upload" >&2
exit 1
