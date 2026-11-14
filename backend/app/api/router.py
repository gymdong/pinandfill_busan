"""Router assembly for liveness and itinerary endpoints."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.modules.places.router import router as places_router
from app.modules.trips.router import router as trips_router

router = APIRouter(prefix="/api")
router.include_router(trips_router)
router.include_router(places_router)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Process liveness only; this does not claim database/provider readiness."""
    return HealthResponse()
