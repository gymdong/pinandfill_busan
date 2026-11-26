"""부산 16개 구·군과 공공데이터 API 지역 코드 대응표(FR-008, DATA-06·07).

crowd_multipliers.csv 의 `region` 은 구·군 이름(장소 주소의 구·군 낱말)이다. API 응답은 시군구 코드만 주므로
어댑터가 이 표로 이름으로 바꾼다. 표에 없는 코드(부산 밖 포함)의 행은 쓰지 않는다.

코드는 코드에 적지 않고 설정 파일(`CROWD_REGION_CODES_PATH`, 기본 data/seed/crowd/busan_region_codes.csv)에서 읽는다.
출처는 행정표준코드관리시스템(code.go.kr)의 시군구 코드와 각 API 활용가이드의 코드 첨부 파일이다.
실제 키로 응답을 확인하기 전에는 값을 채우지 않는다(지어낸 코드로 운영 값을 만들지 않는다).
표가 비면 잡은 호출 없이 실패한다.

파일 열(UTF-8, `#` 줄은 주석):
- `region`: 구·군 이름. 아래 BUSAN_DISTRICTS 중 하나.
- `data06_signgu_code`: DATA-06(빅데이터_지역별 방문자수) 응답의 시군구 코드.
- `data07_area_code`·`data07_signgu_code`: DATA-07(관광지 집중률) 요청 `areaCd`·`signguCd`.
  둘 중 하나라도 비면 DATA-07 은 그 구·군을 부르지 않는다.
"""

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# 부산광역시 15구 1군(행정구역 이름). 코드가 아니라 이름이라 여기 둔다.
BUSAN_DISTRICTS = (
    "중구",
    "서구",
    "동구",
    "영도구",
    "부산진구",
    "동래구",
    "남구",
    "북구",
    "해운대구",
    "사하구",
    "금정구",
    "강서구",
    "연제구",
    "수영구",
    "사상구",
    "기장군",
)
COLUMNS = ("region", "data06_signgu_code", "data07_area_code", "data07_signgu_code")


class RegionCodeError(ValueError):
    """대응표가 없거나 형식이 틀렸다. 값은 메시지에 싣지 않는다(파일 이름·행 번호만)."""


@dataclass(frozen=True)
class RegionCodes:
    # DATA-06 시군구 코드 → 구·군 이름
    data06: dict[str, str]
    # 구·군 이름 → (DATA-07 areaCd, signguCd)
    data07: dict[str, tuple[str, str]]


def load_region_codes(path: Path) -> RegionCodes:
    if not path.is_file():
        raise RegionCodeError(f"지역 코드 대응표가 없습니다: {path.name}")
    data06: dict[str, str] = {}
    data07: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    try:
        with path.open(encoding="utf-8-sig", newline="") as file:
            lines: Iterator[str] = (line for line in file if not line.lstrip().startswith("#"))
            reader = csv.DictReader(lines)
            if reader.fieldnames is None or not set(COLUMNS) <= set(reader.fieldnames):
                raise RegionCodeError(f"지역 코드 대응표 머리줄이 틀렸습니다: {path.name}")
            for number, row in enumerate(reader, start=1):
                region, code06, area07, code07 = ((row.get(name) or "").strip() for name in COLUMNS)
                if region not in BUSAN_DISTRICTS or region in seen:
                    raise RegionCodeError(f"지역 코드 대응표 {number}번째 행의 구·군 이름이 틀렸거나 중복입니다.")
                seen.add(region)
                if code06:
                    if code06 in data06:
                        raise RegionCodeError(f"지역 코드 대응표 {number}번째 행의 DATA-06 코드가 중복입니다.")
                    data06[code06] = region
                if area07 and code07:
                    data07[region] = (area07, code07)
    except (UnicodeDecodeError, csv.Error):
        raise RegionCodeError(f"지역 코드 대응표를 읽을 수 없습니다: {path.name}") from None
    return RegionCodes(data06, data07)
