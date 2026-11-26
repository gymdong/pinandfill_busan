"""FR-009 혼잡 회피: 덜 붐비는 시간대·삽입 위치 고르기.

설정값(min_confidence·min_gain)은 data/seed/crowd/crowd_config.json 의 `avoidance` 에 있다(spec A-14).
"""

from collections.abc import Sequence
from datetime import time

from pydantic import BaseModel, ConfigDict, Field

from app.modules.crowd.schemas import CrowdConfidence, PlaceCrowdResponse

# 신뢰도 순서: 없음 < 낮음 < 중간 < 높음
CONFIDENCE_RANK: dict[CrowdConfidence, int] = {"없음": 0, "낮음": 1, "중간": 2, "높음": 3}
# 0.5 - 0.45 처럼 이득이 정확히 min_gain 인 경우가 부동소수 오차로 떨어지지 않게 한다.
_FLOAT_TOLERANCE = 1e-9


class AvoidanceSettings(BaseModel):
    """혼잡 회피 배치 기준. 기본값은 spec A-14(FR-010 의 '중간 이상' 기준과 맞춤)."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    # 이 신뢰도 미만인 혼잡 정보로는 블록 위치를 바꾸지 않는다.
    min_confidence: CrowdConfidence = "중간"
    # 첫 수락 위치보다 체류 구간 평균 score(백분위)가 이만큼 이상 낮아야 다른 위치를 고른다.
    min_gain: float = Field(default=0.1, ge=0, le=1)


def meets_confidence(crowd: PlaceCrowdResponse | None, min_confidence: CrowdConfidence) -> bool:
    """혼잡 정보가 있고 신뢰도가 기준 이상인가. '없음' 은 기준과 무관하게 쓰지 않는다."""
    if crowd is None or crowd.confidence == "없음" or not crowd.hours:
        return False
    return CONFIDENCE_RANK[crowd.confidence] >= CONFIDENCE_RANK[min_confidence]


def window_cost(crowd: PlaceCrowdResponse, arrive: time, depart: time) -> float | None:
    """체류 구간(arrive~depart)이 걸친 시(h)의 score 평균. score 없는 시는 빼고, 하나도 없으면 None.

    끝 시각은 포함하지 않는다. 10:00~11:00 은 10시만, 10:30~11:15 는 10·11시에 걸친다.
    """
    start = arrive.hour * 60 + arrive.minute
    end = depart.hour * 60 + depart.minute
    last_hour = (end - 1) // 60 if end > start else arrive.hour
    scores = {hour.h: hour.score for hour in crowd.hours if hour.score is not None}
    values = [scores[h] for h in range(arrive.hour, last_hour + 1) if h in scores]
    if not values:
        return None
    return sum(values) / len(values)


def pick_less_crowded(
    crowd: PlaceCrowdResponse | None,
    candidates: Sequence[tuple[time, time]],
    *,
    min_gain: float,
    min_confidence: CrowdConfidence = "중간",
) -> int | None:
    """후보 체류 구간 중 첫 후보보다 `min_gain` 이상 덜 붐비는 최소 비용 후보의 index. 없으면 None.

    None 이면 첫 후보(지금 동작)를 그대로 쓴다. 신뢰도가 기준 미만이거나 첫 후보의 비용을 모르면
    비교 근거가 없으므로 None 이다. 비용을 모르는 후보는 고르지 않고, 비용이 같으면 앞 후보를 고른다.
    """
    if crowd is None or not candidates or not meets_confidence(crowd, min_confidence):
        return None
    baseline = window_cost(crowd, *candidates[0])
    if baseline is None:
        return None
    best: tuple[float, int] | None = None
    for index, window in enumerate(candidates[1:], start=1):
        cost = window_cost(crowd, *window)
        if cost is None or baseline - cost < min_gain - _FLOAT_TOLERANCE:
            continue
        if best is None or cost < best[0]:
            best = (cost, index)
    return best[1] if best is not None else None


def suggest_less_crowded_hour(
    crowd: PlaceCrowdResponse,
    current_hour: int,
    *,
    is_fixed: bool = False,
    allowed_hours: set[int] | None = None,
) -> int | None:
    """더 한산한 시간대를 추천한다.

    실제 일정 이동이나 영업시간 검증은 수행하지 않는다.
    """
    if not 0 <= current_hour <= 23:
        raise ValueError("current_hour must be between 0 and 23")

    if is_fixed or crowd.confidence == "없음":
        return None

    scores = {hour.h: hour.score for hour in crowd.hours if hour.score is not None}

    current_score = scores.get(current_hour)
    if current_score is None:
        return None

    candidates = [
        (hour, score)
        for hour, score in scores.items()
        if hour != current_hour and score < current_score and (allowed_hours is None or hour in allowed_hours)
    ]

    if not candidates:
        return None

    best_hour, _ = min(
        candidates,
        key=lambda item: (
            item[1],
            abs(item[0] - current_hour),
            item[0],
        ),
    )

    return best_hour
