"""data/samples 의 공공 장소 표본(CSV). places·place_hours 테이블이 생기기 전 로컬 기본 구성에서만 쓴다.

값이 비어 있거나 읽을 수 없으면 지어내지 않고 비워 둔다. 엔진이 '확인 필요' 경고로 알린다.
카카오는 매칭표의 장소 ID 만 읽는다(이름·좌표 등 카카오 장소 정보는 저장하지 않는다).
"""

import csv
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, time
from pathlib import Path

from app.modules.engine.schemas import OpeningHours, PlaceRef, PublicPlaceRef, TransientPlaceDetails
from app.modules.trips.schemas import KakaoPlaceKey, PublicPlaceInput

from .repository import InMemoryPublicPlaceRepository
from .schemas import PlaceHours, PublicPlace

logger = logging.getLogger(__name__)

SAMPLE_DIR = Path(__file__).resolve().parents[4] / "data" / "samples"
DAY_TYPES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


@dataclass(frozen=True)
class SamplePlace:
    place: PublicPlace
    ref_date: date | None = None
    stay_min: int | None = None
    # 요일(MON~SUN) → 그날 영업시간. 행이 없는 요일은 '확인 필요'다.
    hours: Mapping[str, OpeningHours] = field(default_factory=dict)


class SamplePlaceData:
    """표본 장소의 엔진 PlaceDataProvider 이자 장소 검색 저장소 재료."""

    def __init__(self, places: Iterable[SamplePlace], kakao_overrides: Mapping[str, str] | None = None) -> None:
        self._places = {item.place.id: item for item in places}
        # 카카오 장소 ID → 공공 장소 ID (수동 매칭표)
        self._kakao_overrides = dict(kakao_overrides or {})

    def get(self, place_ref: PlaceRef, *, on_date: date) -> TransientPlaceDetails:
        item = self._places.get(place_ref.place_id) if isinstance(place_ref, PublicPlaceRef) else None
        if item is None:
            # 모르는 장소는 표시 정보를 비워 두어 엔진이 '확인 필요'로 처리한다.
            return TransientPlaceDetails(place_ref=place_ref)
        return TransientPlaceDetails(
            place_ref=place_ref,
            name=item.place.name,
            lat=item.place.lat,
            lng=item.place.lng,
            category=item.place.category,
            ref_date=item.ref_date,
            hours=item.hours.get(DAY_TYPES[on_date.weekday()]),
        )

    def stay_min(self, place: PublicPlaceInput | KakaoPlaceKey) -> int | None:
        """표본의 기본 체류시간. 카카오 장소는 매칭표로 이어진 공공 장소 값만 쓴다. 근거가 없으면 None"""
        if isinstance(place, PublicPlaceInput):
            place_id: str | None = place.place_id
        else:
            place_id = self._kakao_overrides.get(place.kakao_place_id)
        item = self._places.get(place_id) if place_id is not None else None
        return item.stay_min if item is not None else None

    def repository(self) -> InMemoryPublicPlaceRepository:
        return InMemoryPublicPlaceRepository((item.place for item in self._places.values()), self._kakao_overrides)


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        logger.warning("place_samples missing file=%s", path.name)
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(file)]
    except (UnicodeDecodeError, csv.Error):
        # 파일 하나가 깨져도 앱 시작을 막지 않는다. 그 파일의 값은 비워 두고 '확인 필요'로 남긴다.
        logger.warning("place_samples unreadable file=%s", path.name)
        return []


def _time(value: str) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


def _positive_int(value: str) -> int | None:
    try:
        number = int(value)
    except ValueError:
        return None
    return number if number > 0 else None


def load_sample_places(directory: Path = SAMPLE_DIR) -> SamplePlaceData:
    hours: dict[str, dict[str, OpeningHours]] = {}
    skipped_hours = 0
    for row in _rows(directory / "place_hours.csv"):
        place_id, day_type = row.get("tourapi_contentid", ""), row.get("day_type", "")
        if not place_id or day_type not in DAY_TYPES:
            continue
        try:
            hours.setdefault(place_id, {})[day_type] = OpeningHours(
                is_closed=row.get("is_closed", "").upper() == "TRUE",
                open_time=_time(row.get("open_time", "")),
                close_time=_time(row.get("close_time", "")),
                break_start=_time(row.get("break_start", "")),
                break_end=_time(row.get("break_end", "")),
            )
        except ValueError:  # pydantic ValidationError 포함(예: 초가 붙은 시각)
            skipped_hours += 1
    if skipped_hours:
        logger.warning("place_samples skipped_hours=%d", skipped_hours)

    places: list[SamplePlace] = []
    skipped = 0
    for row in _rows(directory / "places_sample.csv"):
        place_id = row.get("tourapi_contentid", "")
        try:
            place = PublicPlace(
                id=place_id,
                name=row["name"],
                lat=float(row["lat"]),
                lng=float(row["lng"]),
                category=row["category"],
                hours=tuple(
                    PlaceHours(
                        day_type=day_type,
                        open_time=value.open_time,
                        close_time=value.close_time,
                        is_closed=value.is_closed,
                    )
                    for day_type, value in hours.get(place_id, {}).items()
                ),
            )
            ref_date = date.fromisoformat(row["checked_at"]) if row.get("checked_at") else None
        except (KeyError, ValueError):
            skipped += 1
            continue
        if not place.id or not place.name or not place.category:
            skipped += 1
            continue
        places.append(
            SamplePlace(place, ref_date, _positive_int(row.get("default_stay_min", "")), hours.get(place.id, {}))
        )
    if skipped:
        logger.warning("place_samples skipped=%d", skipped)

    overrides = {
        row["kakao_place_id"]: row["tourapi_contentid"]
        for row in _rows(directory / "kakao_id_mapping.csv")
        if row.get("match_status") == "MATCHED"
        and row.get("kakao_place_id", "").isdigit()
        and row.get("tourapi_contentid")
    }
    return SamplePlaceData(places, overrides)
