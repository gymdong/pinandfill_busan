"""FR-009 혼잡도가 낮은 대체 방문 시간대 추천."""

from app.modules.crowd.schemas import PlaceCrowdResponse


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
