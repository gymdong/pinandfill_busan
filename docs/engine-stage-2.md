# FR-003·004·005 초기 일정 엔진 구현 범위

이 문서는 2단계 구현 기록이다. 이후 허용된 seq 재번호화와 API-006·009 HTTP 연결은
[engine-stage-3.md](engine-stage-3.md)를 따른다. 아래의 삽입 간격 제한과 HTTP 미구현 설명은
3단계에서 해소되었다.

PR #1의 `fa293de` API 계약을 기준으로 기존 로컬 작업을 확장했다.
`backend/pyproject.toml`과 `backend/README.md`는 PR #4와 겹치므로 이번 단계에서
수정하지 않았다. 기존 README의 초기 계약 설명보다 이 문서가 최신이다.
브랜치 전환·병합·push·실제 외부 API 호출은 수행하지 않는다.

## 요청과 영속 상태

- API-006 입력은 `{placeId}` 또는 `{kakaoPlaceId, placeUrl}`이며 이름을 받지 않는다.
- API-009·011의 `sessionCoords`는 요청과 `CalculationContext`에서만 사용한다.
  `calculation_context(request)`는 복사한 요청별 맵을 만들고 엔진 인스턴스에 저장하지 않는다.
- `insert_command`는 좌표 없는 내부 명령을 만든다. 체류시간은 호출자가 명시적으로
  제공한다. 미매칭 카카오 장소에 임의의 기본 체류시간을 부여하지 않는다.
- 영속 `ScheduleState`는 카카오 ID·URL 외 검색 데이터를 담지 않는다. URL은
  `https://place.map.kakao.com/{id}` 형태로 검증하며 query·fragment를 허용하지 않는다.
- 내부 참조는 기존 `kakao_place_url` Python 필드와 이전 입력 별칭을 호환하지만 JSON 출력은
  `placeUrl`이다. HTTP 요청은 최신 `placeUrl`만 허용한다.
- API-009는 `days/violations/conflicts`를 유지한다. 카카오 블록의 `place`는
  `source: KAKAO`, `kakaoPlaceId`, `placeUrl`만 반환한다. 공공 장소만 이름·좌표를 반환한다.
- 카카오 좌표는 장소 공급자에서 다시 찾지 않고 이번 요청 맵에서만 해석한다.
  맵에 존재하더라도 일정에 참조되지 않은 장소는 사용하지 않는다.
- DB·캐시·스냅샷 어댑터는 아직 없다. 직렬화 가능한 영속 상태, 응답, 오류·로그 경계를
  테스트한다. 원문 request, `__dict__`, `ValidationError.errors()`를 기록하는 로거를
  추가해서는 안 된다. 향후 저장 계층 연결 시 별도 비저장 통합 테스트가 필요하다.

## 엔진 호출

```python
engine = BasicItineraryEngine(fake_places, fake_routes, clock=fixed_clock)
result = engine.recompute(command, context=calculation_context(request))
report = engine.validate(validation_command, context=calculation_context(request))
```

기존 `insert`, `recompute`, `validate` 인터페이스를 유지하고 선택적 요청 컨텍스트를 추가했다.
명시된 순서와 같은 날의 계산만 지원하며, 첫 코스 자동 생성은 제공하지 않는다.

- `recompute`: `from_block_id`는 편집이 이미 반영된 기준 블록이다. 기준 블록과 앞쪽,
  다른 날짜는 그대로 두고 같은 날짜의 뒤쪽 시각·구간만 재계산한다.
- 고정 블록은 지정 시작·종료를 유지한다. 이동시간이 부족해도 고정 시각을 밀지 않고
  충돌을 보고한다. 고정 시간창이 체류시간과 다르면 `STAY_CONFLICT`를 보고한다.
- `insert`: 같은 날짜의 명시적인 인접 블록 쌍 사이에만 삽입한다. 기존 `seq` 값을
  변경하지 않으므로 두 값 사이에 정수 여유가 있어야 한다. 여유가 없으면
  `PolicyRequiredError`를 반환한다. 이것은 새 seq 정책이 아니라 재번호화 합의 전의 제한이다.
- 미고정 블록의 도착 = 이전 블록 출발 + 이동시간, 출발 = 도착 + 체류시간이다.
  영업시간에 맞춰 기다리기·순서 최적화 등 추가 정책은 적용하지 않는다.
- `validate`: 조회된 날짜별 영업시간·휴무·브레이크타임, 체류시간, 하루 시간창,
  고정 시간, 인접 구간 이동시간을 검사한다. 일정이나 경로 공급자를 변경하지 않는다.
- 날짜를 넘기는 계산은 날짜 분리 검토 경고를 내며 `00:xx`로 잘라내지 않는다.
  여행의 하루 시간창 자체가 자정을 넘는 경우는 지원하지 않는다.

## 확인 필요와 오류

검증 결과는 `type/cause` 목록이며 블록 경고와 최상위 목록에 함께 반영된다.
`*_NEEDS_CHECK`는 정보 부족 경고다. 경고가 있다는 이유로 검증 완료나 위반율 0%로
집계하면 안 된다. 외부 위반율·검증 불가 분모 정의는 후속 합의 대상이다.

- 좌표 없음: 경로 공급자를 호출하지 않고 이동시간을 null로 둔다. 뒤쪽 미고정 시각도
  계산할 수 없다면 null이다. 다음 고정 블록의 지정 시각은 유지한다.
- 영업시간 없음: `HOURS_NEEDS_CHECK`. 카카오 이름·영업시간을 만들어 채우지 않는다.
- 시간 없는 고정 블록: 기존 시각을 보존하며 `FIXED_TIME_NEEDS_CHECK`를 낸다.
- `EngineInputError`: 존재하지 않는 블록·비인접 슬롯·중복 위치 등 잘못된 입력.
- `PolicyRequiredError`: 자동 삽입 위치, seq 재번호화, 자정 넘는 하루 시간창 등 미합의 정책.
- `NeedsConfirmationError`: 공공 장소의 필수 표시 정보나 기존 구간 계산 시각이 없어
  현재 프런트 필수 응답 필드를 정직하게 만들 수 없음. 값을 날조하지 않고 호출자에게 알린다.
  이 예외들을 HTTP 상태·오류 세부값으로 매핑하는 엔드포인트는 아직 없다.

현재 필수 source enum에는 UNKNOWN이 없어 새로 확인 불가한 구간은
`durationMin=null, source=ESTIMATED`를 사용한다. null이면 추정 수치가 있다는 뜻이 아니다.
이 표현과 CACHE의 원래 출처 보존은 프런트와 추가 합의해야 한다.

## 검증 명령

설정 파일을 덮어쓰지 않고 현재 `backend` 가상환경에서 PR #4 규칙을 명령줄로 적용한다.

```powershell
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m ruff check --target-version py312 --line-length 120 --select E,F,I,B,UP app tests
.venv/Scripts/python.exe -m ruff format --check --target-version py312 --line-length 120 app tests
.venv/Scripts/python.exe -m mypy
```

PR #4 통합 후에는 Python 3.12·uv.lock 환경의 `uv sync --locked`와 CI 명령으로
재검증한다. 이번 테스트는 기존 Python 3.14 환경에서 실행하며 해당 통합을 대신하지 않는다.

## 다음 단계와 합의

1. 기존 seq 값까지 고정인지 상대 순서만 고정인지, 연속 seq에서 삽입·재번호화 허용 여부.
2. API-006 자동 배치, 카카오 장소 기본 체류시간, 최초 일정 생성과 시작·종료 위치 처리.
3. 김동현의 삭제·순서 이동 작업이 전달할 재계산 경계와 되돌리기 스냅샷 연결.
4. 검증 불가·충돌 상세 응답, 날짜 분리 제안, 좌표 없는 공공 장소 응답 형태.
5. 홍민지의 날짜별 정규화 영업시간·혼잡 공급자 연결. 계절/공휴일 원문 파싱은 엔진에서 하지 않는다.
6. FR-004의 점수화·최대 3개 후보 조회와 실제 경로 어댑터·상한·폴백은 후속 구현이다.
   현재 API-011은 요청·응답 모델만 제공한다.

프런트 공통 파일, places DB, 마이그레이션, 팀원 화면, CI 워크플로는 이번 구현 범위 밖이다.
