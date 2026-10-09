"""Geocoder provider abstraction."""

import asyncio
import hashlib
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List
from urllib.parse import quote_plus

import httpx

from app.schemas import CandidateLocation, CandidateSource
from config.settings import get_settings
from data.repositories import GeocoderCacheRepository
from data.database import db_session
import logging

logger = logging.getLogger(__name__)


@dataclass
class GeocoderResult:
    """Result from a geocoder."""
    latitude: float
    longitude: float
    confidence: Optional[float] = None
    raw_response: Optional[dict] = None
    provider: str = "unknown"


class GeocoderProvider(ABC):
    """Abstract base class for geocoder providers."""

    @abstractmethod
    async def geocode(self, query: str) -> List[GeocoderResult]:
        """Geocode a query string."""
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Get provider name."""
        pass


class NominatimProvider(GeocoderProvider):
    """OpenStreetMap Nominatim geocoder."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.settings = get_settings()
        self.user_agent = self.config.get("user_agent", self.settings.nominatim_user_agent)
        self.base_url = "https://nominatim.openstreetmap.org/search"
        self.rate_limit = self.config.get("rate_limit", 1.0)  # requests per second
        self.last_request = 0.0
        self.client = httpx.AsyncClient(timeout=10.0)

    async def geocode(self, query: str) -> List[GeocoderResult]:
        """Geocode using Nominatim."""
        await self._rate_limit()
        
        params = {
            "q": query,
            "format": "json",
            "limit": 5,
            "addressdetails": 1,
            "countrycodes": "in",  # India only
        }
        
        headers = {"User-Agent": self.user_agent}
        
        try:
            response = await self.client.get(self.base_url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data:
                lat = float(item.get("lat", 0))
                lon = float(item.get("lon", 0))
                if lat != 0 and lon != 0:
                    results.append(GeocoderResult(
                        latitude=lat,
                        longitude=lon,
                        confidence=float(item.get("importance", 0.5)),
                        raw_response=item,
                        provider="nominatim",
                    ))
            return results
        except Exception as e:
            # Return empty on error
            return []

    def get_name(self) -> str:
        return "nominatim"

    async def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request
        if elapsed < self.rate_limit:
            await asyncio.sleep(self.rate_limit - elapsed)
        self.last_request = time.time()

    async def close(self):
        await self.client.aclose()


class MockGeocoderProvider(GeocoderProvider):
    """Mock geocoder for testing/offline mode."""

    def __init__(self, config: dict = None):
        self.config = config or {}

    async def geocode(self, query: str) -> List[GeocoderResult]:
        """Return mock results for known test addresses."""
        # Deterministic mock based on query hash
        hash_val = int(hashlib.md5(query.encode()).hexdigest()[:8], 16)
        
        # Base coordinates around Bangalore
        base_lat = 12.9716
        base_lon = 77.5946
        
        # Add some variation
        lat = base_lat + (hash_val % 1000) / 100000
        lon = base_lon + ((hash_val // 1000) % 1000) / 100000
        
        return [GeocoderResult(
            latitude=lat,
            longitude=lon,
            confidence=0.5,
            raw_response={"mock": True, "query": query},
            provider="mock",
        )]

    def get_name(self) -> str:
        return "mock"


class GeocoderManager:
    """Manages multiple geocoder providers with caching."""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.settings = get_settings()
        self.providers: List[GeocoderProvider] = []
        self._init_providers()
        self.cache_ttl = self.config.get("cache_ttl", 86400)

    def _init_providers(self):
        """Initialize configured providers."""
        # Add Nominatim as primary provider (real geocoder)
        if not self.config.get("disable_nominatim", False):
            self.providers.append(NominatimProvider(self.config))
        
        # Add mock provider only if explicitly enabled (for testing/offline)
        if self.config.get("enable_mock", False):
            self.providers.append(MockGeocoderProvider(self.config))

    async def geocode(self, query: str, use_cache: bool = True) -> List[CandidateLocation]:
        """Geocode query using available providers with caching."""
        # Check cache first
        if use_cache:
            cached = self._get_cached(query)
            if cached:
                return cached
        
        # Try each provider in order
        for provider in self.providers:
            try:
                results = await provider.geocode(query)
                if results:
                    # Convert to candidates
                    candidates = [
                        CandidateLocation(
                            candidate_id=f"geo_{provider.get_name()}_{i}",
                            latitude=r.latitude,
                            longitude=r.longitude,
                            source=CandidateSource.GEOCODER,
                            gps_accuracy=100.0,  # Approximate for geocoder
                            commercial_geocoder_distance=0.0,
                        )
                        for i, r in enumerate(results)
                    ]
                    
                    # Cache results with provider name in key
                    if use_cache:
                        self._cache_results(query, provider.get_name(), results)
                    
                    return candidates
            except Exception as e:
                logger.warning(f"Provider {provider.get_name()} failed: {e}")
                continue
        
        return []

    def _get_cache_key(self, query: str, provider: str = "") -> str:
        """Generate cache key including provider."""
        content = f"{provider}:{query}" if provider else f"default:{query}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _get_cached(self, query: str) -> Optional[List[CandidateLocation]]:
        """Get cached geocoder results."""
        # Try each provider's cache
        for provider in self.providers:
            key = self._get_cache_key(query, provider.get_name())
            with db_session() as db:
                cache_repo = GeocoderCacheRepository(db)
                entry = cache_repo.get(key)
                if entry and entry.raw_response:
                    import json
                    data = json.loads(entry.raw_response)
                    return [
                        CandidateLocation(
                            candidate_id=f"cache_{i}",
                            latitude=item["latitude"],
                            longitude=item["longitude"],
                            source=CandidateSource.GEOCODER,
                            gps_accuracy=item.get("gps_accuracy", 100),
                            commercial_geocoder_distance=0.0,
                        )
                        for i, item in enumerate(data)
                    ]
        return None

    def _cache_results(self, query: str, provider: str, results: List[GeocoderResult]):
        """Cache geocoder results with provider-specific key."""
        key = self._get_cache_key(query, provider)
        with db_session() as db:
            cache_repo = GeocoderCacheRepository(db)
            import json
            data = [
                {
                    "latitude": r.latitude,
                    "longitude": r.longitude,
                    "confidence": r.confidence,
                    "provider": r.provider,
                    "gps_accuracy": 100.0,
                }
                for r in results
            ]
            cache_repo.set(key, json.dumps(data), self.cache_ttl)

    async def close(self):
        """Close all providers."""
        for provider in self.providers:
            if hasattr(provider, 'close'):
                await provider.close()


# Global instance
_geocoder_manager = None


def get_geocoder_manager(config: dict = None) -> GeocoderManager:
    """Get singleton geocoder manager."""
    global _geocoder_manager
    if _geocoder_manager is None:
        _geocoder_manager = GeocoderManager(config)
    return _geocoder_manager


async def geocode_address(query: str, use_cache: bool = True, config: dict = None) -> List[CandidateLocation]:
    """Convenience function to geocode an address."""
    manager = get_geocoder_manager(config)
    return await manager.geocode(query, use_cache)