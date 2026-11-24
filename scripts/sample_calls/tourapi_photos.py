"""표본 장소의 사진과 저작권 유형을 한국관광공사 TourAPI 이미지 정보 조회로 확인한다(FR-014, 수동 전용).

SRS FR-014 비고 "저작권 유형 필드는 샘플 호출로 확인" 을 위한 스크립트다. 테스트·CI 에서 쓰지 않는다.
backend/.env(또는 환경변수)의 TOURAPI_SERVICE_KEY 를 읽는다. 키는 화면·파일에 남기지 않는다.
공공데이터포털(data.go.kr)에서 '한국관광공사_국문 관광정보 서비스_GW' 활용 신청 후 받은 일반 인증키(Decoding)를 넣는다.

- 기본: data/samples/places_sample.csv 의 장소마다 이미지 정보 조회를 한 번씩 불러,
  응답에 어떤 필드가 오는지와 저작권 유형 값(cpyrhtDivCd)의 분포를 보여 준다. 파일은 쓰지 않는다.
- --write: 확인한 값으로 data/samples/place_photos.csv 를 다시 쓴다.
  저작권 유형을 모르는 사진(아래 표에 없는 값)은 license_type 을 비워 두고, 앱은 그 사진을 보여 주지 않는다(ERR-013).

사용: cd backend && uv run python ../scripts/sample_calls/tourapi_photos.py [--write]
"""

import csv
import os
import sys
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
PLACES = ROOT / "data" / "samples" / "places_sample.csv"
OUTPUT = ROOT / "data" / "samples" / "place_photos.csv"
ENDPOINT = "https://apis.data.go.kr/B551011/KorService2/detailImage2"
SOURCE_ORG = "한국관광공사"
# TourAPI 매뉴얼의 저작권 유형 코드. 샘플 호출로 실제 값을 확인한 뒤 고친다.
LICENSES = {
    "Type1": "공공누리 제1유형(출처표시)",
    "Type3": "공공누리 제3유형(출처표시+변경금지)",
}
MAX_PER_PLACE = 5


def service_key() -> str | None:
    key = os.environ.get("TOURAPI_SERVICE_KEY")
    env = ROOT / "backend" / ".env"
    if not key and env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "TOURAPI_SERVICE_KEY":
                key = value.strip().strip("\"'")
    return key or None


def sample_places() -> list[tuple[str, str]]:
    with PLACES.open(encoding="utf-8-sig", newline="") as file:
        return [
            (row["tourapi_contentid"].strip(), row["name"].strip())
            for row in csv.DictReader(file)
            if row.get("tourapi_contentid", "").strip()
        ]


def fetch(client: httpx.Client, key: str, content_id: str) -> list[dict[str, object]]:
    params = {
        "serviceKey": key,
        "MobileOS": "ETC",
        "MobileApp": "pinandfill",
        "_type": "json",
        "contentId": content_id,
        "imageYN": "Y",
        "numOfRows": str(MAX_PER_PLACE),
        "pageNo": "1",
    }
    response = client.get(ENDPOINT, params=params)
    # 오류 응답 본문에 요청 URL(키 포함)이 섞일 수 있어 상태 코드만 보여 준다.
    response.raise_for_status()
    body = response.json()
    items = (body.get("response", {}).get("body", {}).get("items") or {}) if isinstance(body, dict) else {}
    item = items.get("item", []) if isinstance(items, dict) else []
    return [entry for entry in (item if isinstance(item, list) else [item]) if isinstance(entry, dict)]


def main(write: bool) -> int:
    key = service_key()
    if key is None:
        print("TOURAPI_SERVICE_KEY 가 없습니다. backend/.env 에 직접 넣어 주세요(값을 채팅에 붙여 넣지 마세요).")
        return 1

    rows: list[dict[str, str]] = []
    fields: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    with httpx.Client(timeout=10.0) as client:
        for content_id, name in sample_places():
            try:
                items = fetch(client, key, content_id)
            except httpx.HTTPStatusError as error:
                print(f"{name}({content_id}): 실패 status={error.response.status_code}")
                continue
            except (httpx.HTTPError, ValueError) as error:
                print(f"{name}({content_id}): 실패 {type(error).__name__}")
                continue
            print(f"{name}({content_id}): 사진 {len(items)}장")
            for index, item in enumerate(items):
                fields.update(item.keys())
                code = str(item.get("cpyrhtDivCd") or "")
                codes[code or "(없음)"] += 1
                url = str(item.get("originimgurl") or "")
                if not url:
                    continue
                rows.append(
                    {
                        "tourapi_contentid": content_id,
                        "url": url,
                        "source_org": SOURCE_ORG,
                        "license_type": LICENSES.get(code, ""),
                        # 응답의 첫 사진을 대표 사진으로 둔다.
                        "is_primary": "TRUE" if index == 0 else "FALSE",
                    }
                )

    print(f"\n응답 필드: {sorted(fields)}")
    print(f"저작권 유형(cpyrhtDivCd): {dict(codes)}")
    unknown = sorted(code for code in codes if code not in LICENSES)
    if unknown:
        print(f"표에 없는 값(그 사진은 앱에서 보이지 않음): {unknown}")
    if write:
        with OUTPUT.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file, fieldnames=["tourapi_contentid", "url", "source_org", "license_type", "is_primary"]
            )
            writer.writeheader()
            writer.writerows(rows)
        print(f"{OUTPUT.relative_to(ROOT)} 에 {len(rows)}장을 썼습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv[1:]))
