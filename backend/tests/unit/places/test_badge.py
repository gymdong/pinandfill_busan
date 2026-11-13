from datetime import time

import pytest

from app.modules.places import HoursStatus, PlaceBadge, PlaceHours, PublicPlace, hours_status, place_badge


def place(*hours: PlaceHours) -> PublicPlace:
    return PublicPlace(id="p1", name="예시해변공원", lat=35.15, lng=129.12, category="관광지", hours=hours)


def test_unmatched_place_is_basic_and_needs_check():
    assert place_badge(None) is PlaceBadge.BASIC
    assert hours_status(None) is HoursStatus.NEEDS_CHECK


def test_matched_place_is_detail():
    assert place_badge(place()) is PlaceBadge.DETAIL


@pytest.mark.parametrize(
    "hours",
    [
        (),
        (PlaceHours(day_type="MON"),),
        (PlaceHours(day_type="MON", open_time=time(9)),),
        (PlaceHours(day_type="MON", close_time=time(18)), PlaceHours(day_type="TUE")),
    ],
)
def test_matched_place_without_usable_hours_needs_check(hours):
    assert hours_status(place(*hours)) is HoursStatus.NEEDS_CHECK


@pytest.mark.parametrize(
    "hours",
    [
        (PlaceHours(day_type="MON", open_time=time(9), close_time=time(18)),),
        (PlaceHours(day_type="MON", is_closed=True),),
        (PlaceHours(day_type="MON"), PlaceHours(day_type="TUE", open_time=time(10), close_time=time(17))),
    ],
)
def test_matched_place_with_hours_or_closed_day_is_known(hours):
    assert hours_status(place(*hours)) is HoursStatus.KNOWN
