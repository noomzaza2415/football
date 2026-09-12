"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app import services
from app.analytics.poisson_model import MODEL_VERSION
from app.config import get_settings
from app.database import get_db, init_db
from app.routers import exports, matches, news, predictions, teams
from app.schemas import DISCLAIMER, HealthOut

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

DESCRIPTION = f"""
Statistical analysis of football Over/Under markets using a Poisson goal model.

{DISCLAIMER}
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.environment == "development":
        init_db()
        logger.info("database tables ensured (development mode)")
    yield


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION.strip(),
    version=MODEL_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(teams.router, prefix=settings.api_prefix)
app.include_router(matches.router, prefix=settings.api_prefix)
app.include_router(predictions.router, prefix=settings.api_prefix)
app.include_router(news.router, prefix=settings.api_prefix)
app.include_router(exports.router, prefix=settings.api_prefix)


@app.get("/", tags=["meta"], summary="Service banner")
def root() -> dict[str, str]:
    return {
        "service": settings.app_name,
        "docs": "/docs",
        "model_version": MODEL_VERSION,
        "disclaimer": DISCLAIMER,
    }


@app.get(f"{settings.api_prefix}/health", response_model=HealthOut, tags=["meta"])
def health(db: Session = Depends(get_db)) -> HealthOut:
    return HealthOut(
        status="ok",
        environment=settings.environment,
        model_version=MODEL_VERSION,
        **services.counts(db),
    )
