# 핀앤필 부산 백엔드

FastAPI 기반 API 서버. 패키지 관리는 [uv](https://docs.astral.sh/uv/)를 쓰며 Python 3.12를 기준으로 한다.

## 준비

```bash
cd backend
uv sync              # .venv 생성과 의존성 설치 (Python 3.12가 없으면 uv가 내려받는다)
cp .env.example .env # 키 값을 채운다. .env 는 커밋하지 않는다
```

## 명령

| 명령 | 내용 |
| --- | --- |
| `uv run pytest` | 테스트 |
| `uv run ruff check .` | 린트 |
| `uv run ruff format .` | 포맷 |
| `uv add <패키지>` | 의존성 추가. `pyproject.toml`과 `uv.lock`을 함께 커밋한다 |
| `uv add --dev <패키지>` | 개발용 의존성 추가 |

## DB 와 마이그레이션

`DATABASE_URL` 이 비어 있으면 여행과 되돌리기 이력을 메모리에 저장한다(테스트·로컬 기본, 재시작하면 사라진다).
값이 있으면 PostgreSQL 의 trips·blocks·legs·schedule_snapshots 에 저장한다. 스키마는 alembic 으로만 만든다.

```bash
docker compose up -d db               # 저장소 루트에서. 로컬 개발용 PostgreSQL 16
# backend/.env: DATABASE_URL=postgresql://pinandfill:pinandfill@localhost:5432/pinandfill
uv run alembic upgrade head           # 최신 스키마로 올린다
uv run alembic downgrade -1           # 한 단계 내린다
uv run alembic revision --autogenerate -m "설명"  # app/db/models.py 를 고친 뒤 마이그레이션 초안을 만든다
uv run alembic check                  # 모델과 DB 스키마가 같은지 확인한다
```

- 마이그레이션 파일은 `alembic/versions/` 에 두고, 병합 순서는 마이그레이션 담당(홍민지)이 정한다.
- DB 저장소 테스트는 SQLite(메모리)로 항상 돌고, `TEST_DATABASE_URL` 이 있으면 PostgreSQL 에서도 돈다.
  그 DB 의 public 스키마는 테스트마다 지우고 다시 만드므로 개발 DB 와 다른 DB 를 쓴다. CI 는 PostgreSQL 서비스로 돈다.

```bash
docker run -d --rm --name pinandfill-test-db -p 55432:5432 \
  -e POSTGRES_USER=pinandfill -e POSTGRES_PASSWORD=pinandfill -e POSTGRES_DB=pinandfill_test postgres:16-alpine
TEST_DATABASE_URL=postgresql://pinandfill:pinandfill@localhost:55432/pinandfill_test uv run pytest
```

## 규칙

- 테스트와 CI에서는 실제 외부 API(카카오, Gemini, 경로 API 등)를 호출하지 않는다. 외부 호출은 respx 등으로 목킹한다.
- 실제 호출 확인은 `scripts/sample_calls/`의 스크립트로 무료 한도 안에서 수동으로만 한다. 예: `uv run python ../scripts/sample_calls/kakao_keyword.py 태종대`
- 한 줄 조건 해석(API-001)의 실제 Gemini 호출 확인: `uv run python ../scripts/sample_calls/gemini_interpret.py "이번 주말에 자차로"`. `GEMINI_API_KEY`가 없으면 규칙 해석만 하고, 모델은 `GEMINI_MODEL`로 바꾼다.
- 카카오 로컬 API 응답은 저장하지 않으므로, 테스트 데이터는 실제 응답을 복사하지 않고 형식만 맞춰 직접 작성한다.
- 모듈 구성과 담당은 [`docs/TEAM.md`](../docs/TEAM.md)를 따른다.
