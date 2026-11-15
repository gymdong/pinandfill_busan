# P0 담당 범위 및 후속 작업 확인 — 2026-11-15

## 근거와 완료 기준

[TEAM.md](TEAM.md)는 레이어가 아닌 기능 단위로 화면·API·DB를 담당하며 해당 FR의
P0 인수 기준 통과를 완료 기준으로 정한다. 계획서 7장 일정은 P0 개발 11/2~11/18,
P0 검증 11/19~11/22, P1 개발 11/23~11/27, 최종 발표 12/1이다.
원본 근거는 docs/specs의 프로젝트계획서·SRS·SDD v1.0이다. 별도 PRD 파일은 없으며
프로젝트계획서를 제품 목표의 근거로 사용했다. GitHub Issues 조회에는 PR 항목만 있었고
별도 이슈 기반 완료 기준은 확인하지 못했다.

정현빈 담당: FR-003 핵심지 고정, FR-004 경유지 제안, FR-005 일정 생성·검증,
UI-03 경유지 시트, 일정 엔진·경로 어댑터·RouteQuotaGuard, trips/blocks/legs,
공통 core/db/api와 CI/infra. API-009 연결도 이 범위에 포함된다.
김동현 담당: 타임라인·편집·지도와 EditHistory/schedule_snapshots.
박범찬 담당: UI-01·검색·AI·프런트 공통 API와 컴포넌트.
홍민지 담당: places/place_hours·배치·혼잡·마이그레이션 병합.
따라서 공공 DB 스키마/배치를 대신 만들지 않고 엔진의 공급자 연결을 담당한다.

## 기능별 상태 — 테스트 통과와 제품 완료를 구분

| 항목 | 확인한 상태 | 남은 필수 작업 |
| --- | --- | --- |
| FR-003 / AC-003 | 고정시간·순서 보존 엔진 및 회귀 테스트 | 편집/재생성/경유지 수락 10회 실제 통합 시나리오; 시간 없는 핵심지 UI 매핑 |
| FR-004 / AC-005 | API-011 Fake 추천·우회 검증, API-006 삽입 | UI-03 제공·타임라인 연결, 실데이터 후보/혼잡 공급자, 수락 평균 우회 15분 이내 인수 측정 |
| FR-005 / AC-004 | API-009 재계산·검증 및 내부 최초 생성 엔진 | 선택 입력 HTTP 연결·저장, 대표 일정 50개 영업/휴무 위반율 0% 자동 검사, 충돌 시 날짜 분리 안내 |
| 경로 어댑터 | Mock HTTP 및 KST 출발시각 연결 | 실제 공급자 설정·실환경 검증, 계획의 추정 1차 필터/상위 후보 API 확인 호출 최적화 |
| UI-03 | 별도 feature/FR-004-waypoint-sheet에서 제공 | 타임라인 담당자의 슬롯 연결·통합 검증 |

368개 백엔드 테스트가 위 인수 시나리오·실DB·실제 공급자 품질까지 증명하는 것은 아니다.
추정 1차 필터에는 검증된 추정 모델/정책이 필요하며 임의 속도 상수를 추가하지 않는다.
혼잡 회피(FR-009)는 홍민지의 CrowdService 제공 후 미고정 순서 결정에 연결하는 공동 인터페이스다.

## 최신 GitHub와 기존 합의

기준 dev: 90d52fd. [PR #18](https://github.com/gymdong/pinandfill_busan/pull/18)은 Draft,
내부 엔진만 포함하고 API-009/UI를 연결하지 않았다. 직접 이동 충돌이 후속 삽입으로
해소된 후에도 진단이 남는 결함을 수정했고 368개 회귀 테스트를 통과했다.

[PR #10](https://github.com/gymdong/pinandfill_busan/pull/10) c11b4c9와
[PR #17](https://github.com/gymdong/pinandfill_busan/pull/17) 67600c7은 11/14 제출한
수정 요청 이후 HEAD가 그대로다. 중복 재현/코드 수정 없이 대기 대상으로 둔다.
#10의 after-only 블록 AC-006 검사, #17의 생성 저장/이력 폐기 원자성과 첫 블록 자정
진단은 기존 리뷰의 해결 대상을 유지한다.

이미 합의된 seq 1..n, anchor 앞쪽 불변성, 고정시각 보존, API-006 양쪽 anchor 또는
날짜 마지막 추가, 내부 UNKNOWN/외부 경고 표현을 재합의하지 않는다.
[PR #12](https://github.com/gymdong/pinandfill_busan/pull/12)는 dayNo 타입 병합,
[PR #16](https://github.com/gymdong/pinandfill_busan/pull/16)은 지도 dayNo 전달 작업이다.
[PR #14](https://github.com/gymdong/pinandfill_busan/pull/14)는 조사 데이터이며 운영 DB가 아니다.
[PR #15](https://github.com/gymdong/pinandfill_busan/pull/15)는 검색 API이며 초기 선택 목록 계약이 아니다.

## 실행 순서와 경계

1. PR18 실제 결함 수정 및 회귀 검증. 기존 PR에 관련 수정만 push.
2. 이미 확정된 API-011/006으로 UI-03 독립 컴포넌트·테스트 제공. 팀원 화면을 직접 변경하지 않음.
3. API-009 최초 선택 입력·미배치 응답·부분 저장 기준을 UI-01/편집 담당과 확정한 뒤 서비스 연결.
   기존 initial-schedule-api-proposal.md는 제안이지 합의가 아니다. 태그 기본 체류시간도 미확정.
4. #17 원자성 수정 후 생성→편집→undo 통합. places/place_hours 공급자 계약과 DB 준비 후
   본인 trips/blocks/legs 저장소·경로 공급자 설정 연결. 실제 키 호출은 별도 검증 단계.
5. 11/19~11/22 P0 검증에서 AC-003/004/005 인수 시나리오와 대표 데이터 결과를 수집.

계획 밖 선택 개선: 전역 최적해 탐색, 다중 기기 선택 초안 저장, 추가 UX 기능.
이들은 현재 필수 연동/인수 기준보다 우선하지 않으며 이번에 구현하지 않는다.

