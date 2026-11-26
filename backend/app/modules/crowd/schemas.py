"""FR-008 예상 혼잡 API의 응답 데이터 형식."""

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.modules.engine.schemas import ContractModel

CrowdGrade = Literal["여유", "보통", "붐빔", "매우 붐빔"]
CrowdConfidence = Literal["높음", "중간", "낮음", "없음"]


class CrowdHour(ContractModel):
    """한 시간대의 예상 혼잡도."""

    h: int = Field(ge=0, le=23)
    grade: CrowdGrade | None = None
    score: float | None = Field(default=None, ge=0, le=1)


class PlaceCrowdResponse(ContractModel):
    """API-012 시간대별 예상 혼잡 응답."""

    hours: list[CrowdHour] = Field(default_factory=list)
    confidence: CrowdConfidence = "없음"
    as_of: datetime | None = None
    sources: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_crowd_consistency(self):
        """혼잡도 데이터, 신뢰도, 출처 및 기준 시각의 일관성을 검증한다."""
        if self.confidence == "없음" and self.hours:
            raise ValueError("신뢰도가 '없음'이면 혼잡도 시간대 데이터가 없어야 합니다.")

        if self.hours:
            if self.as_of is None:
                raise ValueError("혼잡도 데이터가 있으면 기준 시각(as_of)이 필요합니다.")
            if not self.sources or any(not source.strip() for source in self.sources):
                raise ValueError("혼잡도 데이터가 있으면 유효한 출처(sources)가 필요합니다.")

        return self
