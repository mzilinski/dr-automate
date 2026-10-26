"""Persönliche API-Keys für /api/v1 (plan-api-v1.md, Abschnitt 3).

Token-Format ``dra_<prefix>_<secret>``: ``prefix`` (12 Hex-Zeichen) dient zum
Nachschlagen und steht im Klartext in der DB, gespeichert wird sonst nur der
SHA-256 des vollständigen Tokens. Der Token hat volle Entropie (32 Byte), ein
langsamer Passwort-Hash ist daher nicht nötig.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy import select

from db import SessionLocal
from models_db import ApiKey, User

SCOPES = ("reisen:read", "reisen:write", "berechnen", "extract")
# `extract` schickt Text an DeepSeek (China) — nur auf ausdrücklichen Wunsch.
DEFAULT_SCOPES = ("reisen:read", "reisen:write", "berechnen")
LAUFZEITEN_TAGE = (30, 90, 365)
MAX_AKTIVE_KEYS = 5
# So lange gelten Keys nach dem letzten Web-Login mit API-Gruppe.
BERECHTIGUNG_DAUER = timedelta(days=90)
BERECHTIGUNG_GRANULARITAET = timedelta(minutes=15)
LAST_USED_GRANULARITAET = timedelta(minutes=1)

_TOKEN_RE = re.compile(r"^dra_([0-9a-f]{12})_([A-Za-z0-9_-]{20,})$")


class ApiKeyError(ValueError):
    """Ungültige Eingabe beim Anlegen (Text für die Profil-Seite)."""


def api_groups() -> set[str]:
    """Authelia-Gruppen, deren Mitglieder API-Keys anlegen und nutzen dürfen."""
    raw = current_app.config.get("API_GROUPS")
    if raw is None:
        raw = os.environ.get("DR_AUTOMATE_API_GROUPS", "admins")
    return {g.strip() for g in raw.split(",") if g.strip()}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_key(user_id: int, name: str, scopes: list[str], laufzeit_tage: int) -> tuple[ApiKey, str]:
    """Legt einen Key an und gibt (Key, Klartext-Token) zurück. Der Token
    ist danach nicht mehr rekonstruierbar."""
    name = (name or "").strip()[:100]
    if not name:
        raise ApiKeyError("Bitte einen Namen für den Key angeben.")
    scopes = [s for s in SCOPES if s in set(scopes or [])]
    if not scopes:
        raise ApiKeyError("Bitte mindestens eine Berechtigung auswählen.")
    if laufzeit_tage not in LAUFZEITEN_TAGE:
        raise ApiKeyError("Ungültige Laufzeit.")
    now = datetime.utcnow()
    with SessionLocal() as s:
        aktiv = s.scalars(
            select(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None), ApiKey.expires_at > now)
        ).all()
        if len(aktiv) >= MAX_AKTIVE_KEYS:
            raise ApiKeyError(f"Höchstens {MAX_AKTIVE_KEYS} aktive Keys — bitte zuerst einen widerrufen.")
        prefix = secrets.token_hex(6)
        token = f"dra_{prefix}_{secrets.token_urlsafe(32)}"
        key = ApiKey(
            user_id=user_id,
            name=name,
            prefix=prefix,
            secret_hash=_hash(token),
            scopes=scopes,
            expires_at=now + timedelta(days=laufzeit_tage),
        )
        s.add(key)
        s.commit()
        s.refresh(key)
        s.expunge(key)
    return key, token


def list_keys(user_id: int) -> list[ApiKey]:
    with SessionLocal() as s:
        keys = s.scalars(select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())).all()
        s.expunge_all()
        return list(keys)


def revoke_key(user_id: int, key_id: int) -> bool:
    with SessionLocal() as s:
        key = s.scalar(select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id))
        if key is None or key.revoked_at is not None:
            return False
        key.revoked_at = datetime.utcnow()
        s.commit()
        return True


def revoke_all(user_id: int) -> int:
    """Offboarding: alle aktiven Keys eines Users widerrufen."""
    now = datetime.utcnow()
    with SessionLocal() as s:
        keys = s.scalars(select(ApiKey).where(ApiKey.user_id == user_id, ApiKey.revoked_at.is_(None))).all()
        for k in keys:
            k.revoked_at = now
        s.commit()
        return len(keys)


def prefix_of(token: str) -> str | None:
    """Präfix aus einem Token (für Rate-Limits, ohne DB-Zugriff)."""
    m = _TOKEN_RE.match(token or "")
    return m.group(1) if m else None


def authenticate(token: str) -> tuple[User, ApiKey] | None:
    """Prüft einen Bearer-Token. None bei unbekannt, falsch, widerrufen,
    abgelaufen oder wenn der Eigentümer seine API-Berechtigung verloren hat."""
    prefix = prefix_of(token)
    if prefix is None:
        return None
    now = datetime.utcnow()
    with SessionLocal() as s:
        key = s.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
        if key is None or not hmac.compare_digest(key.secret_hash, _hash(token)):
            return None
        if key.revoked_at is not None or key.expires_at <= now:
            return None
        user = s.get(User, key.user_id)
        if user is None or user.api_berechtigt_bis is None or user.api_berechtigt_bis <= now:
            return None
        if key.last_used_at is None or now - key.last_used_at > LAST_USED_GRANULARITAET:
            key.last_used_at = now
            s.commit()
            s.refresh(key)
            s.refresh(user)
        s.expunge(key)
        s.expunge(user)
        return user, key


def _cli() -> int:
    """Offboarding: ``python api_keys.py widerrufen <remote_user>`` bzw. ``liste <remote_user>``."""
    import sys

    if len(sys.argv) != 3 or sys.argv[1] not in ("widerrufen", "liste"):
        print("Aufruf: python api_keys.py widerrufen|liste <remote_user>")
        return 2
    with SessionLocal() as s:
        user = s.scalar(select(User).where(User.remote_user == sys.argv[2]))
    if user is None:
        print(f"User {sys.argv[2]!r} nicht gefunden.")
        return 1
    if sys.argv[1] == "widerrufen":
        print(f"{revoke_all(user.id)} Key(s) von {sys.argv[2]} widerrufen.")
    else:
        for k in list_keys(user.id):
            status = "widerrufen" if k.revoked_at else f"gültig bis {k.expires_at:%d.%m.%Y}"
            print(f"dra_{k.prefix}_…  {k.name}  {','.join(k.scopes)}  {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
