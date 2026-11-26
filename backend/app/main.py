"""ASGI entry point: python -m uvicorn app.main:app --no-access-log."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.adapters.kakao import KakaoLocalAdapter, KakaoSettings
from app.adapters.route.service import build_route_provider
from app.api.router import router
from app.core.config import Settings
from app.db.session import Database, DatabaseSettings
from app.modules.crowd.engine_lookup import CrowdServiceLookup
from app.modules.crowd.file_provider import (
    FileCrowdProvider,
    crowd_config_from_env,
    crowd_dir_from_env,
    district,
)
from app.modules.crowd.service import CrowdService
from app.modules.crowd.signals import load_config
from app.modules.engine.initial import InitialSchedulePlanner
from app.modules.engine.service import BasicItineraryEngine
from app.modules.places.detail import PlaceDetailService, SamplePlaceDetails
from app.modules.places.matcher import PlaceMatcher
from app.modules.places.photos import load_place_photos
from app.modules.places.router import PlaceAPIError
from app.modules.places.samples import SamplePlaceData, load_sample_places
from app.modules.places.service import PlaceSearchService
from app.modules.places.settings import PlaceMatchSettings
from app.modules.trips.edit_history import EditHistory
from app.modules.trips.initial import PublicStayDurations
from app.modules.trips.repository import FakeTripRepository
from app.modules.trips.router import TripAPIError
from app.modules.trips.service import TripService
from app.modules.trips.sql_repository import SqlSnapshotRepository, SqlTripRepository

logger = logging.getLogger(__name__)


def default_trip_service(places: SamplePlaceData, *, crowd_service: CrowdService | None = None) -> TripService:
    """로컬 기본 구성: 표본 장소, 경로 키가 있을 때만 실제 경로 조회.

    `crowd_service` 가 있으면 초기 일정 생성이 덜 붐비는 삽입 위치를 고른다(FR-009). 기준은 혼잡 설정 파일의
    `avoidance` 이고, 혼잡 정보가 기준 신뢰도 미만이면(지금 운영은 정보 부족) 배치는 혼잡 없이와 같다.

    `DATABASE_URL` 이 있으면 여행·되돌리기 이력을 DB(trips·blocks·legs·schedule_snapshots)에 저장하고,
    편집 한 번(일정 저장 + 스냅샷)을 한 트랜잭션으로 처리한다. 스키마는 `alembic upgrade head` 로 만든다.
    없으면 메모리 저장소를 쓰며, 프로세스가 재시작되면 여행과 이력이 사라진다.
    """
    engine = BasicItineraryEngine(places, build_route_provider())
    initial_planner = InitialSchedulePlanner(
        engine,
        PublicStayDurations(places.stay_min),
        crowd=CrowdServiceLookup(crowd_service) if crowd_service is not None else None,
        avoidance=load_config(crowd_config_from_env()).avoidance if crowd_service is not None else None,
    )
    url = DatabaseSettings().url()
    if url is None:
        # 워커가 여러 개면 워커마다 여행이 따로 저장된다. 공유 배포에는 DATABASE_URL 을 설정한다.
        logger.warning("trip storage is in-memory (DATABASE_URL unset): trips and undo history are lost on restart")
        return TripService(FakeTripRepository({}), engine, places.stay_min, initial_planner=initial_planner)
    database = Database(url)
    return TripService(
        SqlTripRepository(database),
        engine,
        places.stay_min,
        history=EditHistory(SqlSnapshotRepository(database)),
        initial_planner=initial_planner,
        transaction=database.transaction,
    )


def default_crowd_service(places: SamplePlaceData) -> CrowdService:
    """data/crowd/(또는 CROWD_DATA_DIR)의 정규화 CSV 로 예상 혼잡을 계산한다. 파일이 없으면 정보 부족이다.

    설정은 data/seed/crowd/crowd_config.json(또는 CROWD_CONFIG_PATH). 설정이 없거나 잘못되면 앱 시작이 실패한다.
    """

    def region_of(place_id: str) -> str | None:
        item = places.place(place_id)
        return district(item.address) if item is not None else None

    return CrowdService(FileCrowdProvider.from_dir(crowd_dir_from_env(), region_of, crowd_config_from_env()))


def kakao_settings() -> KakaoSettings | None:
    """KAKAO_REST_API_KEY 가 없거나 비어 있으면(공백뿐인 값 포함) None. 장소 검색은 그때 지금처럼 503(ERR-017)이다.

    키가 아닌 설정(예: KAKAO_SEARCH_RECT)이 잘못되면 검색을 조용히 끄지 않고 앱 시작을 실패시킨다.
    """
    try:
        kakao = KakaoSettings()  # type: ignore[call-arg]  # 값은 환경변수·.env 에서 읽는다
    except ValidationError as error:
        if all(item["loc"] == ("rest_api_key",) for item in error.errors()):
            return None
        raise
    return kakao


def default_place_search_service(places: SamplePlaceData, kakao: KakaoLocalAdapter) -> PlaceSearchService:
    settings = PlaceMatchSettings()  # type: ignore[call-arg]
    return PlaceSearchService(kakao, PlaceMatcher(places.repository(), settings), settings)


def create_app(
    settings: Settings | None = None,
    *,
    trip_service: TripService | None = None,
    place_search_service: PlaceSearchService | None = None,
    place_detail_service: PlaceDetailService | None = None,
    crowd_service: CrowdService | None = None,
) -> FastAPI:
    """주입하지 않은 서비스는 기본 구성으로 만든다.

    카카오 장소 검색은 lifespan 이 시작될 때 붙는다. uvicorn 이나 `with TestClient(...)` 없이 만든 앱에서는
    키가 있어도 장소 검색이 503(ERR-017)이다.
    """
    config = settings if settings is not None else Settings.from_env()
    # 주입하지 않은 서비스만 기본 구성으로 만든다. 만들 때 외부 API 를 호출하지 않는다.
    needs_places = (
        trip_service is None or place_search_service is None or place_detail_service is None or crowd_service is None
    )
    places = load_sample_places() if needs_places else None
    # 혼잡 서비스를 여행 서비스보다 먼저 만들어 API-012 와 초기 일정 생성(FR-009)이 같은 인스턴스를 쓴다.
    if crowd_service is None and places is not None:
        crowd_service = default_crowd_service(places)
    if trip_service is None and places is not None:
        trip_service = default_trip_service(places, crowd_service=crowd_service)
    # API-005 는 외부 API 를 부르지 않으므로 키 없이도 표본 장소로 응답한다.
    if place_detail_service is None and places is not None:
        place_detail_service = PlaceDetailService(SamplePlaceDetails(places, load_place_photos()))
    kakao = kakao_settings() if place_search_service is None else None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if kakao is None or places is None:
            yield
            return
        # 카카오 HTTP 클라이언트는 lifespan 안에서만 열고 닫는다. lifespan 없이 만든 앱에는 열린 연결이 남지 않는다.
        async with httpx.AsyncClient() as kakao_http:
            application.state.place_search_service = default_place_search_service(
                places, KakaoLocalAdapter(kakao_http, kakao)
            )
            try:
                yield
            finally:
                application.state.place_search_service = None

    application = FastAPI(title=config.app_name, version="0.1.0", debug=False, lifespan=lifespan)
    application.state.trip_service = trip_service
    application.state.place_search_service = place_search_service
    application.state.place_detail_service = place_detail_service
    application.state.crowd_service = crowd_service

    @application.exception_handler(TripAPIError)
    async def trip_error(request: Request, exc: TripAPIError) -> JSONResponse:
        error: dict[str, object] = {"id": exc.error_id, "message": exc.message}
        if exc.fields is not None:
            error["fields"] = exc.fields
        return JSONResponse(
            status_code=exc.status,
            content={"error": error},
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
