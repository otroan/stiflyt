"""FastAPI application main entry point."""
from fastapi import FastAPI
from api.routes import router

app = FastAPI(
    title="Stiflyt Route API",
    description="Backend API for processing routes from turrutebasen and mapping matrikkelenhet",
    version="0.1.0"
)

app.include_router(router, prefix="/api/v1", tags=["routes"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Stiflyt Route API",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

