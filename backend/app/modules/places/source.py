"""앱이 읽는 공공 장소 데이터의 출처(FR-016). `PLACE_DATA_SOURCE=csv|db`, 기본 csv.

- csv(기본, 비어 있거나 없을 때): data/samples CSV(`load_sample_places`). 지금까지와 같다.
- db: places·place_hours 를 `SqlPlaceStore.load()` 로 읽는다. DATABASE_URL 이 있어야 하고,
  trips 와 같은 `Database` 를 쓴다.
  카카오 매칭표(kakao_id_mapping.csv)와 장소 사진(place_photos.csv)은 db 에서도 CSV 그대로다.

앱 시작 때 한 번만 읽는다. 배치(seed-places·수집)가 DB 를 바꾸면 앱을 다시 시작해야 반영된다.
db 인데 URL 이 없거나 places 가 비어 있으면 빈 데이터로 조용히 돌지 않고 시작을 실패시킨다.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.session import BACKEND_DIR, Database

from .db_repository import SqlPlaceStore
from .samples import SamplePlaceData, load_kakao_overrides, load_sample_places


class PlaceSourceSettings(BaseSettings):
    """환경변수 `PLACE_DATA_SOURCE` 또는 backend/.env 에서 읽는다. 빈 값은 없는 것으로 본다(csv)."""

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore", env_ignore_empty=True)

    place_data_source: Literal["csv", "db"] = "csv"


class PlaceSourceError(RuntimeError):
    """db 읽기 경로를 쓸 수 없다. 앱 시작을 멈춘다."""


def load_places(database: Database | None, settings: PlaceSourceSettings | None = None) -> SamplePlaceData:
    source = (settings or PlaceSourceSettings()).place_data_source
    if source == "csv":
        return load_sample_places()
    if database is None:
        raise PlaceSourceError("PLACE_DATA_SOURCE=db requires DATABASE_URL")
    places = SqlPlaceStore(database).load()
    if not places:
        raise PlaceSourceError(
            "PLACE_DATA_SOURCE=db but the places table is empty: run `alembic upgrade head` and "
            "`python -m app.batch.cli seed-places`, or unset PLACE_DATA_SOURCE"
        )
    return SamplePlaceData(places, load_kakao_overrides())
