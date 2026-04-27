#!/bin/bash
# Container entrypoint — sets up demo state, then starts uvicorn.
#
# Why this exists: App Runner is stateless. Every container restart wipes the
# filesystem, including our SQLite DB. We re-seed every boot so the demo URL
# always shows consistent state. Idempotent — safe to run multiple times.

set -e

cd /app/backend

DEMO_ASSET_ID="00000000-0000-0000-0000-0000000000a1"

echo ">>> [entrypoint] initializing database tables"
python -c "
import asyncio
from app.db.session import init_db
asyncio.run(init_db())
"

echo ">>> [entrypoint] starting uvicorn in background to seed via simulator"
uvicorn app.main:app --host 127.0.0.1 --port 8001 &
UVICORN_PID=$!

# Wait for uvicorn to be ready
for i in {1..30}; do
    if curl -sf http://127.0.0.1:8001/health > /dev/null; then
        echo ">>> [entrypoint] uvicorn ready"
        break
    fi
    echo "    waiting for uvicorn ($i/30)..."
    sleep 1
done

echo ">>> [entrypoint] firing alert simulator to create demo asset"
for i in 1 2 3; do
    curl -sf -X POST http://127.0.0.1:8001/alerts/_simulate > /dev/null || true
done

# Give the simulator a moment to settle
sleep 2

echo ">>> [entrypoint] seeding 12 match rows"
python seed_matches.py $DEMO_ASSET_ID 12 || echo "WARN: seed_matches failed"

echo ">>> [entrypoint] seeding 12 visual candidates"
python seed_visual_candidates.py $DEMO_ASSET_ID 12 || echo "WARN: seed_visual_candidates failed"

echo ">>> [entrypoint] killing temporary uvicorn"
kill $UVICORN_PID 2>/dev/null || true
wait $UVICORN_PID 2>/dev/null || true

echo ">>> [entrypoint] starting production uvicorn on port ${PORT:-8080}"
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1