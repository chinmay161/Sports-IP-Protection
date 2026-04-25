# Sports IP Protection

Basic setup and run instructions for the current monorepo, plus the proposed target file structure.

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm 9+

## Quick Start

### 1. Backend (FastAPI + Celery + Milvus)

Copy the repo-level example env file and adjust values for your machine:

```powershell
Copy-Item .env.example .env
```

The backend reads these environment variables:

- `DATABASE_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`
- `MILVUS_URI`
- `MILVUS_TOKEN`
- `MILVUS_COLLECTION_NAME`
- `MILVUS_REQUIRED`
- `TEMP_ROOT`
- `CRAWLER_MODE`
- `CRAWLER_DISCOVERY_MODE`
- `CRAWLER_WATCHLIST_URLS`
- `VISUAL_CRAWL_MAX_PAGES`
- `VISUAL_CRAWL_MAX_IMAGES`
- `VISUAL_CRAWL_MAX_CANDIDATES`
- `VISUAL_PHASH_THRESHOLD`

Local defaults in `.env.example` use SQLite for quick startup. For a Postgres setup, replace `DATABASE_URL` with an async SQLAlchemy DSN such as `postgresql+asyncpg://postgres:postgres@localhost:5432/sports_ip`.

The crawler defaults to generated mock candidates with `CRAWLER_MODE=mock`. Set `CRAWLER_MODE=real` to enable live discovery and downloads; YouTube discovery and most downloads use `yt-dlp`, while web/TikTok/Telegram discovery uses search-result URLs that feed into the same download path.

Real mode can also use visual discovery with `CRAWLER_DISCOVERY_MODE=visual` or `hybrid`. Visual discovery indexes protected asset frames during ingest, crawls configured watchlists plus web result pages, compares thumbnails/previews with pHash and optional local CLIP embeddings, then forwards only likely visual candidates to the matcher.

Required local services:

- `ffmpeg` installed and available on `PATH`
- Redis running for Celery broker/result storage
- Milvus running at `MILVUS_URI` for fingerprint operations

If you want the API to boot without Milvus during local development, leave `MILVUS_REQUIRED=false`. In that mode `/health` reports a degraded state until Milvus is reachable.

You can start Redis and a complete Milvus stack from the repository root with:

```powershell
docker compose up -d
```

This compose file includes `redis`, `etcd`, `minio`, and `milvus`, which avoids the Milvus crash caused by missing object storage.

Run the API from the repository root:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run the Celery worker in a second terminal:

```powershell
cd backend
.venv\Scripts\activate
celery -A app.core.celery.celery_app worker --loglevel=info
```

On Windows, the backend config defaults Celery to the `solo` worker pool because Celery's default prefork pool is not supported reliably there.

Run backend tests:

```powershell
cd backend
.venv\Scripts\activate
pytest -q tests/test_fingerprint.py
```

Backend URLs:

- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs

### 2. Frontend (React + Vite + Tailwind CSS)

From the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL:

- App: http://localhost:5173

### 3. Build Frontend

```powershell
cd frontend
npm run build
```

## Proposed Project Structure (Documentation Only)

Note: This is the intended architecture reference. These folders/files are not auto-created by this README.

```text
sports-ip-protection/
|
|-- backend/                      # FastAPI
|   |-- app/
|   |   |-- api/                  # Route modules
|   |   |   |-- v1/
|   |   |   |   |-- auth.py
|   |   |   |   |-- assets.py
|   |   |   |   |-- alerts.py
|   |   |   |   |-- analytics.py
|   |   |   |   |-- detection.py
|   |   |   |   `-- cases.py
|   |   |
|   |   |-- core/                 # Config, security
|   |   |   |-- config.py
|   |   |   |-- security.py
|   |   |   `-- logging.py
|   |   |
|   |   |-- services/             # Core logic (your main work)
|   |   |   |-- fingerprint/
|   |   |   |-- watermark/
|   |   |   |-- crawler/
|   |   |   |-- scene_match/
|   |   |   |-- propagation_graph/
|   |   |   |-- evidence/
|   |   |   `-- lookalike/
|   |   |
|   |   |-- models/               # DB models (SQLAlchemy)
|   |   |-- schemas/              # Pydantic schemas
|   |   |-- workers/              # Background jobs (Celery/BullMQ bridge)
|   |   |-- db/                   # DB setup
|   |   |   |-- session.py
|   |   |   `-- base.py
|   |   |
|   |   `-- main.py               # FastAPI entry
|   |
|   |-- tests/
|   |-- requirements.txt
|   `-- Dockerfile
|
|-- frontend/                     # React + Vite + Tailwind
|   |-- src/
|   |   |-- components/           # Reusable UI
|   |   |-- pages/                # Route pages
|   |   |   |-- Dashboard.jsx
|   |   |   |-- Alerts.jsx
|   |   |   |-- Assets.jsx
|   |   |   |-- Cases.jsx
|   |   |   `-- Analytics.jsx
|   |   |
|   |   |-- features/             # Feature-based modules
|   |   |   |-- detection/
|   |   |   |-- alerts/
|   |   |   |-- heatmap/
|   |   |   `-- lookalike/
|   |   |
|   |   |-- hooks/
|   |   |-- services/             # API calls
|   |   |-- store/                # Zustand/Redux
|   |   |-- utils/
|   |   |-- App.jsx
|   |   `-- main.jsx
|   |
|   |-- index.html
|   |-- tailwind.config.js
|   `-- vite.config.js
|
|-- worker/                       # Async jobs (important for crawler, alerts)
|   |-- tasks/
|   |   |-- crawl_tasks.py
|   |   |-- detection_tasks.py
|   |   `-- alert_tasks.py
|   |-- celery_app.py
|   `-- requirements.txt
|
|-- shared/                       # Shared logic/constants
|   |-- constants/
|   |-- utils/
|   `-- types/
|
|-- infra/                        # DevOps / deployment
|   |-- docker-compose.yml
|   |-- nginx/
|   `-- terraform/ (optional)
|
|-- docs/
|   |-- architecture.md
|   |-- api-spec.md
|   `-- roadmap.md
|
|-- .env.example
|-- README.md
`-- package.json (optional root scripts)
```
