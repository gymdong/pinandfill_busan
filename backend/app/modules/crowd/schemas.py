"""FR-008 예상 혼잡 API의 응답 데이터 형식."""

from datetime import datetime
from typing import Literal

from pydantic import Field

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
