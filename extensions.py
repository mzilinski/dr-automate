"""Flask-Erweiterungen, die App und Blueprints gemeinsam nutzen (vermeidet
Import-Zyklen zwischen app.py und api_v1.py)."""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# In-Memory reicht: gunicorn laeuft mit genau einem Worker (Dockerfile).
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")
