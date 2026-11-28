"""저장 전 수락 검사에 쓰는 판정. 편집(API-006~008)·플랜 B(API-014·015)가 같은 기준을 쓴다."""

from app.modules.engine.interfaces import EngineResult

# 고정 블록이 이 경고를 받으면 지정 시각을 지킬 수 없는 결과다.
FIXED_TIMING_ERRORS = frozenset(
    {
        "TRAVEL_TIME_CONFLICT",
        "FIXED_TIME_CONFLICT",
        "STAY_CONFLICT",
        "DAY_WINDOW_CONFLICT",
        "TIME_WINDOW_UNSUPPORTED",
    }
)


def fixed_timing_conflicts(result: EngineResult, *, days: set[int] | None = None) -> set[str]:
    """고정 시각을 지킬 수 없는 고정 블록 ID. `days` 를 주면 그 날만 본다."""
    return {
        block.id
        for day in result.schedule.days
        if days is None or day.day_no in days
        for block in day.blocks
        if block.is_fixed and any(warning.type in FIXED_TIMING_ERRORS for warning in block.warnings)
    }
