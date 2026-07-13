# Security notes

## Encryption at rest

XLRI ERP passwords and Google OAuth tokens are encrypted at rest with
`cryptography.fernet` (AES-128-CBC + HMAC) using a single symmetric key read from
the `ENCRYPTION_KEY` environment variable (`app/services/crypto.py`). Called only
from the service layer, never from routers directly.

- Generate a key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- Store it only in `.env` (`chmod 600`), never commit it.
- **Back up `ENCRYPTION_KEY` separately from database backups, never in the same
  archive.** Losing the key makes every encrypted row permanently unrecoverable --
  not just hard, actually impossible with Fernet. Storing the key alongside a DB
  dump turns that dump into a plaintext-equivalent leak.

## Key rotation (manual -- not automated, do this only if actually needed)

1. Generate a new key.
2. Construct `cryptography.fernet.MultiFernet([new_key, old_key])` so both keys
   decrypt correctly during the migration.
3. Re-encrypt every `xlri_credentials.encrypted_password`,
   `google_oauth_tokens.encrypted_refresh_token`, and
   `google_oauth_tokens.access_token_encrypted` row with the new key only.
4. Update `ENCRYPTION_KEY` everywhere (`.env` on the laptop, any key backups).
5. Discard the old key.

## Sessions

The app's own login session (`app/services/session.py`) is a random opaque token
in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie. Only `sha256(token)` is stored
in Postgres (`sessions` table) -- a database leak alone cannot be used to forge a
valid session. This is separate from the transient `SessionMiddleware` cookie
Authlib uses to hold OAuth state/nonce during the login redirect round-trip.

## Logging

Never log decrypted XLRI passwords, Google tokens, or raw session tokens. Log
only identifiers (`user_id`) and error classes/messages.

## Dedicated calendar, not the user's primary

All synced events live on a secondary "XLRI Schedule" calendar created via the
Calendar API, never the user's primary calendar. Disconnecting deletes that whole
calendar in one call rather than enumerating and deleting individual events.
