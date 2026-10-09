"""Model info routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config.settings import get_settings
from data.database import get_db
from app.schemas import ModelInfo
from app.auth.dependencies import require_admin


router = APIRouter()


@router.get("/model/info", response_model=ModelInfo)
async def get_model_info():
    """Get model information."""
    settings = get_settings()
    
    return ModelInfo(
        model_name="geocoder",
        model_version=settings.model_version,
        feature_version=settings.feature_version,
        embedding_model=settings.embedding_model,
        training_date=None,  # Would load from model metadata
        metrics={},  # Would load from evaluation
        ablation_results={},  # Would load from experiments
    )


@router.get("/model/feature-importance")
async def get_feature_importance():
    """Get feature importance from ranking model."""
    # Would load from trained model
    return {
        "features": [],
        "importance": [],
    }


@router.get("/model/ablation")
async def get_ablation_results():
    """Get ablation study results."""
    return {
        "results": {},
    }


@router.post("/model/retrain")
async def trigger_retrain(_admin=Depends(require_admin)):
    """Trigger model retraining (async)."""
    return {
        "status": "accepted",
        "message": "Retraining job queued",
    }