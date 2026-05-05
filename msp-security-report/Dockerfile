FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# WeasyPrint runtime dependencies (Pango, Cairo, GDK-PixBuf, fonts, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libffi-dev \
        shared-mime-info \
        fonts-liberation \
        fonts-dejavu-core \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/data /app/app/static/uploads /app/app/static/uploads/reports

EXPOSE 8000

# Run Alembic migrations before starting the API. This keeps the schema in sync
# whenever the image is rebuilt against an existing database volume.
CMD ["sh", "-c", "python -m app.scripts.run_migrations && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
