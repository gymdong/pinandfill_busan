"""API-013 `POST /recommend/mood`. 프런트 `MoodRequest`·`MoodResponse`(frontend/src/types/api.ts)와 같다.

SD-03 순서대로 두 번 부른다: 문장을 보내면 태그·피할 조건만 돌려주고(places 비움),
태그를 보내면 그 태그로 공공 DB 장소를 추천한다.
"""

from datetime import date
from typing import Annotated, Literal, Self

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, model_validator

from app.modules.ai.sanitizer import InvalidInputError
from app.modules.engine.schemas import ContractModel
from app.modules.places.api_schemas import PlaceDetailPhoto, SourceInfo
from app.modules.places.router import PlaceAPIError
from app.modules.places.samples import load_sample_places

from .mood import MoodService, UnknownMoodValueError, build_mood_service
from .mood_data import ThemeTag, load_mood_data

router = APIRouter(prefix="/recommend", tags=["recommend"])


class MoodRequest(ContractModel):
    # 혼잡 기준일. 혼잡 요약이 붙기 전까지는 형식만 검사한다.
    date: date
    limit: int = Field(10, ge=1, le=20)
    text: str | None = None
    tags: tuple[Annotated[str, Field(min_length=1, max_length=40)], ...] | None = Field(None, max_length=10)
    avoid: tuple[Annotated[str, Field(min_length=1, max_length=20)], ...] = Field((), max_length=5)

    @model_validator(mode="after")
    def text_or_tags(self) -> Self:
        if (self.text is None) == (self.tags is None):
            raise ValueError("send either text or tags")
        if self.text is not None and self.avoid:
            raise ValueError("avoid goes with tags")
        return self


class ThemeTagOut(ContractModel):
    code: str
    label: str


class MoodPlaceSummary(ContractModel):
    """공공 DB 장소(PlaceSummary). 카카오 장소는 추천하지 않는다."""

    id: str
    name: str
    lat: float
    lng: float
    category: str
    source: Literal["PUBLIC"] = "PUBLIC"
    ref_date: date | None = None


class MoodEvidence(ContractModel):
    matched_tags: tuple[str, ...]
    # 장소 설명 원문의 한 문장. 없으면 null('근거 문장 정보 없음')
    excerpt: str | None = None
    # 근거 문장(장소 설명)의 출처 기관·기준일. 발췌가 없거나 출처 기관을 모르면 null 이다(NFR-007).
    source: SourceInfo | None = None


class MoodPlace(ContractModel):
    place: MoodPlaceSummary
    # 대표 사진(FR-014). 없으면 null('사진 없음')이다.
    photo: PlaceDetailPhoto | None = None
    # 혼잡 데이터가 들어오기 전에는 null('정보 부족')이다.
    evidence: MoodEvidence
    crowd: None = None


class MoodResponse(ContractModel):
    tags: tuple[ThemeTagOut, ...] = ()
    avoid: tuple[str, ...] = ()
    places: tuple[MoodPlace, ...] = ()


def mood_service(request: Request) -> MoodService:
    """주입한 서비스가 없으면 표본 데이터와 환경 설정(GEMINI_*)으로 한 번 만들어 재사용한다."""
    service = getattr(request.app.state, "mood_service", None)
    if not isinstance(service, MoodService):
        service = build_mood_service(load_mood_data(load_sample_places()))
        request.app.state.mood_service = service
    return service


Service = Annotated[MoodService, Depends(mood_service)]


def _tags_out(tags: tuple[ThemeTag, ...]) -> tuple[ThemeTagOut, ...]:
    return tuple(ThemeTagOut(code=tag.code, label=tag.label) for tag in tags)


@router.post("/mood", response_model=MoodResponse)
async def recommend_mood(body: MoodRequest, response: Response, service: Service) -> MoodResponse:
    """LLM 이 실패해도 사전 키워드 규칙 결과로 200 을 돌려준다(AC-016). 문장은 로그·오류에 남기지 않는다."""
    response.headers["Cache-Control"] = "no-store"
    if body.text is not None:
        try:
            interpreted = await service.interpret(body.text)
        except InvalidInputError:
            raise PlaceAPIError(
                400, "ERR-001", "입력할 수 없는 내용이에요. 원하는 분위기를 짧게 적어 주세요."
            ) from None
        return MoodResponse(tags=_tags_out(interpreted.tags), avoid=interpreted.avoid)

    assert body.tags is not None
    try:
        tags = service.tags_for(body.tags)
        found = service.recommend(tags, body.avoid, body.limit)
    except UnknownMoodValueError:
        raise PlaceAPIError(400, "ERR-001", "태그와 피할 조건을 다시 골라 주세요.") from None
    return MoodResponse(
        tags=_tags_out(tags),
        avoid=body.avoid,
        places=tuple(
            MoodPlace(
                place=MoodPlaceSummary(
                    id=item.candidate.place_id,
                    name=item.candidate.name,
                    lat=item.candidate.lat,
                    lng=item.candidate.lng,
                    category=item.candidate.category,
                    ref_date=item.candidate.ref_date,
                ),
                photo=item.candidate.photo,
                evidence=MoodEvidence(
                    matched_tags=item.matched_tags,
                    excerpt=item.excerpt,
                    source=(
                        SourceInfo(org=item.candidate.source_org, ref_date=item.candidate.ref_date)
                        if item.excerpt is not None and item.candidate.source_org
                        else None
                    ),
                ),
            )
            for item in found
        ),
    )
