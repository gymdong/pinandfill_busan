# 핀앤필 부산 (Pin & Fill Busan)

부산을 1~3일 여행하는 개별 여행자가 정한 핵심 여행지를 고정(Pin)하고, 사이 구간을 우회가 적은 경유지로
채워(Fill) 영업시간·이동시간까지 검증해 주는 모바일 웹 플래너. 팀 짜조.

- 백엔드: FastAPI, PostgreSQL(개발 SQLite), Redis(잠정), Docker Compose
- 프런트엔드: React 모바일 웹(360px 기준), 카카오맵 JS SDK
- 외부: 카카오 로컬, TMAP 대중교통(주력)·ODsay(예비), 기상청, TourAPI·부산시 공공데이터, Gemini 2.5 Flash-Lite, bge-m3

문서: [`docs/specs/`](docs/specs) (계획서·SRS·SDD), 역할 분담: [`docs/TEAM.md`](docs/TEAM.md)

## 디렉터리 구조

개발은 P0 기능 단위로 나눈다. 아래 이름은 디렉터리의 주 담당이며, 기능별 배분은 [`docs/TEAM.md`](docs/TEAM.md) 를 따른다.

```
.
├── backend/
│   ├── app/
│   │   ├── core/            # 설정(app_config 연동)·로깅·오류·캐시·보안           정현빈
│   │   ├── db/              # DB 세션·Base                                        정현빈
│   │   ├── api/             # 라우터 조립, 공통 의존성                            정현빈
│   │   ├── modules/
│   │   │   ├── trips/       # 여행·블록·구간 API (API-002, 006~010, 026)          정현빈·김동현(편집·되돌리기)
│   │   │   ├── engine/      # ItineraryEngine, 삽입 스케줄러, 되돌리기            정현빈
│   │   │   │   └── constraints/  # 영업시간·휴무·이동시간 검증 체인              정현빈
│   │   │   ├── plan_b/      # 플랜 B 3안                                          P1
│   │   │   ├── places/      # 장소 검색·상세, 카카오↔공공 DB 매칭                 박범찬
│   │   │   ├── recommend/   # 경유지(우회 비용)·분위기 추천                       정현빈(경유지)·박범찬(분위기)
│   │   │   ├── ai/          # AIService, OutputGuard, InputSanitizer, 규칙 폴백   박범찬
│   │   │   │   ├── providers/  # Gemini(LLM·VLM), bge-m3 임베딩
│   │   │   │   └── prompts/
│   │   │   ├── crowd/       # 3단 융합 예상 혼잡                                  홍민지
│   │   │   ├── weather/     # 블록별 예보                                         P1
│   │   │   ├── admin/       # 소스 상태·설정·수동 보정 (API-022~025)              홍민지
│   │   │   └── auth/        # 카카오 로그인·공유 링크                             P1
│   │   ├── adapters/        # SourceAdapter 인터페이스
│   │   │   ├── kakao/       # 카카오 로컬 (응답 미저장)                           박범찬
│   │   │   ├── route/       # TMAP·ODsay·추정, RouteQuotaGuard                    정현빈
│   │   │   ├── weather/     # 기상청 단기·중기                                    P1
│   │   │   └── public_data/ # TourAPI·부산시·교통공사                             홍민지
│   │   └── batch/           # 스케줄러·수집 작업 (compose의 batch 서비스)          홍민지
│   │       └── jobs/
│   ├── alembic/versions/    # DB 마이그레이션 (병합 담당)                         홍민지
│   └── tests/
│       ├── unit/            # engine, recommend, crowd, ai
│       ├── contract/        # 어댑터 계약 테스트 (외부 API 목킹)
│       ├── integration/
│       └── fixtures/        # 저장해 둔 경로·공공 API 응답(mock)
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── app/             # 라우팅·전역 Provider                                박범찬
│   │   ├── pages/
│   │   │   ├── trip-start/      # UI-01 여행 시작                                 박범찬
│   │   │   ├── timeline/        # UI-02 코스 타임라인                             김동현
│   │   │   ├── place-detail/    # UI-04 장소 상세 (혼잡 그래프는 홍민지)          박범찬
│   │   │   ├── map-view/        # UI-06 지도 보기                                 김동현
│   │   │   ├── mood-search/     # UI-08 분위기로 찾기                             박범찬
│   │   │   ├── admin/           # UI-09 관리자                                    홍민지
│   │   │   └── photo-search/ shared-trip/   # UI-07, 공유 열람                    P1
│   │   ├── features/
│   │   │   ├── waypoint-sheet/  # UI-03 경유지 시트                               정현빈
│   │   │   ├── block-editor/    # 블록 편집·순서 변경                             김동현
│   │   │   ├── place-search/    # 카카오 검색·배지                                박범찬
│   │   │   ├── crowd/           # 혼잡 배지·그래프                                홍민지
│   │   │   └── plan-b-sheet/ weather/ auth/                                       P1
│   │   ├── components/      # 공용 UI (탭 영역 44px 이상, 색 비의존 표기)          박범찬
│   │   ├── map/             # 카카오맵 SDK 래퍼                                   김동현
│   │   ├── api/             # API 클라이언트                                      박범찬
│   │   └── store/ hooks/ types/ styles/ utils/
│   └── tests/
├── data/                                                                          홍민지
│   ├── seed/                # 테마 태그 사전(10~15개), 수동 매칭표
│   ├── samples/             # 착수 주 공공 API 샘플 응답
│   └── eval/                # 대표 장소 100곳·태그 점검 세트(AI-TC-08)
├── scripts/sample_calls/    # 데이터 확인용 샘플 호출 스크립트
├── infra/docker/            # Dockerfile 외 배포 설정                             정현빈
├── .github/workflows/       # CI: 린트·단위·계약 테스트, 위반율 검사(샘플 50개)   정현빈
└── docs/
    ├── specs/               # 계획서·SRS·SDD 원본
    ├── TEAM.md              # 역할 분담
    ├── adr/                 # ADR-013 이후 설계 결정
    ├── data-notes/          # 데이터 확인 메모
    └── meetings/
```
