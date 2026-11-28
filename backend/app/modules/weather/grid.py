"""위경도 → 기상청 동네예보 격자(nx, ny). 기상청 단기예보 조회서비스 활용가이드의 람베르트 정각원추 변환식."""

import math

RE = 6371.00877  # 지구 반경(km)
GRID = 5.0  # 격자 간격(km)
SLAT1, SLAT2 = 30.0, 60.0  # 표준 위도
OLON, OLAT = 126.0, 38.0  # 기준점 경도·위도
XO, YO = 43, 136  # 기준점 격자


def to_grid(lat: float, lng: float) -> tuple[int, int]:
    degrad = math.pi / 180.0
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * degrad, SLAT2 * degrad, OLON * degrad, OLAT * degrad
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(
        math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    )
    sf = math.tan(math.pi * 0.25 + slat1 * 0.5) ** sn * math.cos(slat1) / sn
    ro = re * sf / math.tan(math.pi * 0.25 + olat * 0.5) ** sn
    ra = re * sf / math.tan(math.pi * 0.25 + lat * degrad * 0.5) ** sn
    theta = lng * degrad - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    return int(ra * math.sin(theta) + XO + 0.5), int(ro - ra * math.cos(theta) + YO + 0.5)
