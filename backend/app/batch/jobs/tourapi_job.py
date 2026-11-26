"""TourAPI 장소 수집 잡(FR-016). `BatchCollector` 의 `SourceJob` 구현.

수집 대상은 DB places 의 PUBLIC 장소 중 TourAPI contentid(숫자) 인 것이다. 새 장소는 수집으로 생기지 않는다.
장소를 늘리려면 data/samples/places_sample.csv 에 실제 contentid 로 행을 넣고 `seed-places` 를 다시 돌린다.
수집은 이름·좌표·주소·collected_at 만 바꾼다(`SqlPlaceStore.update_collected`).
"""

from collections.abc import Callable
from datetime import datetime

import httpx

from app.core.logging import quiet_http_client_logs
from app.db.session import Database
from app.modules.places.db_repository import SqlPlaceStore

from ..collector import INTERRUPTED, JobOutcome
from .public_places_batch import collect_public_places


class TourAPIPlacesJob:
    def __init__(self, api_key: str | None, *, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client
        # 요청 URL 에 serviceKey 가 들어가므로 이 잡만 써도 httpx 가 URL 을 로그에 남기지 않게 한다.
        quiet_http_client_logs()

    @staticmethod
    def _content_ids(database: Database) -> list[str]:
        return [place_id for place_id in SqlPlaceStore(database).public_ids() if place_id.isdigit()]

    def planned_calls(self, database: Database) -> int:
        return len(self._content_ids(database))

    def collect(self, database: Database, should_stop: Callable[[], bool]) -> JobOutcome:
        ids = self._content_ids(database)
        if not self._api_key:
            # 키가 없으면 호출하지 않는다. 환경변수 대신 설정(BatchSettings)으로만 받는다.
            return JobOutcome(call_count=0, error="TOURAPI_SERVICE_KEY가 설정되지 않았습니다.")
        result = collect_public_places(ids, api_key=self._api_key, client=self._client, should_stop=should_stop)
        if result.interrupted:
            return JobOutcome(call_count=result.call_count, rejected_count=result.rejected, error=INTERRUPTED)
        if result.transport_failures:
            return JobOutcome(call_count=result.call_count, rejected_count=result.rejected, error=result.error_message)
        records = result.records

        def write(at: datetime) -> int:
            return SqlPlaceStore(database).update_collected(records, at)

        return JobOutcome(call_count=result.call_count, rejected_count=result.rejected, write=write)
