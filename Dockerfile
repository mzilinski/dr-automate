# Basis-Image
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

WORKDIR /app

# Dependency-Manifest zuerst kopieren für Layer-Caching
COPY pyproject.toml uv.lock README.md ./

# Runtime-Dependencies aus pyproject.toml installieren
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Restliche Dateien kopieren
COPY . /app

# Verzeichnisse erstellen
RUN mkdir -p forms out

# Nicht-Root User für Sicherheit
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# Health-Check honoriert die PORT-Env-Var
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"5000\")}/health')" || exit 1

# Shell-Form, damit ${PORT} expandiert wird (override via `docker run -e PORT=...`)
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --access-logfile - app:app
