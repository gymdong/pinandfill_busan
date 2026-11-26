"""FR-016 관광지 공공데이터 검증 테스트."""

from app.batch.jobs.public_places import (
    parse_public_place,
    parse_public_places,
)


def sample_item():
    return {
        "contentid": "1997221",
        "title": "감천문화마을",
        "addr1": "부산광역시 사하구 감내2로",
        "mapy": "35.0974607",
        "mapx": "129.010597",
    }


def test_valid_public_place():
    record = parse_public_place(sample_item())

    assert record is not None
    assert record.content_id == "1997221"
    assert record.name == "감천문화마을"
    assert record.latitude == 35.0974607
    assert record.longitude == 129.010597


def test_missing_title():
    item = sample_item()
    item["title"] = ""

    assert parse_public_place(item) is None


def test_invalid_coordinates():
    item = sample_item()
    item["mapy"] = "999"

    assert parse_public_place(item) is None


def test_invalid_content_id():
    item = sample_item()
    item["contentid"] = "invalid"

    assert parse_public_place(item) is None


def test_duplicate_places():
    records, rejected = parse_public_places([sample_item(), sample_item()])

    assert len(records) == 1
    assert rejected == 1


def test_mixed_valid_and_invalid_places():
    invalid = sample_item()
    invalid["mapx"] = "not-a-number"

    records, rejected = parse_public_places([sample_item(), invalid])

    assert len(records) == 1
    assert rejected == 1
