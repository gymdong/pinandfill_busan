# PR #11 리뷰 반영 계약

2026-11-11 기준. PR #11 리뷰(5853965231), PR #9 `6081354`, PR #10 `180e3a7`을 확인했다.
이 문서는 이전 단계 문서의 간격 seq·미조회 ESTIMATED·anchor 필수 설명을 대체한다.
PR #9·#10 및 프런트 코드는 수정하거나 병합하지 않았다.

## 순서와 AC-006

- 신규/정규화된 일정은 날짜별 `seq=1..n`이다.
- k번 뒤에 삽입하면 신규 블록은 k+1, 기존 뒤쪽 블록만 +1이다.
- 삽입 위치 앞쪽과 anchor의 모든 저장 필드, 다른 날짜의 블록은 보존한다.
- 뒤쪽 고정 블록은 seq만 위치에 맞춰 바뀌며 지정·도착·출발 시각은 유지한다.
  이동시간으로 도달할 수 없으면 충돌을 보고하고 HTTP 계층은 ERR-009로 저장을 거부한다.
- 재계산은 anchor를 보존하고 같은 날짜의 뒤쪽만 계산한다. seq를 재발급하지 않는다.
- 삭제·순서 변경 API는 구현하지 않는다. PR #9 mock의 삭제 뒤 -1, 이동 구간만 ±1,
  PR #10 EditHistory의 편집 전 스냅샷/트랜잭션 경계와 호환되는 규칙이다.
  첫 블록 삭제·이동의 시작시각 결정은 해당 편집 서비스의 명시적 anchor 처리 대상이다.

구형 10/20/30 또는 0 기반·간격 순서는 validate/recompute에서 읽을 수 있지만 숨겨서
정규화하지 않는다. 해당 날짜에 insert하면 ERR-001과 별도 정규화 안내를 반환한다.
`BasicItineraryEngine.normalize_sequences(trip, state, day_no=...)`는 명시적 마이그레이션
도구로만 제공한다. ID·시간·legs·다른 날짜를 보존하고 새 상태를 반환하며 저장하지 않는다.
운영 전 데이터 소유자가 별도 스냅샷과 트랜잭션으로 적용해야 한다. 일반 편집 경로는 이
함수를 호출하지 않는다. 따라서 정규화의 앞쪽 seq 변경을 일반 편집의 AC-006 통과로
주장하지 않는다. SQL unique 제약 적용 시 뒤에서 갱신하거나 deferrable 제약이 필요하다.

## API-006 dayNo

`AddBlockRequest`에 선택 필드 `dayNo: number`를 추가했다. 기존 anchor 요청은 그대로다.

1. fromBlockId와 toBlockId가 모두 있으면 같은 날짜의 인접 블록 사이에 삽입한다.
2. anchor가 모두 없으면 dayNo 날짜의 마지막에 추가한다.
3. dayNo가 없고 fixedWindow가 있다면 기존 요청 호환을 위해 fixedWindow.dayNo를 사용한다.
4. anchor가 하나만 있거나, 날짜·위치 모두 없거나, anchor/dayNo/fixedWindow가 모순이면 ERR-001.
5. 유효 날짜는 여행 startDate~endDate의 1 기반 일차다. 블록이 비어 있는 일차도 유효하다.

빈 날짜의 첫 블록은 seq=1이다. fixedWindow가 있으면 그 시간을 사용하고, 없으면
arriveAt/departAt=null 및 TIME_NEEDS_CHECK를 반환한다. dayStart로 방문시간을 임의 지정하지
않는다. 기존 날짜에 추가하면 마지막 블록의 출발시각으로 이동·체류시간을 계산한다.
첫 블록 앞에 끼워넣는 새로운 prepend 계약이나 최초 전체 자동 배치는 도입하지 않았다.

프런트 담당 후속: `frontend/src/types/api.ts`의 AddBlockRequest에 `dayNo?: number` 추가,
`features/block-editor` 및 `pages/map-view`에서 선택한 일차를 전송하고 mock에도 동일 규칙 적용.
PR #9의 현재 무anchor·무dayNo·무fixedWindow 요청은 여전히 ERR-001이다. 날짜를 1로 추측하지 않는다.
카카오 fixture는 실제 계약과 같이 숫자 ID와 `https://place.map.kakao.com/{id}`로 조정해야 한다.

## 미조회·실패 경로의 출처

PR #9 최신 LegSource는 TMAP/ODSAY/CACHE/ESTIMATED뿐이고 computedAt은 필수 문자열이다.
따라서 이번 변경에서 HTTP enum에 UNKNOWN이나 nullable computedAt을 추가하지 않았다.

| 내부 상태 | source | durationMin | computedAt | lookup_failed |
|---|---|---|---|---|
| 공급자 성공 | TMAP/ODSAY | 확인된 분 | 조회 시각 | false |
| 실제 추정 대역 결과 | ESTIMATED | 계산된 분 | 계산 시각 | false |
| 좌표/출발시각 부족 등 미조회 | UNKNOWN | null | null | false |
| 조회 실패 | UNKNOWN | null | 실패 조회 시각 | true |

저장 상태의 UNKNOWN은 장소 이름·좌표를 포함하지 않는다. 어댑터의 진단용
LookupResult.provider는 시도한 공급자를 뜻하고, 엔진용 RouteEstimate.source에는 실패 시
UNKNOWN을 반환한다. 이전 null-duration legacy 상태도 확인된 경로처럼 응답하지 않는다.

HTTP 호환 처리: 확인 불가능한 leg는 `days[].legs`에서 제외하고 기존
`warnings`/`violations`에 TRAVEL_TIME_NEEDS_CHECK, ROUTE_LOOKUP_FAILED 또는
DEPARTURE_TIME_NEEDS_CHECK 등을 반환한다. PR #9는 leg 유무를 확인해 렌더링하며
블록·일정 경고를 따로 표시하므로 거짓 '(추정)' 출처를 노출하지 않는다. 이동시간 숫자는
만들지 않는다. 이 변경은 불완전한 경로에 대한 표시 방식 변경이므로 프런트 연동 확인이 필요하다.

팀 합의 제안: UNKNOWN을 LegSource에 추가하고 computedAt을 string|null로 바꾼 다음,
실패/미조회 leg도 응답에 포함한다. 타임라인·지도에서 UNKNOWN은 '이동시간 확인 필요'로만
표시하고 source/시각을 성공의 근거로 사용하지 않는다. 이번 PR에서는 이 외부 타입 변경은 보류한다.

## Retry-After·TMAP 시각

Retry-After의 숫자·HTTP-date 대기시간은 최대 3,600초로 제한한다. 음수·잘못된 값·비유한
값은 무시해 기존 429 기본 cooldown 60초를 사용한다. CallBudget도 별도로 상한을 적용한다.
이는 자동 sleep/retry가 아니라 다음 호출 허용 시점 제한이다. 같은 요청의 재시도는 추가하지 않았다.

CAR predictionTime은 입력 datetime을 Asia/Seoul(현대 UTC+09)로 변환한 뒤 기존 TMAP
형식 `YYYY-MM-DDTHH:MM:SS+0900`으로 보낸다. UTC·UTC-05 및 날짜 변경을 테스트했다.
이 오프셋 형식은 [TMAP 공식 요청 예제](https://tmap-skopenapi.readme.io/reference/타임머신-자동차-길-안내)와 같다.
시간대별 예측과 TMAP transit 운행 여부·ODsay 시간 컨텍스트의 차이는 이전 설명대로 유지한다.

## 자정과 null 시각

- 기존 하루 내 비고정 블록: 이전 출발+이동+체류가 24:00 이상이면 arriveAt/departAt을
  모두 null로 둔다. 날짜를 자동 증가시키거나 시각을 00:xx로 잘라 쓰지 않는다.
  DAY_OVERFLOW 충돌은 '날짜 분리 필요', TIME_NEEDS_CHECK는 시각 미확정을 뜻한다.
- 좌표·이동시간·이전 출발시각 부족도 null을 만든다. 이 경우는 날짜 초과가 입증된 것이
  아니므로 DAY_OVERFLOW를 만들지 않고 해당 확인 필요 경고를 반환한다.
- 명시적으로 다음 일차에 배치된 블록은 그 일차의 날짜로 조회한다. 이는 정상적인 날짜
  변경이다. 전날 마지막 장소와 다음날 첫 장소의 이동 구간은 이번 엔진에서 자동 연결하지 않는다.
- 고정 블록 시간은 자정/이동 충돌에도 바꾸지 않는다. 밤샘 시간창의 자동 분할은 미구현이다.

## 검증

기존 224개 테스트는 유지하되 간격 seq 및 실패 source를 기대하던 테스트를 새 계약으로 수정했다.
추가 테스트는 앞쪽 전체 필드 보존, 연속 삽입·첫/중간/마지막 위치, dayNo·모순·빈 날짜,
독립 정규화, 미조회/실패 source, Retry-After, KST 날짜 경계를 검증한다.
실제 외부 API·DB·인증 연결은 수행하지 않는다. Python 3.12와 PR #4의 uv.lock을 그대로 사용한다.

검증 결과: pytest 256개 통과(기존 224개 + 신규 32개), Ruff·포맷 검사 통과,
기존 strict mypy 설정으로 Python 3.12 의존성을 대상으로 42개 소스 검사 통과.
Starlette TestClient의 httpx 사용 중단 예정 경고 1개는 기존 의존성 경고이며 이번 변경에서
잠금 파일을 바꾸지 않았다.
