"""한 줄 조건 해석(API-001)을 실제 Gemini 로 확인한다(수동 전용, 테스트·CI 에서 쓰지 않는다).

무료 한도 안에서만 쓴다. backend/.env 의 GEMINI_API_KEY 를 읽는다. 키가 없으면 규칙 해석 결과만 나온다.
문장에 날짜가 숫자로 적혀 있으면 규칙만으로 해석하므로, LLM 을 확인하려면 '이번 주말' 같은 표현을 쓴다.

사용: cd backend && uv run python ../scripts/sample_calls/gemini_interpret.py "이번 주말에 부모님이랑 렌터카로"
"""

import asyncio
import logging
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.modules.ai.interpret import build_interpret_service  # noqa: E402
from app.modules.ai.sanitizer import InvalidInputError  # noqa: E402


async def main(text: str) -> int:
    # 호출 성공·실패 사유(상태 코드)를 보이게 한다. 문장과 키는 로그에 남지 않는다.
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        result = await build_interpret_service().interpret(text)
    except InvalidInputError as error:
        print(f"입력 거절: {error.reason}")
        return 1
    filled = {key: str(value) for key, value in asdict(result.conditions).items() if value is not None}
    print(f"해석 경로: {result.source}, 폼 전환: {result.needs_form}")
    print(f"해석 결과: {filled}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit('사용: uv run python ../scripts/sample_calls/gemini_interpret.py "<문장>"')
    sys.exit(asyncio.run(main(sys.argv[1])))
