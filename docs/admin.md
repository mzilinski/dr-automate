# Admin-Handbuch

Dieser Abschnitt richtet sich an den Betreiber (Admin), nicht an Endnutzer.

## Neuen User anlegen

User-Verwaltung läuft über **Authelia** im paperless_etal-Stack. Self-Service ist deaktiviert; Admin trägt User manuell ein.

### Schritt-für-Schritt

1. **Anfrage prüfen.** Im dr-automate-Dashboard liegt jede Account-Anfrage in `account_requests` (oder kommt per E-Mail an `DR_AUTOMATE_ADMIN_EMAIL`).
2. **Argon2id-Hash erzeugen:**
   ```bash
   docker run --rm authelia/authelia:4.39.10 \
     authelia crypto hash generate argon2 --password 'SecureInitialPassword'
   ```
   Output kopieren (`$argon2id$v=19$m=65536,t=3,p=4$...`).
3. **Vault-Variable anlegen:** in `~/Developer/paperless_etal/ansible/inventory/group_vars/all/vault.yml`:
   ```yaml
   vault_authelia_password_hash_alice: '$argon2id$...'
   ```
4. **User in Template eintragen:** in `~/Developer/paperless_etal/ansible/roles/docker-deploy/templates/authelia-users.yml.j2`:
   ```yaml
     alice:
       disabled: false
       displayname: "Alice Beispiel"
       password: '{{ vault_authelia_password_hash_alice }}'
       email: alice@example.org
       groups:
         - dr-automate-users   # NICHT adults — sonst hat sie auch Landing-Zugriff!
   ```
5. **Deploy:**
   ```bash
   cd ~/Developer/paperless_etal
   ansible-playbook playbooks/deploy.yml --tags authelia
   ```
6. **Authelia lädt die User-DB alle 5 Minuten neu** (`refresh_interval: 5m`). Innerhalb dieser Frist ist der User loginfähig.
7. **User benachrichtigen** mit Login-Link (`https://dr-automate.zilinski.eu/`) und Initial-Passwort. Beim ersten Login richtet Authelia automatisch TOTP/WebAuthn ein.

## Gruppen

| Gruppe | Zugriff |
|---|---|
| `adults` | Landing + Cisco-Email + dr-automate + alle Family-Tools |
| `dr-automate-users` | **NUR** dr-automate. Keine Landing! |

Wichtig: Wenn jemand nur dr-automate nutzen soll – `dr-automate-users`. Wenn vollständiger Familien-Zugang gewünscht – `adults`.

## User deaktivieren

```yaml
alice:
  disabled: true   # ← reicht; Datensätze bleiben in dr-automate erhalten
```
Deploy. Bestehender Login wird auch durch existierende Sessions binnen kurzer Zeit ungültig (Authelia prüft `disabled` bei jedem ForwardAuth-Call).

## User löschen

1. In dr-automate-DB: `DELETE FROM users WHERE remote_user='alice';` – Cascade entfernt Profil, Reisen, Abrechnungen, PDFs müssen separat aus dem Dateisystem gelöscht werden (`rm -rf /app/data/pdfs/<user_id>`).
2. In Authelia: User-Block aus `authelia-users.yml.j2` entfernen → Deploy.
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
5. Bei Bedarf alle verschlüsselten Felder durchschreiben (Re-Save aller Profile/Reisen). Danach kann der alte Key entfernt werden.

## DB-Migrationen

Beim Container-Start läuft `alembic upgrade head` automatisch (siehe Dockerfile). Neue Migration anlegen:

```bash
alembic revision -m "add new column XY" --autogenerate
# Migration manuell prüfen, dann committen
```

## Backups

`scripts/backup.sh` im paperless_etal-Stack sichert auch das `dr-automate-data`-Volume. Wiederherstellung:

```bash
docker compose stop dr-automate
docker run --rm -v dr-automate-data:/data -v /backup:/backup alpine \
  tar xzf /backup/dr-automate-data-YYYY-MM-DD.tar.gz -C /data
docker compose start dr-automate
```

## Logs einsehen

```bash
docker logs -f dr-automate
# oder Access-Log isoliert:
docker logs dr-automate 2>&1 | grep -E 'POST|PUT|DELETE'
```

## Health-Check

`GET /health` → 200 mit JSON-Body. Wird vom Docker-Healthcheck und externem Monitoring gepollt.
