"""Main FastAPI application."""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from config.settings import get_settings
from data.database import init_db, get_db
from data.repositories import (
    AccountRepository, VisitRepository, PredictionRepository,
    PlaceClusterRepository
)
from app.schemas import (
    Account, Visit, VisitCreateRequest, VisitValidateRequest,
    GeocodeRequest, GeocodeBatchRequest, Prediction,
    HealthResponse, ModelInfo, PlaceCluster, MetricsResponse,
    VisitOutcome, RecommendedAction
)
from app.routes import accounts, visits, geocode, clusters, metrics, model, real_data, planner
from app.routes import auth as auth_routes
from app.routes import compliance as compliance_routes
from app.auth.dependencies import require_operational_user


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup - skip DB init in test mode (tests override get_db with their own DB)
    if not os.environ.get("TESTING"):
        init_db()
    yield
    # Shutdown
    pass


app = FastAPI(
    title="AI-Native Field Address Geocoder",
    description="Geocoding system for Indian debt-collection field operations",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
operational_dependencies = [Depends(require_operational_user)]
app.include_router(geocode.router, prefix="/api", tags=["geocode"], dependencies=operational_dependencies)
app.include_router(visits.router, prefix="/api", tags=["visits"], dependencies=operational_dependencies)
app.include_router(accounts.router, prefix="/api", tags=["accounts"], dependencies=operational_dependencies)
app.include_router(clusters.router, prefix="/api", tags=["clusters"], dependencies=operational_dependencies)
app.include_router(metrics.router, prefix="/api", tags=["metrics"], dependencies=operational_dependencies)
app.include_router(model.router, prefix="/api", tags=["model"])
app.include_router(real_data.router, prefix="/api", tags=["real-data"], dependencies=operational_dependencies)
app.include_router(planner.router, prefix="/api", tags=["planner"], dependencies=operational_dependencies)
app.include_router(auth_routes.router, prefix="/api", tags=["auth"])
app.include_router(compliance_routes.router, prefix="/api", tags=["compliance"])



@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        database="connected",
        model_loaded=True,  # Would check actual model loading
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.environment == "development",
    )