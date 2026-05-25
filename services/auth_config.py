"""Auth configuration: Google OAuth client + email allow-list.

Env vars (set via .env or the process environment):
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET — from Google Cloud Console.
    SESSION_SECRET_KEY                    — random bytes; rotates invalidate sessions.
    OAUTH_REDIRECT_URI                    — absolute URL of /api/v1/auth/callback
                                            on the current host (must match a redirect
                                            URI registered in Google Cloud Console).
    SESSION_HTTPS_ONLY                    — "1" in production (HTTPS), unset in dev.

Allow-list lives in data/auth.yaml — see that file for the format.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Set

from authlib.integrations.starlette_client import OAuth

ALLOW_LIST_PATH = Path(__file__).resolve().parent.parent / "data" / "auth.yaml"


def _load_allow_list() -> Set[str]:
    if not ALLOW_LIST_PATH.exists():
        return set()
    try:
        import yaml
        with ALLOW_LIST_PATH.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return {str(e).strip().lower() for e in (cfg.get("allow") or []) if e}
    except (OSError, ImportError, Exception):
        return set()


@lru_cache(maxsize=1)
def allowed_emails() -> Set[str]:
    """Cached at first call; restart the API to pick up YAML edits."""
    return _load_allow_list()


def is_email_allowed(email: str | None) -> bool:
    if not email:
        return False
    return email.strip().lower() in allowed_emails()


def session_secret() -> str:
    secret = os.getenv("SESSION_SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "SESSION_SECRET_KEY is not set. Generate one with `python -c "
            "\"import secrets; print(secrets.token_urlsafe(48))\"` and put it in .env."
        )
    return secret


def session_https_only() -> bool:
    return os.getenv("SESSION_HTTPS_ONLY", "").strip() in ("1", "true", "yes")


def oauth_redirect_uri() -> str:
    uri = os.getenv("OAUTH_REDIRECT_URI")
    if not uri:
        raise RuntimeError(
            "OAUTH_REDIRECT_URI is not set. In dev set it to "
            "http://localhost:5174/api/v1/auth/callback (Vite host) or "
            "http://localhost:8001/api/v1/auth/callback (direct API)."
        )
    return uri


_oauth: OAuth | None = None


def get_oauth() -> OAuth:
    """Build the Authlib OAuth registry on first use.

    Lazy so importing this module doesn't blow up when Google env vars
    aren't configured yet (e.g. during unit tests).
    """
    global _oauth
    if _oauth is not None:
        return _oauth
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set. "
            "Create an OAuth 2.0 Client (Web application) in Google Cloud Console "
            "and copy the credentials into .env."
        )
    _oauth = OAuth()
    _oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return _oauth
