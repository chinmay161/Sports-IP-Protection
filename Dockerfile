#
# Multi-stage build for Sports IP Protection.
#
# Stage 1: builds the React frontend with Vite, producing static assets in /dist.
# Stage 2: Python image that runs FastAPI and serves the built frontend at /.
#
# Both API and frontend served on a single port (8080) — App Runner expects this.

# ---------------------------------------------------------------------------
# Stage 1 — frontend build
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend-build

WORKDIR /frontend

# Copy package manifests first to leverage layer caching
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

# Copy the rest and build
COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2 — backend + frontend serving
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# System packages we actually need:
# - ffmpeg for visual frame extraction
# - libpq for any future Postgres support (cheap to include)
# - tini for proper PID 1 signal handling
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libpq5 \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source
COPY backend/ /app/backend/

# Copy built frontend from stage 1 into a known location the backend serves from
COPY --from=frontend-build /frontend/dist /app/frontend_dist

# Copy entrypoint and seed scripts
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# App Runner sends traffic to whatever PORT we listen on
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AUTH_DISABLED=true \
    DATABASE_URL=sqlite+aiosqlite:////app/data/sports_ip.db \
    FRONTEND_DIST=/app/frontend_dist

# SQLite file lives in /app/data — created at container start
RUN mkdir -p /app/data

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/entrypoint.sh"]