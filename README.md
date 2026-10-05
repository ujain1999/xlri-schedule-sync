# XLRI Schedule Sync

Multi-user, self-hosted service that keeps your XLRI class schedule + activities
continuously synced to a dedicated Google Calendar. Sign in with Google, connect
your XLRI ERP credentials once, and a background job keeps things up to date.

`legacy/` holds the original single-user, no-database Cloudflare Pages tool this
project replaced -- kept only as a reference for the exact XLRI ERP API shapes.

## Architecture

- FastAPI + Postgres, APScheduler running in-process (no Celery/Redis).
- Auth = Google OAuth only (no separate app password); the same consent grant
  provides identity *and* Calendar API access.
- Self-hosted via Docker Compose, deployed with quick-deploy (`qd`), which
  exposes it through a shared Cloudflare Tunnel + Traefik on the server.
- Auto-sync cadence is global, not per-user -- set once via `SYNC_INTERVAL_MINUTES`
  in `.env` and it applies to every connected account. Users always have a
  "Sync now" button for an on-demand update regardless of that interval; the
  cadence is displayed on the login page and dashboard so it's never a surprise.
- See `SECURITY.md` for the encryption/credential-storage model.

## Local development

Requires Docker Desktop.

1. Copy `.env.example` to `.env` and fill in:
   - `ENCRYPTION_KEY`: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   - `SESSION_SECRET`: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
   - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`: see "Google Cloud setup" below.
2. `docker compose -f docker-compose.dev.yml up --build`
3. App is at http://localhost:8000. Postgres is exposed at `localhost:5433` for a
   local `psql`/GUI client.
4. Code changes hot-reload (`uvicorn --reload`, source is bind-mounted).

### Generating a new Alembic migration after changing a model

```
docker compose -f docker-compose.dev.yml run --rm app alembic revision --autogenerate -m "describe the change"
docker compose -f docker-compose.dev.yml restart app   # applies it on boot
```

### Testing the XLRI ERP client against a real account

```
docker compose -f docker-compose.dev.yml run --rm app python scripts/test_xlri_login.py
```

Prompts interactively so your password never ends up in shell history or a chat transcript.

## Google Cloud setup (do this once, manually)

1. Create/reuse a project at console.cloud.google.com, enable the **Google Calendar API**.
2. **OAuth consent screen**: User type = External. Add scopes `openid`,
   `.../auth/userinfo.email`, `.../auth/userinfo.profile`, `.../auth/calendar.calendars`,
   `.../auth/calendar.events`. Add a Privacy Policy + Terms of Service URL (simple
   static pages are fine). Leave **Publishing status = Testing** to start -- this
   works immediately for up to 100 explicitly-added test users, with an
   "unverified app" warning they click through. Revisit Google's verification
   process only if you outgrow 100 users.
3. **Credentials -> Create Credentials -> OAuth client ID -> Web application.**
   Add both redirect URIs on the same client:
   - `http://localhost:8000/auth/google/callback` (dev)
   - `https://<your-subdomain>.<your-domain>/auth/google/callback` (prod)
4. Put the client ID/secret into `.env` as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

## Deploying (quick-deploy)

Production runs on the home server through [quick-deploy](../quick_deploy) (`qd`),
which owns the Cloudflare Tunnel and Traefik. This repo has no tunnel of its own;
`qd` picks `docker-compose.yml`, routes `https://<name>.<domain>` to the `app`
service on port 8000, and leaves `db` private.

First deploy (after `qd setup` has been done once for the server):

1. Put production values in `.env` (it is synced to the server by `qd`):
   - `BASE_URL=https://<name>.<domain>`
   - `GOOGLE_REDIRECT_URI=https://<name>.<domain>/auth/google/callback`, also
     added as a redirect URI on the Google OAuth client.
2. `qd deploy --name <name>`

Subsequent deploys: `qd deploy` from this directory (it reuses the name). Logs:
`qd logs <name> -s app`. Containers restart on reboot via `restart: unless-stopped`.

Keep it to one deployment: the scheduler has no cross-instance locking, so two
copies would double-sync every user. **Never `qd rm <name> --volumes`** unless
you mean to delete the database.

## Backups

On the server:

```
crontab -e
# add: 0 3 * * * ~/.qd/apps/<name>/src/scripts/backup.sh >> ~/.qd/apps/<name>/src/backups/backup.log 2>&1
```

Writes a daily `pg_dump` to `backups/`, retained 14 days. `backups/` is in
`.qdignore`, so redeploys neither overwrite nor delete it. **Copy backups offsite**
(rclone, encrypted USB) periodically -- a laptop is a single point of failure for
disk loss/theft. See `SECURITY.md` for why `ENCRYPTION_KEY` must be backed up
separately from these dumps.
