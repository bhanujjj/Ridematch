# Multi-stage build for the RideMatch match API.
#
# Stage 1 compiles wheels (confluent-kafka and pyarrow need a toolchain);
# stage 2 ships only the runtime, so the final image carries no compilers.
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential librdkafka-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        librdkafka1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Run as a non-root user.
RUN useradd --create-home --uid 10001 ridematch
WORKDIR /app

COPY --chown=ridematch:ridematch src/ ./src/
COPY --chown=ridematch:ridematch feature_repo/ ./feature_repo/
COPY --chown=ridematch:ridematch models/ ./models/

USER ridematch
EXPOSE 8000

# Container-internal service names, overridable at run time.
ENV S3_ENDPOINT_URL=http://minio:9000 \
    REDIS_HOST=redis \
    REDIS_PORT=6379 \
    KAFKA_BOOTSTRAP_SERVERS=kafka:29092 \
    MLFLOW_TRACKING_URI=http://mlflow:5000 \
    API_WORKERS=4

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=4 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["sh", "-c", "uvicorn src.match_api.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS}"]
