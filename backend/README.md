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

공공 장소·수집 기록 테이블(places·place_hours·data_sources·ingestion_runs, FR-016)도 같은 마이그레이션으로 만든다.
data_sources 의 tourapi·data06·data07 행은 마이그레이션이 넣는다. 표본 CSV(`data/samples/`)는 시드 명령으로 넣는다.
앱이 장소를 어디서 읽을지는 `PLACE_DATA_SOURCE` 로 정한다.

- `csv`(기본, 비어 있거나 없을 때): `data/samples/` CSV. 테스트와 로컬 기본이다.
- `db`: places·place_hours 를 읽는다. `DATABASE_URL` 이 필요하고 trips 와 같은 DB 연결(풀)을 쓴다.
  검색·장소 상세(API-005)·일정 엔진·체류시간·분위기 추천·예상 혼잡의 구·군 조회가 모두 같은 데이터를 본다.
- 장소는 앱 시작 때 한 번만 읽는다. 시드·배치로 DB 를 바꾸면 앱을 다시 시작해야 반영된다.
- `db` 인데 `DATABASE_URL` 이 없거나 places 가 비어 있으면(시드 전) 빈 데이터로 돌지 않고 앱 시작이 실패한다.
- 카카오 매칭표(`kakao_id_mapping.csv`)와 장소 사진(`place_photos.csv`)은 `db` 에서도 CSV 를 읽는다.
- 혼잡 검증 도구(`python -m app.modules.crowd.validation`)는 앱이 아니라 따로 도는 명령이라 `db` 에서도
  표본 CSV 의 장소를 읽는다.
- 앱이 끝나면(lifespan 종료) 함께 쓰던 DB 연결 풀을 닫고, 시작이 실패해도 닫은 뒤 예외를 낸다.

```bash
uv run alembic upgrade head
uv run python -m app.batch.cli seed-places              # data/samples 의 places_sample.csv·place_hours.csv
uv run python -m app.batch.cli seed-places --dir <디렉터리>  # 다른 표본 디렉터리
uv run python -m app.batch.cli seed-places --prune      # CSV 에 없는 영업시간 행도 지운다
```

- 시드는 다시 돌려도 결과가 같고, 값이 그대로인 장소는 updated_at 도 그대로다. 표본에 없는 장소 행은 지우지 않는다.
- CSV 에 없는 영업시간 행(DB 에 직접 넣은 MANUAL 행 등)은 `--prune` 일 때만 지운다. CSV 에서 읽지 못한 행
  (예: 초가 붙은 시각, 알 수 없는 origin)의 요일은 `--prune` 이어도 DB 행을 그대로 두고 경고 로그에 건수를 남긴다.
- 주의: `--prune` 은 CSV 에 없는 DB 영업시간 행을 origin 과 상관없이 지운다(DB 에서 직접 넣은 MANUAL 행·HOLIDAY 행 포함).
- 배치가 갱신한 이름·좌표·주소(collected_at 이 있는 행)는 시드가 덮어쓰지 않는다. ref_date(수동 확인 기준일)·
  영업시간·출처 기관은 시드(CSV)만 바꾼다.
- 마이그레이션 파일은 `alembic/versions/` 에 두고, 병합 순서는 마이그레이션 담당(홍민지)이 정한다.
- DB 저장소 테스트는 SQLite(메모리)로 항상 돌고, `TEST_DATABASE_URL` 이 있으면 PostgreSQL 에서도 돈다.
  그 DB 의 public 스키마는 테스트마다 지우고 다시 만드므로 개발 DB 와 다른 DB 를 쓴다. 실제로 연결된 DB 이름이
  `_test` 로 끝나지 않으면(`?dbname=` 쿼리로 바뀐 경우 포함) 지우기 전에 멈춘다. CI 는 PostgreSQL 서비스로 돈다.

```bash
docker run -d --rm --name pinandfill-test-db -p 55432:5432 \
  -e POSTGRES_USER=pinandfill -e POSTGRES_PASSWORD=pinandfill -e POSTGRES_DB=pinandfill_test postgres:16-alpine
TEST_DATABASE_URL=postgresql://pinandfill:pinandfill@localhost:55432/pinandfill_test uv run pytest
```

### 배치 수집(FR-016)

```bash
uv run python -m app.batch.cli run --source tourapi   # 지금 수집(주기·백오프 무시, 한도·잠금은 지킨다)
uv run python -m app.batch.cli run-due                # 주기가 돌아온 소스만 한 번
uv run python -m app.batch.cli loop --tick 300        # 300초마다 run-due (SIGTERM 이면 지금 tick 을 마치고 끝)
docker compose up -d batch                            # 저장소 루트에서. loop 를 도는 로컬 개발용 서비스
```

- 주기는 `data_sources.refresh_cycle`(MONTH·DAY·MINUTE)이고 KST 달력 기준이다. MONTH 는 마지막 성공과 달이 다를 때,
  DAY 는 날짜가 다를 때, MINUTE 는 60초가 지났을 때 돈다. 꺼진(`enabled=false`) 소스는 돌지 않는다.
- 실행마다 `ingestion_runs` 에 RUNNING → SUCCESS/FAILED/SKIPPED, record_count·rejected_count·call_count·as_of·
  error_message(키·URL 없음)를 남긴다.
- 전송 오류(키 없음·HTTP·네트워크·응답 틀)가 1건이라도 나면 FAILED 이고 places 에 아무것도 쓰지 않는다(이전 수집본 유지).
  검증 거절(항목 없음·ID 불일치 등)은 그 장소만 건너뛰고 rejected_count 로 센다. 수집은 이름·좌표·주소·collected_at 만 바꾼다.
- 호출 한도: 오늘(KST 0시부터) call_count 합 + 이번 예정 호출 수가 `daily_call_limit` 를 넘으면 호출 없이 SKIPPED.
- 백오프: 마지막 성공과 이번 주기 시작(KST) 중 늦은 쪽 뒤로 FAILED·한도 SKIPPED 가 n 회면
  마지막 실패 + min(`BATCH_BACKOFF_BASE_MIN`(15)분 × 2^(n-1), 주기, 24시간) 전에는 `run-due` 가 건너뛴다.
  꺼진 소스를 직접 돌린 SKIPPED 는 세지 않는다.
- 같은 소스를 동시에 돌리지 않는다. PostgreSQL 은 advisory lock 을 못 잡으면 기록 없이 끝낸다.
  잠금을 잡았는데 RUNNING 행이 남아 있으면(이전 프로세스가 죽음) FAILED('abandoned') 로 닫고 알림 규칙을 탄다.
- SIGTERM·SIGINT 를 받으면 지금 호출을 마친 뒤 그 실행을 쓰기 없이 FAILED('interrupted') 로 끝낸다
  (compose `stop_grace_period: 60s`). 한 소스의 예외는 FAILED 로 남기고 같은 tick 의 다른 소스는 계속 돈다.
- 알림: FAILED·한도 SKIPPED 이면 `ingestion_alert source=… run_id=… status=… reason=…` 오류 로그,
  `ADMIN_ALERT_WEBHOOK_URL` 이 있으면 JSON POST(5초). 실패가 시작될 때 1회, 계속되면 24시간마다 1회, 복구되면
  `ingestion_recovered` 1회(`ingestion_runs.alerted_at` 으로 판정).
- 수집 대상은 DB places 의 PUBLIC 장소 중 contentid(숫자)인 것이다. 수집이 장소를 새로 만들지 않으므로, 장소를 늘리려면
  `data/samples/places_sample.csv` 에 실제 TourAPI contentid 로 행을 넣고 `seed-places` 를 다시 돌린다.

### 날짜 배수 M 수집(FR-008, DATA-06·07)

`data06`(지역별 방문자수, 과거)·`data07`(관광지 집중률 예측, 향후 30일) 잡이 `CROWD_DATA_DIR`(기본 `data/crowd`)의
`crowd_multipliers.csv` 를 만든다. 계산 규칙·파일 형식은 [`data/crowd/README.md`](../data/crowd/README.md).
기록·한도·알림·백오프·중단은 위 수집기 규칙 그대로다. 둘 다 `DAY` 주기이고 **기본으로 꺼져 있다**.

```bash
uv run python -m app.batch.cli run --source data06   # 최근 DATA06_BASELINE_DAYS(28)일, 하루 1호출
uv run python -m app.batch.cli run --source data07   # 대응표에 DATA-07 코드가 있는 구·군마다 1호출
```

- 키: `DATA06_SERVICE_KEY`·`DATA07_SERVICE_KEY`(공공데이터포털 Decoding 키, 환경변수 또는 backend/.env). 비어 있으면
  호출 없이 FAILED + 알림. 키·요청 URL 은 로그·error_message 에 남기지 않는다.
- 지역 코드: 응답의 시군구 코드를 `data/seed/crowd/busan_region_codes.csv`(`CROWD_REGION_CODES_PATH`)로 구·군 이름으로
  바꾼다. **지금은 코드 칸이 비어 있다(TODO)**. 실제 응답·활용가이드 코드 첨부로 확인한 값만 채운다. 비어 있으면 호출 없이 FAILED.
- 엔드포인트 경로·응답 필드 이름은 키가 없어 확인하지 못했다. `app/adapters/public_data/visitors.py` 의
  `DATA06_OPERATION`·`DATA07_OPERATION`·`DATA06_FIELDS`·`DATA07_FIELDS` 에 모아 두었다(명세 확인 필요).
- 쓰기: 수집이 모두 성공한 뒤에만 임시 파일 → rename 으로 바꾼다. 실패·중단이면 기존 파일이 그대로다.
  같은 (날짜, 구·군) 행만 새 값으로 바꾸고 다른 행(다른 소스·지난 날짜)은 남긴다. DATA-07 은 오늘 이후의 자기 행을 통째로 바꾸고,
  두 소스 모두 `CROWD_MULTIPLIER_RETENTION_DAYS`(365)일보다 오래된 자기 행을 지운다. 앱은 시작 때 읽으므로 반영하려면 앱을 다시 시작한다.
- 쓰기 동안 `.crowd_multipliers.csv.lock` 에 `fcntl.flock` 을 잡는다(POSIX 전용, Windows 에서는 배치를 돌리지 않는다).
- 파일 교체는 DB 커밋보다 먼저다. 커밋이 실패하면 파일이 ingestion_runs 기록보다 새것일 수 있다(허용).
- 응답 totalCount 가 `PUBLIC_DATA_PAGE_SIZE`(1000)보다 크면 잘린 자료로 계산하지 않고 FAILED 다(값을 늘린다).
  응답 header 에 resultCode 가 없으면 봉투 오류로 FAILED 다.
- 항목이 왔는데 쓸 수 있는 행이 0 이면 `DATA-06 no usable rows (rejected=N, unmapped=M)` 로 FAILED + 알림이다
  (필드 이름·코드 자릿수가 명세와 다를 때 빈 성공으로 넘기지 않는다). DATA-06 은 쓸 자료가 하나도 없어도 FAILED 이고,
  `as_of` 는 실제로 쓴 가장 늦은 자료일이다. 거절 항목이 있는 (날짜, 구·군)은 계산에서 뺀다.
- 공휴일은 평일로 센다(파일 제공자와 같다, spec A-9).

켜는 법(키·코드를 갖춘 뒤):

1. backend/.env 에 두 키를 넣고, `busan_region_codes.csv` 의 코드 칸을 확인한 값으로 채운다(출처·확인일을 주석에 적는다).
2. 켠다(꺼진 소스는 `run` 으로도 SKIPPED 다). 필요하면 한도도 둔다:

```sql
UPDATE data_sources SET enabled = true, daily_call_limit = 100 WHERE id IN ('data06', 'data07');
```

3. `run --source data06`·`run --source data07` 을 한 번씩 돌려 `ingestion_runs` 가 SUCCESS 이고 파일 행이 맞는지 본다.
   엔드포인트·필드가 다르면 위 상수와 시험 픽스처를 고친다. 그 뒤로는 `loop`(compose `batch`)가 하루 1회 돈다.

## 규칙

- 테스트와 CI에서는 실제 외부 API(카카오, Gemini, 경로 API 등)를 호출하지 않는다. 외부 호출은 respx 등으로 목킹한다.
- 실제 호출 확인은 `scripts/sample_calls/`의 스크립트로 무료 한도 안에서 수동으로만 한다. 예: `uv run python ../scripts/sample_calls/kakao_keyword.py 태종대`
- 한 줄 조건 해석(API-001)의 실제 Gemini 호출 확인: `uv run python ../scripts/sample_calls/gemini_interpret.py "이번 주말에 자차로"`. `GEMINI_API_KEY`가 없으면 규칙 해석만 하고, 모델은 `GEMINI_MODEL`로 바꾼다. 호출 한 번의 시간 제한은 `GEMINI_TIMEOUT_SECONDS`(기본 12초)다. 재시도는 대기 없이 최대 2회라 최악은 12초 × 2 = 24초로, 화면의 요청 제한(30초) 안이다.
- 카카오 로컬 API 응답은 저장하지 않으므로, 테스트 데이터는 실제 응답을 복사하지 않고 형식만 맞춰 직접 작성한다.
- 모듈 구성과 담당은 [`docs/TEAM.md`](../docs/TEAM.md)를 따른다.
