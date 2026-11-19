"""분위기 추천(FR-015)의 재료: 테마 태그 사전과 장소별 태그·설명.

theme_tags·place_tags 테이블(홍민지)이 생기기 전에는 아래 CSV 가 있으면 읽고, 없으면 비워 둔다.
비어 있으면 추천은 '분위기를 읽지 못했어요'로 끝나고, 장소·태그를 지어내지 않는다(NFR-012).

잠정 파일 형식(데이터 담당과 합의 전):
- data/seed/theme_tags/theme_tags.csv : code,label,keywords   (keywords 는 '|' 로 구분한 문장 속 표현)
- data/samples/place_tags.csv         : tourapi_contentid,tag_code
"""

import csv
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

from app.modules.places.detail import INDOOR_OUTDOOR
from app.modules.places.samples import SAMPLE_DIR, SamplePlaceData

logger = logging.getLogger(__name__)

THEME_TAGS_FILE = SAMPLE_DIR.parent / "seed" / "theme_tags" / "theme_tags.csv"
PLACE_TAGS_FILE = SAMPLE_DIR / "place_tags.csv"


@dataclass(frozen=True)
class ThemeTag:
    code: str
    label: str
    # 문장에서 이 태그를 가리키는 표현. 규칙 해석과 근거 문장 발췌에 쓴다. 표시명도 포함한다.
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class MoodCandidate:
    """추천 후보가 되는 공공 DB 장소. 카카오 장소는 후보가 아니다(FR-015)."""

    place_id: str
    name: str
    lat: float
    lng: float
    category: str
    ref_date: date | None
    tag_codes: frozenset[str]
    description: str | None = None
    # '실내' / '야외' / '반야외' / None(모름)
    indoor_outdoor: str | None = None


class MoodDataProvider(Protocol):
    def tags(self) -> tuple[ThemeTag, ...]: ...

    def candidates(self) -> tuple[MoodCandidate, ...]: ...


class StaticMoodData:
    def __init__(self, tags: Iterable[ThemeTag], candidates: Iterable[MoodCandidate]) -> None:
        self._tags = tuple(tags)
        self._candidates = tuple(candidates)

    def tags(self) -> tuple[ThemeTag, ...]:
        return self._tags

    def candidates(self) -> tuple[MoodCandidate, ...]:
        return self._candidates


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            return [{key: (value or "").strip() for key, value in row.items() if key} for row in csv.DictReader(file)]
    except (UnicodeDecodeError, csv.Error):
        logger.warning("mood_data unreadable file=%s", path.name)
        return []


def load_theme_tags(path: Path = THEME_TAGS_FILE) -> tuple[ThemeTag, ...]:
    tags: dict[str, ThemeTag] = {}
    for row in _rows(path):
        code, label = row.get("code", ""), row.get("label", "")
        if not code or not label or code in tags:
            continue
        keywords = [label, *(word.strip() for word in row.get("keywords", "").split("|"))]
        tags[code] = ThemeTag(code, label, tuple(dict.fromkeys(word for word in keywords if word)))
    return tuple(tags.values())


def load_place_tags(path: Path = PLACE_TAGS_FILE) -> Mapping[str, frozenset[str]]:
    by_place: dict[str, set[str]] = {}
    for row in _rows(path):
        place_id, code = row.get("tourapi_contentid", ""), row.get("tag_code", "")
        if place_id and code:
            by_place.setdefault(place_id, set()).add(code)
    return {place_id: frozenset(codes) for place_id, codes in by_place.items()}


def load_mood_data(
    places: SamplePlaceData, *, theme_tags: Path = THEME_TAGS_FILE, place_tags: Path = PLACE_TAGS_FILE
) -> StaticMoodData:
    """표본 장소에 태그를 붙여 후보를 만든다. 사전에 없는 태그 코드는 버린다."""
    tags = load_theme_tags(theme_tags)
    known = {tag.code for tag in tags}
    candidates = []
    for place_id, codes in load_place_tags(place_tags).items():
        item = places.place(place_id)
        valid = codes & known
        if item is None or not valid:
            continue
        candidates.append(
            MoodCandidate(
                place_id=item.place.id,
                name=item.place.name,
                lat=item.place.lat,
                lng=item.place.lng,
                category=item.place.category,
                ref_date=item.ref_date,
                tag_codes=frozenset(valid),
                description=item.description,
                indoor_outdoor=INDOOR_OUTDOOR.get(item.indoor_outdoor or ""),
            )
        )
    logger.info("mood_data tags=%d candidates=%d", len(tags), len(candidates))
    return StaticMoodData(tags, candidates)
