# 개발 역할 분담

계획서상 개발자는 1명(PE)이지만 실제 개발은 4명이 나눈다. SDD의 컴포넌트(COMP-xx) 경계를 따라 담당을 나눠
같은 파일을 여럿이 고치는 일을 줄인다. 담당자 배정은 제안이며 팀 회의에서 확정한다.

| 파트 | 담당(제안) | 맡는 컴포넌트 | 주 디렉터리 | 관련 요구사항 |
|---|---|---|---|---|
| A. 일정 엔진·경로 | 박범찬 | COMP-03 ItineraryEngine, COMP-07 PlanBService, 경로 어댑터(TMAP·ODsay·추정, RouteQuotaGuard) | `backend/app/modules/engine`, `trips`, `plan_b`, `backend/app/adapters/route` | FR-003, 005, 006, 009, 010, NFR-001, 012, 013, AI-REQ-03 |
| B. 추천·AI | 김동현 | COMP-04 RecommendService, COMP-06 AIService, 카카오 로컬 연동·장소 매칭 | `backend/app/modules/recommend`, `ai`, `places`, `backend/app/adapters/kakao` | FR-001, 002, 004, 012, 015, AI-REQ-01~08 |
| C. 데이터·혼잡·운영 | 홍민지 | COMP-05 CrowdService, COMP-09 BatchCollector, COMP-12 AdminModule, DB 스키마·마이그레이션, 날씨 | `backend/app/batch`, `modules/crowd`, `weather`, `admin`, `backend/app/adapters/public_data`, `weather`, `backend/alembic`, `data/` | FR-008, 013, 014, 016, 017, NFR-002, 003, 004, 007, 010 |
| D. 프런트엔드 | 정현빈 | COMP-01 Frontend (UI-01~UI-09), 회원·공유(P1) 화면 | `frontend/` | FR-006, 007, 011, NFR-008, 011 |

배정 근거: PE는 정확성의 핵심인 일정 엔진, PO는 UI 시안을 직접 그린 만큼 프런트엔드, QA는 데이터 검증을
맡으므로 수집·혼잡 데이터, PM은 외부 AI·추천 연동을 맡는다. 관리(PM)·인수 기준(QA) 업무는 기존대로 병행한다.

## 공동 소유

아래는 여러 파트가 함께 쓰므로 변경 시 PR에 관련 담당자를 모두 리뷰어로 지정한다.

- `backend/app/core` (설정·로깅·오류·캐시), `backend/app/db` (세션·Base), `backend/app/api` (라우터 조립)
- `backend/app/adapters/__init__.py` 의 SourceAdapter 인터페이스
- API 요청·응답 스키마(SDD 6장, API-001~026): 백엔드 담당이 먼저 스키마를 정하고 D가 확인한다
- `.github/workflows`, `infra/`, `docker-compose.yml`

## 파트 간 인터페이스

| 제공 | 사용 | 내용 |
|---|---|---|
| A → B | 경유지 추천 | 구간 이동시간 조회(추정·API), 삽입 후 재계산·위반 검사 |
| C → A, B | 일정·추천 | 영업시간(place_hours), 예상 혼잡(CrowdService), 날씨 예보 |
| B → A | 일정 생성 | 조건 해석 결과(Trip 조건), 설명 문구(비동기, 일정 계산과 분리) |
| A·B·C → D | 화면 | REST API (SDD 6장) |

## 디렉터리별 모듈 구성 규칙

`backend/app/modules/<모듈>/` 은 필요에 따라 다음 파일로 구성한다.

- `router.py` — FastAPI 라우터. 서비스 호출만 한다(Facade, SDD 11장)
- `schemas.py` — Pydantic 요청·응답 모델
- `models.py` — SQLAlchemy 테이블(SDD 5.2)
- `repository.py` — DB 접근
- `service.py` — 비즈니스 로직

## 작업 방식 (SDD 10.2)

- 브랜치: `feature/<요구사항 ID>` (예: `feature/FR-004`), `main` 은 항상 배포 가능 상태
- PR: 1명 이상 승인 + CI 통과, 설명에 FR/NFR ID 기재
- 외부 API는 테스트에서 목킹하고, 저장해 둔 응답은 `backend/tests/fixtures/` 에 둔다
