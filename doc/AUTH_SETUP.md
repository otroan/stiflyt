# Sign-in setup (Google OAuth)

The signs tool gates every `/api/v1/*` route behind a Google login. Users
whose Google email isn't in `data/auth.yaml` get a 403 after the callback.

## 1. Create a Google Cloud OAuth client (one-time, ~5 min)

1. Open <https://console.cloud.google.com/> and create or pick a project.
   Call it `stiflyt` or similar — anything works.
2. **APIs & Services → OAuth consent screen**:
   - User type: **External** (unless you have a Google Workspace org)
   - App name: `Skiltverktøy`
   - User support email: your address
   - Developer contact: your address
   - Scopes: skip (the defaults — openid, email, profile — are enough)
   - Test users (while the app is in *Testing*): add every email that needs
     to sign in. Production-publishing the consent screen is optional for an
     internal tool; staying in *Testing* with explicit test users is fine.
3. **APIs & Services → Credentials → + Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - Name: `Stiflyt signs_app`
   - **Authorized redirect URIs** — add all three:
     - `http://localhost:5174/api/v1/auth/callback` *(dev, Vite host)*
     - `http://localhost:8001/api/v1/auth/callback` *(dev, direct API)*
     - `https://stiflyt.hanazo.no/api/v1/auth/callback` *(production)*
4. Copy the **Client ID** and **Client secret** that appear after creation.

## 2. Configure the backend

Edit `.env` (stubs were appended automatically):

```bash
# A random 48-byte URL-safe string. Generate with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
SESSION_SECRET_KEY=...

GOOGLE_CLIENT_ID=...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=...

# Match the host the browser is on (NOT the API host if you're behind a proxy).
# Dev (Vite at 5174 proxies /api to FastAPI at 8001):
OAUTH_REDIRECT_URI=http://localhost:5174/api/v1/auth/callback
# Production:
# OAUTH_REDIRECT_URI=https://stiflyt.hanazo.no/api/v1/auth/callback
# SESSION_HTTPS_ONLY=1
```

Then restart the API server.

## 3. Manage who can sign in

`data/auth.yaml`:

```yaml
allow:
  - otroan@employees.org
  - someone@dnt.no
```

Add or remove emails, then restart the API. Anyone not listed gets bounced
back to the login screen with "E-postadressen din står ikke i tilgangslisten".

## 4. Local dev flow

1. Start the API: `uvicorn main:app --reload --port 8001`
2. Start Vite: `cd signs_app && npm run dev`
3. Open <http://localhost:5174/>. You'll see the login screen.
4. Click "Logg inn med Google" → Google prompt → back to the app.
5. Top right shows your email + a **Logg ut** button.

## 5. Production deploy (Stage B — not done yet)

Stage A (this) only wires up auth. Deployment (Docker, Caddy, systemd, TLS,
domain DNS) is a separate iteration. When that lands, you'll set:

- `OAUTH_REDIRECT_URI=https://stiflyt.hanazo.no/api/v1/auth/callback`
- `SESSION_HTTPS_ONLY=1`
- A long-lived `SESSION_SECRET_KEY` (rotating it logs everyone out)

## How it works

- **Cookie sessions**: Starlette `SessionMiddleware` signs the cookie with
  `SESSION_SECRET_KEY`. No DB session table. SameSite=Lax + HttpOnly.
- **Authlib** runs the OAuth dance — `/api/v1/auth/login` builds the Google
  URL with a CSRF `state` cookie; `/api/v1/auth/callback` exchanges the code
  for an ID token, verifies it, reads the userinfo claim, and (on allow-list
  match) writes the user dict into the session.
- **`require_user`** dependency is attached to the main router, so every
  `/api/v1/*` route except `/api/v1/auth/*` returns 401 to anonymous callers.
  The frontend treats any mid-session 401 as "session expired" and redirects
  back to `/api/v1/auth/login`.
- **Frontend boot**: `App.tsx` calls `/api/v1/auth/me` first. If it 401s, the
  login screen is shown instead of the map; the user clicks the Google button
  to start the OAuth flow.
