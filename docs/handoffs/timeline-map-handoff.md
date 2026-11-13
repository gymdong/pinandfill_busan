# 타임라인·편집·지도 파트 인수인계 (김동현 → 팀)

작성일 2026-11-11, 갱신 2026-11-12(PR #8·#11 병합 반영). 대상 FR-006(블록 편집·되돌리기), FR-007(지도 보기·지도에서 고르기).

## 현재 상태

| 영역 | 상태 | 위치 |
|---|---|---|
| 타임라인 편집 UI(추가·삭제·순서·체류시간·경유지 삽입·되돌리기) | 완료(mock). PR #9 | `frontend/src/pages/timeline`, `features/block-editor` |
| 지도 보기(경로·마커·목록 동기화·길게 누르기) | 완료(mock·단위 테스트). 실제 키로 수동 확인 전. PR #9 | `frontend/src/map/KakaoMap.tsx`, `pages/map-view` |
| EditHistory(1단계 되돌리기)·AC-006 판정 | 완료. 엔진 `ScheduleState` 기준, 메모리 저장소(시험용). PR #10 | `backend/app/modules/trips/edit_history.py` |
| 엔진 `insert`·`recompute`·`validate`, API-006·009·011 | 병합됨(PR #11, 정현빈) | `backend/app/modules/engine`, `modules/trips` |
| `schedule_snapshots` 테이블·마이그레이션 | 미착수. ORM이 `core/db`에 아직 없음 | - |
| API-007(PATCH)·008(DELETE)·010(undo) 라우터, `TripService` 에 EditHistory 연결 | 미착수. 다음 작업 | - |

## 합의된 계약 (PR #11)

- **seq**: 같은 날 안의 순서 번호 1..n(빈틈 없음). 편집은 편집 지점 뒤 블록의 seq 만 ±1 한다. 기존 10·20 형식 데이터는 편집 중에 바꾸지 않고 400 으로 거절하며, `BasicItineraryEngine.normalize_sequences` 로 따로 정규화한다.
- **AC-006 판정**: 다른 날 블록과 재계산 시작점까지의 앞쪽 블록은 seq 를 포함해 그대로여야 한다. 뒤쪽 고정 블록은 seq(위치)만 바뀔 수 있다. `ac006_violations(before, after, day_no=, anchor_seq=, edited_block_id=)` 가 이 규칙을 검사한다.
- **API-006 위치**: `fromBlockId`·`toBlockId` 가 있으면 그 사이에 삽입하고, 없으면 `dayNo`(없으면 `fixedWindow.dayNo`) 날짜의 마지막에 붙인다.
- **미조회 구간**: 엔진 내부는 `source="UNKNOWN"`, `durationMin=null`. 응답 `days[].legs` 에서는 빠지고 블록 경고로 확인 필요를 알린다. 외부 `LegSource` 에 `UNKNOWN` 을 넣을지는 프런트와 따로 정한다.

## 정현빈에게 (엔진·core/db)

1. API-007·008·010 과 `TripService` 연결은 내가 이어서 맡는다. 편집 한 번의 처리 순서는 다음과 같다. 지금은 `TripService` 의 RLock 안에서, DB 를 붙인 뒤에는 한 트랜잭션 안에서 처리한다.
   `현재 상태 조회 → EditHistory.record_before_edit(trip_id, record.schedule) → 엔진 편집 → _save`
   `_save` 가 `FixedScheduleConflictError` 로 거절하면 방금 기록한 스냅샷도 저장되지 않아야 한다.
2. 되돌리기(API-010)는 `EditHistory.undo(trip_id)` 가 돌려준 `ScheduleState` 로 저장한다. 스냅샷이 없으면 `NothingToUndoError` 이므로 **409** 로 변환한다.
3. `core/db` 에 ORM(SQLAlchemy)·세션이 들어오면 `SnapshotRepository` Protocol(`next_version`·`save`·`latest`·`delete`)의 DB 구현을 내가 붙인다. `schedule_snapshots` 컬럼은 SDD 5.2 그대로다(id, trip_id, version, payload JSONB, reason, created_at). payload 는 `ScheduleState.model_dump(mode="json", by_alias=True)` 다.
4. 경유지 시트(UI-03) 컴포넌트를 타임라인 경유지 슬롯에 붙여야 한다. 지금은 `BlockEditor` 의 경유지 추가 폼이 임시로 그 자리에 있다. 시트 컴포넌트가 나오면 교체한다. props 형태를 알려 달라.

## 홍민지에게

1. `schedule_snapshots` 마이그레이션은 ORM 이 정해지면 내가 파일을 만들고 병합 순서는 네가 정한다.
2. 혼잡 배지: 타임라인은 `day.crowd[]`(blockId별)를 `CrowdBadge` 로 그린다. 응답 스키마가 `frontend/src/types/api.ts` 의 crowd 타입과 같은지 확인해 달라. 근거 신호 0개일 때 '정보 부족' 표기는 `CrowdBadge` 가 처리한다.

## 박범찬에게

1. `AddBlockRequest` 에 `dayNo` 가 필요하다(PR #11 에서 API-006 에 추가됨). 타입을 고쳐 주면 지도의 "핵심지에 추가"가 지금 보는 일차를 보내도록 맞춘다.
2. mock 의 카카오 장소 키(`mock-kakao-3`, `https://example.com/...`)가 백엔드 형식(숫자 ID, `https://place.map.kakao.com/{id}`)과 다르다. 실제 연동 전에 fixture 를 맞춰 달라.
3. 개발용 `VITE_KAKAO_MAP_JS_KEY`(허용 도메인에 `localhost` 포함)가 필요하다. 키는 문서에 적지 말고 DM 등 비공개 경로로 전달해 달라.
4. 지도에서 길게 눌러 장소를 추가하는 흐름은 `kakaoSession.ts` 의 장소 메모리를 쓴다. 서버는 카카오 장소의 이름·좌표를 모른다는 `@provisional` 가정을 그대로 두었다.

## 모두에게

- 되돌리기는 **직전 EDIT 1단계만** 지원한다(SRS FR-006). 새 편집은 이전 스냅샷을 대체하고, PLAN_B 스냅샷은 되돌리기에서 소비하지 않는다(FR-010 용).
- P0 검증 기간은 11/19~11/22다. 그 전에 실제 백엔드 연동(`VITE_API_MODE` 를 mock 이 아니게)으로 편집·되돌리기·지도를 한 번 통과해야 한다.
