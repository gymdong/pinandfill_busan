# 타임라인·편집·지도 파트 인수인계 (김동현 → 팀)

작성일 2026-11-11, 갱신 2026-11-14(API-007·008·010 구현 반영). 대상 FR-006(블록 편집·되돌리기), FR-007(지도 보기·지도에서 고르기).

## 현재 상태

| 영역 | 상태 | 위치 |
|---|---|---|
| 타임라인 편집 UI(추가·삭제·순서·체류시간·경유지 삽입·되돌리기) | 완료(mock). PR #9 | `frontend/src/pages/timeline`, `features/block-editor` |
| 지도 보기(경로·마커·목록 동기화·길게 누르기) | 완료(mock·단위 테스트). 실제 키로 수동 확인 전. PR #9 | `frontend/src/map/KakaoMap.tsx`, `pages/map-view` |
| EditHistory(1단계 되돌리기)·AC-006 판정 | 완료. 엔진 `ScheduleState` 기준, 메모리 저장소(시험용). PR #10 | `backend/app/modules/trips/edit_history.py` |
| 엔진 `insert`·`recompute`·`validate`, API-006·009·011 | 병합됨(PR #11, 정현빈) | `backend/app/modules/engine`, `modules/trips` |
| `schedule_snapshots` 테이블·마이그레이션 | 미착수. ORM이 `core/db`에 아직 없음 | - |
| API-007(PATCH)·008(DELETE)·010(undo) 라우터, `TripService` 에 EditHistory 연결(API-006 포함) | 완료. `feature/FR-006-edit-api` 브랜치. 이력 저장소는 아직 메모리 구현 | `backend/app/modules/trips/{service,router,commands,schemas}.py`, 엔진 `project` |

## 합의된 계약 (PR #11)

- **seq**: 같은 날 안의 순서 번호 1..n(빈틈 없음). 편집은 편집 지점 뒤 블록의 seq 만 ±1 한다. 기존 10·20 형식 데이터는 편집 중에 바꾸지 않고 400 으로 거절하며, `BasicItineraryEngine.normalize_sequences` 로 따로 정규화한다.
- **AC-006 판정**: 다른 날 블록과 재계산 시작점까지의 앞쪽 블록은 seq 를 포함해 그대로여야 한다. 뒤쪽 고정 블록은 seq(위치)만 바뀔 수 있다. `ac006_violations(before, after, day_no=, anchor_seq=, edited_block_id=)` 가 이 규칙을 검사한다.
- **API-006 위치**: `fromBlockId`·`toBlockId` 가 있으면 그 사이에 삽입하고, 없으면 `dayNo`(없으면 `fixedWindow.dayNo`) 날짜의 마지막에 붙인다.
- **미조회 구간**: 엔진 내부는 `source="UNKNOWN"`, `durationMin=null`. 응답 `days[].legs` 에서는 빠지고 블록 경고로 확인 필요를 알린다. 외부 `LegSource` 에 `UNKNOWN` 을 넣을지는 프런트와 따로 정한다.

## API-007·008·010 동작 (`feature/FR-006-edit-api`)

| 요청 | 동작 | 재계산 시작점(AC-006 `anchor_seq`) |
|---|---|---|
| `PATCH {stayMin}` | 체류시간을 바꾸고 이 블록부터 다시 계산(이 블록 출발 시각도 바뀜) | 같은 날 앞 블록(`seq-1`) |
| `PATCH {seq}` | 같은 날 안에서만 옮기고 1..n 으로 다시 매김. 범위 밖이면 400 | `min(이전, 새 위치) - 1` |
| `PATCH {isFixed:false}` | 지정 시각(`fixedStart/End`)을 지우고(mock 과 같음) 도착 시각은 유지, 출발 = 도착 + 체류. 뒤 블록 재계산 | 이 블록 |
| `PATCH {isFixed:true}` | 지정 시각이 없으면 400 ERR-001. 남아 있으면 그 시각으로 고정 | 같은 날 앞 블록 |
| `DELETE` | 뒤 블록 seq 를 1씩 당기고 같은 날 앞 블록부터 재계산 | 같은 날 앞 블록 |
| `POST undo` | 직전 편집 전 상태를 재계산 없이 복원 | - |

- 본문: PATCH 는 `isFixed`·`seq`·`stayMin` 중 정확히 하나 + 선택 `sessionCoords`(아니면 400 ERR-001). DELETE·undo 본문은 없어도 되며 `sessionCoords` 만 받는다.
- 오류: 없는 블록·범위 밖 seq → 400 ERR-001, 기존 10·20 seq → 400 ERR-001, 고정 시각을 지킬 수 없는 결과 → 409 ERR-009, 없는 여행 → 404 ERR-016, 되돌릴 편집 없음 → 409 ERR-001(잠정).
- 같은 값으로 바꾸는 편집(같은 seq·stayMin·isFixed)은 저장·스냅샷 없이 현재 일정을 돌려준다.

### 미결 사항 (팀 확인 필요)

1. **그날 첫 블록이 바뀔 때의 시작 시각**: 첫 블록 삭제, 첫 위치로의 이동 등으로 새 첫 블록이 일반 블록이면 원래 첫 블록의 도착 시각(그날 시작 시각)을 이어받는다. 새 첫 블록이 고정이면 지정 시각을 그대로 둔다. 원래 첫 블록 시각이 없으면 새 첫 블록 시각도 비운다.
2. **그날 유일한 블록 삭제**: 그날은 빈 날이 되고 재계산 없이 투영만 한다(경로 조회 없음).
3. **고정 해제 시 시각**: 블록이 움직이지 않도록 도착 시각을 유지한다(앞 블록 기준으로 당기지 않음). 프런트 mock 은 이 블록 시각을 비워 재계산 대상으로 둔다. 당기는 쪽이 낫다면 시작점만 바꾸면 된다.
4. **고정 켜기**: API-007 이 시각을 받지 않아 사실상 다시 추가해야 한다. 고정 해제가 지정 시각을 지우므로 해제 후 다시 켜기도 400 이다. 시각을 함께 받을지(`fixedWindow`) 프런트와 정해야 한다.
5. **되돌릴 편집 없음의 오류 ID**: SDD 8장에 전용 ID 가 없어 409 + ERR-001 을 잠정으로 쓴다. 프런트 `ERROR_CATALOG` 의 ERR-001 상태 목록은 [400] 뿐이다.
6. **API-009 뒤 되돌리기**: 일정 생성은 기록하지 않으므로, 편집 → 일정 생성 → 되돌리기를 하면 생성 결과도 함께 사라지고 편집 전으로 돌아간다.

## 정현빈에게 (엔진·core/db)

1. API-007·008·010 과 `TripService` 연결을 마쳤다. 편집 한 번의 처리 순서는 다음과 같다(이전 문서의 "스냅샷 먼저" 순서에서 바뀌었다). 지금은 `TripService` 의 RLock 안에서, DB 를 붙인 뒤에는 한 트랜잭션 안에서 처리한다.
   `현재 상태 조회 → 엔진 편집 → 수락 검사(_accept: FixedScheduleConflictError 등) → EditHistory.record_before_edit(trip_id, record.schedule) → 저장`
   엔진 오류나 수락 검사로 거절된 편집은 스냅샷을 남기지 않으므로 **직전 EDIT 스냅샷이 그대로** 남는다(시험: `tests/unit/trips/test_service_edits.py::test_rejected_edit_keeps_previous_snapshot`). 상태가 그대로인 편집(같은 값)은 저장도 기록도 하지 않는다. API-006(블록 추가)도 같은 경로로 기록되어 되돌릴 수 있다. API-009(일정 생성)는 기록하지 않는다.
2. 되돌리기(API-010)는 `EditHistory.undo(trip_id)` 가 돌려준 `ScheduleState` 를 **다시 계산하지 않고** 저장하며, 응답 `{schedule}` 은 엔진 `project`(경로 조회 없이 `_present` 로 투영, 경고는 validate 규칙)로 만든다. 되돌리기 자체는 스냅샷을 남기지 않는다. 투영에 실패하면 소비한 스냅샷을 되살린다. 스냅샷이 없으면 `NothingToUndoError` → **409**.
3. `TripService(history=...)` 를 주입하지 않으면 `EditHistory(InMemorySnapshotRepository())` 를 쓴다. 로컬 Fake 저장소와 짝을 이루는 기본값이므로 DB 저장소를 붙일 때 함께 바꿔야 한다.
4. `core/db` 에 ORM(SQLAlchemy)·세션이 들어오면 `SnapshotRepository` Protocol(`next_version`·`save`·`latest`·`delete`)의 DB 구현을 내가 붙인다. `schedule_snapshots` 컬럼은 SDD 5.2 그대로다(id, trip_id, version, payload JSONB, reason, created_at). payload 는 `ScheduleState.model_dump(mode="json", by_alias=True)` 다.
5. 경유지 시트(UI-03) 컴포넌트를 타임라인 경유지 슬롯에 붙여야 한다. 지금은 `BlockEditor` 의 경유지 추가 폼이 임시로 그 자리에 있다. 시트 컴포넌트가 나오면 교체한다. props 형태를 알려 달라.

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
