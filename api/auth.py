"""OAuth (Google) login flow + session helpers.

Flow:
    GET  /api/v1/auth/login    — redirect to Google with state cookie
    GET  /api/v1/auth/callback — exchange code, check allow-list, set session
    POST /api/v1/auth/logout   — clear session
    GET  /api/v1/auth/me       — return current user or 401

Sessions are signed cookies via Starlette's SessionMiddleware (wired in main.py).
The session stores ``{"user": {"email", "name", "picture", "features"}}`` — no
DB row needed. `features` is the sorted list of feature flags granted to this
user (e.g. `["grunneier", "signs"]`), driven by `data/auth.yaml`.

Any route under /api/v1/* that isn't this router uses the ``require_user``
dependency to enforce a valid session; unauthenticated requests get 401, which
the frontend handles by redirecting to /api/v1/auth/login. Endpoints that
require a specific feature attach ``Depends(require_feature("feature_name"))``
in addition — those get 403 when the session lacks the feature.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Any, Callable, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuthError

from services.auth_config import features_for_email, get_oauth, is_email_allowed, oauth_redirect_uri

logger = logging.getLogger(__name__)

router = APIRouter()


# Default landing if the login flow wasn't given an explicit `next` target.
DEFAULT_POST_LOGIN_REDIRECT = "/"

# Session key for the post-login target carried across the OAuth round-trip.
_NEXT_SESSION_KEY = "auth_next"


def _safe_next(raw: str | None) -> str | None:
    """Accept only same-origin paths so `?next=` can't be used as an open
    redirect. Must start with a single `/` (not `//` or `/\\`) and contain
    no scheme."""
    if not raw:
        return None
    if not raw.startswith("/"):
        return None
    if raw.startswith("//") or raw.startswith("/\\"):
        return None
    return raw


def _frontend_login_failure(reason: str, next_url: str | None = None) -> RedirectResponse:
    """Bounce back to the app with an error query — the frontend reads this
    and shows the message on the login screen."""
    target = next_url or DEFAULT_POST_LOGIN_REDIRECT
    sep = "&" if "?" in target else "?"
    return RedirectResponse(url=f"{target}{sep}login_error={reason}", status_code=302)


@router.get("/login", name="auth_login")
async def login(request: Request, next: str | None = None):
    # Stash the post-login target in the session so /callback can pick it up
    # after the OAuth round-trip. Only same-origin paths accepted.
    request.session[_NEXT_SESSION_KEY] = _safe_next(next) or DEFAULT_POST_LOGIN_REDIRECT
    oauth = get_oauth()
    return await oauth.google.authorize_redirect(request, oauth_redirect_uri())


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    # Pull (and clear) the stashed target before any early-return path uses it.
    next_url = _safe_next(request.session.pop(_NEXT_SESSION_KEY, None)) or DEFAULT_POST_LOGIN_REDIRECT

    oauth = get_oauth()
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        logger.warning("OAuth callback rejected: %s", exc)
        return _frontend_login_failure("oauth_error", next_url)

    # `userinfo` is the OpenID userinfo claim set; Authlib parses it from
    # the id_token automatically when the openid scope is requested.
    userinfo: Dict[str, Any] = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    if not email or not userinfo.get("email_verified", False):
        logger.info("Login rejected: email missing or unverified (%s)", email)
        return _frontend_login_failure("email_unverified", next_url)

    if not is_email_allowed(email):
        logger.info("Login rejected: %s not in allow-list", email)
        return _frontend_login_failure("not_allowed", next_url)

    request.session["user"] = {
        "email": email,
        "name": userinfo.get("name") or email,
        "picture": userinfo.get("picture"),
        # Sorted for deterministic shape — frontend can === compare for "did
        # my permissions change since last load".
        "features": sorted(features_for_email(email)),
    }
    return RedirectResponse(url=next_url, status_code=302)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


@router.get("/me")
async def me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    # Hydrate features on the fly for sessions minted before the field
    # existed — avoids forcing every active user to re-log after the rollout.
    if "features" not in user:
        user["features"] = sorted(features_for_email(user.get("email")))
        request.session["user"] = user
    return user


# --- Dependency used by the rest of the API ---------------------------------

def require_user(request: Request) -> Dict[str, Any]:
    """Inject the logged-in user into a route, 401 if there is none.

    Attached to the main router at include_router time so every /api/v1/*
    route is gated. Bypassed by /api/v1/auth/* (different router) and
    /health (app-level, no router).
    """
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    return user


def _session_features(user: Dict[str, Any]) -> List[str]:
    """Pull features from the session, re-resolving from auth.yaml if the
    session pre-dates the feature flag rollout."""
    feats = user.get("features")
    if feats is None:
        feats = sorted(features_for_email(user.get("email")))
    return feats


def require_feature(feature: str) -> Callable[[Request], Dict[str, Any]]:
    """FastAPI dependency factory: 403 unless the session user has `feature`.

    Reads the session directly (rather than `Depends(require_user)` inside
    it) so dependency_overrides in tests on require_user still take effect
    when the route also lists `Depends(require_feature(...))`. The router-
    level `Depends(require_user)` in main.py guarantees a session exists by
    the time this runs in real requests — but we still raise 401 here as a
    belt-and-braces so the dep is safe to use standalone.
    """
    def _dep(request: Request) -> Dict[str, Any]:
        user = request.session.get("user")
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="not_authenticated",
            )
        if feature not in _session_features(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"feature_required:{feature}",
            )
        return user

    return _dep


def require_user_or_api_key(request: Request) -> Dict[str, Any]:
    """Auth dep that accepts either a Google session OR an X-API-Key header.

    Enables automation (stiflyt_mcp) to talk to the backend without going
    through the OAuth flow. The side door only opens when STIFLYT_API_KEY
    is set in the backend env; unset → behaves exactly like require_user.

    Identity for audit fields (recorded_by / updated_by / uploaded_by) is
    taken from the X-User header when entering via the key — mutating
    routes read X-User independently, so just synthesizing a user dict
    here is enough to satisfy the dependency check.
    """
    expected = os.environ.get("STIFLYT_API_KEY")
    if expected:
        provided = request.headers.get("x-api-key")
        if provided and hmac.compare_digest(provided, expected):
            actor = request.headers.get("x-user") or "mcp-agent"
            return {"email": actor, "name": actor, "via": "api_key"}
    return require_user(request)
