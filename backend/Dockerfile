FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Keep OCR in a separate layer so adding/updating system language packs does
# not invalidate the much larger Python dependency cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && if [ \"${SEED_DEMO_DATA:-false}\" = \"true\" ]; then python -m scripts.seed; fi && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
