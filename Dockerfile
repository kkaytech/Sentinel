# Sentinel application image (ADR-015): the API serving the built React frontend.

# ---- frontend build ----------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- application -------------------------------------------------------------------------
FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/sentinel

COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/src ./src
COPY backend/migrations ./migrations
COPY config ./config
COPY --from=web /web/dist ./frontend
ENV SENTINEL_CONFIG_DIR=/srv/sentinel/config \
    SENTINEL_FRONTEND_DIR=/srv/sentinel/frontend
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 sentinel

USER sentinel
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=6 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "sentinel.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
