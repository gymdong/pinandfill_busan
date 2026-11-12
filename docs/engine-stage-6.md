# 6단계: 실제 일정 출발시각 전달

## 변경 범위

기존 API-006·009·011과 `RouteProvider.estimate`를 유지하고 선택적
`DepartureAwareRouteProvider.estimate_at(..., departure_at=...)` 경계를 추가했다.
실제 `LiveRouteProvider`는 이 경계를 구현한다. 기존 시각 독립 Fake는 이전 메서드로 동작한다.
호환 경로가 시간대별 예측 지원을 의미하지는 않는다.

`engine/routing.py`에서 `trip.start_date + dayNo - 1`과 이전 블록의 계산된 `depart_at`을
결합한다. 시간대는 부산 현지 `Asia/Seoul`이다. 현재 Windows 가상환경에 IANA tzdata가
없어, ZoneInfo가 제공되면 이를 쓰고 없으면 1989년 이후 날짜만 명시적인 UTC+09로 처리한다.
역사적 날짜는 UTC+09로 가정하지 않고 계산 불가로 처리한다. 운영 환경에는 IANA tzdata를
제공하는 것이 권장되며 이번 단계에서는 PR #4 설정·패키지 의존성을 변경하지 않았다.
근거: [IANA Asia 시간대 데이터](https://data.iana.org/time-zones/tzdb/asia).

출발시각이 없으면 경로 공급자를 호출하지 않는다. 조회 시각(`computedAt`)과 여행
출발시각(`departure_at`)은 별개이며 현재 시각으로 출발시각을 대체하지 않는다.
자정 초과는 기존대로 날짜 분리 검토 대상이다. 임의로 다음날로 넘기거나 00:xx로 자르지
않는다. 다음 날짜의 첫 블록이 명시되어 있다면 그 날짜의 별도 출발시각으로 계산한다.

## API-011의 시각

- 직접 경로: A의 출발시각으로 A→B 조회.
- 경유 경로: 같은 A 출발시각으로 A→C 조회.
- C 출발: C 도착시각 + 장소 데이터에서 제공한 체류시간.
- 후속 경로: C 출발시각으로 C→B 조회. 이후 블록도 같은 방식으로 이어 계산.
- 우회시간: `이동(A→C) + 이동(C→B) − 이동(A→B)`이며 체류시간은 더하지 않는다.
  다만 체류시간이 C→B의 출발시각과 후속 고정시간 제약에 영향을 준다.

추천 점수·가중치·최대 3개·임계값·기존 일정 비변경 정책은 그대로다. 시각별 예측이 아닌
공급자 값은 추천 이유에 그 한계를 표시한다. 정보성 경고를 제약 충돌로 오인해 전부
탈락시키지 않으며, 실제 시간·영업시간 충돌과 데이터 부족 후보는 기존대로 제외한다.

## 공급자별 시간 의미

| 경로 | 내부 time_semantics | 실제 의미 |
|---|---|---|
| TMAP 자동차 타임머신 | prediction | predictionTime에 실제 출발 datetime을 전송 |
| TMAP 대중교통 | service_availability | searchDttm은 운행 여부 조회. 시간표/교통량 기반 소요시간 예측으로 표현하지 않음 |
| TMAP 도보 | static | 출발시각 입력 미지원. 날짜 값을 허위로 보내지 않고 일반 도보 경로 조회임을 명시 |
| ODsay maasRP | search_context | SearchTime은 구간별 출발·도착 표시의 기준. 시간표 기반 경로 탐색이 아님 |

TMAP 대중교통에는 서울 현지 분 단위 `searchDttm`을 전달한다. ODsay에는 같은 실제
출발 datetime을 설정된 공급자 시간대로 변환해 `SearchTime`으로 보낸다. ODsay 시간대
설정과 상품 권한은 이전 단계처럼 운영 계약 확인 대상이다.

`LiveRouteProvider.estimate_at`은 비예측 조회를 허용하되 그 의미를 반환한다.
기존 직접 `lookup` 호출의 동작을 유지하기 위해 TMAP 비자차의 시각 컨텍스트 전송은
`allow_time_context=True`로 명시적으로 선택한다. `departure_applied=True`는 **파라미터를
전달했다는 뜻**이며 예측 지원 여부는 `time_semantics`로 구분한다. 기존 untimed
`estimate`/`lookup`은 호환용으로 남지만 일정 엔진은 출발시각이 있을 때만 `estimate_at`을 사용한다.

공식 근거(2026-11-10 확인):

- [TMAP 자동차 타임머신](https://tmap-skopenapi.readme.io/reference/타임머신-자동차-길-안내)
- [TMAP searchDttm 설명](https://transit.tmapmobility.com/docs/routes)
- [ODsay 관리자 답변: SearchTime은 시간표 기반 탐색이 아님](https://lab.odsay.com/community/boardView?seq=718)

## 실패와 외부 API 호환

내부 `RouteEstimate`·`StoredLeg`에 비민감 `time_semantics`, `lookup_failed`를 추가했다.
카카오 이름·좌표·키·원문 오류는 포함하지 않는다. 내부 메타데이터는 HTTP Leg 직렬화에서
제외하므로 기존 `durationMin/source/computedAt` 필드 구조는 바뀌지 않는다.

- 공급자 전체 실패: `durationMin=null` 유지. 기존 `TRAVEL_TIME_NEEDS_CHECK`에
  `ROUTE_LOOKUP_FAILED` 경고를 추가해 source가 확인된 경로 출처가 아님을 명시한다.
- 출발시각 없음: 조회하지 않고 `DEPARTURE_TIME_NEEDS_CHECK` 표시.
- 조회값이 시각별 예측이 아님: `ROUTE_TIME_CONTEXT_ONLY` 정보성 경고. 실제 데이터
  공급자 표시는 유지하며 이를 임의로 ESTIMATED 숫자로 바꾸지 않는다.
- 이 메타데이터는 저장 상태에서 재검증할 때도 유지된다. 운영 DB 칼럼이나 마이그레이션은
  추가하지 않았다. 내부 상태 직렬화를 직접 사용하는 팀원은 새 선택 필드를 확인해야 한다.

외부 `source` enum에는 UNKNOWN이 없으므로 null 시간에 붙는 마지막 조회 공급자명은
일단 유지한다. **프런트는 source만 보고 경로 성공으로 판정하면 안 되며 null·경고를 함께
봐야 한다.** 향후 제안은 `status: available|unavailable`, 실패 시 `source:null`,
`timeSemantics` 같은 명시 필드다. 이번 단계에서는 외부 필드·enum을 임의 변경하지 않았다.
새 경고 type의 UI 표시·위반율 집계 방식은 팀원과 합의해야 한다.

## 검증과 다음 단계

기존 테스트 파일은 변경하지 않고 `tests/integration/test_departure_routing.py`를 추가했다.
여행 날짜·시각 전달, 자정 경계·날짜 변경, 체류 후 출발, 고정 충돌, 모든 공급자 실패,
출발시각 미상, 공급자 시간 의미, 카카오 좌표·키 포함 예외의 비노출을 Mock으로 검증한다.

`backend`에서 실행:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check --select E,F,I,B,UP --line-length 120 --target-version py312 app tests
.venv/Scripts/ruff.exe format --check --line-length 120 --target-version py312 app tests
.venv/Scripts/mypy.exe app
```

검증 결과: Python 3.14에서 기존 197개와 신규 20개, 총 217개 테스트 통과.
위 PR #4 기준 Ruff 검사·포맷 검사와 mypy(42개 소스)도 통과했다.
TestClient 의존성의 httpx 사용 중단 예정 경고 1개가 있으며 의존성은 변경하지 않았다.
로컬 pyproject의 기본 줄 길이 100으로 실행하면 기존 코드의 E501 오류가 있으므로,
설정을 덮어쓰지 않고 위와 같이 PR #4의 120 기준을 명시해 검증했다.
Python 3.12·uv 잠금 환경의 별도 검증은 해당 실행 환경이 없어 수행하지 못했다.

실제 경로 서버 호출·키 설정·공공DB·최초 자동 배치·프런트 수정·GitHub 업로드는 하지 않았다.
운영 준비에는 공급자 권한·ODsay 시간대·저장 허용범위 확인, IANA tzdata 배포,
공유 쿼터·호출 예산, 여행 소유권·DB 트랜잭션, 내부 경로 메타데이터 저장 매핑이 남아 있다.
실제 키를 이용한 검증은 별도 승인된 단계에서 진행한다.
