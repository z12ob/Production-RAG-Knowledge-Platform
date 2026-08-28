from fastapi import APIRouter

from app.schemas.health import HealthResponse

router = APIRouter()


@router.get("/health", tags=["system"], summary="Check API health")
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
