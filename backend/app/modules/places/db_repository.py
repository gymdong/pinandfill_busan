"""공공 장소 표본의 DB 저장소(places·place_hours, FR-016).

열의 주인을 나눈다.
- 시드(`upsert_seed`, data/samples CSV)가 수동 값을 쓴다: 카테고리·영업시간(origin 포함)·체류시간·실내외·휴무 원문·
  설명·출처 기관·ref_date(수동 확인 기준일).
- 배치(`update_collected`)는 이름·좌표·주소·collected_at 만 쓴다. ref_date·영업시간·source_org 는 건드리지 않는다
  (NFR-012: MANUAL 영업시간의 기준일을 수집일로 덮어쓰지 않는다).
- 이름·좌표·주소는 배치가 한 번 갱신한 뒤(collected_at 이 있으면) 시드가 다시 덮어쓰지 않는다.
- 시드는 CSV 에 없는 영업시간 행(DB 에서 직접 넣은 MANUAL 행 등)을 지우지 않는다. `prune=True` 일 때만 지운다.
  CSV 에서 읽지 못한 행(예: 초가 붙은 시각)의 요일은 `prune` 이어도 DB 행을 그대로 둔다.
- 값이 바뀐 장소만 updated_at 을 바꾼다.

앱 읽기 경로는 아직 CSV 다. `load()` 는 DB 읽기 경로(U5)가 쓸 `SamplePlace` 목록을 만든다.
"""

import logging
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.batch.jobs.public_places import PublicPlaceRecord
from app.db.models import PlaceHourRow, PlaceRow
from app.db.session import Database
from app.modules.engine.schemas import OpeningHours

from .samples import DAY_TYPES, SamplePlace
from .schemas import PlaceHours, PublicPlace

logger = logging.getLogger(__name__)

PUBLIC = "PUBLIC"
# 표본 CSV 는 사람이 확인해 적은 값이다. origin 열이 비어 있으면 MANUAL 로 본다.
DEFAULT_HOURS_ORIGIN = "MANUAL"


@dataclass(frozen=True)
class SeedResult:
    places: int
    # 값이 바뀐(새로 넣은 것 포함) 장소 수
    changed: int
    # CSV 에서 읽지 못해 DB 값을 그대로 둔 영업시간 행 수
    kept_invalid: int
    # CSV 에 없어 그대로 둔 영업시간 행 수(prune 이 아닐 때)
    kept_unlisted: int
    # CSV 에 없어 지운 영업시간 행 수(prune 일 때)
    pruned: int


def _assign(row: Any, values: dict[str, Any]) -> bool:
    changed = False
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed = True
    return changed


class SqlPlaceStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_seed(
        self,
        places: Iterable[SamplePlace],
        at: datetime,
        *,
        invalid_hours: Collection[tuple[str, str]] = (),
        prune: bool = False,
    ) -> SeedResult:
        """표본 장소를 넣거나 갱신한다. 같은 표본으로 다시 불러도 결과가 같다. 표본에 없는 장소 행은 지우지 않는다.

        `invalid_hours` 는 CSV 에서 읽지 못한 (장소 ID, 요일)이다(`SamplePlaceData.invalid_hours`).
        """
        count = changed = kept_invalid = kept_unlisted = pruned = 0
        with self.database.transaction() as session:
            for item in places:
                place = item.place
                row = session.get(PlaceRow, place.id)
                dirty = row is None
                if row is None:
                    row = PlaceRow(id=place.id, source=PUBLIC, source_ref=place.id, updated_at=at)
                    session.add(row)
                values: dict[str, Any] = {
                    "category": place.category,
                    "description": item.description,
                    "closed_days_text": item.closed_days_text,
                    "default_stay_min": item.stay_min,
                    "indoor_outdoor": item.indoor_outdoor,
                    "source_org": item.source_org,
                    "ref_date": item.ref_date,
                }
                if row.collected_at is None:
                    values |= {"name": place.name, "lat": place.lat, "lng": place.lng, "address": item.address}
                dirty = _assign(row, values) or dirty

                existing = {
                    hour.day_type: hour
                    for hour in session.scalars(select(PlaceHourRow).where(PlaceHourRow.place_id == place.id))
                }
                for day_type, hour in existing.items():
                    if day_type in item.hours:
                        continue
                    if (place.id, day_type) in invalid_hours:
                        kept_invalid += 1
                    elif prune:
                        session.delete(hour)
                        pruned += 1
                        dirty = True
                    else:
                        kept_unlisted += 1
                session.flush()
                for day_type, hours in item.hours.items():
                    current = existing.get(day_type)
                    if current is None:
                        current = PlaceHourRow(place_id=place.id, day_type=day_type)
                        session.add(current)
                        dirty = True
                    hour_values = {
                        "open_time": hours.open_time,
                        "close_time": hours.close_time,
                        "break_start": hours.break_start,
                        "break_end": hours.break_end,
                        "is_closed": hours.is_closed,
                        "origin": item.hours_origin.get(day_type, DEFAULT_HOURS_ORIGIN),
                    }
                    dirty = _assign(current, hour_values) or dirty
                if dirty:
                    row.updated_at = at
                    changed += 1
                count += 1
        if kept_invalid or kept_unlisted:
            logger.warning(
                "place_seed kept_hours invalid_in_csv=%d not_in_csv=%d (prune=%s)", kept_invalid, kept_unlisted, prune
            )
        return SeedResult(count, changed, kept_invalid, kept_unlisted, pruned)

    def update_collected(self, records: Iterable[PublicPlaceRecord], at: datetime) -> int:
        """배치 수집 결과로 이미 있는 장소의 이름·좌표·주소·collected_at 만 바꾼다. 갱신한 장소 수를 돌려준다."""
        count = 0
        with self.database.transaction() as session:
            for record in records:
                row = session.get(PlaceRow, record.content_id)
                if row is None:
                    continue
                row.name, row.lat, row.lng = record.name, record.latitude, record.longitude
                row.address = record.address or row.address
                row.collected_at = at
                row.updated_at = at
                count += 1
        return count

    def public_ids(self) -> list[str]:
        with self.database.transaction() as session:
            return list(session.scalars(select(PlaceRow.id).where(PlaceRow.source == PUBLIC).order_by(PlaceRow.id)))

    def load(self) -> list[SamplePlace]:
        """DB 의 공공 장소를 `load_sample_places()` 와 같은 모양으로 읽는다(장소 ID 순)."""
        with self.database.transaction() as session:
            rows = session.scalars(select(PlaceRow).where(PlaceRow.source == PUBLIC).order_by(PlaceRow.id)).all()
            hour_rows: dict[str, list[PlaceHourRow]] = {}
            for hour in session.scalars(select(PlaceHourRow)):
                hour_rows.setdefault(hour.place_id, []).append(hour)
        result = []
        unknown = 0
        for row in rows:
            # HOLIDAY 등 요일이 아닌 행은 아직 엔진이 쓰지 않으므로 읽지 않는다.
            known = [hour for hour in hour_rows.get(row.id, []) if hour.day_type in DAY_TYPES]
            unknown += len(hour_rows.get(row.id, [])) - len(known)
            days = sorted(known, key=lambda hour: DAY_TYPES.index(hour.day_type))
            hours = {
                hour.day_type: OpeningHours(
                    is_closed=hour.is_closed,
                    open_time=hour.open_time,
                    close_time=hour.close_time,
                    break_start=hour.break_start,
                    break_end=hour.break_end,
                )
                for hour in days
            }
            place = PublicPlace(
                id=row.id,
                name=row.name,
                lat=row.lat,
                lng=row.lng,
                category=row.category,
                hours=tuple(
                    PlaceHours(
                        day_type=day_type,
                        open_time=value.open_time,
                        close_time=value.close_time,
                        is_closed=value.is_closed,
                    )
                    for day_type, value in hours.items()
                ),
            )
            result.append(
                SamplePlace(
                    place,
                    row.ref_date,
                    row.default_stay_min,
                    hours,
                    indoor_outdoor=row.indoor_outdoor,
                    closed_days_text=row.closed_days_text,
                    source_org=row.source_org,
                    description=row.description,
                    address=row.address,
                    hours_origin={hour.day_type: hour.origin for hour in days},
                )
            )
        if unknown:
            logger.warning("place_store skipped_hours day_type_not_weekday=%d", unknown)
        return result
