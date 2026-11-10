# 타임라인·편집·지도 파트 인수인계 (김동현 → 팀)

작성일 2026-11-11. 대상 FR-006(블록 편집·되돌리기), FR-007(지도 보기·지도에서 고르기).
프런트는 mock API 기준으로 완료했고(`feature/fr-006-007-timeline-map`), 백엔드는 EditHistory 골격만 있다.

## 현재 상태

| 영역 | 상태 | 위치 |
|---|---|---|
| 타임라인 편집 UI(추가·삭제·순서·체류시간·경유지 삽입·되돌리기) | 완료(mock) | `frontend/src/pages/timeline`, `features/block-editor` |
| 지도 보기(경로·마커·목록 동기화·길게 누르기) | 완료(mock·단위 테스트). 실제 키로 수동 확인 전 | `frontend/src/map/KakaoMap.tsx`, `pages/map-view` |
| EditHistory(1단계 되돌리기) | 완료(순수 파이썬, 메모리 저장소) | `backend/app/modules/trips/edit_history.py` |
| `schedule_snapshots` 테이블·마이그레이션 | 미착수. ORM이 `core/db`에 아직 없음 | - |
| API-006·007·008·010 라우터 | 미착수. 엔진 의존 | - |

## 정현빈에게 (엔진·core/db)

1. 엔진 `insert` · `recompute`(변경 블록 뒤만) · `validate` 시그니처를 알려 달라. API-006~008 은 이 위에서 동작한다.
2. 편집 API 한 번의 처리 순서는 다음과 같이 쓰려고 한다.
   `현재 일정 조회 → EditHistory.record_before_edit(trip_id, 현재 일정) → 엔진으로 변경·재계산 → 저장 → {schedule, violations} 응답`
   트랜잭션 하나로 묶어야 한다(스냅샷만 남고 편집이 실패하면 안 된다).
3. 되돌리기(API-010)는 `EditHistory.undo(trip_id)` 가 돌려준 일정으로 blocks·legs 를 통째로 복원한다. 스냅샷이 없으면 `NothingToUndoError` 이므로 **409** 로 변환해 달라.
4. `core/db` 에 ORM(SQLAlchemy)·세션이 들어오면 `SnapshotRepository` Protocol(`next_version`·`save`·`latest`·`delete`)의 DB 구현을 내가 붙인다. `schedule_snapshots` 컬럼은 SDD 5.2 그대로다(id, trip_id, version, payload JSONB, reason, created_at).
5. AC-006 자동 검사용으로 `changed_block_ids(before, after)` 를 만들어 두었다. 엔진 시험에서 "변경 블록 뒤를 제외한 변경 0%"를 검사할 때 쓸 수 있다.
6. 경유지 시트(UI-03) 컴포넌트를 타임라인 경유지 슬롯에 붙여야 한다. 지금은 `BlockEditor` 의 경유지 추가 폼이 임시로 그 자리에 있다. 시트 컴포넌트가 나오면 교체한다. props 형태를 알려 달라.

## 홍민지에게

1. `schedule_snapshots` 마이그레이션은 ORM 이 정해지면 내가 파일을 만들고 병합 순서는 네가 정한다. `backend/alembic/versions` 의 리비전 번호를 미리 비워 둘 필요는 없다.
2. 혼잡 배지: 타임라인은 `day.crowd[]`(blockId별)를 `CrowdBadge` 로 그린다. 응답 스키마가 `frontend/src/types/api.ts` 의 crowd 타입과 같은지 확인해 달라. 근거 신호 0개일 때 '정보 부족' 표기는 `CrowdBadge` 가 처리한다.

## 박범찬에게

1. 지도에서 길게 눌러 장소를 추가하는 흐름은 `kakaoSession.ts` 의 장소 메모리를 쓴다. 서버는 카카오 장소의 이름·좌표를 모른다는 `@provisional` 가정을 그대로 두었다. 장소 상세(UI-04)에서 이 가정이 바뀌면 알려 달라.
2. `VITE_KAKAO_MAP_JS_KEY` 가 `.env` 에 필요하다. 개발용 키를 공유해 줄 수 있는지, 허용 도메인에 `localhost` 가 들어 있는지 확인해 달라.
3. `frontend/src/api` · `components` 는 네 소유라 이번 브랜치에서 `api/mock/index.ts` 를 고쳤다. PR 리뷰어로 지정한다.

## 모두에게

- 되돌리기는 **직전 EDIT 1단계만** 지원한다(SRS FR-006). 새 편집은 이전 스냅샷을 대체하고, PLAN_B 스냅샷은 되돌리기에서 소비하지 않는다(FR-010 용).
- P0 검증 기간은 11/19~11/22다. 그 전에 실제 백엔드 연동(`VITE_API_MODE` 를 mock 이 아니게)으로 편집·되돌리기·지도를 한 번 통과해야 한다.
