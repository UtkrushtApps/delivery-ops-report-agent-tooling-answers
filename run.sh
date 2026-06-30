#!/usr/bin/env bash
set -euo pipefail

cd /root/task

echo "[run] Installing Python dependencies..."
pip install -q -r requirements.txt

echo "[run] Starting datastores..."
docker compose up -d

echo "[run] Waiting for PostgreSQL health..."
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U delivery_app -d delivery_ops >/dev/null 2>&1; then
    echo "[run] PostgreSQL is ready."
    break
  fi
  sleep 2
  if [ "$i" -eq 30 ]; then echo "[run] PostgreSQL did not become ready" >&2; exit 1; fi
done

echo "[run] Waiting for Redis health..."
for i in $(seq 1 30); do
  if docker compose exec -T redis redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "[run] Redis is ready."
    break
  fi
  sleep 2
  if [ "$i" -eq 30 ]; then echo "[run] Redis did not become ready" >&2; exit 1; fi
done

echo "[run] Verifying seed data..."
COUNT=$(docker compose exec -T postgres psql -U delivery_app -d delivery_ops -tAc "SELECT COUNT(*) FROM customers;")
echo "[run] customers rows: ${COUNT}"
if [ "${COUNT}" -lt 5 ]; then echo "[run] Seed data missing" >&2; exit 1; fi

echo "[run] Verifying Redis round trip..."
docker compose exec -T redis redis-cli set __readiness__ ok >/dev/null
docker compose exec -T redis redis-cli get __readiness__ | grep -q ok
docker compose exec -T redis redis-cli del __readiness__ >/dev/null
echo "[run] Redis round trip OK."

echo "[run] Running key-free selfcheck..."
AGENT_TEST_MODE=1 python -m agent --selfcheck

echo "[run] READY: scaffold is up. Implement the stubs, then run: pytest -q"
exit 0

