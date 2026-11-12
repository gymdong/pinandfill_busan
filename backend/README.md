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

## 규칙

- 테스트와 CI에서는 실제 외부 API(카카오, Gemini, 경로 API 등)를 호출하지 않는다. 외부 호출은 respx 등으로 목킹한다.
- 실제 호출 확인은 `scripts/sample_calls/`의 스크립트로 무료 한도 안에서 수동으로만 한다. 예: `uv run python ../scripts/sample_calls/kakao_keyword.py 태종대`
- 카카오 로컬 API 응답은 저장하지 않으므로, 테스트 데이터는 실제 응답을 복사하지 않고 형식만 맞춰 직접 작성한다.
- 모듈 구성과 담당은 [`docs/TEAM.md`](../docs/TEAM.md)를 따른다.
