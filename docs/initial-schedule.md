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

미배치 장소는 ID와 정형 사유로 남긴다. 체류시간·경로·영업시간을 임의 생성하지 않는다.
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
연결하려면 다음을 먼저 정해야 한다.

1. UI-01 선택 목록 전달 계약과 미배치 목록의 화면 표현(별도 선택 저장소는 필수가 아님).
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

## 검증 (2026-11-15)

Python 3.12.16, 기존 uv.lock 변경 없이 별도 환경에서 검증했다.
전체 pytest 367 passed(기존 dev 324 + 신규 43), Ruff 검사·포맷 82개 파일 통과,
mypy app 52개 소스 통과. 새 initial.py는 strict mypy도 통과했다.
Starlette TestClient의 기존 httpx 사용 중단 예정 경고 1개가 있다.

실행 위치는 이 worktree의 backend 디렉터리다. 아래 실행 파일은 별도 환경의 경로다.

```powershell
& 'C:/Users/HyunBin/AppData/Local/Temp/pinandfill-initial-schedule-venv/Scripts/python.exe' -m pytest
& 'C:/Users/HyunBin/AppData/Local/Temp/pinandfill-initial-schedule-venv/Scripts/ruff.exe' check .
& 'C:/Users/HyunBin/AppData/Local/Temp/pinandfill-initial-schedule-venv/Scripts/ruff.exe' format --check .
```

기존 API-006·009·011 회귀 테스트도 함께 실행했다. 실제 공급자 호출, DB·UI 연동,
실데이터 성능 목표(NFR-001 3초)와 혼잡 최적화(FR-009)는 검증 범위 밖이다.

## 후속 검증 (2026-11-15)

고정 블록만 배치한 중간 계산의 직접 이동 충돌이 후속 장소 삽입으로 해소되어도
최종 결과에 남는 결함을 수정했다. 최종 수락된 일별 계산의 진단만 수집하며,
고정 입력 순서 자체의 충돌 검사는 유지한다. 회귀 테스트를 추가해 전체 368개 통과,
Ruff·포맷·mypy 52개 소스 통과를 확인했다. HTTP 계약 변경은 없다.
