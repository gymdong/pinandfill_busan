"""경유지 추천 이유 문구(FR-004, API-011)의 LLM 설명 경로(SDD 7.3 (3), AI-REQ-03·04·05).

후보와 수치는 엔진이 이미 계산해 정한 값이다. 여기서는 각 후보의 '이유' 문장만 다시 쓴다.
- LLM 에는 엔진이 낸 값(우회·체류 분, 예상 혼잡)과 공공 DB 의 장소 이름·분류만 넘긴다.
  카카오 정보와 좌표는 넘기지 않는다.
- 출력은 후보마다 OutputGuard 로 검사한다. 엔진 값과 다른 수치, '실시간' 같은 금지 표현, 혼잡 등급과 맞지 않는 말,
  다른 후보의 이름이 있으면 그 후보는 규칙 문구를 그대로 둔다(AI-REQ-04).
- LLM 이 실패하거나 시간 안에 답하지 않으면 모든 후보가 규칙 문구다(ERR-002, 200).
- 규칙 문구 뒤의 확인 필요 안내(';' 뒤)는 LLM 문장 뒤에 그대로 붙인다. 설명을 바꿔도 경고는 빠지지 않는다.
"""

import asyncio
import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.trips.schemas import SuggestWaypointsResponse, WaypointCandidate

from .providers.base import LlmError, LlmProvider
from .settings import AISettings

logger = logging.getLogger(__name__)

# 엔진 규칙 문구(recommend/waypoints.py)는 '기본 설명; 확인 필요 안내; …' 형식이다.
RULE_CAVEAT_SEPARATOR = "; "
REASON_MAX_CHARS = 60

# 확인할 수 없는 단정·실시간 표현(NFR-012, AI-REQ-04)
_FORBIDDEN = re.compile(r"실시간|라이브|지금|현재|보장|반드시|무조건|확실|영업\s*중|문\s*(을\s*)?열|https?://|www\.")
# 혼잡을 말하는 표현. 혼잡 근거가 없으면 쓰지 못하고, 근거가 있으면 '예상'과 함께 등급에 맞게만 쓴다.
_QUIET_WORDS = re.compile(r"여유|한산|한적|조용")
_BUSY_WORDS = re.compile(r"붐비|붐빔|북적|복잡")
_CROWD_WORDS = re.compile(r"혼잡|사람")
_NUMBER = re.compile(r"\d+")
_WHITESPACE = re.compile(r"\s+")

_SYSTEM_PROMPT = (
    "You write a short Korean reason for each recommended stop on the way between two places in Busan.\n\n"
    "Rules:\n"
    "- The facts are inside <facts> tags as JSON. Use only these facts. Never invent places, numbers, hours, "
    "prices or events.\n"
    "- One reason per candidate, in Korean, at most 40 characters, a noun-phrase style like the examples. "
    "No line breaks.\n"
    "- Numbers: you may only use detourMin or stayMin of that candidate, followed by '분'. No other numbers.\n"
    "- Crowd: mention crowd only if crowdGrade is not null, and then always with the word '예상' "
    "(for example '예상 혼잡 여유'). Never say real-time, now or currently.\n"
    "- Do not mention opening hours, and do not mention other candidates by name.\n"
    "- Examples: '우회가 가장 짧은 전시·문화 공간', '체류 40분이면 둘러보기 좋은 관광지', '예상 혼잡 여유로운 시장'.\n"
    'Return JSON: {"reasons": [{"placeId": string, "text": string}]}'
)

RESPONSE_SCHEMA: dict[str, object] = {
    "type": "OBJECT",
    "properties": {
        "reasons": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"placeId": {"type": "STRING"}, "text": {"type": "STRING"}},
                "required": ["placeId", "text"],
            },
        }
    },
    "required": ["reasons"],
}


@dataclass(frozen=True)
class ReasonFacts:
    """LLM 에 넘기는 후보 한 곳의 사실. 엔진 값과 공공 DB 값만 담는다."""

    place_id: str
    name: str
    category: str
    detour_min: int
    stay_min: int
    crowd_grade: str | None
    crowd_confidence: str | None
    shortest_detour: bool
    least_crowded: bool


def facts_for(candidates: Sequence[WaypointCandidate]) -> list[ReasonFacts]:
    detours = [candidate.detour_min for candidate in candidates]
    # 응답 모델(CrowdSummary)이 등급을 네 값으로 제한한다. 모르는 값이 와도 혼잡 사실을 넘기지 않을 뿐 실패하지 않는다.
    order = {"여유": 0, "보통": 1, "붐빔": 2, "매우 붐빔": 3}

    def grade_of(candidate: WaypointCandidate) -> str | None:
        grade = candidate.crowd.grade if candidate.crowd is not None else None
        return grade if grade in order else None

    graded = [order[grade] for grade in map(grade_of, candidates) if grade is not None]
    facts = []
    for candidate in candidates:
        grade = grade_of(candidate)
        facts.append(
            ReasonFacts(
                place_id=candidate.place.id,
                name=candidate.place.name,
                category=candidate.place.category,
                detour_min=candidate.detour_min,
                stay_min=candidate.stay_min,
                crowd_grade=grade,
                crowd_confidence=candidate.crowd.confidence if candidate.crowd is not None and grade else None,
                # 후보가 둘 이상일 때만 비교 사실을 준다. 하나뿐이면 '가장'이라는 말이 근거가 없다.
                shortest_detour=len(candidates) > 1 and candidate.detour_min == min(detours),
                least_crowded=len(graded) > 1 and grade is not None and order[grade] == min(graded),
            )
        )
    return facts


def build_prompt(facts: Sequence[ReasonFacts]) -> tuple[str, str]:
    payload = [
        {
            "placeId": item.place_id,
            "name": item.name,
            "category": item.category,
            "detourMin": item.detour_min,
            "stayMin": item.stay_min,
            "crowdGrade": item.crowd_grade,
            "crowdConfidence": item.crowd_confidence,
            "shortestDetour": item.shortest_detour,
            "leastCrowded": item.least_crowded,
        }
        for item in facts
    ]
    # 공공 DB 값이라도 지시문과 분리해 데이터로만 넘긴다(AI-REQ-07).
    return _SYSTEM_PROMPT, f"<facts>{json.dumps(payload, ensure_ascii=False)}</facts>"


def guard_reason(text: object, item: ReasonFacts, others: Sequence[str]) -> str | None:
    """OutputGuard: 통과하면 정리한 문장, 아니면 None(그 후보는 규칙 문구를 쓴다)."""
    if not isinstance(text, str):
        return None
    cleaned = _WHITESPACE.sub(" ", text).strip()
    if not cleaned or len(cleaned) > REASON_MAX_CHARS or any(char in cleaned for char in "<>{}\n"):
        return None
    if _FORBIDDEN.search(cleaned):
        return None
    # 수치는 엔진이 낸 이 후보의 값만 쓸 수 있다(AI-REQ-04). 장소 이름·분류에 든 숫자('168계단')는 수치가 아니다.
    numbers_text = cleaned.replace(item.name, " ").replace(item.category, " ")
    if any(int(number) not in {item.detour_min, item.stay_min} for number in _NUMBER.findall(numbers_text)):
        return None
    quiet, busy = bool(_QUIET_WORDS.search(cleaned)), bool(_BUSY_WORDS.search(cleaned))
    if quiet or busy or _CROWD_WORDS.search(cleaned):
        if item.crowd_grade is None or "예상" not in cleaned:
            return None
        if quiet and item.crowd_grade != "여유":
            return None
        if busy and item.crowd_grade not in {"붐빔", "매우 붐빔"}:
            return None
    # 다른 후보를 섞어 말하지 않는다. 자기 이름 안에 다른 후보 이름이 들어 있을 수 있어('범어사 성보박물관'과 '범어사')
    # 자기 이름을 먼저 지우고 본다. 한국어는 조사가 붙어 단어 경계로 나눌 수 없어 이름 전체가 들어 있는지로 본다.
    # 반대로 다른 후보 이름이 자기 이름을 품고 있으면('범어사'에게 '범어사 성보박물관') 지우기 전 문장에서 찾는다.
    others_text = cleaned.replace(item.name, " ")
    for name in others:
        if len(name) < 2 or name == item.name:
            continue
        if name in (cleaned if item.name in name else others_text):
            return None
    return cleaned


def _caveats(rule_reason: str) -> list[str]:
    return [part for part in rule_reason.split(RULE_CAVEAT_SEPARATOR)[1:] if part]


def with_reason(candidate: WaypointCandidate, sentence: str) -> WaypointCandidate:
    """LLM 문장 뒤에 규칙 문구의 확인 필요 안내를 그대로 붙인다."""
    reason = RULE_CAVEAT_SEPARATOR.join([sentence, *_caveats(candidate.reason)])
    return candidate.model_copy(update={"reason": reason})


class WaypointReasonService:
    """AIService 의 설명 문구 경로(SDD COMP-06). 후보·수치·순서는 바꾸지 않는다(AI-REQ-03)."""

    def __init__(self, settings: AISettings, llm: LlmProvider | None = None) -> None:
        self._settings = settings
        self._llm = llm

    async def explain(self, response: SuggestWaypointsResponse) -> SuggestWaypointsResponse:
        """예외를 던지지 않는다. 설명 단계에서 무엇이 실패해도 규칙 문구 그대로 돌려준다(ERR-002)."""
        if self._llm is None or not response.candidates:
            return response
        try:
            return await self._explain(response)
        except Exception as error:  # noqa: BLE001 - 설명은 부가 기능이라 어떤 실패도 후보 응답을 막지 않는다.
            # 예외 메시지에는 요청·응답 내용이 담길 수 있어 종류 이름만 남긴다(NFR-010).
            logger.warning("ai_waypoint_reason failed reason=unexpected error=%s", type(error).__name__)
            return response

    async def _explain(self, response: SuggestWaypointsResponse) -> SuggestWaypointsResponse:
        candidates = response.candidates
        facts = facts_for(candidates)
        try:
            texts = await asyncio.wait_for(self._ask(facts), timeout=self._settings.explain_budget_seconds)
        except TimeoutError:
            texts = None
            logger.warning("ai_waypoint_reason failed reason=budget_exceeded")
        if texts is None:
            logger.info("ai_waypoint_reason source=fallback candidates=%d replaced=0", len(candidates))
            return response

        updated: list[WaypointCandidate] = []
        replaced = 0
        for candidate, item in zip(candidates, facts, strict=True):
            others = [other.name for other in facts if other.place_id != item.place_id]
            sentence = guard_reason(texts.get(item.place_id), item, others)
            if sentence is None:
                updated.append(candidate)
                continue
            updated.append(with_reason(candidate, sentence))
            replaced += 1
        # 문장과 장소 정보는 로그에 남기지 않는다(NFR-010).
        logger.info(
            "ai_waypoint_reason source=llm candidates=%d replaced=%d discarded=%d",
            len(candidates),
            replaced,
            len(candidates) - replaced,
        )
        return response.model_copy(update={"candidates": tuple(updated)})

    async def _ask(self, facts: Sequence[ReasonFacts]) -> dict[str, object] | None:
        """후보 전체를 한 번에 묻는다(NFR-005). 실패·형식 위반이면 한 번 더 묻고, 그래도 안 되면 None"""
        assert self._llm is not None
        system, user = build_prompt(facts)
        known = {item.place_id for item in facts}
        for _ in range(self._settings.max_attempts):
            try:
                raw = await self._llm.generate_json(system=system, user=user, schema=RESPONSE_SCHEMA)
            except LlmError as error:
                if error.reason in {"auth", "quota_exceeded"}:
                    # 다시 불러도 같은 결과이므로 호출을 아낀다(NFR-005).
                    return None
                continue
            texts = _texts(raw, known)
            if texts is not None:
                return texts
            logger.warning("ai_waypoint_reason discarded reason=schema_violation")
        return None


def _texts(raw: object, known: set[str]) -> dict[str, object] | None:
    """`{reasons: [{placeId, text}]}` 에서 아는 후보의 첫 문장만 모은다. 형식이 다르면 None"""
    reasons = raw.get("reasons") if isinstance(raw, dict) else None
    if not isinstance(reasons, list):
        return None
    texts: dict[str, object] = {}
    for entry in reasons:
        if not isinstance(entry, dict):
            continue
        place_id = entry.get("placeId")
        if isinstance(place_id, str) and place_id in known and place_id not in texts:
            texts[place_id] = entry.get("text")
    return texts


def build_waypoint_reason_service(settings: AISettings | None = None) -> WaypointReasonService:
    """환경 설정으로 서비스를 만든다. 키가 없으면 규칙 문구를 그대로 둔다."""
    from .providers.gemini import GeminiProvider

    config = settings if settings is not None else AISettings()
    llm = GeminiProvider(config) if config.api_key is not None else None
    return WaypointReasonService(config, llm)
