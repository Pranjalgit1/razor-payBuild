"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.database.base import Base
from app.database.session import engine

# Importing the entities module registers every model on Base.metadata, which
# both create_all and Alembic autogenerate depend on.
from app.models import entities  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Alembic owns the schema in any real deployment. This is a convenience for
    # local demo runs so the app is usable before migrations are applied.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    description=(
        "AI revenue recovery: detect revenue at risk, diagnose the cause, "
        "decide an intervention, act within bounded limits, verify, and "
        "measure the money recovered."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    """Liveness probe, also reporting which backends are configured."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "database": settings.database_url.split("://", 1)[0],
        "ai_provider": settings.ai_provider,
    }
