"""ASGI entry point: python -m uvicorn app.main:app --no-access-log."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import router
from app.core.config import Settings
from app.modules.places.router import PlaceAPIError
from app.modules.places.service import PlaceSearchService
from app.modules.trips.router import TripAPIError
from app.modules.trips.service import TripService


def create_app(
    settings: Settings | None = None,
    *,
    trip_service: TripService | None = None,
    place_search_service: PlaceSearchService | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings.from_env()
    application = FastAPI(title=config.app_name, version="0.1.0", debug=False)
    application.state.trip_service = trip_service
    application.state.place_search_service = place_search_service

    @application.exception_handler(TripAPIError)
    async def trip_error(request: Request, exc: TripAPIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"id": exc.error_id, "message": exc.message}},
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(PlaceAPIError)
    async def place_error(request: Request, exc: PlaceAPIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"error": {"id": exc.error_id, "message": exc.message}},
            headers={"Cache-Control": "no-store"},
        )

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic errors can contain raw inputs, URLs and names. Do not echo/log them.
        # The envelope is provisional; status 400 follows SDD ERR-001.
        return JSONResponse(
            status_code=400,
            content={"error": {"id": "ERR-001", "message": "입력 형식이 올바르지 않습니다."}},
            headers={"Cache-Control": "no-store"},
        )

    application.include_router(router)
    return application


app = create_app()
