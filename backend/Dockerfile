# syntax=docker/dockerfile:1
# Sevaro Pulse API: FastAPI + SQLite. Build from backend/:  docker build -t sevaro-pulse/backend .

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

# --- Dependencies in their own layer so code changes don't reinstall OR-Tools.
FROM base AS deps
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install -r requirements.txt

# --- Runtime image
FROM base AS runtime
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app
COPY --from=deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    APP_ENV=production

COPY app ./app
COPY sample_data ./sample_data

# SQLite lives in /app/data (the default DATABASE_URL resolves there). Mount a volume on it
# so the dataset, event log, simulation clock and workflow state survive restarts.
RUN mkdir -p data/raw && chown -R app:app data
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# One worker on purpose: SQLite has a single writer, and the analysis caches and SSE
# version stream are per-process. FastAPI's thread pool still serves requests concurrently.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-graceful-shutdown", "10"]
