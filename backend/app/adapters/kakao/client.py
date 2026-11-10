import json
import logging
import time

import httpx
from pydantic import ValidationError

from .schemas import KakaoPlace
from .settings import KakaoSettings

logger = logging.getLogger(__name__)

# httpx 는 INFO 로 요청 URL 전체(검색어 포함)를 남긴다. 로그 규칙(NFR-010)을 지키도록 낮춘다.
logging.getLogger("httpx").setLevel(logging.WARNING)

KEYWORD_SEARCH_PATH = "/v2/local/search/keyword.json"
QUOTA_EXCEEDED_CODE = -10


class KakaoLocalError(Exception):
    """카카오 로컬 API 호출 실패. API 계층에서 ERR-003(503)으로 바꾼다.

    reason: timeout / network / quota_exceeded / auth / http_status / invalid_response
    """

    def __init__(self, reason: str, status_code: int | None = None) -> None:
        super().__init__(reason if status_code is None else f"{reason} ({status_code})")
        self.reason = reason
        self.status_code = status_code


class KakaoLocalAdapter:
    """카카오 로컬 키워드 검색 어댑터(SDD COMP-08).

    요청마다 카카오를 호출하고 응답을 저장·캐시하지 않는다(ADR-005, D6).
    로그와 예외에는 상태·소요시간·건수만 담고 검색어·장소 정보·키는 담지 않는다.
    """

    def __init__(self, client: httpx.AsyncClient, settings: KakaoSettings) -> None:
        self._client = client
        self._settings = settings

    async def search_keyword(self, query: str, *, category_group_code: str | None = None) -> list[KakaoPlace]:
        """검색어로 부산의 장소를 찾는다. 결과는 카카오의 정확도순 첫 페이지다."""
        query = query.strip()
        if not query:
            raise ValueError("검색어가 비어 있다")

        settings = self._settings
        params: dict[str, str | int] = {"query": query, "size": settings.page_size, "rect": settings.search_rect}
        if category_group_code:
            params["category_group_code"] = category_group_code

        started = time.perf_counter()
        # 원래 예외에는 요청 URL(검색어)이 담기므로 except 밖에서 새 예외를 던져 연결을 끊는다.
        response: httpx.Response | None = None
        transport_failure = ""
        try:
            response = await self._client.get(
                f"{settings.base_url}{KEYWORD_SEARCH_PATH}",
                params=params,
                headers={"Authorization": f"KakaoAK {settings.rest_api_key.get_secret_value()}"},
                timeout=settings.timeout_seconds,
            )
        except httpx.TimeoutException:
            transport_failure = "timeout"
        except httpx.HTTPError:
            transport_failure = "network"
        if response is None:
            raise self._failure(transport_failure, started)

        if response.status_code != httpx.codes.OK:
            raise self._failure(_error_reason(response), started, response.status_code)

        documents = _documents(response)
        if documents is None:
            raise self._failure("invalid_response", started, response.status_code)

        places = [place for place in map(_to_place, documents) if place is not None]
        skipped = len(documents) - len(places)
        # 지번 주소가 없는 장소는 도로명 주소로 지역을 가린다.
        prefix = settings.region_prefix
        places = [place for place in places if (place.address or place.road_address).startswith(prefix)]
        logger.info(
            "kakao_local_search status=200 duration_ms=%d count=%d skipped=%d",
            _elapsed_ms(started),
            len(places),
            skipped,
        )
        return places

    def _failure(self, reason: str, started: float, status_code: int | None = None) -> KakaoLocalError:
        logger.warning(
            "kakao_local_search failed reason=%s status=%s duration_ms=%d", reason, status_code, _elapsed_ms(started)
        )
        return KakaoLocalError(reason, status_code)


def _load_json(response: httpx.Response) -> object:
    try:
        return json.loads(response.content)
    except ValueError:
        return None


def _documents(response: httpx.Response) -> list[object] | None:
    """응답의 documents 목록. 형식이 다르면 None"""
    body = _load_json(response)
    documents = body.get("documents") if isinstance(body, dict) else None
    return documents if isinstance(documents, list) else None


def _to_place(document: object) -> KakaoPlace | None:
    """형식이 맞지 않는 장소 하나 때문에 검색 전체가 실패하지 않도록 건너뛴다."""
    try:
        return KakaoPlace.model_validate(document)
    except ValidationError:
        return None


def _error_reason(response: httpx.Response) -> str:
    """쿼터 초과(400, code -10)와 키·권한 문제(401·403)를 다른 장애와 구분한다. 오류 문구는 읽지 않는다."""
    body = _load_json(response)
    if isinstance(body, dict) and body.get("code") == QUOTA_EXCEEDED_CODE:
        return "quota_exceeded"
    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        return "auth"
    return "http_status"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
