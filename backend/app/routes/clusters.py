"""Place cluster routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
import json

from data.database import get_db
from data.repositories import PlaceClusterRepository
from app.schemas import PlaceCluster


router = APIRouter()


def _serialize_cluster(cluster):
    return {
        "cluster_id": cluster.cluster_id,
        "latitude": cluster.latitude,
        "longitude": cluster.longitude,
        "account_ids": json.loads(cluster.account_ids or "[]"),
        "landmarks": json.loads(cluster.landmarks or "[]"),
        "address_variants": json.loads(cluster.address_variants or "[]"),
        "visit_count": cluster.visit_count,
        "confidence": cluster.confidence,
        "created_at": cluster.created_at,
    }


@router.get("/place-clusters", response_model=List[PlaceCluster])
async def list_place_clusters(
    limit: int = Query(100, le=1000),
    db: Session = Depends(get_db),
):
    """List all place clusters."""
    cluster_repo = PlaceClusterRepository(db)
    clusters = cluster_repo.get_all(limit)
    return [_serialize_cluster(cluster) for cluster in clusters]


@router.get("/place-clusters/{cluster_id}", response_model=PlaceCluster)
async def get_place_cluster(
    cluster_id: str,
    db: Session = Depends(get_db),
):
    """Get a specific place cluster."""
    cluster_repo = PlaceClusterRepository(db)
    cluster = cluster_repo.get_by_id(cluster_id)
    if not cluster:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cluster {cluster_id} not found"
        )
    return _serialize_cluster(cluster)


@router.get("/place-clusters/nearby")
async def get_nearby_clusters(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(500, le=5000),
    db: Session = Depends(get_db),
):
    """Get clusters near a location."""
    cluster_repo = PlaceClusterRepository(db)
    clusters = cluster_repo.get_nearby(lat, lon, radius_m)
    return [_serialize_cluster(cluster) for cluster in clusters]