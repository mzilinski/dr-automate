"""Re-Encrypt aller verschlüsselten Spalten mit dem aktuellen Key.

Teil der Key-Rotation (docs/admin.md): Nach dem Umstellen auf einen neuen
``DR_AUTOMATE_ENCRYPTION_KEY`` (alter Key in ``DR_AUTOMATE_ENCRYPTION_KEY_OLD``)
liest die App zwar beide Keys, schreibt aber nur geänderte Spalten neu.
Dieses Skript schreibt jeden Token einmal mit dem neuen Key um
(``MultiFernet.rotate`` — ohne Klartext-Umweg über JSON), danach kann der alte
Key aus dem Vault entfernt werden.

    docker exec dr-automate python rotate_keys.py           # umschlüsseln
    docker exec dr-automate python rotate_keys.py --check   # nur zählen
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import String, select, type_coerce, update

import models_db  # noqa: F401  -- registriert alle Tabellen in Base.metadata
from crypto import EncryptedJSON, EncryptedString, get_fernet
from db import Base, SessionLocal


def _encrypted_columns():
    for table in Base.metadata.sorted_tables:
        cols = [c for c in table.columns if isinstance(c.type, EncryptedString | EncryptedJSON)]
        if cols:
            yield table, cols


def rotate(check_only: bool = False) -> int:
    """Gibt die Zahl der (umzuschlüsselnden) Werte zurück."""
    fernet = get_fernet()
    count = 0
    with SessionLocal() as s:
        for table, cols in _encrypted_columns():
            pk = list(table.primary_key.columns)
            raw_cols = [type_coerce(c, String).label(c.name) for c in cols]
            for row in s.execute(select(*pk, *raw_cols)).mappings():
                neu = {}
                for c in cols:
                    token = row[c.name]
                    if token:
                        neu[c.name] = type_coerce(fernet.rotate(token.encode("ascii")).decode("ascii"), String)
                if not neu:
                    continue
                count += len(neu)
                if not check_only:
                    where = [p == row[p.name] for p in pk]
                    s.execute(update(table).where(*where).values(**neu))
        if not check_only:
            s.commit()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="nur zählen, nichts schreiben")
    args = parser.parse_args()
    n = rotate(check_only=args.check)
    print(f"{n} verschlüsselte Werte {'gefunden' if args.check else 'mit dem aktuellen Key neu geschrieben'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
