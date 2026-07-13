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
- Self-hosted via Docker Compose, exposed through a Cloudflare Tunnel.
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

## Cloudflare Tunnel setup (production, on the laptop)

```
cloudflared tunnel create xlri-schedule-sync
cloudflared tunnel route dns xlri-schedule-sync <subdomain>.<your-domain>
```

Grab the tunnel token from the Cloudflare Zero Trust dashboard (Networks -> Tunnels)
and set it as `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. Under the tunnel's **Public
Hostnames**, map `<subdomain>.<your-domain>` to `http://app:8000` (the `app`
service name in `docker-compose.yml`, reachable over the Compose network).

## Deploying to the laptop

First-time setup on the laptop:

```
git clone <this repo>
cd xlri_schedule_sync
cp .env.example .env   # fill in real production values
./deploy.sh
```

Subsequent deploys: SSH in and run `./deploy.sh` (pulls latest `main`, rebuilds,
restarts). Deploys are intentionally manual, not an auto-pull timer -- see
`scripts/xlri-schedule-sync.service` for reboot resilience only.

To survive laptop reboots without a manual restart:

```
sudo cp scripts/xlri-schedule-sync.service /etc/systemd/system/
sudo sed -i "s|WorkingDirectory=.*|WorkingDirectory=$(pwd)|" /etc/systemd/system/xlri-schedule-sync.service
sudo systemctl enable --now xlri-schedule-sync.service
```

## Backups

```
crontab -e
# add: 0 3 * * * /home/<user>/xlri_schedule_sync/scripts/backup.sh >> /home/<user>/xlri_schedule_sync/backups/backup.log 2>&1
```

Writes a daily `pg_dump` to `backups/`, retained 14 days. **Copy backups offsite**
(rclone, encrypted USB) periodically -- a laptop is a single point of failure for
disk loss/theft. See `SECURITY.md` for why `ENCRYPTION_KEY` must be backed up
separately from these dumps.
