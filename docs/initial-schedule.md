# FR-005 최초 일정 생성 엔진

## 범위와 근거

2026-11-14 `origin/dev=90d52fd`를 기준으로 만든 별도 엔진 기능이다.
프로젝트계획서 4장(고정 블록 우선 배치), SRS FR-003·005·006 및 AC-003·004·006,
SDD ADR-003(삽입 휴리스틱), COMP-03, API-009를 따른다.

기존 insert/recompute/validate, API-006·009·011의 요청·응답 및 저장 동작은 변경하지 않는다.
PR #10·#17의 편집·스냅샷 구현을 포함하지 않는다. 최초 배치는 기존 일정을 편집하는
작업과 구분되며, 기존 일정 상태를 받아 몰래 재배치하지 않는다.

## 입력과 정책 경계

- 여행 시작·종료일, 하루 시간창, 이동수단은 기존 TripWindow를 사용한다.
- 선택 장소는 기존 PUBLIC/KAKAO PlaceRef와 안정적인 block ID를 사용한다.
- 사용자가 지정한 날짜·시간창은 고정 제약이다. 지정 시각을 바꾸어 충돌을 해결하지 않는다.
- 시간 미지정 선택 장소는 배치 대상이다. 기존 HTTP의 isFixed 의미를 바꾸지 않는다.
  시각 없이 고정된 장소의 순서를 잠그는 UI 의미는 API 연결 전에 별도로 매핑해야 한다.
- 장소별 체류시간은 사용자 지정값 → 주입된 공공 장소별 값 → 명시적으로 주입한
  정책 순서로 해결한다. 태그별 숫자 기본값을 내장하지 않는다.
- 배치 정책은 호출자가 명시적으로 선택한다. 시험용 결정적 FIRST_FEASIBLE은
  최단 경로·최적 일정·혼잡 최소화를 보장하지 않는다. 실패는 이 휴리스틱에서
  배치하지 못했다는 뜻이며 수학적 불가능 판정이 아니다.

## 정보 부족과 안전성

미배치 장소는 ID와 정형 사유로 남긴다. 체류시간·경로·영업시간을 임의 생성하지 않는다. 운영시간 미확인은 배치를 막지 않고 HOURS_NEEDS_CHECK로 표시한다.
고정 시간창에 충돌이 있어도 사용자 지정값을 보존하고 확인 필요/충돌을 반환한다.
영업 시작까지 대기할 수 있지만 자정을 넘어 다음 날짜로 이어지는 방문은 자동 생성하지 않는다.
일차 간 숙소/출발지/종료지 이동은 입력 계약이 없으므로 포함하지 않는다.

생성 상태는 기존 ScheduleState이며 카카오 장소는 ID·URL만 저장한다.
sessionCoords는 호출의 CalculationContext로만 전달하며 결과·로그·공유 캐시에 넣지 않는다.
공공 장소 표시 정보가 부족하면 API 응답을 지어내지 않고 표시 불가로 명시한다.
추정 이동시간이나 출발시각 예측이 아닌 공급자 값은 정확하게 확정된 일정으로 표시하지 않는다.

## HTTP/UI 연결 후속 작업

SDD와 현재 GenerateScheduleRequest는 `{options?}` 및 요청 전용 sessionCoords만 받는다.
최초 선택 목록 저장·조회 경로가 없으므로 이번 변경은 새 HTTP 필드를 추가하거나
options에 비공식 데이터를 숨겨 전달하지 않는다. API-009가 내부 생성기를 호출하도록
연결은 2026-11-18 PM 결정에 따라 별도 PR에서 수행한다. 다음은 연결 작업이다.

1. PM이 확정한 initial.selections/clientId 입력과 미배치 목록의 화면 표현 연결.
2. 시각 없는 핵심지의 순서 고정 여부 및 생성 정책 선택/기본 정책.
3. 미확정·부분 생성 결과의 사용자 확인과 저장 시점(기존 일정 덮어쓰기 금지).
4. 장소별 체류시간 공급자와 실제 DB 매핑. 태그 기본값은 합의 전까지 미설정.

기존 API-009 Schedule의 days/violations/conflicts를 재사용하지만 내부 전체 결과를
그대로 기존 HTTP 응답으로 내보내지는 않는다. 기존 서비스의 최초 자동 배치 거절은
선택 목록 계약을 연결할 때 교체한다. 실제 DB·외부 API·프런트 연동은 이번 범위 밖이다.

## 내부 호출 예시

```python
from datetime import date, time
from app.modules.engine.initial import (
    InitialScheduleCommand, InitialSchedulePlanner, InitialSelection,
)
from app.modules.engine.schemas import PublicPlaceRef, TripWindow

planner = InitialSchedulePlanner(existing_engine, public_stay_provider)
result = planner.plan(InitialScheduleCommand(
    trip=TripWindow(
        start_date=date(2026, 11, 20), end_date=date(2026, 11, 21),
        day_start=time(9), day_end=time(18), transport_mode="CAR",
    ),
    selections=(
        InitialSelection(block_id="chosen-a", place_ref=PublicPlaceRef(place_id="public-a"), stay_min=45),
        InitialSelection(block_id="chosen-b", place_ref=PublicPlaceRef(place_id="public-b")),
    ),
    policy="FIRST_FEASIBLE",
))
```

`public_stay_provider.get(place_ref, on_date=...)`는 실제 후보 방문일의 공공 체류시간을 돌려준다.
사용자 stayMin이 없고 fixedWindow가 있으면 명시된 시작·종료 차이를 사용자 지정 체류시간으로
해석한다. 사용자 stayMin과 창 길이가 다르면 고정 시각을 유지하고 충돌로 보고한다.
카카오 참조는 공공 체류시간 공급자에 넘기지 않으며 사용자 시간 근거가 없으면 미배치한다.

결과:
- `state`: 기존 ScheduleState, 저장 가능한 장소 참조와 블록·구간만 포함.
- `schedule`: 기존 API-009 Schedule 형태의 표시용 결과. 공공 표시 정보 부족 시 None.
- `unplaced`: 배치하지 못한 선택의 blockId와 정형 사유. 선택 장소를 조용히 삭제하지 않는다.
- `violations`, `conflicts`: 검증 결과 및 미배치 사유.
- `confirmed`: 모든 선택을 배치하고 검증 위반·확인 필요가 없으며 추정/시간 컨텍스트만으로
  계산한 경로가 아닐 때만 True. 최적해 보장은 아니다.

FIRST_FEASIBLE은 선택 입력 순서로 처리하고 날짜·삽입 구간을 앞에서부터 시도한다.
뒤에 입력한 시간 미지정 장소가 앞 구간에 들어갈 수 있다. 고정 블록의 상대 순서는 유지하며,
지정 날짜 순서 자체가 서로 모순되면 충돌로 보고한다. 운영 기본 순위 정책으로 자동 등록하지 않는다.
공공 장소 정보는 호출 내부에서만 재사용하고 경로 결과는 수락된 후보 계산을 그대로 사용한다.
최종 표시 단계에서 경로를 다시 조회하여 수락된 선택을 잃지 않도록 했다.

## PM 리뷰 반영 및 검증 (2026-11-18)

HIGH1: 기준 고정 블록의 충돌을 블록·종류·지연량으로 비교한다. 새 충돌이나 악화를
만들지 않는 유연 장소를 배치할 수 있다. 기존 고정 충돌은 그대로 반환한다.
HIGH2: 블록별 실패를 초기화하여 충돌 없는 뒤쪽 고정 블록에 이전 실패가 전파되지 않는다.
유연 배치는 day_start 이전으로 내려가지 않는다. 카카오·영업시간 미확인 공공 장소도
체류시간과 시각 계산 근거가 있으면 배치하고 HOURS_NEEDS_CHECK를 반환한다.
confirmed는 전체 검증의 확정 여부이며 배치 성공이나 HTTP 저장 가능 여부와 같지 않다.
이 내부 모듈에는 저장 동작이 없다. 이동시간이 없어 시각 계산 자체가 불가능하면
임의 이동시간을 만들어 배치하지 않는다.

경로 memo는 plan 호출 내부에만 존재한다. 키는 고유 블록 ID쌍·출발시각·이동수단이며
좌표·API 키가 없다. 요청 간 공유하지 않고 결과/스냅샷에 넣지 않는다. 12개 선택 테스트는
132회 이하·동일 키 중복 조회 없음과 다음 요청 재조회를 검증한다. 모든 입력에 대한
절대 호출 상한/성능 보장은 아니며 기존 공급자 쿼터 가드는 계속 필요하다.

시간 충돌은 최종 검증 체인에서 보고해 동일 원인 FIXED_ORDER/TRAVEL 중복을 제거했다.
allowed_days 중복·기간 밖 값을 거절한다. 미배치 대표 사유는 첫 실패를 유지한다(LOW8).
날짜 분리 안내 문구는 일부 사유에 있지만 FR-005의 구체적인 날짜 분리 제안 기능은 범위 밖이다.

PM 재현 테스트는 수정 전 5개 실패, 수정 후 통과했다. 신규10개 포함 최초배치54개,
브랜치 전체378개 통과. Ruff 검사/포맷, mypy app52개 및 initial strict 통과.

```sh
cd backend
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run --with mypy mypy app
```

mypy는 기존 dev 의존성에 없으므로 --with로 실행한다. 공통 pyproject/uv.lock은 변경하지 않는다.
실제 DB·경로 API·브라우저 연결은 검증하지 않았다. Draft 유지.

2026-11-19 별도 최신 dev 040ad76 + 수정 엔진 검증: pytest 737개, Ruff/포맷, mypy65개 통과. 기능 브랜치는 dev를 자동 병합하지 않았다.
