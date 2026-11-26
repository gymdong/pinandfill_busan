"""공공 장소 표본의 DB 저장소(places·place_hours, FR-016).

열의 주인을 나눈다.
- 시드(`upsert_seed`, data/samples CSV)가 수동 값을 쓴다: 카테고리·영업시간(origin 포함)·체류시간·실내외·휴무 원문·
  설명·출처 기관·ref_date(수동 확인 기준일).
- 배치(`update_collected`)는 이름·좌표·주소·collected_at 만 쓴다. ref_date·영업시간·source_org 는 건드리지 않는다
  (NFR-012: MANUAL 영업시간의 기준일을 수집일로 덮어쓰지 않는다).
- 이름·좌표·주소는 배치가 한 번 갱신한 뒤(collected_at 이 있으면) 시드가 다시 덮어쓰지 않는다.

앱 읽기 경로는 아직 CSV 다. `load()` 는 DB 읽기 경로(U5)가 쓸 `SamplePlace` 목록을 만든다.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select

from app.batch.jobs.public_places import PublicPlaceRecord
from app.db.models import PlaceHourRow, PlaceRow
from app.db.session import Database
from app.modules.engine.schemas import OpeningHours

from .samples import DAY_TYPES, SamplePlace
from .schemas import PlaceHours, PublicPlace

PUBLIC = "PUBLIC"
# 표본 CSV 는 사람이 확인해 적은 값이다. origin 열이 비어 있으면 MANUAL 로 본다.
DEFAULT_HOURS_ORIGIN = "MANUAL"


class SqlPlaceStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_seed(self, places: Iterable[SamplePlace], at: datetime) -> int:
        """표본 장소를 넣거나 갱신한다. 같은 표본으로 다시 불러도 결과가 같다. 표본에 없는 행은 지우지 않는다."""
        count = 0
        with self.database.transaction() as session:
            for item in places:
                place = item.place
                row = session.get(PlaceRow, place.id)
                if row is None:
                    row = PlaceRow(id=place.id, source=PUBLIC, source_ref=place.id)
                    session.add(row)
                if row.collected_at is None:
                    row.name, row.lat, row.lng, row.address = place.name, place.lat, place.lng, item.address
                row.category = place.category
                row.description = item.description
                row.closed_days_text = item.closed_days_text
                row.default_stay_min = item.stay_min
                row.indoor_outdoor = item.indoor_outdoor
                row.source_org = item.source_org
                row.ref_date = item.ref_date
                row.updated_at = at
                self._replace_hours(item)
                count += 1
        return count

    def _replace_hours(self, item: SamplePlace) -> None:
        with self.database.transaction() as session:
            existing = {
                row.day_type: row
                for row in session.scalars(select(PlaceHourRow).where(PlaceHourRow.place_id == item.place.id))
            }
            for day_type, row in existing.items():
                if day_type not in item.hours:
                    session.delete(row)
            session.flush()
            for day_type, hours in item.hours.items():
                row = existing.get(day_type) or PlaceHourRow(place_id=item.place.id, day_type=day_type)
                row.open_time, row.close_time = hours.open_time, hours.close_time
                row.break_start, row.break_end = hours.break_start, hours.break_end
                row.is_closed = hours.is_closed
                row.origin = item.hours_origin.get(day_type, DEFAULT_HOURS_ORIGIN)
                session.add(row)

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
        for row in rows:
            days = sorted(hour_rows.get(row.id, []), key=lambda hour: DAY_TYPES.index(hour.day_type))
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
        return result
