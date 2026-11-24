"""장소 사진(FR-014). place_photos 테이블이 생기기 전에는 data/samples/place_photos.csv 표본을 읽는다.

잠정 파일 형식(데이터 담당과 합의 전): tourapi_contentid,url,source_org,license_type,is_primary
- source_org: 출처 기관(한국관광공사·부산시 등). 비어 있으면 그 사진은 쓰지 않는다(NFR-007).
- license_type: 저작권 유형(공공누리 제1유형 등). 비어 있으면 그 사진은 쓰지 않는다(ERR-013).
- is_primary: TRUE 면 대표 사진이다.

사진이 없으면 화면이 '사진 없음'을 보여 준다. 다른 출처의 사진으로 채우지 않는다(FR-014).
"""

import csv
import logging
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from .api_schemas import PlaceDetailPhoto
from .samples import SAMPLE_DIR

logger = logging.getLogger(__name__)

PLACE_PHOTOS_FILE = SAMPLE_DIR / "place_photos.csv"
# place_photos.url·source_org·license_type 길이(SDD 5.2)
_MAX_URL = 500
_MAX_ORG = 50
_MAX_LICENSE = 50


class PlacePhotos:
    """장소별 사진. 대표 사진을 먼저 둔다."""

    def __init__(self, photos: Iterable[tuple[str, PlaceDetailPhoto]] = ()) -> None:
        by_place: dict[str, list[PlaceDetailPhoto]] = {}
        for place_id, photo in photos:
            by_place.setdefault(place_id, []).append(photo)
        # 대표 사진을 앞으로 옮기고, 나머지는 파일 순서를 지킨다.
        self._by_place = {
            place_id: tuple(sorted(items, key=lambda photo: not photo.is_primary))
            for place_id, items in by_place.items()
        }

    def photos(self, place_id: str) -> tuple[PlaceDetailPhoto, ...]:
        return self._by_place.get(place_id, ())

    def primary(self, place_id: str) -> PlaceDetailPhoto | None:
        """추천 카드에 보일 한 장. 대표 사진이 없으면 첫 사진이다."""
        photos = self.photos(place_id)
        return photos[0] if photos else None


def _is_web_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and len(value) <= _MAX_URL


def load_place_photos(path: Path = PLACE_PHOTOS_FILE) -> PlacePhotos:
    """표본 사진을 읽는다. 파일이 없거나 깨졌으면 사진 없이 시작한다(앱 시작을 막지 않는다)."""
    if not path.is_file():
        return PlacePhotos()
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(file)]
    except (UnicodeDecodeError, csv.Error):
        logger.warning("place_photos unreadable file=%s", path.name)
        return PlacePhotos()

    photos: list[tuple[str, PlaceDetailPhoto]] = []
    seen: set[tuple[str, str]] = set()
    missing_license = invalid = 0
    for row in rows:
        place_id, url = row.get("tourapi_contentid", ""), row.get("url", "")
        source_org, license_type = row.get("source_org", ""), row.get("license_type", "")
        if not place_id or not _is_web_url(url) or not source_org or len(source_org) > _MAX_ORG:
            invalid += 1
            continue
        if not license_type or len(license_type) > _MAX_LICENSE:
            # 저작권 유형을 모르는 사진은 보여 주지 않는다(ERR-013).
            missing_license += 1
            continue
        if (place_id, url) in seen:
            continue
        seen.add((place_id, url))
        photos.append(
            (
                place_id,
                PlaceDetailPhoto(
                    # 같은 사진은 다시 읽어도 같은 ID 다.
                    id=str(uuid5(NAMESPACE_URL, f"{place_id} {url}")),
                    url=url,
                    source_org=source_org,
                    license_type=license_type,
                    is_primary=row.get("is_primary", "").upper() == "TRUE",
                ),
            )
        )
    # URL 은 남기지 않고 건수만 남긴다.
    logger.info("place_photos loaded=%d missing_license=%d invalid=%d", len(photos), missing_license, invalid)
    return PlacePhotos(photos)
