#!/bin/sh
  set -eu

  echo "[entrypoint] starting codex2api on Hugging Face"

  # ---- defaults ----
  export CODEX_PORT="${CODEX_PORT:-7860}"
  export TZ="${TZ:-Asia/Shanghai}"

  # codex2api standard mode
  export DATABASE_DRIVER="${DATABASE_DRIVER:-postgres}"
  export CACHE_DRIVER="${CACHE_DRIVER:-redis}"

  # Supabase Postgres usually needs SSL
  export DATABASE_SSLMODE="${DATABASE_SSLMODE:-require}"

  # local redis inside same container
  export REDIS_ADDR="${REDIS_ADDR:-127.0.0.1:6379}"
  export REDIS_DB="${REDIS_DB:-0}"

  # ---- required vars ----
  : "${DATABASE_HOST:?DATABASE_HOST is required}"
  : "${DATABASE_PORT:?DATABASE_PORT is required}"
  : "${DATABASE_USER:?DATABASE_USER is required}"
  : "${DATABASE_PASSWORD:?DATABASE_PASSWORD is required}"
  : "${DATABASE_NAME:?DATABASE_NAME is required}"

  # ---- start local redis ----
  if [ -n "${REDIS_PASSWORD:-}" ]; then
    echo "[entrypoint] starting local redis with password"
    redis-server \
      --daemonize yes \
      --bind 127.0.0.1 \
      --port 6379 \
      --save "" \
      --appendonly no \
      --loglevel warning \
      --requirepass "${REDIS_PASSWORD}"
  else
    echo "[entrypoint] starting local redis without password"
    redis-server \
      --daemonize yes \
      --bind 127.0.0.1 \
      --port 6379 \
      --save "" \
      --appendonly no \
      --loglevel warning
  fi

  # ---- wait for redis ----
  i=0
  until [ "$i" -ge 20 ]
  do
    if [ -n "${REDIS_PASSWORD:-}" ]; then
      if redis-cli -h 127.0.0.1 -p 6379 -a "${REDIS_PASSWORD}" ping >/dev/null 2>&1; then
        break
      fi
    else
      if redis-cli -h 127.0.0.1 -p 6379 ping >/dev/null 2>&1; then
        break
      fi
    fi
    i=$((i+1))
    sleep 1
  done

  echo "[entrypoint] redis ready"
  echo "[entrypoint] DATABASE_HOST=${DATABASE_HOST}"
  echo "[entrypoint] DATABASE_PORT=${DATABASE_PORT}"
  echo "[entrypoint] DATABASE_NAME=${DATABASE_NAME}"
  echo "[entrypoint] REDIS_ADDR=${REDIS_ADDR}"
  echo "[entrypoint] CODEX_PORT=${CODEX_PORT}"

  exec /usr/local/bin/codex2api