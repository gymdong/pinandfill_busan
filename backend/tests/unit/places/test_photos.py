"""장소 사진 표본(FR-014) 읽기. 사진 URL·기관은 직접 만든 예시다."""

import logging
from pathlib import Path

from app.modules.places.photos import load_place_photos

HEADER = "﻿tourapi_contentid,url,source_org,license_type,is_primary\n"


def write(tmp_path: Path, rows: str) -> Path:
    path = tmp_path / "place_photos.csv"
    path.write_text(HEADER + rows, encoding="utf-8")
    return path


def test_photos_are_loaded_with_the_primary_photo_first(tmp_path):
    path = write(
        tmp_path,
        "100,https://img.example.com/a.jpg,예시 기관,공공누리 제1유형,FALSE\n"
        "100,https://img.example.com/b.jpg,예시 기관,공공누리 제3유형,TRUE\n"
        "100,https://img.example.com/c.jpg,예시 기관,공공누리 제1유형,\n",
    )
    photos = load_place_photos(path)
    assert [(p.url.rsplit("/", 1)[1], p.is_primary) for p in photos.photos("100")] == [
        ("b.jpg", True),
        ("a.jpg", False),
        ("c.jpg", False),
    ]
    primary = photos.primary("100")
    assert primary is not None
    assert primary.model_dump(mode="json", by_alias=True) == {
        "id": primary.id,
        "url": "https://img.example.com/b.jpg",
        "sourceOrg": "예시 기관",
        "licenseType": "공공누리 제3유형",
        "isPrimary": True,
    }


def test_primary_falls_back_to_the_first_photo(tmp_path):
    path = write(tmp_path, "100,https://img.example.com/a.jpg,예시 기관,공공누리 제1유형,FALSE\n")
    primary = load_place_photos(path).primary("100")
    assert primary is not None and primary.url.endswith("a.jpg")


def test_ids_are_stable_and_duplicates_are_dropped(tmp_path):
    path = write(
        tmp_path,
        "100,https://img.example.com/a.jpg,예시 기관,공공누리 제1유형,TRUE\n"
        "100,https://img.example.com/a.jpg,예시 기관,공공누리 제1유형,TRUE\n",
    )
    first, second = load_place_photos(path), load_place_photos(path)
    assert len(first.photos("100")) == 1
    assert first.photos("100")[0].id == second.photos("100")[0].id


def test_photos_without_license_or_source_are_not_shown(tmp_path, caplog):
    # ERR-013: 저작권 유형을 모르면 '사진 없음'이다. 출처 기관이 없거나 URL 이 아니면 쓰지 않는다.
    path = write(
        tmp_path,
        "100,https://img.example.com/no-license.jpg,예시 기관,,TRUE\n"
        "100,https://img.example.com/no-org.jpg,,공공누리 제1유형,TRUE\n"
        "100,javascript:alert(1),예시 기관,공공누리 제1유형,TRUE\n"
        "100,/relative.jpg,예시 기관,공공누리 제1유형,TRUE\n"
        "100,https://img.example.com/with space.jpg,예시 기관,공공누리 제1유형,TRUE\n"
        ",https://img.example.com/no-place.jpg,예시 기관,공공누리 제1유형,TRUE\n",
    )
    with caplog.at_level(logging.INFO):
        photos = load_place_photos(path)
    assert photos.photos("100") == ()
    assert photos.primary("100") is None
    # 건수만 남기고 URL 은 남기지 않는다.
    assert caplog.messages == ["place_photos loaded=0 missing_license=1 invalid=5"]
    assert "img.example.com" not in caplog.text


def test_only_the_first_of_several_primary_photos_stays_primary(tmp_path):
    path = write(
        tmp_path,
        "100,https://img.example.com/a.jpg,예시 기관,공공누리 제1유형,FALSE\n"
        "100,https://img.example.com/b.jpg,예시 기관,공공누리 제1유형,TRUE\n"
        "100,https://img.example.com/c.jpg,예시 기관,공공누리 제1유형,TRUE\n",
    )
    photos = load_place_photos(path)
    assert [(p.url.rsplit("/", 1)[1], p.is_primary) for p in photos.photos("100")] == [
        ("b.jpg", True),
        ("c.jpg", False),
        ("a.jpg", False),
    ]
    primary = photos.primary("100")
    assert primary is not None and primary.url.endswith("b.jpg")


def test_missing_or_broken_file_means_no_photos(tmp_path):
    assert load_place_photos(tmp_path / "none.csv").photos("100") == ()
    broken = tmp_path / "place_photos.csv"
    broken.write_bytes(b"\xff\xfe\x00broken")
    assert load_place_photos(broken).photos("100") == ()


def test_unreadable_file_does_not_stop_the_app(tmp_path, monkeypatch, caplog):
    path = write(tmp_path, "100,https://img.example.com/a.jpg,예시 기관,공공누리 제1유형,TRUE\n")

    def denied(*args: object, **kwargs: object) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", denied)
    with caplog.at_level(logging.WARNING):
        assert load_place_photos(path).photos("100") == ()
    assert caplog.messages == ["place_photos unreadable file=place_photos.csv"]
