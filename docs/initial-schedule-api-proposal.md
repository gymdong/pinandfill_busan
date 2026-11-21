# API-009 연결: 2026-11-18 PM 확정 기준

근거: PR #18의 PM 결정 댓글. 엔진 PR #18에서는 HTTP에 적용하지 않았으며,
별도 API 연결 브랜치에서 구현했다. 실제 요청·응답·오류·화면 연결 방법은
[API-009 연결 계약](initial-schedule-api.md)을 따른다.

- initial.selections: place, clientId, 선택 dayNo/fixedWindow/stayMin. initial.policy=FIRST_FEASIBLE.
- initial과 options 동시 사용 거절. 기존 일정이 비어 있지 않으면 덮어쓰지 않고 명시적 오류.
- blockId는 서버 UUID, 미배치 응답은 clientId로 연결. 선택 목록 저장소 없음.
- isFixed는 방문시각 고정. 시간 미지정 핵심지는 true로 만들지 않는다.
- 모든 선택 배치 + 고정시각 충돌 없음이면 저장 가능. confirmed와 저장 여부는 분리.
- 하나라도 미배치면 saved=false, 기존 일정 보존. 부분 수락 API는 MVP에서 제외.
- 운영시간 미확인은 배치+경고. 체류시간은 사용자→공공값, 근거 없으면 입력 필요.
- DB 단계에서 일정/EDIT폐기/revision을 한 트랜잭션으로 처리. expectedRevision은 편집과 함께 도입.

## 별도 연결 PR의 구현 범위

1. 최신 dev의 #25 기본 서비스 조립과 API-026을 재사용한다. 중복 팩터리를 추가하지 않는다.
2. GenerateScheduleRequest에 확정 initial 모델과 엄격한 검증을 추가하고 서버 UUID 매핑을 만든다.
3. TripService.generate에 빈 일정 전용 초기 분기를 추가한다. 기존 initial 없는 재계산 경로 유지.
4. Internal result를 기존 days/violations/conflicts와 generation 메타데이터로 변환한다.
   메타데이터는 generation.saved/confirmed/unplaced, 미배치 매핑은 clientId로 고정한다.
   오류 매핑과 프런트 후속 변경은 연결 계약 문서에 정리했다. 요청 sessionCoords/카카오 이름·좌표는
   결과·저장·오류에 포함하지 않는다.
5. #17의 수락 검사/이력 보상을 재사용한다. 미배치·고정충돌·저장실패 시 기존 상태 보존 테스트.
6. 프런트 후속(이 PR 미포함): 박범찬의 createCourse를 API002→API009 initial 흐름으로 연결한다.
   생성→편집→삭제→undo는 백엔드 HTTP 테스트에 포함하며 실제 화면 연결 검증은 김동현과 이어간다.

#10/#17은 dev에 병합됐다. #17의 discard→save 실패 보상을 이전 결함 상태로 보고하지 않는다.
#25는 메모리 저장소/표본 장소/경로 설정 조립과 API026을 제공한다. 실제 DB는 미완료이며
API011 기본 CandidateProvider는 아직 미설정이다. 실제 TMAP/ODsay 품질·성능·쿼터 검증도 별도다.

## 남는 경계

내부 엔진은 미확인 경로의 이동시간을 지어내지 않는다. 시각을 계산할 수 없는 유연 블록은
미배치될 수 있다. 확인되지 않은 시각을 가진 블록까지 저장할 HTTP 표현은 이 PR에서 추가하지 않는다.
구체적 날짜 분리 제안, 태그별 체류 기본시간, DB revision은 이 PR 범위 밖이다.
