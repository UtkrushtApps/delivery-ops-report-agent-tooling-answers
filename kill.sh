#!/usr/bin/env bash
set -euo pipefail

echo "[kill] Starting cleanup..."
if [ -d /root/task ]; then
  cd /root/task
fi

echo "[kill] Bringing down docker-compose services..."
docker compose down --remove-orphans || true

echo "[kill] Removing named volumes..."
docker volume rm task_delivery_pg_data || true
docker volume rm task_delivery_redis_data || true
docker volume rm delivery_pg_data || true
docker volume rm delivery_redis_data || true

echo "[kill] Removing networks..."
docker network rm task_default || true

echo "[kill] No app image was built; skipping image removal."
docker rmi -f delivery-ops-report-agent-tooling || true

echo "[kill] Pruning docker system..."
docker system prune -a --volumes -f || true

echo "[kill] Removing /root/task..."
rm -rf /root/task || true

echo "Cleanup completed successfully!"

