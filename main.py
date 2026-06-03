"""FastAPI application main entry point."""
import os
from urllib.parse import quote
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from api.routes import router
from api.auth import router as auth_router, require_user_or_api_key
from services.auth_config import session_secret, session_https_only
from services.startup_checks import run_startup_checks

app = FastAPI(
    title="Stiflyt Route API",
    description="Backend API for processing routes from turrutebasen and mapping matrikkelenhet",
    version="0.1.0",
)


@app.on_event("startup")
async def startup_event() -> None:
    """
    Run database validation on startup and abort if required tables are missing.

    This ensures we fail fast if the database import is incomplete or inconsistent.
    """
    # This function raises RuntimeError if validation fails, which prevents the app from starting
    run_startup_checks()

# Session middleware — signed cookies via itsdangerous. Must be installed
# before any route that touches request.session (i.e., all of them).
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    https_only=session_https_only(),
    same_site="lax",
)


# When a browser navigates directly to a server-rendered HTML endpoint (e.g.
# a shared rutekort link) and isn't logged in, require_user raises 401 with a
# JSON body — useless to the user. Convert that to a 302 → /auth/login with
# the original path stashed as `next` so the OAuth callback bounces them back.
@app.exception_handler(HTTPException)
async def html_aware_auth_handler(request: Request, exc: HTTPException):
    if exc.status_code == 401 and "text/html" in request.headers.get("accept", ""):
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(
            url=f"/api/v1/auth/login?next={quote(target, safe='/?&=')}",
            status_code=302,
        )
    return JSONResponse(
        {"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers or None,
    )

# CORS: in dev the Vite proxy makes the API same-origin (no CORS needed); in
# production the frontend is served by FastAPI from the same domain. Origins
# can be overridden via ALLOWED_ORIGINS (comma-separated) for unusual setups.
_allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "").strip()
_allowed_origins = (
    [o.strip() for o in _allowed_origins_env.split(",") if o.strip()]
    if _allowed_origins_env
    else []
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth router — must be mounted BEFORE the protected router so the /auth/*
# paths aren't gated by require_user.
app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])

# Everything else under /api/v1/* requires a valid session.
app.include_router(
    router,
    prefix="/api/v1",
    tags=["routes"],
    dependencies=[Depends(require_user_or_api_key)],
)

# Changeset routes — internal admin surface, also gated.
from api.changeset import router as changeset_router
app.include_router(
    changeset_router,
    prefix="/api",
    tags=["changeset"],
    dependencies=[Depends(require_user_or_api_key)],
)

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


# --- signs_app (Breheimen Skiltverktøy) served at the site root ---
# Built by `make signs-build` (or scripts/deploy.sh). Vite base is "/", so the
# built asset URLs are /assets/...  StaticFiles(html=True) serves index.html at
# "/" (the desktop app) and the touch-first field app at /field.html.
#
# Mounted LAST and at "/" because that's a catch-all: the /api/v1/*, /api/* and
# /health routes registered above are matched first, and everything else falls
# through to the SPA's static files. The app uses in-memory navigation, so no
# SPA deep-link fallback is needed. (This replaces the retired vanilla frontend
# and the earlier /skilt/ mount + "/" → /skilt redirect.)
signs_dist = Path(__file__).parent / "signs_app" / "dist"
if signs_dist.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(signs_dist), html=True),
        name="signs_app",
    )

