# 5단계: 경로 HTTP 어댑터와 Mock 검증

확인일: 2026-11-08. 실제 키·외부 경로 호출 없이 공식 문서와 합성 HTTP 응답으로 검증했다.
기존 엔진, API-006·009·011, 방문시간·삽입·체류시간 정책을 변경하지 않았다.

## 구현과 연결 범위

`backend/app/adapters/route/`에 다음 경계를 추가했다.

- `providers.py`: TMAP 자차·도보·대중교통 및 자차 타임머신, ODsay maasRP 도보·대중교통,
  `RouteQuery`, 비민감 `LookupResult`, `ProviderSettings`.
- `service.py`: `LiveRouteProvider`. 기존 `RouteProvider.estimate`에 그대로 주입 가능.
  별도 `lookup(..., departure_at=aware_datetime)`은 후속 엔진 연결을 위한 입력 경계다.
- `transport.py`: 표준 라이브러리 HTTPS 전송. 추가 패키지·설정 파일 변경 없음.
- `quota.py`: 동시 요청에도 안전한 프로세스 내 rolling-window 호출 한도와 cooldown.

정상 응답의 시간만 분 단위 정수로 반환한다. 초 단위는 분으로 나눈 뒤 올림하여 시간을
과소 계산하지 않는다. 유효한 경로가 여러 개면 반환된 경로 중 최소 소요시간을 선택한다.
TMAP에서 운행 종료로 표시된 대중교통 경로는 제외한다. 부분 응답의 구간시간을 합쳐
총 이동시간을 만들어내지 않는다. bool·음수·NaN·무한대 등 잘못된 값은 사용하지 않는다.

TMAP 실패 시 같은 이동수단을 지원하는 ODsay로 한 번 폴백한다. 자차는 확인된 ODsay
공급자가 없으므로 폴백하지 않는다. 임의의 거리/속도 추정은 구현하지 않았으며
`ESTIMATED` 숫자도 반환하지 않는다. 모든 공급자가 실패하면 `duration_min=None`이다.
`lookup`에는 실패 분류와 마지막 조회 공급자가 남는다. 기존 API source enum에는 UNKNOWN이
없어 `estimate`의 null 시간에 붙은 source는 **마지막 조회 공급자**다. null이면 실제 경로를
확보했다는 뜻이 아니다. UNKNOWN 응답 계약 추가 여부는 팀 합의 대상이다.

앱 기본 구성에는 실제 공급자를 자동 연결하지 않았다. HTTP 통합 테스트에서는 공급자
어댑터를 엔진에 주입하고 전송 계층만 Mock으로 바꿔 요청→엔진→어댑터→응답을 검증한다.
기존 엔진 호출에는 출발시각이 없으므로 현재/미지정 시각 조회다. 실제 날짜별 출발시각을
엔진에서 전달하는 변경은 이번 단계에서 하지 않았다.

## 공식 API 조사 결과

| 공급자·기능 | 확인한 요청과 응답 | 출발시각 처리 |
|---|---|---|
| TMAP 자차 | POST `/tmap/routes?version=1`, appKey 헤더, startX/Y·endX/Y; `features[].properties.totalTime` 초 | 일반 API gpsTime을 미래 출발시각으로 해석하지 않음 |
| TMAP 도보 | POST `/tmap/routes/pedestrian?version=1`, 좌표·필수 시작/종료 라벨; 동일 totalTime 초 | 출발시각 필드 확인 안 됨; 지정 시각 조회 거절 |
| TMAP 타임머신 자차 | POST `/tmap/routes/prediction?version=1`, `routesInfo`, predictionType=departure, predictionTime ISO8601 | 시간대 있는 datetime 전달, 반환 source는 TMAP |
| TMAP 대중교통 | POST `/transit/routes`, 좌표·count; `metaData.plan.itineraries[].totalTime` 초 | searchDttm은 운행 여부 기능으로 설명됨. 특정 출발시각의 소요시간을 보장한다고 가정하지 않고 지정 시각은 ODsay로 넘김 |
| ODsay maasRP | POST form `/v1/api/maasRP`, apiKey·SX/SY/EX/EY·SearchTime·SearchMethod; `result.paths[].totalTime` 분 | SearchTime yyyyMMddHHmm, SearchMethod 1 도보/2 대중교통. 요청 수단의 pathType만 사용 |

ODsay의 기존 `searchPubTransPathT`에는 출발시각 입력이 없다. 별도 도보 API
`searchWalkPathV2`도 존재한다. 이번 예비 어댑터는 **시간 입력과 분 단위가 명시된 maasRP만**
구현했다. 자차 지원은 공개 API 목록에서 확인하지 못했다.

ODsay 문서는 SearchTime의 시간대·미래 조회 범위·요금제별 maasRP 권한을 명시하지 않는다.
따라서 `search_timezone`은 필수 설정이며 운영자가 공급자와 확인해야 한다. 테스트의 UTC+9는
명시적으로 주입한 합성 조건으로, 공급자가 확인한 기본값이라는 뜻이 아니다. 명시적 시각에
초·마이크로초가 있으면 분 단위로 임의 절삭하지 않고 미지원으로 처리한다. 출발시각을
생략한 ODsay 조회는 주입된 clock의 현재 분을 사용한다.

공식 출처:

- [TMAP 자동차](https://tmap-skopenapi.readme.io/reference/자동차-경로안내)
- [TMAP 보행자](https://tmap-skopenapi.readme.io/reference/보행자-경로안내)
- [TMAP 타임머신](https://tmap-skopenapi.readme.io/reference/타임머신-자동차-길-안내)
- [TMAP 응답 샘플·시간 단위](https://tmap-skopenapi.readme.io/reference/경로안내-샘플예제)
- [TMAP 대중교통 요청·응답·오류](https://transit.tmapmobility.com/docs/routes)
- [ODsay Reference: maasRP·도보·legacy](https://lab.odsay.com/guide/releaseReference)

## 요금·한도·저장 제약

| 상품 | 공개 요금·한도 | 출처 |
|---|---|---|
| TMAP 경로안내 그룹 | Free 1,000건/일; Premium 11원/건(VAT 포함). Lite 월 2,200,000원, 경로안내 10,000건/일 | [SK 상품 요금](https://openapi.sk.com/products/calc?menuSeq=5&svcSeq=4) |
| TMAP 대중교통 | Free 10건/일; 경로 0.88원/건, 요약 0.55원/건 표기. 이번 구현은 경로 API | [대중교통 요금](https://transit.tmapmobility.com/) |
| ODsay | Basic 자격 대상 30건/일 무료; Standard 100,000건/일·Premium 초과량은 문의; Flex 25원/건(VAT 별도), 표상 100,000건/일 | [운영정책·약관](https://lab.odsay.com/doc/totalPolicy) |

상품별 적용 한도·권한은 실제 신청 화면/계약을 우선한다. 대중교통 무료 한도를 TMAP의
일반 경로 1,000건과 혼동하면 안 된다. ODsay는 정확한 초당 제한치를 공개하지 않는다.

[TMAP API 약관](https://tmapapi.tmapmobility.com/terms.html)은 저장 후 24시간 이상 사용을
제한한다. 대중교통 별도 상품에 대한 세부 저장 권한은 계약 확인이 필요하다.
[ODsay 약관 4.5.10](https://lab.odsay.com/doc/totalPolicy)은 사전 동의 없는 결과 데이터의
복제·저장·가공·배포·제삼자 전송을 제한한다. 이 때문에 이번 구현에는 공공 경로를 포함해
**결과 캐시가 없다**. 향후 실제 결과를 legs/스냅샷에 저장하려면 재사용 기한·삭제·재조회 및
허용 범위를 먼저 확인해야 한다. Mock 상태 저장 테스트가 실제 데이터 저장 허가를 의미하지 않는다.

## 오류·시간 제한·호출 예산

- `ProviderSettings.timeout_seconds` 기본 5초는 공급자 SLA가 아닌 앱의 socket timeout 정책이다.
  전체 작업 wall-clock deadline을 의미하지 않는다. 응답 최대 2MiB, HTTPS 호스트 제한,
  리다이렉트 미추적, 환경 프록시 미사용, 자동 재시도 없음.
- 타임아웃/네트워크/응답형식/인증/호출한도/지원불가/결과없음을 내부 코드로만 구분한다.
  HTTP 401·403은 인증, 429는 호출 제한이다. HTTP 200 내 오류 본문도 성공으로 처리하지 않는다.
- 429의 Retry-After를 따르며 없으면 로컬 60초 cooldown. 같은 공급자 재시도 없이 폴백한다.
- `CallBudget(limit=..., window_seconds=...)`는 필수 예산 설정이다. 실패한 시도도 보수적으로
  계산한다. 실제 공급자의 날짜 경계/환불 규칙을 복제한 것이 아니다. 현재 한 TMAP 인스턴스는
  자차·도보·대중교통에 하나의 예산을 공유하므로 가장 작은 사용 한도 이하로 잡거나 별도 조립한다.
- 여러 프로세스·서버가 같은 키를 쓰면 현재 메모리 예산만으로 총량을 제한할 수 없다.
  운영 전 키별 공유 쿼터와 API-011의 상위 후보 사전 필터를 추가해야 한다.

## 키 발급 및 명시적 설정

1. TMAP: [SK 이용 가이드](https://transit.tmapmobility.com/guide)에 따라 가입→앱 생성→사용할
   TMAP/대중교통 상품 신청→앱의 appKey 확인. 사용할 상품이 해당 앱에 활성화되어야 한다.
2. ODsay: [공식 가이드](https://lab.odsay.com/guide/guide)에 따라 앱 생성→서버 플랫폼/IP 등록→
   서버용 API Key 발급. maasRP 권한·시간대·결과 사용 범위를 확인한다.
3. 키를 저장소·프런트 코드에 쓰지 말고 실행 환경의 비밀값으로 주입한다. 아래 환경변수 이름은
   조립 예이며 앱이 자동으로 읽거나 외부 호출을 활성화하지 않는다.

```python
import os
from pydantic import SecretStr
from app.adapters.route.providers import ProviderSettings, TMAPAdapter, ODsayAdapter
from app.adapters.route.quota import CallBudget
from app.adapters.route.service import LiveRouteProvider
from app.adapters.route.transport import SafeHTTPTransport

transport = SafeHTTPTransport()
tmap = TMAPAdapter(
    transport, ProviderSettings(SecretStr(os.environ["TMAP_APP_KEY"])),
    CallBudget(limit=10),  # 합성 예시: 실제 활성 상품/전체 앱 예산에 맞춰 지정
)
# confirmed_timezone은 공급자와 확인한 tzinfo 설정이다. 암묵적 기본값 없음.
odsay = ODsayAdapter(
    transport, ProviderSettings(SecretStr(os.environ["ODSAY_SERVER_KEY"])),
    CallBudget(limit=30), search_timezone=confirmed_timezone,
)
routes = LiveRouteProvider(tmap, odsay)
# BasicItineraryEngine(public_places, routes) / WaypointRecommender(..., routes, ...)에 주입
# 실제 운영 배선은 인증·공공DB·저장 정책 검증 후 진행한다.
```

## 카카오 비저장 경계

전송 계층은 요청별 연결만 사용하고 요청 본문·원문 응답을 속성/캐시에 보관하지 않는다.
표준 http.client의 디버그 출력을 끄며 별도 로깅을 하지 않는다. 키와 좌표는 URL query에 넣지
않고 헤더/POST body로만 전송한다. TMAP의 정적인 `version=1` query만 예외 허용한다.
필수 장소 라벨은 `origin`/`destination`이며 카카오 검색 이름을 보내지 않는다.
요청 모델은 좌표를 repr/dump에서 제외하고, 응답 컨테이너 repr도 body를 제외한다.
공급자 예외·오류 원문은 결과로 넘기지 않는다. 모든 구간이 캐시를 우회하므로 카카오 구간도
공유 캐시에 접근하지 않는다. 외부 APM의 locals/body 수집까지 통제하는 구현은 아니므로
배포 때 별도로 차단·검증해야 한다.

## 검증 및 다음 단계

`backend`에서 기존과 동일한 pytest, Ruff(py312/E,F,I,B,UP/120), mypy 명령을 실행한다.
Mock 검증은 키 발급·유료 호출·실제 공급자의 응답 가용성을 검증하지 않는다.
Python 3.12와 uv는 현재 설치되어 있지 않으며 기존 3.14 환경·PR #4 설정을 변경하지 않았다.

다음 순서: 공급자 권한·시간대·저장 사용범위 확인 → 엔진의 날짜별 실제 departure 전달 합의 →
공유 쿼터·후보별 호출 예산 → 허용된 환경에서 소량 실제 키 smoke 검증 → 공공DB/인증 연결.
최초 배치·기본 체류시간·프런트 변경은 이번 단계에 포함하지 않는다.
