# ==============================================================================
# IMNID Hub - Backend Multi-Stage Dockerfile (Headless Python 3.12 Slim)
# ==============================================================================

# Stage 1: Build & Dependencies
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends     build-essential     curl     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=120 --retries 5 --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     curl     ca-certificates     && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root user
RUN groupadd -g 1001 appgroup &&     useradd -u 1001 -g appgroup -m -s /bin/bash appuser

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY --chown=appuser:appgroup . /app/backend

# Create data directories with appropriate permissions
RUN mkdir -p /data/uploads /data/exports /data/logs /data/checkpoints /data/db &&     chown -R appuser:appgroup /data /app

ENV PYTHONUNBUFFERED=1     PYTHONDONTWRITEBYTECODE=1     PYTHONPATH=/app     DATA_DIR=/data

USER appuser

EXPOSE 8085

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3     CMD curl -f http://localhost:8085/api/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8085"]
