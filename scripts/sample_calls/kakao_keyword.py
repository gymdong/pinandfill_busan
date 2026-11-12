"""카카오 키워드 검색을 실제로 호출해 확인한다(수동 전용, 테스트·CI 에서 쓰지 않는다).

무료 한도 안에서만 쓴다. 카카오 응답은 저장하지 않으므로 건수와 분류 코드별 개수만 출력한다.

사용: cd backend && uv run python ../scripts/sample_calls/kakao_keyword.py 태종대
"""

import asyncio
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import httpx  # noqa: E402

from app.adapters.kakao import KakaoLocalAdapter, KakaoLocalError, KakaoSettings  # noqa: E402


async def main(query: str) -> int:
    settings = KakaoSettings()
    async with httpx.AsyncClient() as client:
        try:
            places = await KakaoLocalAdapter(client, settings).search_keyword(query)
        except KakaoLocalError as error:
            print(f"실패: {error}")
            return 1
    groups = Counter(place.category_group_code or "-" for place in places)
    print(f"성공: {len(places)}건, 분류 코드별 {dict(groups)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("사용: uv run python ../scripts/sample_calls/kakao_keyword.py <검색어>")
    sys.exit(asyncio.run(main(sys.argv[1])))
