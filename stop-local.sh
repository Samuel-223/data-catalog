#!/usr/bin/env bash
sudo fuser -k 8000/tcp 2>/dev/null || true
docker compose down 2>/dev/null || true
echo "端口 8000 已释放"
