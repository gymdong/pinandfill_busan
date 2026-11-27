# API-009 최초 자동 일정 생성 연결

기준: [2026-11-18 PM 결정](https://github.com/gymdong/pinandfill_busan/pull/18#issuecomment-6973149812).
이 연결은 PR #18의 `InitialSchedulePlanner`를 재사용한다. #18이 dev에 병합되기 전에는 선행 의존 PR이다.
프런트엔드 소스, API-011 후보 공급자, PostgreSQL 저장소는 이 변경에 포함하지 않는다.

## 요청

API-002로 빈 여행을 만든 다음 `POST /api/trips/{tripId}/schedule`을 호출한다.
`initial` 없는 기존 API-009 재계산은 동일하게 동작하며 응답 키도 `days`, `violations`, `conflicts` 그대로다.

```json
{
  "initial": {
    "policy": "FIRST_FEASIBLE",
    "selections": [
      {
        "clientId": "selection-1",
        "place": {"placeId": "126848"},
        "dayNo": 1,
        "fixedWindow": {"dayNo": 1, "start": "09:00", "end": "10:00"},
        "stayMin": 60
      },
      {
        "clientId": "selection-2",
        "place": {"kakaoPlaceId": "900000009", "placeUrl": "https://place.map.kakao.com/900000009"},
        "stayMin": 30
      }
    ]
  }
}
```

- `selections`는 1~30개이며(30은 잠정 상한, `MAX_INITIAL_SELECTIONS`) `clientId`는 요청 안에서 유일한 1~64자 문자열이다(공공 `placeId`도 64자 상한, 잠정).
  화면의 선택 항목 식별용으로만 사용한다. 서버 블록 ID는 각 선택에 새 UUID를 발급한다.
- `place`는 기존 API-006과 같은 PUBLIC ID 또는 KAKAO ID·URL 형식이다. 이름·좌표를 넣지 않는다.
- `dayNo`는 선택 사항이다. 없으면 여행 기간의 날짜를 순서대로 시도한다. 있으면 해당 날짜에만 배치한다.
- `fixedWindow`가 있을 때만 `isFixed=true`가 된다. `dayNo`도 있다면 서로 일치해야 한다.
  `stayMin`도 있다면 고정 시간창 길이와 일치해야 한다. 시간은 부산 현지 시각(HH:mm)이다.
- 체류시간은 사용자 지정 → 공공 장소 값 순서다. 고정 시간창 자체도 명시된 체류시간 근거다.
  근거가 없으면 `STAY_NEEDS_CHECK`로 미배치하며 태그별 임의 기본값을 만들지 않는다.
- `FIRST_FEASIBLE`은 입력 순서로 유연 장소를 처리하면서 날짜와 삽입 위치를 차례대로 시도한다.
  최단 경로나 전역 최적해를 보장하지 않는다. 고정 장소의 상대 순서는 보존한다.
- 고정 시간창이 있는 선택도 요청의 상대 순서를 보존한다. 따라서 고정 선택은 날짜·시각 순서로 보내야 한다.
  서버가 자동 정렬하면 사용자가 정한 방문 순서를 바꾸므로, 역순 입력은 `409 / ERR-009`로 거절한다.
- `initial`과 `options`는 함께 보내지 않는다. `options: {}`나 `options: null`도 거절한다.
  이미 블록 또는 구간이 있는 여행에는 최초 생성을 적용하지 않는다.
- 카카오 좌표가 있으면 기존 요청 최상위 `sessionCoords`에 카카오 장소 ID를 키로 전달한다.
  계산 중에만 사용하며 선택 목록·좌표 저장소는 만들지 않는다. 이름은 받지 않는다.

## 응답과 저장 여부

최초 생성에만 기존 Schedule에 `generation`을 추가한다. 아래는 체류시간이 없는 카카오 선택 한 개가
미배치된 응답 예시다(표시하는 빈 배열은 실제 빈 결과이며 필드 생략 표기가 아니다).

```json
{
  "days": [{"dayNo": 1, "date": "2026-11-20", "blocks": [], "legs": [], "crowd": [], "weather": []}],
  "violations": [{"type": "STAY_NEEDS_CHECK", "cause": "체류시간 근거 확인이 필요합니다."}],
  "conflicts": [],
  "generation": {
    "saved": false,
    "confirmed": false,
    "unplaced": [{"clientId": "selection-2", "reason": {"type": "STAY_NEEDS_CHECK", "cause": "체류시간 근거 확인이 필요합니다."}}],
    "previewClientIds": {}
  }
}
```

| 필드 | 의미 및 화면 처리 |
|---|---|
| `days`, `violations`, `conflicts` | 기존 Schedule 구조. `saved=false`이면 저장된 일정이 아닌 계산 결과 미리보기다. |
| `generation.saved` | 모두 배치되고 고정 시각 수락 검사를 통과해 저장됐는지 여부. |
| `generation.confirmed` | 정보 부족·경고 없이 엔진이 확정했는지 여부. 저장 여부와 별개다. |
| `generation.unplaced` | 미배치 선택의 `clientId`와 `reason`(기존 Violation 구조). |
| `generation.previewClientIds` | `saved=false`일 때만 채운다. 미리보기의 서버 블록 ID(`days[].blocks[].id`, `conflicts[].blockIds`) → 요청 `clientId`. 같은 장소를 여러 번 고른 선택을 구분하는 응답 전용 매핑이며 저장하지 않는다. `saved=true`이면 `{}`. 추가 필드라 무시해도 된다. |

모두 배치되면 `unplaced: []`이다. 경로 또는 운영시간 미확인(추정 구간 포함) 때문에 `confirmed=false`여도 저장할 수 있다.
고정 시각 충돌은 기존 `409 / ERR-009`로 거절하며 저장하지 않는다.
경로가 미확인이어도 이전 방문 종료가 다음 고정 시작보다 늦으면 그 후보 구간은 알려진 시간 충돌이다.
엔진은 다음 구간을 계속 시도하고, 가능한 구간이 없으면 해당 선택을 미배치로 반환한다.
저장 경계에도 같은 겹침 검사를 두어 잘못된 전체 배치가 저장되지 않게 방어한다.
하나라도 미배치면 HTTP 200 / `saved=false`로 부분 결과를 반환하고 기존 일정과 EDIT 이력을 건드리지 않는다.
부분 결과를 수락하거나 저장하는 별도 API는 없다.

기본 구성에서 경로 API(TMAP → ODsay)를 쓸 수 없으면(키 없음·실패·한도 초과) 두 장소 좌표로 추정한
`ESTIMATED`(화면 '추정') 구간을 쓰고 `confirmed=false`로 둔다(#69, `backend/app/adapters/route/estimated.py`).
좌표가 없어 추정도 할 수 없는 구간만 외부 `legs`에서 생략하고 확인 필요 경고를 남긴다. 가짜 0분 구간은 만들지 않는다.
후속 유연 장소의 시각을 정할 수 없으면 미배치될 수 있다.
영업시간이 미확인인 PUBLIC/KAKAO 장소는 체류시간 등 배치 근거가 있다면 배치하고 `HOURS_NEEDS_CHECK`를 남긴다.

## 계산 상한(잠정)

| 상한 | 값 | 초과 시 |
|---|---|---|
| `selections` 개수 (`MAX_INITIAL_SELECTIONS`, `app/modules/trips/schemas.py`) | 30 | `400 / ERR-001` |
| 요청 하나의 경로 조회 횟수 (`MAX_ROUTE_LOOKUPS_PER_PLAN`, `app/modules/engine/initial.py`) | 300 | 남은 유연 선택은 더 시도하지 않고 `PLACEMENT_NEEDS_CHECK`로 미배치(`saved=false`) |

경로 조회 횟수는 요청 내 메모에 없는 조회(공급자 호출 시도)만 센다. 실패한 호출도 센다.
고정 선택만으로 상한에 닿으면 고정 선택을 버릴 수 없으므로 `503 / ERR-017`이다(30개 상한 아래에서는 도달하지 않는다).
두 값은 PM 잠정 기본값(2026-11-22)이며 실제 공급자 쿼터·지연 측정 후 조정한다.

## 오류

오류 형식은 기존 `{ "error": { "id": "...", "message": "...", "fields"?: { "<키>": "<안내 문구>" } } }`이다.
요청 원문·좌표·공급자 예외는 포함하지 않는다.

| HTTP / ID | 조건 |
|---|---|
| 400 / ERR-001 | 잘못된 입력, 중복 clientId, 범위 밖 날짜, dayNo/fixedWindow 모순, initial/options 동시 사용, 비어 있지 않은 일정 덮어쓰기 |
| 404 / ERR-016 | 여행 없음 |
| 400 / ERR-001 | `selections` 31개 이상 |
| 409 / ERR-009 | 고정 방문시각 또는 고정 순서 충돌로 저장 불가. `fields`에 충돌한 선택마다 `"selections.<clientId>": "<안내 문구>"`를 싣는다(요청 순서) |
| 503 / ERR-017 | 장소 표시 정보 확인 불가, 공급자/저장소 처리 실패 또는 초기 생성 서비스 미주입 |

응답은 `Cache-Control: no-store`다. 에러 메시지 문자열에 의존하지 말고 HTTP 상태와 ID로 처리한다.

409 예시 — 두 번째 고정 선택이 첫 고정 선택 뒤 이동시간 때문에 지정 시각을 지킬 수 없다:

```json
{"error": {"id": "ERR-009", "message": "고정 장소의 지정 시각을 지킬 수 없습니다. 날짜 분리를 검토해 주세요.",
  "fields": {"selections.selection-b": "고정 장소의 지정 시각을 지킬 수 없습니다. 날짜 분리를 검토해 주세요."}}}
```

`fields` 값은 기존 ERR-001처럼 문자열이다(프런트 `ApiError.fields: Record<string, string>` 유지).
`selections.` 접두사를 뗀 나머지가 `clientId`다. 서버 블록 UUID는 오류에 싣지 않는다.
편집 API(006/007/008)의 409는 `fields` 없이 그대로다.

## 프런트 연결 인수인계 — 박범찬

현재 연결 지점은 `frontend/src/features/trip-start/createCourse.ts`의 `createCourse`,
`frontend/src/api/endpoints/trips.ts`의 `tripsApi.generateSchedule`,
`frontend/src/types/api.ts`의 `GenerateScheduleRequest`다. 기존 `withSessionCoords`는 재사용할 수 있다.
이 PR은 해당 파일을 수정하지 않는다.

1. `createCourse`에서 API-002 성공 후 API-006 반복 대신 API-009 `initial`을 한 번 호출한다.
2. 기존 장소 선택 목록의 안정적인 항목 키를 `clientId`로 보낸다. 방문시각 없는 장소에 `isFixed`를 붙이지 않는다.
3. 체류시간 근거가 없는 장소는 사용자가 입력하게 한다. 카카오 이름은 화면 메모리에만 두고 요청에서는 제외한다.
4. 응답 타입은 `Schedule & { generation: { saved: boolean; confirmed: boolean; unplaced: {clientId: string; reason: Violation}[]; previewClientIds: Record<string, string> } }`로 확장한다.
   일반 재계산은 여전히 Schedule만 반환한다.
5. `saved=true`일 때 일정 화면으로 진행한다. `confirmed=false`이면 확인 필요 경고를 유지한다.
6. `saved=false`일 때 생성 완료로 처리하지 않는다. `unplaced[].clientId`로 선택 항목에 사유를 보여주고 수정 후 재요청한다.
   미리보기의 서버 UUID를 저장된 블록 ID처럼 편집/삭제 API에 보내지 않는다.
7. 네트워크 실패로 저장 여부가 불명확하면 API-026으로 확인한다. 성공한 최초 생성 요청의 재전송은 덮어쓰기 방지 오류다.

기존 `CourseProgress.addedKeys`는 API-006 부분 삽입 재개용이다. 이미 일부 블록이 저장된 그 여행에
`initial`을 보내면 400이므로, 진행 중인 구형 흐름은 기존 API-009 재계산으로 마무리해야 한다.
새 최초 생성 흐름에서는 항목별 삽입 재개 대신 같은 빈 여행에 전체 선택을 재요청한다.

김동현 담당 편집·삭제·undo에는 저장된 `days[].blocks[].id`를 그대로 전달한다.
생성 자체는 undo 스냅샷을 만들지 않으며 성공한 새로운 생성은 이전 EDIT 이력을 폐기한다.
이후 정상 편집부터 기존 1단계 undo 규칙이 적용된다.

## 조립·저장·보안 경계

`default_trip_service`는 앱이 선택한 공공 장소 공급자와 동일한 일정 엔진으로 planner를 구성한다.
경로 공급자는 TMAP → ODsay → 추정 순서이고, 같은 공급자로 경유지 제안(`WaypointRecommender`)도 만든다.
혼잡 서비스가 있으면 planner 에 혼잡 조회와 회피 기준(`avoidance`)을 넘긴다(FR-009).
시험에서는 Fake 장소·경로 공급자를 사용할 수 있다. 저장소는 `DATABASE_URL`이 비어 있으면 메모리,
설정돼 있으면 PostgreSQL을 사용한다. DB와 장소 출처의 설정 방법은 [백엔드 README](../backend/README.md)를 참조한다.

경로를 포함한 일정 계산은 DB 트랜잭션 밖에서 수행한다. 저장 시 여행 상태가 계산 시작 때와 같은지 다시 확인하고,
달라졌으면 최신 상태로 재시도한다(최대 `MAX_EDIT_ATTEMPTS`회, 모두 겹치면 아무것도 저장하지 않고 503 `ERR-017`). 변경된 계획을 수락하면 EDIT 이력을 폐기하고 일정을 저장한다.
PostgreSQL에서는 두 쓰기를 같은 트랜잭션에서 처리해 실패 시 함께 롤백한다.
메모리 저장소는 프로세스 잠금과 실패 시 보상 복원을 사용한다.

`sessionCoords`는 계산 컨텍스트에만 전달한다. KAKAO 블록·스냅샷·응답에는 ID·URL만 남는다.
`clientId`는 요청 내 매핑에만 사용하며 영속 블록 식별자로 쓰지 않는다. 409 `fields`와 `previewClientIds`에만 실린다.
장소·체류시간 공급자 예외는 `initial_place_lookup` / `initial_stay_lookup` / `initial_tag_stay_lookup` 경고 로그로 남긴다.
로그 필드는 예외 타입과 장소 종류(`PUBLIC` 또는 `KAKAO`)로 제한한다. 장소 ID, 좌표, 키, 예외 메시지, 응답 본문은 기록하지 않는다(NFR-010).
저장 실패 보상 중 일정 복원이 실패하면 `trip_generation restore_failed`, EDIT 이력 복원이 실패하면
`trip_generation history_restore_failed` 경고를 남긴다. 두 경고 모두 예외 타입만 기록하며 원래 저장 예외를 다시 올린다.

## 검증 명령

`backend/`에서 Python 3.12 환경으로 실행한다. 잠금 파일을 갱신하지 않는다.

```sh
uv sync --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run --with mypy mypy app
```

테스트는 Fake/Mock 공급자를 사용하고 실제 공급자 키를 비운다. 실제 공급자의 응답 품질·쿼터·지연 검증은 별도다.

2026-11-20 검증: Python 3.12.16에서 전체 781 passed(최신 dev 737 + 최초 생성 엔진 2 + 신규 HTTP 42),
Ruff 검사 통과, 포맷 113개 파일 통과, mypy Python 3.12 대상으로 app 66개 소스 통과.
mypy 도구는 기존 별도 환경에서 Python 3.12 인터프리터를 지정해 실행했다.
Starlette TestClient의 httpx 사용 중단 예정 경고 1건이 있으며 기존 잠금 의존성은 변경하지 않았다.

2026-11-23 리뷰 반영(실패 로그에 장소 ID 대신 종류만, 일정·이력 복원 독립 보호, ID 64자 상한) 검증: 로컬 Python 3.12에서 전체 867 passed,
Ruff 검사·포맷(120개 파일) 통과, `uv run --with mypy mypy app` 69개 소스 통과.
