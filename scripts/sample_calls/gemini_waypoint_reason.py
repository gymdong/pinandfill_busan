"""경유지 추천 이유 문구(API-011)를 실제 Gemini 로 확인한다(수동 전용, 테스트·CI 에서 쓰지 않는다).

data/samples 의 공공 장소 표본 세 곳으로 경유지 후보를 흉내 낸다. 우회 분은 확인용 예시 값이고,
체류 분은 표본의 기본 체류시간이다. 경로 API 는 부르지 않는다. backend/.env 의 GEMINI_API_KEY 를 읽는다.

사용: cd backend && uv run python ../scripts/sample_calls/gemini_waypoint_reason.py
"""

import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.modules.ai.waypoint_reason import build_waypoint_reason_service  # noqa: E402
from app.modules.places.samples import load_sample_places  # noqa: E402
from app.modules.trips.schemas import (  # noqa: E402
    CrowdSummary,
    PlaceSummary,
    SuggestWaypointsResponse,
    WaypointCandidate,
)

# (표본 장소 ID, 예시 우회 분, 예시 예상 혼잡 등급)
EXAMPLES = (("130166", 9, "여유"), ("126148", 14, None), ("2815627", 12, "붐빔"))
CAVEAT = "출발시각별 시간표·교통 예측은 아님"


def sample_response() -> SuggestWaypointsResponse:
    places = load_sample_places()
    candidates = []
    for place_id, detour, grade in EXAMPLES:
        sample = places.place(place_id)
        if sample is None or sample.stay_min is None:
            continue
        place = sample.place
        crowd = CrowdSummary(grade=grade, confidence="중간", as_of=None, sources=("예시",)) if grade else None
        candidates.append(
            WaypointCandidate(
                place=PlaceSummary(
                    id=place.id,
                    name=place.name,
                    lat=place.lat,
                    lng=place.lng,
                    category=place.category,
                    source="PUBLIC",
                    ref_date=sample.ref_date or date.today(),
                ),
                detour_min=detour,
                stay_min=sample.stay_min,
                crowd=crowd,
                reason=f"우회 {detour}분·체류 {sample.stay_min}분, 후보 영업시간과 후속 시간 제약 확인; {CAVEAT}",
            )
        )
    return SuggestWaypointsResponse(candidates=tuple(candidates))


async def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    before = sample_response()
    after = await build_waypoint_reason_service().explain(before)
    for old, new in zip(before.candidates, after.candidates, strict=True):
        print(f"- {new.place.name} (우회 {new.detour_min}분, 체류 {new.stay_min}분)")
        print(f"  규칙: {old.reason}")
        print(f"  결과: {new.reason}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
