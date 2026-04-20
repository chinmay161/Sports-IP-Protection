# Sports IP Protection

Basic setup and run instructions for the current monorepo, plus the proposed target file structure.

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm 9+

## Quick Start

### 1. Backend (FastAPI)

From the repository root:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
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
