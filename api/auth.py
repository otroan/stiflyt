"""OAuth (Google) login flow + session helpers.

Flow:
    GET  /api/v1/auth/login    — redirect to Google with state cookie
    GET  /api/v1/auth/callback — exchange code, check allow-list, set session
    POST /api/v1/auth/logout   — clear session
    GET  /api/v1/auth/me       — return current user or 401

Sessions are signed cookies via Starlette's SessionMiddleware (wired in main.py).
The session stores ``{"user": {"email", "name", "picture"}}`` — no DB row needed.

Any route under /api/v1/* that isn't this router uses the ``require_user``
dependency to enforce a valid session; unauthenticated requests get 401, which
the frontend handles by redirecting to /api/v1/auth/login.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuthError

from services.auth_config import get_oauth, is_email_allowed, oauth_redirect_uri

logger = logging.getLogger(__name__)

router = APIRouter()


# Where to send the user once login succeeds. Kept simple — always the app root.
# Could become configurable later if we serve multiple frontends from one API.
POST_LOGIN_REDIRECT = "/"


def _frontend_login_failure(reason: str) -> RedirectResponse:
    """Bounce back to the app with an error query — the frontend reads this
    and shows the message on the login screen."""
    return RedirectResponse(url=f"/?login_error={reason}", status_code=302)


@router.get("/login", name="auth_login")
async def login(request: Request):
    oauth = get_oauth()
    return await oauth.google.authorize_redirect(request, oauth_redirect_uri())


@router.get("/callback", name="auth_callback")
async def callback(request: Request):
    oauth = get_oauth()
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        logger.warning("OAuth callback rejected: %s", exc)
        return _frontend_login_failure("oauth_error")

    # `userinfo` is the OpenID userinfo claim set; Authlib parses it from
    # the id_token automatically when the openid scope is requested.
    userinfo: Dict[str, Any] = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    if not email or not userinfo.get("email_verified", False):
        logger.info("Login rejected: email missing or unverified (%s)", email)
        return _frontend_login_failure("email_unverified")

    if not is_email_allowed(email):
        logger.info("Login rejected: %s not in allow-list", email)
        return _frontend_login_failure("not_allowed")

    request.session["user"] = {
        "email": email,
        "name": userinfo.get("name") or email,
        "picture": userinfo.get("picture"),
    }
    return RedirectResponse(url=POST_LOGIN_REDIRECT, status_code=302)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})


@router.get("/me")
async def me(request: Request):
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
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
