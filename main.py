"""FastAPI application main entry point."""
import os
from urllib.parse import quote
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path
from api.routes import router
from api.auth import router as auth_router, require_user
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
    dependencies=[Depends(require_user)],
)

# Changeset routes — internal admin surface, also gated.
from api.changeset import router as changeset_router
app.include_router(
    changeset_router,
    prefix="/api",
    tags=["changeset"],
    dependencies=[Depends(require_user)],
)

# Serve frontend static files
frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    # Mount static files directory for JS, CSS, etc.
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")
    # Also mount js directory directly for easier access
    js_path = frontend_path / "js"
    if js_path.exists():
        app.mount("/js", StaticFiles(directory=str(js_path)), name="js")
    # Mount images directory for easier access
    images_path = frontend_path / "images"
    if images_path.exists():
        app.mount("/images", StaticFiles(directory=str(images_path)), name="images")

    @app.get("/")
    async def serve_frontend():
        """Serve frontend index.html."""
        index_path = frontend_path / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return {"message": "Stiflyt Route API", "version": "0.1.0", "docs": "/docs"}

    @app.get("/routes.html")
    async def serve_routes_page():
        """Serve frontend routes.html."""
        routes_path = frontend_path / "routes.html"
        if routes_path.exists():
            return FileResponse(str(routes_path))
        raise HTTPException(status_code=404, detail="routes.html not found")

    # debug.html route removed - debug functionality no longer used

# --- signs_app (Breheimen Skiltverktøy) served at /skilt/ ---
# Built by `make signs-build` (or by scripts/deploy.sh in production). Vite
# is configured with base=/skilt/, so the asset URLs in the built index.html
# already start with /skilt/... StaticFiles(html=True) serves the index for
# /skilt/ and the files under it. The app uses in-memory state for navigation,
# so no SPA-fallback route is needed.
signs_dist = Path(__file__).parent / "signs_app" / "dist"
if signs_dist.exists():
    app.mount(
        "/skilt",
        StaticFiles(directory=str(signs_dist), html=True),
        name="signs_app",
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

