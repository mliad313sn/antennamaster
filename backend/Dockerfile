# AntennaMaster backend — FastAPI + NumPy/SciPy/pyproj RF engine.
# Multi-stage: build deps into an isolated venv, then copy only that venv and
# the app into a slim runtime image (no compilers, no caches shipped).

# ---------------------------------------------------------------- builder
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# All runtime deps (numpy, scipy, pyproj, Pillow, reportlab …) ship manylinux
# wheels for cp311, so no compiler toolchain is required.  If you add a
# dependency that must build from source, install build-essential here.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# ---------------------------------------------------------------- runtime
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    AM_DATA_DIR=/data \
    AM_CORS_ORIGINS=* \
    UVICORN_WORKERS=2
# Non-root runtime user; /data is the single writable volume (SQLite DB, DEM
# tile cache, uploaded DXFs, rendered results).
RUN groupadd -r app && useradd -r -g app -d /app app \
    && mkdir -p /data && chown app:app /data
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY app ./app
COPY benchmarks ./benchmarks
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && chown -R app:app /app
USER app
EXPOSE 8000
VOLUME ["/data"]
# Liveness probe against the app's own health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)"]
# JSON exec-form entrypoint; the wrapper expands ${UVICORN_WORKERS} at start.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
