"""FR-008 예상 혼잡 계산(순수 함수). score(p,d,h) = B × M × R.

- B: 장소에 연결된 1단계 신호(DATA-04·DATA-05)를 신호마다 자기 평균으로 나눈 상대값의 가중 평균.
- M: 날짜 배수 파일 값. 없으면 곱하지 않는다(대체 상수 없음).
- R: 3단계 보정(DATA-08, P2). P0 에서는 곱하지 않는다(spec A-8).
등급은 방문일 점수를 장소별 기준 분포(B 만, 모든 평일·주말×시간대) 안의 백분위로 바꿔 설정 파일의 경계로 나눈다.
기준 분포는 M 과 무관해 안정적이고, M>1 이면 그날이 더 붐비게, M<1 이면 더 한산하게 나온다.
"""

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from datetime import date

from .schemas import CrowdConfidence, CrowdGrade
from .signals import DayType, HourlyValues

GRADES: tuple[CrowdGrade, ...] = ("여유", "보통", "붐빔", "매우 붐빔")


def day_type(on_date: date) -> DayType:
    return "WEEKEND" if on_date.weekday() >= 5 else "WEEKDAY"


def relative(values: HourlyValues) -> HourlyValues | None:
    """신호 하나를 자기 평균(모든 day_type·시간대)으로 나눈다. 값이 없거나 평균이 0 이면 쓸 수 없다(None)."""
    if not values:
        return None
    mean = sum(values.values()) / len(values)
    if mean <= 0:
        return None
    return {slot: value / mean for slot, value in values.items()}


def base_profile(weighted: Iterable[tuple[float, HourlyValues]]) -> HourlyValues:
    """(가중치, 상대값) 들의 시간대별 가중 평균. 어떤 신호에 없는 시간대는 그 시간대에 있는 신호만으로 평균한다."""
    totals: dict[tuple[DayType, int], float] = {}
    weights: dict[tuple[DayType, int], float] = {}
    for weight, values in weighted:
        for slot, value in values.items():
            totals[slot] = totals.get(slot, 0.0) + weight * value
            weights[slot] = weights.get(slot, 0.0) + weight
    return {slot: totals[slot] / weights[slot] for slot in totals}


def score(base: float, multiplier: float | None) -> float:
    """B × M. M 이 없으면 곱하지 않고 B 그대로다(상수 M 을 쓰지 않는다)."""
    if multiplier is None:
        return base
    return base * multiplier


def percentile(value: float, reference: Sequence[float]) -> float:
    """중간 순위 백분위: (작은 값 수 + 같은 값 수 / 2) / 전체 수. reference 는 오름차순 정렬돼 있어야 한다.

    값이 모두 같으면 0.5, 최댓값보다 크면 1.0, 최솟값보다 작으면 0.0.
    """
    if not reference:
        raise ValueError("reference must not be empty")
    below = bisect_left(reference, value)
    equal = bisect_right(reference, value) - below
    return (below + equal / 2) / len(reference)


def grade(rank: float, cutoffs: Sequence[float]) -> CrowdGrade:
    """백분위를 경계(오름차순 3개)로 나눈다. 경계 값과 같으면 위 등급이다."""
    for index, cutoff in enumerate(cutoffs):
        if rank < cutoff:
            return GRADES[index]
    return GRADES[len(cutoffs)]


def confidence(signal_count: int) -> CrowdConfidence:
    """실제로 쓰인 서로 다른 근거 소스 수 → 3+ 높음, 2 중간, 1 낮음, 0 없음."""
    if signal_count >= 3:
        return "높음"
    if signal_count == 2:
        return "중간"
    if signal_count == 1:
        return "낮음"
    return "없음"
