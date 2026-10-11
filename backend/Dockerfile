FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libpq5 curl \
      # WeasyPrint runtime deps (HTML+CSS -> PDF rendering)
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
      libcairo2 libgdk-pixbuf-2.0-0 libjpeg62-turbo libopenjp2-7 \
      shared-mime-info fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
