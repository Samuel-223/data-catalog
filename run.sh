#!/usr/bin/env bash
cd "$(dirname "$0")"
source apienv/bin/activate
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
