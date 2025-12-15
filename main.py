"""FastAPI application main entry point."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from api.routes import router
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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1", tags=["routes"])

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

    @app.get("/debug.html")
    async def serve_debug():
        """Serve debug.html."""
        debug_path = frontend_path / "debug.html"
        if debug_path.exists():
            return FileResponse(str(debug_path))
        return {"error": "debug.html not found"}, 404


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

