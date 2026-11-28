"""기상청 단기예보·중기예보 조회(공공데이터포털). 키는 쿼리(serviceKey)로만 보내고 로그·오류에 남기지 않는다.

- 단기예보 getVilageFcst: 격자(nx, ny)별 시간 단위, 발표 02·05·08·11·14·17·20·23시(10분 뒤부터 조회), 약 3일 앞까지.
- 중기예보 getMidLandFcst(육상, 부산·울산·경남 11H20000)·getMidTa(기온, 부산 11H20201):
  발표 06·18시, 4(또는 5)~10일 뒤 일 단위.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.core.logging import quiet_http_client_logs

KST = ZoneInfo("Asia/Seoul")
SHORT_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
MID_LAND_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidLandFcst"
MID_TA_URL = "https://apis.data.go.kr/1360000/MidFcstInfoService/getMidTa"
MID_LAND_REGION = "11H20000"  # 부산·울산·경남
MID_TA_REGION = "11H20201"  # 부산
SHORT_BASE_HOURS = (2, 5, 8, 11, 14, 17, 20, 23)

PTY = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}
SKY = {"1": "맑음", "3": "구름많음", "4": "흐림"}


class KmaError(Exception):
    """조회 실패. 종류만 담는다(키가 든 URL·응답 본문은 담지 않는다)."""


@dataclass(frozen=True, slots=True)
class ShortSlot:
    pop: int | None
    pty: str | None
    sky: str | None
    temp: float | None
    wind: float | None


@dataclass(frozen=True, slots=True)
class ShortForecast:
    issued_at: datetime
    slots: dict[tuple[date, int], ShortSlot]


@dataclass(frozen=True, slots=True)
class MidDay:
    pop_am: int | None
    pop_pm: int | None
    sky_am: str | None
    sky_pm: str | None
    temp_min: float | None
    temp_max: float | None


@dataclass(frozen=True, slots=True)
class MidForecast:
    issued_at: datetime
    days: dict[date, MidDay]


def short_base(now: datetime) -> datetime:
    """`now`(KST) 에 조회할 수 있는 가장 최근 단기예보 발표 시각."""
    local = now.astimezone(KST) - timedelta(minutes=10)
    for hour in reversed(SHORT_BASE_HOURS):
        if local.hour >= hour:
            return datetime.combine(local.date(), time(hour), tzinfo=KST)
    return datetime.combine(local.date() - timedelta(days=1), time(23), tzinfo=KST)


def mid_base(now: datetime) -> datetime:
    """`now`(KST) 에 조회할 수 있는 가장 최근 중기예보 발표 시각(06·18시, 10분 뒤부터)."""
    local = now.astimezone(KST) - timedelta(minutes=10)
    for hour in (18, 6):
        if local.hour >= hour:
            return datetime.combine(local.date(), time(hour), tzinfo=KST)
    return datetime.combine(local.date() - timedelta(days=1), time(18), tzinfo=KST)


def _number(value: object) -> float | None:
    try:
        return float(str(value))
    except ValueError:
        return None


class KmaClient:
    def __init__(self, key: str, *, timeout: float = 10.0, transport: httpx.BaseTransport | None = None) -> None:
        quiet_http_client_logs()
        self._key = key
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _items(self, url: str, params: dict[str, str | int]) -> list[dict[str, object]]:
        try:
            response = self._client.get(
                url, params={"serviceKey": self._key, "pageNo": 1, "dataType": "JSON", **params}
            )
            response.raise_for_status()
            body = response.json()["response"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            raise KmaError("request_failed") from None
        code = str(body.get("header", {}).get("resultCode", ""))
        if code == "03":  # NO_DATA
            return []
        if code != "00":
            raise KmaError(f"result_{code or 'unknown'}")
        items = body.get("body", {}).get("items", {})
        rows = items.get("item", []) if isinstance(items, dict) else []
        return [row for row in rows if isinstance(row, dict)]

    def short(self, nx: int, ny: int, base: datetime) -> ShortForecast:
        rows = self._items(
            SHORT_URL,
            {
                "numOfRows": 1500,
                "base_date": base.strftime("%Y%m%d"),
                "base_time": base.strftime("%H%M"),
                "nx": nx,
                "ny": ny,
            },
        )
        raw: dict[tuple[date, int], dict[str, str]] = {}
        for row in rows:
            try:
                day = datetime.strptime(str(row["fcstDate"]), "%Y%m%d").date()
                hour = int(str(row["fcstTime"])[:2])
            except (KeyError, ValueError):
                continue
            raw.setdefault((day, hour), {})[str(row.get("category"))] = str(row.get("fcstValue"))
        slots = {
            key: ShortSlot(
                pop=int(v["POP"]) if v.get("POP", "").isdigit() else None,
                pty=PTY.get(v.get("PTY", "")),
                sky=SKY.get(v.get("SKY", "")),
                temp=_number(v["TMP"]) if "TMP" in v else None,
                wind=_number(v["WSD"]) if "WSD" in v else None,
            )
            for key, v in raw.items()
        }
        return ShortForecast(issued_at=base, slots=slots)

    def mid(self, base: datetime) -> MidForecast:
        tm = base.strftime("%Y%m%d%H%M")
        land = self._items(MID_LAND_URL, {"numOfRows": 10, "regId": MID_LAND_REGION, "tmFc": tm})
        temps = self._items(MID_TA_URL, {"numOfRows": 10, "regId": MID_TA_REGION, "tmFc": tm})
        land_row = land[0] if land else {}
        ta_row = temps[0] if temps else {}
        days: dict[date, MidDay] = {}
        for n in range(4, 11):
            am, pm = (f"{n}Am", f"{n}Pm") if n <= 7 else (str(n), str(n))
            if f"wf{am}" not in land_row and f"taMax{n}" not in ta_row:
                continue
            pop_am, pop_pm = _number(land_row.get(f"rnSt{am}", "")), _number(land_row.get(f"rnSt{pm}", ""))
            days[base.date() + timedelta(days=n)] = MidDay(
                pop_am=int(pop_am) if pop_am is not None else None,
                pop_pm=int(pop_pm) if pop_pm is not None else None,
                sky_am=str(land_row[f"wf{am}"]) if f"wf{am}" in land_row else None,
                sky_pm=str(land_row[f"wf{pm}"]) if f"wf{pm}" in land_row else None,
                temp_min=_number(ta_row.get(f"taMin{n}", "")),
                temp_max=_number(ta_row.get(f"taMax{n}", "")),
            )
        return MidForecast(issued_at=base, days=days)
