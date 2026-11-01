# Single-image container for StudyCoach + its project-owned PowerContext.
#
# The app and PowerContext still run as two processes (same order as the
# one-click scripts): the app must answer /health before PowerContext starts,
# because PowerContext probes the embedding endpoint at startup.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8090 \
    DATA_DIR=/data \
    SEEKDB_PATH=/data/seekdb \
    MODEL_DIR=/data/models

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker ./docker

EXPOSE 8090
CMD ["sh", "docker/entrypoint.sh"]
