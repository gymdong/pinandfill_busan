# 핀앤필 부산 (Pin & Fill Busan)

부산을 1~3일 여행하는 개별 여행자가 정한 핵심 여행지를 고정(Pin)하고, 사이 구간을 우회가 적은 경유지로
채워(Fill) 영업시간·이동시간까지 검증해 주는 모바일 웹 플래너. 팀 짜조.

- 백엔드: FastAPI, PostgreSQL(개발 SQLite), Redis(잠정), Docker Compose
- 프런트엔드: React 모바일 웹(360px 기준), 카카오맵 JS SDK
- 외부: 카카오 로컬, TMAP 대중교통(주력)·ODsay(예비), 기상청, TourAPI·부산시 공공데이터, Gemini 2.5 Flash-Lite, bge-m3

문서: [`docs/specs/`](docs/specs) (계획서·SRS·SDD), 역할 분담: [`docs/TEAM.md`](docs/TEAM.md)

## 디렉터리 구조

```
.
├── backend/
│   ├── app/
│   │   ├── core/            # 설정(app_config 연동)·로깅·오류·캐시·보안           [공동]
│   │   ├── db/              # DB 세션·Base                                        [공동]
│   │   ├── api/             # 라우터 조립, 공통 의존성                            [공동]
│   │   ├── modules/
│   │   │   ├── trips/       # 여행·블록·구간·스냅샷 API (API-002, 006~010, 026)    [A]
│   │   │   ├── engine/      # ItineraryEngine, 삽입 스케줄러, 되돌리기            [A]
│   │   │   │   └── constraints/  # 영업시간·휴무·이동시간 검증 체인              [A]
│   │   │   ├── plan_b/      # 플랜 B 3안 (P1)                                     [A]
│   │   │   ├── places/      # 장소 검색·상세, 카카오↔공공 DB 매칭                 [B]
│   │   │   ├── recommend/   # 경유지(우회 비용)·분위기 추천                       [B]
│   │   │   ├── ai/          # AIService, OutputGuard, InputSanitizer, 규칙 폴백   [B]
│   │   │   │   ├── providers/  # Gemini(LLM·VLM), bge-m3 임베딩
│   │   │   │   └── prompts/
│   │   │   ├── crowd/       # 3단 융합 예상 혼잡                                  [C]
│   │   │   ├── weather/     # 블록별 예보                                         [C]
│   │   │   ├── admin/       # 소스 상태·설정·수동 보정 (API-022~025)              [C]
│   │   │   └── auth/        # 카카오 로그인·공유 링크 (P1)                        [D와 협업]
│   │   ├── adapters/        # SourceAdapter 인터페이스                            [공동]
│   │   │   ├── kakao/       # 카카오 로컬 (응답 미저장)                           [B]
│   │   │   ├── route/       # TMAP·ODsay·추정, RouteQuotaGuard                    [A]
│   │   │   ├── weather/     # 기상청 단기·중기                                    [C]
│   │   │   └── public_data/ # TourAPI·부산시·교통공사                             [C]
│   │   └── batch/           # 스케줄러·수집 작업 (compose의 batch 서비스)          [C]
│   │       └── jobs/
│   ├── alembic/versions/    # DB 마이그레이션                                     [C]
│   └── tests/
│       ├── unit/            # engine, recommend, crowd, ai
│       ├── contract/        # 어댑터 계약 테스트 (외부 API 목킹)
│       ├── integration/
│       └── fixtures/        # 저장해 둔 경로·공공 API 응답(mock)
├── frontend/                                                                      [D]
│   ├── public/
│   ├── src/
│   │   ├── app/             # 라우팅·전역 Provider
│   │   ├── pages/           # trip-start(UI-01), timeline(UI-02), place-detail(UI-04),
│   │   │                    # map-view(UI-06), photo-search(UI-07), mood-search(UI-08),
│   │   │                    # shared-trip, admin(UI-09)
│   │   ├── features/        # waypoint-sheet(UI-03), plan-b-sheet(UI-05), block-editor,
│   │   │                    # place-search, crowd, weather, auth
│   │   ├── components/      # 공용 UI (탭 영역 44px 이상, 색 비의존 표기)
│   │   ├── map/             # 카카오맵 SDK 래퍼
│   │   ├── api/             # API 클라이언트
│   │   └── store/ hooks/ types/ styles/ utils/
│   └── tests/
├── data/                                                                          [C]
│   ├── seed/                # 테마 태그 사전(10~15개), 수동 매칭표
│   ├── samples/             # 착수 주 공공 API 샘플 응답
│   └── eval/                # 대표 장소 100곳·태그 점검 세트(AI-TC-08)
├── scripts/sample_calls/    # 데이터 확인용 샘플 호출 스크립트
├── infra/docker/            # Dockerfile 외 배포 설정
├── .github/workflows/       # CI: 린트·단위·계약 테스트, 위반율 검사(샘플 50개)
└── docs/
    ├── specs/               # 계획서·SRS·SDD 원본
    ├── TEAM.md              # 역할 분담
    ├── adr/                 # ADR-013 이후 설계 결정
    ├── data-notes/          # 데이터 확인 메모
    └── meetings/
```

`[A]`~`[D]` 는 [`docs/TEAM.md`](docs/TEAM.md) 의 담당 파트다.
