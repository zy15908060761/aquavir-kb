FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ncbi-blast+ \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only what's needed at runtime
COPY backend.py .
COPY api_models.py .
COPY db_utils.py .
COPY sync_runtime.py .
COPY templates/ templates/
COPY public_assets/ public_assets/

RUN mkdir -p /app/sequences /app/downloads /app/blastdb

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "backend:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-keep-alive", "65"]
