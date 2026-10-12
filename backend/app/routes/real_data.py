"""API routes for real dataset."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pathlib import Path
import os

from data.real_data import RealDatasetLoader, load_dataset, get_dataset_loader
from geospatial.real_geocoder import RealDataGeocoder, RealDatasetLoader as RDLoader
from ml.address_normalizer import normalize_address
from ml.entity_extractor import extract_entities
from evaluation.ps3_experiments import run_ps3_experiments

router = APIRouter()

# Configuration: skip full dataset loading in production for performance
_DISABLE_DATASET_LOOKUPS = os.environ.get("DISABLE_DATASET_LOOKUPS") == "1"

# Module-level cached loader - loaded once at import time
# When DISABLE_DATASET_LOOKUPS is True, loader is created but data is not loaded
_cached_loader: RDLoader | None = None


def get_cached_loader() -> RDLoader:
    """Get the cached dataset loader, loading data once if needed."""
    global _cached_loader
    if _cached_loader is None:
        _cached_loader = get_dataset_loader()
        # Only load all data if dataset lookups are enabled
        if not _DISABLE_DATASET_LOOKUPS:
            if not _cached_loader.accounts:
                _cached_loader.load_all("train")
    return _cached_loader


def get_geocoder() -> RealDataGeocoder:
    """Get geocoder with loaded dataset."""
    loader = get_cached_loader()
    # Only load data if dataset lookups are enabled (lazy load for geocoder)
    if not _DISABLE_DATASET_LOOKUPS and not _cached_loader.accounts:
        _cached_loader.load_all("train")
    return RealDataGeocoder(_cached_loader)