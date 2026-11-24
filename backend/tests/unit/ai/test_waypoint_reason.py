"""경유지 추천 이유 문구: 사실 구성, OutputGuard, 실패 시 규칙 문구(AI-REQ-03·04·05). LLM 은 가짜 공급자다."""

import asyncio
import json
import logging
from datetime import date

import pytest

from app.modules.ai.providers.base import LlmError
from app.modules.ai.settings import AISettings
from app.modules.ai.waypoint_reason import (
    RESPONSE_SCHEMA,
    ReasonFacts,
    WaypointReasonService,
    build_prompt,
    build_waypoint_reason_service,
    facts_for,
    guard_reason,
    with_reason,
)
from app.modules.trips.schemas import CrowdSummary, PlaceSummary, SuggestWaypointsResponse, WaypointCandidate

pytestmark = pytest.mark.anyio

SETTINGS = AISettings(_env_file=None, api_key=None)
RULE = "우회 {d}분·체류 {s}분, 후보 영업시간과 후속 시간 제약 확인"
CAVEAT_HOURS = "기존 장소 영업시간은 별도 확인 필요"
CAVEAT_TIMETABLE = "출발시각별 시간표·교통 예측은 아님"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def candidate(
    place_id: str,
    name: str,
    *,
    detour: int,
    stay: int,
    category: str = "관광지",
    grade: str | None = None,
    caveats: tuple[str, ...] = (),
) -> WaypointCandidate:
    crowd = CrowdSummary(grade=grade, confidence="중간", as_of=None, sources=("행정동 생활인구",)) if grade else None
    return WaypointCandidate(
        place=PlaceSummary(
            id=place_id, name=name, lat=35.1, lng=129.0, category=category, source="PUBLIC", ref_date=date(2026, 11, 23)
        ),
        detour_min=detour,
        stay_min=stay,
        crowd=crowd,
        reason="; ".join([RULE.format(d=detour, s=stay), *caveats]),
    )


HUIN = candidate("p1", "흰여울문화마을", detour=12, stay=40, grade="여유", caveats=(CAVEAT_TIMETABLE,))
KKANG = candidate("p2", "깡깡이예술마을", detour=9, stay=30, category="전시·문화", grade="보통")
JAGAL = candidate("p3", "자갈치시장", detour=14, stay=50, category="시장", caveats=(CAVEAT_HOURS, CAVEAT_TIMETABLE))
RESPONSE = SuggestWaypointsResponse(candidates=(HUIN, KKANG, JAGAL))

GOOD = {
    "reasons": [
        {"placeId": "p1", "text": "바다를 따라 걷는 예상 혼잡 여유로운 관광지"},
        {"placeId": "p2", "text": "우회가 가장 짧은 전시·문화 공간"},
        {"placeId": "p3", "text": "체류 50분이면 둘러보기 좋은 시장"},
    ]
}


class FakeLlm:
    def __init__(self, *outcomes: object, delay: float = 0) -> None:
        self.outcomes = list(outcomes)
        self.delay = delay
        self.calls: list[dict[str, object]] = []

    async def generate_json(self, *, system: str, user: str, schema: dict[str, object]) -> object:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.delay:
            await asyncio.sleep(self.delay)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def service(llm: FakeLlm | None, **settings: object) -> WaypointReasonService:
    return WaypointReasonService(AISettings(_env_file=None, api_key=None, **settings), llm)


# ---------- 사실과 프롬프트 ----------


def test_facts_hold_only_engine_values_and_public_place_fields():
    facts = facts_for(RESPONSE.candidates)
    assert facts[0] == ReasonFacts(
        place_id="p1",
        name="흰여울문화마을",
        category="관광지",
        detour_min=12,
        stay_min=40,
        crowd_grade="여유",
        crowd_confidence="중간",
        shortest_detour=False,
        least_crowded=True,
    )
    assert [(item.shortest_detour, item.least_crowded) for item in facts] == [
        (False, True),
        (True, False),
        (False, False),
    ]
    # 혼잡 근거가 없는 후보는 등급·신뢰도가 없다.
    assert (facts[2].crowd_grade, facts[2].crowd_confidence) == (None, None)


def test_single_candidate_gets_no_comparison_facts():
    [only] = facts_for((HUIN,))
    assert (only.shortest_detour, only.least_crowded) == (False, False)


def test_prompt_sends_facts_as_data_without_coordinates_or_rule_text():
    system, user = build_prompt(facts_for(RESPONSE.candidates))
    assert user.startswith("<facts>") and user.endswith("</facts>")
    payload = json.loads(user.removeprefix("<facts>").removesuffix("</facts>"))
    assert payload[1] == {
        "placeId": "p2",
        "name": "깡깡이예술마을",
        "category": "전시·문화",
        "detourMin": 9,
        "stayMin": 30,
        "crowdGrade": "보통",
        "crowdConfidence": "중간",
        "shortestDetour": True,
        "leastCrowded": False,
    }
    for secret in ("35.1", "129.0", "lat", "lng", "확인 필요"):
        assert secret not in user
    assert "깡깡이" not in system
    assert "Use only these facts" in system


# ---------- OutputGuard ----------

ITEM = facts_for(RESPONSE.candidates)[0]  # 흰여울: 우회 12, 체류 40, 예상 여유
NO_CROWD = facts_for(RESPONSE.candidates)[2]  # 자갈치: 혼잡 근거 없음


@pytest.mark.parametrize(
    "text",
    [
        "바다를 따라 걷기 좋은 관광지",
        "  체류 40분이면 충분한   관광지 ",
        "우회 12분으로 들를 수 있는 관광지",
        "예상 혼잡 여유로운 관광지",
        "흰여울문화마을의 바다 산책길",
        "바다\n산책",  # 줄바꿈은 공백으로 합친다
    ],
)
def test_guard_accepts_grounded_short_reasons(text):
    assert guard_reason(text, ITEM, ["깡깡이예술마을", "자갈치시장"]) == " ".join(text.split())


@pytest.mark.parametrize(
    ("text", "item"),
    [
        (None, ITEM),
        (["바다"], ITEM),
        ("", ITEM),
        ("가" * 61, ITEM),
        ("<b>바다</b>", ITEM),
        # 엔진 값과 다른 수치
        ("우회 5분이면 가는 관광지", ITEM),
        ("체류 2시간 추천", ITEM),
        ("평점 4.5의 관광지", ITEM),
        # 금지 표현
        ("실시간으로 한산한 곳", ITEM),
        ("지금 가기 좋은 관광지", ITEM),
        ("현재 영업 중인 관광지", ITEM),
        ("반드시 들러야 할 곳", ITEM),
        ("자세히 보기 https://example.com", ITEM),
        # 혼잡: '예상' 없이, 등급과 반대로, 근거 없이
        ("한산한 바다 관광지", ITEM),
        ("예상 혼잡 붐비는 관광지", ITEM),
        ("예상 혼잡 여유로운 시장", NO_CROWD),
        ("조용한 시장", NO_CROWD),
        ("예상 혼잡 정보가 있는 시장", NO_CROWD),
        ("사람 적은 시장", NO_CROWD),
        ("혼잡이 덜한 관광지", ITEM),
        # 다른 후보 이름
        ("깡깡이예술마을보다 가까운 곳", ITEM),
    ],
)
def test_guard_rejects_ungrounded_or_unsafe_reasons(text, item):
    assert (
        guard_reason(text, item, ["깡깡이예술마을", "흰여울문화마을"] if item is NO_CROWD else ["깡깡이예술마을"])
        is None
    )


TEMPLE = facts_for(
    (
        candidate("q1", "범어사", detour=20, stay=30, grade="여유"),
        candidate("q2", "다른 곳", detour=5, stay=30, grade="여유"),
    )
)[0]  # #46 리뷰 재현: 우회 20·체류 30, 가장 짧지도 가장 한산하지도 않음


@pytest.mark.parametrize(
    "text",
    [
        # 비교 사실이 거짓인 '가장'
        "우회가 가장 짧은 관광지",
        "예상 혼잡 가장 한산한 관광지",
        "가장 가까운 관광지",
        "최단 우회 관광지",
        # 무엇을 비교하는지 알 수 없는 '가장'·'최고'
        "가장 아름다운 관광지",
        "전망이 최고인 관광지",
        # 글자로 쓴 시간·수치
        "한 시간 둘러보기 좋은 관광지",
        "두 시간이면 충분한 관광지",
        "삼십 분이면 되는 관광지",
        "반나절 코스로 좋은 관광지",
        # 영업·요금 단정
        "연중무휴로 들르기 좋은 관광지",
        "입장료 무료인 관광지",
        "주말 휴관 없는 관광지",
        # 구분자
        "들르기 좋은 관광지; 무료 입장",
        "들르기 좋은 관광지; 기존 장소 영업시간 확인",
    ],
)
def test_guard_rejects_claims_the_engine_did_not_make(text):
    assert (TEMPLE.shortest_detour, TEMPLE.least_crowded) == (False, False)
    assert guard_reason(text, TEMPLE, ["다른 곳"]) is None


def test_superlatives_pass_only_when_the_comparison_fact_is_true():
    shortest, _ = facts_for(
        (
            candidate("s1", "짧은 곳", detour=3, stay=30, grade="보통"),
            candidate("s2", "긴 곳", detour=9, stay=30, grade="여유"),
        )
    )
    _, quietest = facts_for(
        (
            candidate("s1", "짧은 곳", detour=3, stay=30, grade="보통"),
            candidate("s2", "긴 곳", detour=9, stay=30, grade="여유"),
        )
    )
    assert guard_reason("우회가 가장 짧은 관광지", shortest, []) is not None
    assert guard_reason("최단 우회 관광지", shortest, []) is not None
    assert guard_reason("예상 혼잡 가장 한산한 관광지", shortest, []) is None
    assert guard_reason("예상 혼잡 가장 여유로운 관광지", quietest, []) is not None
    assert guard_reason("우회가 가장 짧은 관광지", quietest, []) is None
    # 비교 사실이 참이어도 두 가지를 섞어 말하면 둘 다 참이어야 한다.
    assert guard_reason("가장 가깝고 예상 혼잡 여유로운 곳", quietest, []) is None


def test_guard_allows_numbers_that_are_part_of_the_place_name():
    [ibagu] = facts_for((candidate("p9", "초량 168계단", detour=8, stay=30),))
    assert guard_reason("초량 168계단에서 보는 항구", ibagu, []) == "초량 168계단에서 보는 항구"
    assert guard_reason("168개의 계단", ibagu, []) is None


def test_own_name_containing_another_candidate_name_is_allowed():
    temple, museum = facts_for(
        (
            candidate("q1", "범어사", detour=10, stay=60),
            candidate("q2", "범어사 성보박물관", detour=12, stay=40),
        )
    )
    # 자기 이름을 쓰는 것은 되지만, 자기 이름 밖에서 다른 후보를 말하면 안 된다.
    assert guard_reason("범어사 성보박물관의 불교 유물", museum, ["범어사"]) is not None
    assert guard_reason("범어사와 함께 들르기", museum, ["범어사"]) is None
    assert guard_reason("범어사 성보박물관 옆 사찰", temple, ["범어사 성보박물관"]) is None
    # 한 글자 이름은 일반 단어와 겹치기 쉬워 보지 않는다.
    assert guard_reason("산사 산책", temple, ["산"]) is not None


def test_busy_grade_allows_busy_words_with_expected():
    [busy] = facts_for((candidate("p8", "시장", detour=5, stay=30, grade="매우 붐빔"),))
    assert guard_reason("예상 혼잡 붐비는 곳이라 짧게 들르기", busy, []) is not None
    assert guard_reason("예상 혼잡 여유로운 곳", busy, []) is None


def test_reason_keeps_rule_caveats_after_the_sentence():
    assert with_reason(JAGAL, "시장 구경").reason == f"시장 구경; {CAVEAT_HOURS}; {CAVEAT_TIMETABLE}"
    assert with_reason(KKANG, "전시 공간").reason == "전시 공간"


# ---------- 서비스 ----------


async def test_without_llm_the_response_is_returned_unchanged():
    assert await service(None).explain(RESPONSE) is RESPONSE


async def test_no_candidates_means_no_llm_call():
    llm = FakeLlm()
    empty = SuggestWaypointsResponse()
    assert await service(llm).explain(empty) is empty
    assert llm.calls == []


async def test_replaces_only_reason_text_and_keeps_engine_values_order_and_caveats():
    llm = FakeLlm(GOOD)
    result = await service(llm).explain(RESPONSE)

    assert len(llm.calls) == 1
    assert llm.calls[0]["schema"] is RESPONSE_SCHEMA
    assert [item.reason for item in result.candidates] == [
        f"바다를 따라 걷는 예상 혼잡 여유로운 관광지; {CAVEAT_TIMETABLE}",
        "우회가 가장 짧은 전시·문화 공간",
        f"체류 50분이면 둘러보기 좋은 시장; {CAVEAT_HOURS}; {CAVEAT_TIMETABLE}",
    ]
    # 후보·순서·수치·혼잡은 엔진 결과 그대로다(AI-REQ-03).
    for before, after in zip(RESPONSE.candidates, result.candidates, strict=True):
        assert after.model_dump(exclude={"reason"}) == before.model_dump(exclude={"reason"})


async def test_each_candidate_falls_back_independently():
    llm = FakeLlm(
        {
            "reasons": [
                {"placeId": "p1", "text": "우회 3분이면 가는 곳"},  # 수치 불일치
                {"placeId": "p2", "text": "우회가 가장 짧은 전시·문화 공간"},
                {"placeId": "p2", "text": "두 번째 답은 무시"},
                {"placeId": "unknown", "text": "모르는 후보"},
                "not an object",
            ]
        }
    )
    result = await service(llm).explain(RESPONSE)
    assert [item.reason for item in result.candidates] == [
        HUIN.reason,
        "우회가 가장 짧은 전시·문화 공간",
        JAGAL.reason,
    ]


@pytest.mark.parametrize(
    "failure",
    [LlmError("timeout"), LlmError("network"), LlmError("http_status", 500), LlmError("invalid_response", 200)],
)
async def test_retries_once_then_keeps_rule_reasons(failure):
    llm = FakeLlm(failure, failure)
    assert await service(llm).explain(RESPONSE) is RESPONSE
    assert len(llm.calls) == 2


async def test_second_attempt_can_succeed():
    llm = FakeLlm(LlmError("timeout"), GOOD)
    result = await service(llm).explain(RESPONSE)
    assert result.candidates[1].reason == "우회가 가장 짧은 전시·문화 공간"


@pytest.mark.parametrize("failure", [LlmError("auth", 403), LlmError("quota_exceeded", 429)])
async def test_does_not_retry_failures_that_cannot_recover(failure):
    llm = FakeLlm(failure)
    assert await service(llm).explain(RESPONSE) is RESPONSE
    assert len(llm.calls) == 1


@pytest.mark.parametrize("raw", [["list"], "text", {"reasons": "text"}, {"other": []}])
async def test_schema_violation_is_requested_once_more(raw):
    llm = FakeLlm(raw, raw)
    assert await service(llm).explain(RESPONSE) is RESPONSE
    assert len(llm.calls) == 2


@pytest.mark.parametrize("failure", [RuntimeError("공급자 내부 오류"), ValueError("bad"), KeyError("x")])
async def test_unexpected_errors_keep_rule_reasons_and_log_only_the_type(failure, caplog):
    llm = FakeLlm(failure)
    with caplog.at_level(logging.DEBUG):
        assert await service(llm).explain(RESPONSE) is RESPONSE
    messages = " | ".join(caplog.messages)
    assert f"ai_waypoint_reason failed reason=unexpected error={type(failure).__name__}" in messages
    assert "공급자 내부 오류" not in messages


def test_unknown_crowd_grade_gives_no_crowd_fact():
    odd = HUIN.model_copy(update={"crowd": HUIN.crowd.model_copy(update={"grade": "알 수 없음"})})
    [item, other] = facts_for((odd, KKANG))
    assert (item.crowd_grade, item.crowd_confidence, item.least_crowded) == (None, None, False)
    assert other.least_crowded is False


async def test_slow_llm_is_cut_off_by_the_time_budget():
    llm = FakeLlm(GOOD, delay=1.0)
    assert await service(llm, explain_budget_seconds=0.05).explain(RESPONSE) is RESPONSE


async def test_logs_counts_only(caplog):
    llm = FakeLlm(GOOD)
    with caplog.at_level(logging.DEBUG):
        await service(llm).explain(RESPONSE)
    messages = " | ".join(caplog.messages)
    assert "ai_waypoint_reason source=llm candidates=3 replaced=3 discarded=0" in messages
    for secret in ("흰여울", "바다", "p1", "40"):
        assert secret not in messages


def test_service_built_without_a_key_has_no_llm():
    assert build_waypoint_reason_service(AISettings(_env_file=None, api_key=None))._llm is None


def test_invalid_settings_disable_the_llm_instead_of_failing(monkeypatch, caplog):
    monkeypatch.setenv("GEMINI_EXPLAIN_BUDGET_SECONDS", "abc")
    with caplog.at_level(logging.WARNING):
        built = build_waypoint_reason_service()
    assert built._llm is None
    assert "ai_waypoint_reason disabled reason=invalid_settings fields=explain_budget_seconds" in caplog.messages


async def test_service_built_from_invalid_settings_returns_rule_reasons(monkeypatch):
    monkeypatch.setenv("GEMINI_EXPLAIN_BUDGET_SECONDS", "abc")
    assert await build_waypoint_reason_service().explain(RESPONSE) is RESPONSE


def test_service_built_with_a_key_uses_gemini():
    from app.modules.ai.providers.gemini import GeminiProvider

    built = build_waypoint_reason_service(AISettings(_env_file=None, api_key="test-key"))
    assert isinstance(built._llm, GeminiProvider)
    assert SETTINGS.explain_budget_seconds == 4.0
