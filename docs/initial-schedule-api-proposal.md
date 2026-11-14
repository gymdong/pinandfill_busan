# API-009 최초 생성 연결 제안 (팀 검토용, 미구현)

확인일: 2026-11-15 KST. 기준 dev `90d52fd`, 내부 엔진 `520d427`.
이 문서는 제안이며 HTTP 스키마·서비스·프런트 동작을 변경하지 않는다.

## 현재 계약과 변경 범위

백엔드 `app/modules/trips/schemas.py`와 프런트 `src/types/api.ts`의
GenerateScheduleRequest는 options와 sessionCoords만 받는다. TripService.generate는
기존 블록의 일별 첫 시각을 기준으로 재계산하며 빈 일정의 최초 생성은 거절한다.
내부 InitialSchedulePlanner는 저장소를 변경하지 않고 ScheduleState, schedule,
unplaced, violations, conflicts, confirmed를 반환한다.

현재 PR은 엔진·테스트·문서만 추가한다. API-006·009·011은 기존 계약을 유지한다.

## 최소 변경안

기존 요청을 유지하면서 선택적 `initial` 객체를 추가하는 방안을 권고한다.
options 내부에 비공식 선택 목록을 숨기지 않는다. 아래 이름과 형식은 합의 전 제안이다.

| 제안 필드 | 의미 및 검증 |
| --- | --- |
| initial.selections | 비어 있지 않은 선택 배열. 배열 순서는 처리 우선순위이며 최종 방문 순서와 다름 |
| selection.clientId | 요청 내 고유 식별자. 미배치 결과와 UI 연결; 서버가 안정적인 blockId로 매핑 |
| selection.place | API-006의 PUBLIC `{placeId}` 또는 기존 KakaoPlaceKey(ID·URL) 형식 재사용 |
| selection.dayNo? | 여행 내 날짜 제한. 생략하면 여행 기간 전체. 실제 날짜는 TripWindow에서 파생 |
| selection.fixedWindow? | 기존 FixedWindow 재사용. 선택 사항이며 지정 시 보존; dayNo와 모순되면 거절 |
| selection.stayMin? | 양의 사용자 지정 분. 없으면 PUBLIC 장소별 값; 근거가 없으면 미배치 |
| initial.policy | FIRST_FEASIBLE 명시. 운영 기본값·최적화 정책은 합의 전 자동 적용하지 않음 |
| sessionCoords? | 기존 요청 전용 필드 유지. 장소 식별자 매핑 후 CalculationContext에만 전달 |

tripId의 여행 기간·일일 시간창·이동수단을 서버에서 조회한다. 클라이언트가 동일 정보를
중복 전송해 서로 다른 여행 조건을 만들지 않게 한다. 외부 clientId를 서버 blockId로
매핑하는 규칙과 재시도 식별자 수명은 HTTP 연결 테스트에서 고정해야 한다.
선택 중복 방문을 허용할 때 같은 placeId라도 clientId는 달라야 한다.

initial이 없으면 기존 generate 재계산 동작을 유지한다. initial이 있고 기존 일정이
비어 있지 않으면 묵시적으로 덮어쓰지 않는다. 재생성은 별도 명시적 의도와 예상 일정
revision을 받아 동시 편집을 검사하도록 후속 설계한다. 오류 ID·상태는 현재 카탈로그와
대조해 합의하며 새 ID나 409 ERR-001을 이번 PR에서 임의 도입하지 않는다.

## 응답과 저장

기존 days/violations/conflicts를 유지하고 최초 생성 요청에만 선택적 generation 메타데이터를
추가하는 방안을 권고한다: confirmed, saved, unplaced[{clientId, reason}].
미배치 사유는 정형 코드·안전한 메시지만 포함한다. 이동시간 미확인은 기존 검증 경고와
confirmed=false로 표현하고 확인된 경로처럼 표시하지 않는다. 내부 UNKNOWN을 기존
프런트 LegSource enum에 그대로 노출하지 않는다.

안전한 기본 권고는 모든 선택 배치·검증 완료·표시 가능 결과만 저장하는 것이다.
부분 생성·미확정 결과는 saved=false인 미리보기로 반환하고 기존 일정을 보존한다.
PUBLIC 표시 정보가 없어 내부 schedule=None이면 정상 Schedule을 조작하지 말고
기존 확인 필요 오류 매핑을 검토한다. 미리보기 수락·부분 저장 API는 별도 합의 전 제공하지 않는다.
UI는 saved=false를 서버 일정으로 교체하지 않고 미배치 목록과 확인 필요 상태를 표시해야 한다.

## 선택 목록 저장소 비교

MVP에는 요청으로 받은 목록을 즉시 계산하고 수락된 ScheduleState만 저장하는 방식이
충분하다. 별도 선택 목록 테이블은 필수가 아니다. 미배치 목록은 응답으로 전달하고 UI의
편집 상태에 유지한다. 새로고침·다중 기기에서 미배치 선택까지 복구해야 할 때만 별도
초안 저장소를 도입한다. 그 경우에도 KAKAO ID·URL만 저장하고 좌표·검색 이름은 저장하지 않는다.
영속 선택 목록이 없으면 재생성 시 클라이언트가 전체 선택 목록을 다시 보내거나 저장된
블록 참조로 명시적으로 구성해야 한다. 이전 요청을 서버가 기억한다고 가정하지 않는다.

## PR #10·#17 호환성과 트랜잭션

- [#10](https://github.com/gymdong/pinandfill_busan/pull/10), HEAD c11b4c9:
  EditHistory는 ScheduleState를 직전 EDIT 스냅샷으로 저장한다. 최신 리뷰는 수정 요청 상태다.
- [#17](https://github.com/gymdong/pinandfill_busan/pull/17), HEAD 67600c7:
  generate는 `_save` 후 `history.discard`를 수행한다. 이력 폐기가 실패하면 일정만 저장될 수
  있으므로 생성 연결 전에 함께 해결해야 한다. 최신 리뷰도 수정 요청 상태다.
- 생성 계산·검증은 저장 전 수행하고 일정 저장, EDIT 이력 폐기, revision 갱신은 하나의
  저장소 트랜잭션으로 묶는다. 어느 단계가 실패해도 이전 일정·이력이 그대로 남아야 한다.
  메모리 Fake도 중간 실패 주입 테스트가 필요하다. 단순 RLock은 DB 원자성을 대신하지 않는다.
- 무변경 재계산은 이력을 지우지 않는다. 변경된 재생성이 성공한 경우 기존 EDIT 이력을
  폐기하는 #17 방향을 따르되 PLAN_B 등 다른 스냅샷까지 지우지 않는다.
- 생성 결과는 기존 block ID, 날짜별 seq 1..n, 고정 시간창 모델을 사용하므로 이후 편집의
  입력 구조와 호환된다. 다만 #17이 미병합이라 실제 생성→수정→삭제→undo 통합은 미검증이다.
- 시각 미지정 핵심지는 현재 내부 엔진에서 배치 가능한 블록이다. UI의 핵심지 여부와
  방문시각 고정(isFixed)을 같은 의미로 처리할지는 연결 전에 명시해야 한다.
- undo의 project는 PUBLIC 조회 및 현재 TripWindow에 의존한다. 공급자 장애나 여행 날짜
  변경 때 복원을 막는 문제와 표시용 투영 실패를 영속 복원 실패로 볼지는 후속 서비스 설계 대상이다.

## 카카오와 검증 계획

sessionCoords는 요청 중에만 사용한다. 요청 본문 로깅·캐시·오류 echo·스냅샷을 금지하고,
응답의 KAKAO place에는 ID·URL만 포함한다. 재생성 시 좌표가 없으면 확인 필요로 남긴다.

후속 작업 순서:
1. 위 선택 입력·응답 메타데이터·저장 기준과 핵심지/시간 고정 의미 합의.
2. 백엔드 schemas/commands/TripService.generate에 명시적 최초 생성 분기 연결.
3. DB의 일정·이력 트랜잭션과 revision 검사 구현; 실패·중복 요청·동시 편집 테스트.
4. 프런트 타입, API 클라이언트, 선택 화면 상태와 생성 결과/미배치 표시 연결.
5. HTTP 테스트: 기존 빈 요청 재계산 유지, 최초/부분/미확정 생성, 저장 실패 롤백,
   재생성 이력 보존, 생성 후 #17 편집·undo, KAKAO 비저장, 날짜 경계.
6. 실제 장소별 체류시간·영업시간 DB 및 경로 공급자 설정 후 별도 승인된 실환경 검증.

이번 검증은 Python 3.12.16에서 pytest 367개, Ruff·포맷, mypy app 52개 소스를 대상으로 했다.
실제 DB·외부 공급자·UI 통합과 이 문서의 새 HTTP 형식은 구현하거나 검증하지 않았다.
