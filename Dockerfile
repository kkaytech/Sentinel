# Sentinel application image (ADR-015). The frontend build stage is added in M1 step 6.
FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/sentinel

COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/src ./src
COPY backend/migrations ./migrations
COPY config ./config
ENV SENTINEL_CONFIG_DIR=/srv/sentinel/config
RUN pip install --no-cache-dir . \
    && useradd --system --uid 10001 sentinel

USER sentinel
EXPOSE 8000
CMD ["uvicorn", "sentinel.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
