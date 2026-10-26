# Basis-Image
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000

WORKDIR /app

# uv nur als Build-Werkzeug: exportiert die im uv.lock fixierten Versionen
# (mit Hashes) — sonst loeste `pip install .` bei jedem Rebuild nur gegen die
# `>=`-Grenzen auf und Produktion lief mit anderen Paketstaenden als die Tests.
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv

# Dependency-Manifest zuerst kopieren für Layer-Caching
COPY pyproject.toml uv.lock README.md ./

# Runtime-Dependencies exakt nach uv.lock installieren
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt -o /tmp/requirements.txt && \
    pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Restliche Dateien kopieren; das Projekt selbst nur fuer die Paket-Metadaten
# (Version in /health und im Footer) installieren.
COPY . /app
RUN pip install --no-cache-dir --no-deps . && rm -rf build *.egg-info

# Verzeichnisse erstellen.
# - forms/ enthaelt die PDF-Vorlagen (read-only, im Image)
# - out/   ist legacy-Scratch
# - data/  ist persistent: SQLite-DB + verschluesselte JSONs + generierte PDFs.
#          MUSS bei Production als Volume gemountet werden, sonst Restart =
#          Datenverlust. Siehe paperless_etal/dr-automate.yml.
RUN mkdir -p forms out data

# Nicht-Root User für Sicherheit
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# Health-Check honoriert die PORT-Env-Var
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"5000\")}/health')" || exit 1

# Beim Start: Alembic-Migration laufen lassen, dann gunicorn.
# `alembic upgrade head` ist idempotent (schema_version-Tabelle), kein Risiko
# bei wiederholten Restarts. JSON-Form mit explizitem 'sh -c', damit
# ${PORT}-Expansion + && funktionieren. 'exec gunicorn' sorgt dafuer, dass
# gunicorn PID 1 wird und SIGTERM vom Container-Stop direkt erreicht — sonst
# bliebe die sh dazwischen und der Stop dauert bis zum Timeout.
# 1 Worker: flask-limiter mit storage_uri=memory:// arbeitet pro-Worker.
# Bei mehreren Workern wuerden Rate-Limits multipliziert — solange kein
# Redis im Stack ist, ist 1 Worker die saubere Loesung.
CMD ["sh", "-c", "alembic upgrade head && exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --access-logfile - app:app"]
