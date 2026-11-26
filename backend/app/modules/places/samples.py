"""data/samples 의 공공 장소 표본(CSV). 앱 기본 읽기 경로(`PLACE_DATA_SOURCE=csv`)이자 DB 시드의 원본이다.

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
# place_hours.origin 의 값. PARSED(파서) / MANUAL(수동 보정)
HOURS_ORIGINS = ("PARSED", "MANUAL")


@dataclass(frozen=True)
class SamplePlace:
    place: PublicPlace
    ref_date: date | None = None
    stay_min: int | None = None
    # 요일(MON~SUN) → 그날 영업시간. 행이 없는 요일은 '확인 필요'다.
    hours: Mapping[str, OpeningHours] = field(default_factory=dict)
    # 장소 상세(API-005)에 쓰는 표본 값. 비어 있으면 None 이고 화면이 '정보 없음'으로 둔다.
    indoor_outdoor: str | None = None
    closed_days_text: str | None = None
    # 표본 CSV 의 출처 표기(source_label_original) 그대로. 예: '한국관광공사 TourAPI, 비짓부산'
    source_org: str | None = None
    # 공공 데이터의 장소 설명(description 열, 있으면). 분위기 추천의 근거 문장은 여기서 원문 그대로 발췌한다.
    description: str | None = None
    # 표본 CSV 의 주소(address 열). 예상 혼잡의 날짜 배수 지역(구·군)을 고를 때 쓴다.
    address: str | None = None
    # 요일 → 영업시간 값의 출처(CSV origin 열: MANUAL·PARSED). 열이 비어 있는 요일은 없다.
    hours_origin: Mapping[str, str] = field(default_factory=dict)


class SamplePlaceData:
    """표본 장소의 엔진 PlaceDataProvider 이자 장소 검색 저장소 재료."""

    def __init__(
        self,
        places: Iterable[SamplePlace],
        kakao_overrides: Mapping[str, str] | None = None,
        invalid_hours: Iterable[tuple[str, str]] = (),
    ) -> None:
        self._places = {item.place.id: item for item in places}
        # 카카오 장소 ID → 공공 장소 ID (수동 매칭표)
        self._kakao_overrides = dict(kakao_overrides or {})
        # 영업시간 CSV 에서 읽지 못해 건너뛴 (장소 ID, 요일). 시드가 DB 의 그 요일 행을 지우지 않게 한다.
        self.invalid_hours = frozenset(invalid_hours)

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

    def place(self, place_id: str) -> SamplePlace | None:
        """공공 장소 ID 로 표본 한 곳을 찾는다. 카카오 장소 ID 는 공공 장소가 아니므로 찾지 않는다."""
        return self._places.get(place_id)

    def all(self) -> list[SamplePlace]:
        return list(self._places.values())

    def repository(self) -> InMemoryPublicPlaceRepository:
        # 시작 때 읽은 장소(CSV 또는 DB, PLACE_DATA_SOURCE)를 메모리에서 찾는다.
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
    hours_origin: dict[str, dict[str, str]] = {}
    invalid_hours: set[tuple[str, str]] = set()
    for row in _rows(directory / "place_hours.csv"):
        place_id, day_type = row.get("tourapi_contentid", ""), row.get("day_type", "")
        if not place_id or day_type not in DAY_TYPES:
            continue
        origin = row.get("origin", "").upper()
        if origin and origin not in HOURS_ORIGINS:
            invalid_hours.add((place_id, day_type))
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
            invalid_hours.add((place_id, day_type))
            continue
        if origin:
            hours_origin.setdefault(place_id, {})[day_type] = origin
    if invalid_hours:
        logger.warning("place_samples skipped_hours=%d", len(invalid_hours))

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
            SamplePlace(
                place,
                ref_date,
                _positive_int(row.get("default_stay_min", "")),
                hours.get(place.id, {}),
                indoor_outdoor=row.get("indoor_outdoor") or None,
                closed_days_text=row.get("closed_days_raw") or None,
                source_org=row.get("source_label_original") or None,
                description=row.get("description") or None,
                address=row.get("address") or None,
                hours_origin=hours_origin.get(place.id, {}),
            )
        )
    if skipped:
        logger.warning("place_samples skipped=%d", skipped)

    return SamplePlaceData(places, load_kakao_overrides(directory), invalid_hours)


def load_kakao_overrides(directory: Path = SAMPLE_DIR) -> dict[str, str]:
    """카카오 장소 ID → 공공 장소 ID 수동 매칭표(kakao_id_mapping.csv). 장소를 DB 에서 읽을 때도 이 CSV 를 쓴다."""
    return {
        row["kakao_place_id"]: row["tourapi_contentid"]
        for row in _rows(directory / "kakao_id_mapping.csv")
        if row.get("match_status") == "MATCHED"
        and row.get("kakao_place_id", "").isdigit()
        and row.get("tourapi_contentid")
    }
