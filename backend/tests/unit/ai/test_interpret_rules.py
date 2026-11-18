"""규칙 기반 조건 해석(FR-002) 단위 테스트. 기준일은 2026-11-16(월)이다."""

from datetime import date, time

import pytest

from app.modules.ai.interpret import Conditions, interpret_by_rules

TODAY = date(2026, 11, 16)


def rules(text: str) -> Conditions:
    return interpret_by_rules(text, TODAY)


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("11/20~22 2박 3일 대중교통", date(2026, 11, 20), date(2026, 11, 22)),
        ("11/20~11/22", date(2026, 11, 20), date(2026, 11, 22)),
        ("11.20-22", date(2026, 11, 20), date(2026, 11, 22)),
        ("12월 5일부터 7일까지", date(2026, 12, 5), date(2026, 12, 7)),
        ("12월 5일 ~ 12월 7일", date(2026, 12, 5), date(2026, 12, 7)),
        ("2026-12-24~2026-12-25", date(2026, 12, 24), date(2026, 12, 25)),
        ("2027년 1월 3일부터 2박", date(2027, 1, 3), date(2027, 1, 5)),
        # 날짜 하나와 길이
        ("12/5 2박 3일", date(2026, 12, 5), date(2026, 12, 7)),
        ("12/5부터 3일간", date(2026, 12, 5), date(2026, 12, 7)),
        ("12/5 당일치기", date(2026, 12, 5), date(2026, 12, 5)),
        ("12/5", date(2026, 12, 5), date(2026, 12, 5)),
        # 이미 지난 날짜는 다음 해로 본다.
        ("10/17~19 2박 3일 대중교통", date(2027, 10, 17), date(2027, 10, 19)),
        # 오늘은 지난 날짜가 아니다.
        ("11/16 당일", date(2026, 11, 16), date(2026, 11, 16)),
        # 해와 달을 넘기는 범위
        ("12/30~1/2 자차", date(2026, 12, 30), date(2027, 1, 2)),
        ("11/29~2", date(2026, 11, 29), date(2026, 12, 2)),
        ("12/30~2", date(2026, 12, 30), date(2027, 1, 2)),
    ],
)
def test_reads_dates(text, start, end):
    result = rules(text)
    assert (result.start, result.end) == (start, end)


@pytest.mark.parametrize(
    "text",
    [
        "이번 주말에 바다 보러",  # 상대 표현은 규칙으로 읽지 않는다(LLM 몫).
        "2/30 여행",  # 없는 날짜
        "12/5~31/40",  # 종료일이 날짜가 아님
        "12/1~1/31",  # 지나치게 긴 기간
        "예산 3.5만원",  # 금액의 소수점을 날짜로 읽지 않는다.
        "친구 1/2명",
        "2박 3일",
        "10:30에 출발",
    ],
)
def test_leaves_dates_empty_when_not_stated_or_implausible(text):
    result = rules(text)
    assert (result.start, result.end) == (None, None)


@pytest.mark.parametrize(
    ("text", "day_start", "day_end"),
    [
        ("10:00~19:00", time(10), time(19)),
        ("10시부터 19시까지", time(10), time(19)),
        ("오전 10시부터 저녁 8시까지", time(10), time(20)),
        ("9시 반부터 6시까지", time(9, 30), time(18)),
        ("아침 9시 30분에 출발해서 밤 9시 전에 끝", time(9, 30), time(21)),
        ("10시-7시", time(10), time(19)),
        ("7시까지", None, time(19)),
        ("오전 11시까지", None, time(11)),
        ("10시부터", time(10), None),
        # 길이·날짜는 시각이 아니다.
        ("10시부터 3시간", time(10), None),
        ("12월 5일 2박 3일", None, None),
        ("10시에 만나요", None, None),
        # 뒤집힌 시각은 버린다.
        ("오후 8시부터 오후 3시까지", None, None),
        ("25시부터", None, None),
    ],
)
def test_reads_daily_hours(text, day_start, day_end):
    result = rules(text)
    assert (result.day_start, result.day_end) == (day_start, day_end)


@pytest.mark.parametrize(
    ("text", "mode"),
    [
        ("대중교통", "TRANSIT"),
        ("지하철이랑 버스로", "TRANSIT"),
        ("뚜벅이 여행", "TRANSIT"),
        ("렌터카 빌려서", "CAR"),
        ("자차로 이동", "CAR"),
        ("도보 위주", "WALK"),
        ("걸어서 다닐래", "WALK"),
        # 여러 이동수단이 섞이면 고르지 않는다.
        ("지하철 타고 가서 걸어서 구경", None),
        ("바다 보고 싶어", None),
    ],
)
def test_reads_transport_mode(text, mode):
    assert rules(text).mode == mode


@pytest.mark.parametrize(
    ("text", "budget"),
    [
        ("예산 30만원", 300_000),
        ("3.5만 원 정도", 35_000),
        ("5천원", 5_000),
        ("150,000원 안에서", 150_000),
        ("50000원", 50_000),
        ("예산은 20만 정도", 200_000),
        # 단위가 없거나 금액이 아닌 숫자는 읽지 않는다.
        ("친구 30명", None),
        ("12월 5일", None),
        ("999999999만원", None),
    ],
)
def test_reads_budget(text, budget):
    assert rules(text).budget == budget


@pytest.mark.parametrize(
    ("text", "companions"),
    [
        ("부모님 모시고", "부모님"),
        ("친구 2명이랑", "친구 2명"),
        ("친구들과", "친구"),
        ("혼자 가요", "혼자"),
        ("12/5 여행", None),
    ],
)
def test_reads_companions(text, companions):
    assert rules(text).companions == companions


def test_reads_every_item_from_one_sentence():
    result = rules("12월 5일부터 7일까지 부모님이랑 렌터카로 오전 9시부터 오후 6시까지, 예산 30만원")
    assert result == Conditions(
        start=date(2026, 12, 5),
        end=date(2026, 12, 7),
        day_start=time(9),
        day_end=time(18),
        mode="CAR",
        companions="부모님",
        budget=300_000,
    )
