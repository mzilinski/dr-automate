"""
Application-Level Encryption fuer DSGVO-sensible Felder.

Verwendet ``cryptography.fernet`` (AES-128-CBC + HMAC-SHA256, authenticated).
Key kommt aus ENV ``DR_AUTOMATE_ENCRYPTION_KEY`` (32 byte url-safe-base64).
Im DEBUG-Modus wird ein ephemerer Key generiert — Daten ueberleben keinen
Restart, aber die App startet ohne Setup.

Konsequenzen der Wahl:
- Fernet-Token sind nicht deterministisch (Random IV) → keine UNIQUE-Indices
  und keine Suche auf verschluesselten Spalten moeglich.
- Key-Verlust = Datenverlust. Key gehoert in Authelias Ansible-Vault als
  ``vault_dr_automate_encryption_key``.
- Key-Rotation: ``MultiFernet`` akzeptiert mehrere Keys; alter Key bleibt
  fuer Read, neuer Key fuer Write.
"""

from __future__ import annotations

import json
import logging
import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)


def _load_fernet() -> MultiFernet:
    primary = os.environ.get("DR_AUTOMATE_ENCRYPTION_KEY", "").strip()
    secondary = os.environ.get("DR_AUTOMATE_ENCRYPTION_KEY_OLD", "").strip()
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    if not primary:
        if not debug:
            raise RuntimeError(
                "DR_AUTOMATE_ENCRYPTION_KEY ist nicht gesetzt. "
                "Erzeugen mit: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        ephemeral = Fernet.generate_key().decode()
        logger.warning(
            "DR_AUTOMATE_ENCRYPTION_KEY nicht gesetzt — verwende ephemeren Key (Debug-Modus). "
            "Verschluesselte Daten ueberleben keinen Restart."
        )
        primary = ephemeral

    keys = [Fernet(primary.encode())]
    if secondary:
        keys.append(Fernet(secondary.encode()))
    return MultiFernet(keys)


_fernet: MultiFernet | None = None


def get_fernet() -> MultiFernet:
    global _fernet
    if _fernet is None:
        _fernet = _load_fernet()
    return _fernet


def encrypt(plaintext: str) -> str:
    return get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    return get_fernet().decrypt(token.encode("ascii")).decode("utf-8")


class EncryptedString(TypeDecorator):
    """Fernet-verschluesselter Text. Speichert ASCII-Token in TEXT-Spalte."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, str):
            value = str(value)
        return encrypt(value)

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return value
        try:
            return decrypt(value)
        except InvalidToken:
            logger.error("EncryptedString: Token konnte nicht entschluesselt werden (falscher Key?)")
            raise


class EncryptedJSON(TypeDecorator):
    """Fernet-verschluesseltes JSON. Beim Lesen automatisch deserialisiert."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(json.dumps(value, ensure_ascii=False, default=str))

    def process_result_value(self, value, dialect):
        if value is None or value == "":
            return value
        try:
            return json.loads(decrypt(value))
        except InvalidToken:
            logger.error("EncryptedJSON: Token konnte nicht entschluesselt werden (falscher Key?)")
            raise
