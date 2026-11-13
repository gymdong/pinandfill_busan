from .schemas import HoursStatus, PlaceBadge, PublicPlace


def place_badge(matched: PublicPlace | None) -> PlaceBadge:
    """공공 DB 와 매칭되면 '상세 정보 있음', 아니면 '기본 정보만'(FR-001)."""
    return PlaceBadge.DETAIL if matched is not None else PlaceBadge.BASIC


def hours_status(matched: PublicPlace | None) -> HoursStatus:
    """영업시간을 알 수 있는지. 카카오는 영업시간을 주지 않으므로 공공 DB 값만 본다(NFR-012).

    휴무로 표시됐거나 여는 시각과 닫는 시각이 모두 있는 행이 하나라도 있으면 KNOWN 이다.
    """
    if matched is None:
        return HoursStatus.NEEDS_CHECK
    known = any(row.is_closed or (row.open_time is not None and row.close_time is not None) for row in matched.hours)
    return HoursStatus.KNOWN if known else HoursStatus.NEEDS_CHECK
