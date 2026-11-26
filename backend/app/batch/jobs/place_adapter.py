"""FR-016: TourAPI 검증 결과를 기존 장소 모델에 연결한다."""

from app.modules.places.samples import SamplePlaceData
from app.modules.places.schemas import PublicPlace

from .public_places import PublicPlaceRecord


def to_existing_place(
    record: PublicPlaceRecord,
    samples: SamplePlaceData,
) -> PublicPlace | None:
    """기존 장소 데이터가 있는 경우에만 변환한다.

    category와 hours는 팀의 기존 데이터를 유지한다.
    이 함수는 CSV 또는 DB를 변경하지 않는다.
    """
    existing = samples.place(record.content_id)
    if existing is None:
        return None

    return PublicPlace(
        id=record.content_id,
        name=record.name,
        lat=record.latitude,
        lng=record.longitude,
        category=existing.place.category,
        hours=existing.place.hours,
    )
