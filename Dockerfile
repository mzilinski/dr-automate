# Basis-Image
FROM python:3.12-slim AS base

# Setze Umgebungsvariablen
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

WORKDIR /app

# Dependencies zuerst kopieren (besseres Caching)
COPY pyproject.toml .

# Dependencies installieren
RUN pip install --no-cache-dir pip --upgrade && \
    pip install --no-cache-dir flask flask-wtf flask-limiter gunicorn pypdf reportlab pillow pydantic

# Restliche Dateien kopieren
COPY . /app

# Verzeichnisse erstellen
RUN mkdir -p forms out

# Nicht-Root User für Sicherheit
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Port freigeben
EXPOSE 5000

# Health-Check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# Anwendung starten
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-", "app:app"]
