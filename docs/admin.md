# Admin-Handbuch

Dieser Abschnitt richtet sich an den Betreiber (Admin), nicht an Endnutzer.

## Neuen User anlegen

User-Verwaltung läuft über **Authelia** im paperless_etal-Stack (datengetrieben, Details in
`paperless_etal/docs/konzept-authelia-rollen.md`). Self-Service ist deaktiviert.

1. **Anfrage prüfen** unter `/admin/account-requests` (Hinweis kommt per E-Mail an
   `DR_AUTOMATE_ADMIN_EMAIL` und als Telegram-Nachricht nur mit der Anfrage-Nummer).
2. **Argon2id-Hash erzeugen** (Tag wie im Stack):
   ```bash
   docker run --rm authelia/authelia:<tag> authelia crypto hash generate argon2 --password '…'
   ```
3. **Vault:** `vault_authelia_password_hash_<name>` in `ansible/inventory/group_vars/all/vault.yml` anhängen.
4. **Nutzerliste:** Eintrag in `authelia_users` (`ansible/inventory/group_vars/all/vars.yml`) mit
   `groups: [dr-automate-users]` — nur dr-automate, keine Landing.
5. **Deploy:** `ansible-playbook playbooks/deploy.yml --limit cloud --tags env` (Restart von Authelia per Handler).
6. Anfrage auf der Admin-Seite als erledigt markieren und den Nutzer mit Login-Link
   (`https://dr-automate.zilinski.eu/`) benachrichtigen. Beim ersten Login richtet Authelia TOTP/WebAuthn ein.

## Gruppen

| Gruppe | Zugriff auf dr-automate |
|---|---|
| `admins` | ja (plus Infrastruktur-Tools) |
| `dr-automate-users` | **nur** dr-automate, keine Landing |
| alle anderen (`household`, `readers`, …) | nur Gast-Modus — `DR_AUTOMATE_ALLOWED_GROUPS` lässt sie nicht in den Account-Modus |

Die Admin-Seite `/admin/account-requests` ist zusätzlich auf `ADMIN_REMOTE_USERS` beschränkt.

## User deaktivieren

Im `authelia_users`-Eintrag `disabled: true` setzen und deployen. Die Datensätze in
dr-automate bleiben erhalten; bestehende Sessions werden beim nächsten ForwardAuth-Call ungültig.

## User löschen

1. In dr-automate-DB: `DELETE FROM users WHERE remote_user='alice';` – Cascade entfernt Profil, Reisen, Abrechnungen, PDFs müssen separat aus dem Dateisystem gelöscht werden (`rm -rf /app/data/pdfs/<user_id>`).
2. In Authelia: Eintrag aus `authelia_users` entfernen → Deploy.
3. Vault-Variable löschen.

## Encryption-Key-Rotation

1. Neuen Key erzeugen:
   ```bash
   python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
   ```
2. Alten Key in `vault_dr_automate_encryption_key_old` ablegen, neuen Key in `vault_dr_automate_encryption_key`.
3. ENV beim Container setzen:
   ```yaml
   environment:
     DR_AUTOMATE_ENCRYPTION_KEY: '{{ vault_dr_automate_encryption_key }}'
     DR_AUTOMATE_ENCRYPTION_KEY_OLD: '{{ vault_dr_automate_encryption_key_old }}'
   ```
4. Restart Container. App liest mit beiden Keys (MultiFernet), schreibt nur mit dem neuen.
5. Bestandsdaten umschlüsseln:
   ```bash
   docker exec dr-automate python rotate_keys.py --check   # zählt die verschlüsselten Werte
   docker exec dr-automate python rotate_keys.py           # schreibt alle mit dem neuen Key
   ```
   Erst danach den alten Key aus Vault und `.env` entfernen und den Container neu starten. Ohne diesen Schritt sind alle nicht neu gespeicherten Datensätze mit dem Entfernen des alten Keys verloren.

## DB-Migrationen

Beim Container-Start läuft `alembic upgrade head` automatisch (siehe Dockerfile). Neue Migration anlegen:

```bash
alembic revision -m "add new column XY" --autogenerate
# Migration manuell prüfen, dann committen
```

## Backups

`scripts/backup.sh` im paperless_etal-Stack sichert das `dr-automate-data`-Volume täglich nach
`/backups/<timestamp>/dr-automate/data-backup.tar.gz`. Wiederherstellung über
`scripts/restore.sh` (Volume-Tabelle dort enthält `dr-automate-data`). Der Encryption-Key
ist **nicht** im Backup — ohne den Vault-Key sind die verschlüsselten Felder nicht lesbar.

## Logs einsehen

```bash
docker logs -f dr-automate
# oder Access-Log isoliert:
docker logs dr-automate 2>&1 | grep -E 'POST|PUT|DELETE'
```

## Health-Check

`GET /health` → 200 mit JSON-Body. Wird vom Docker-Healthcheck und externem Monitoring gepollt.
