# Shared image for the Python services (ingestion collector + one-shot migrate).
# Build context is the repo root: docker build -f infra/python.Dockerfile .
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# Install ingestion (with its deps), then analytics without re-resolving the
# local bellwether-ingestion dependency from PyPI, then analytics' runtime deps.
COPY ingestion ./ingestion
COPY analytics ./analytics
RUN pip install ./ingestion \
 && pip install --no-deps ./analytics \
 && pip install "typer>=0.12" "rich>=13.7" "python-dateutil>=2.9"

CMD ["python", "-m", "bellwether_ingestion.collector"]
