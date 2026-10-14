FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOCK_DATA_DIR=/app/data

WORKDIR /app

COPY requirements.txt requirements-dev.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY assets ./assets

FROM base AS runtime

RUN useradd --system --uid 10001 --create-home app \
    && mkdir -p /app/data \
    && chown app:app /app/data
USER app

EXPOSE 8000

CMD ["sh", "-c", "python -m app.init_db && python -m app.enterprise.seed_demo && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]

FROM base AS test

RUN python -m pip install --no-cache-dir -r requirements-dev.txt
COPY tests ./tests
COPY pytest.ini ./pytest.ini
COPY scripts ./scripts
COPY docs ./docs
COPY workflows ./workflows
CMD ["python", "-m", "pytest", "-q"]
