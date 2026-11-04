FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     curl     ca-certificates     && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1002 mediatorgroup &&     useradd -u 1002 -g mediatorgroup -m -s /bin/bash mediatoruser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=mediatoruser:mediatorgroup . /app

RUN mkdir -p /data/checkpoints && \
    chown -R mediatoruser:mediatorgroup /data/checkpoints && \
    ln -sf /data/checkpoints/sync_checkpoint.json /app/sync_checkpoint.json

USER mediatoruser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3     CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
