from datetime import date, time

import pytest

from app.modules.engine.schemas import BlockDraft, InsertInput, RecomputeInput, ScheduleState
from app.modules.engine.service import SequenceNormalizationRequiredError
from app.modules.trips.repository import TripRecord
from tests.integration.test_trip_api import insertion, setup_api
from tests.unit.engine.test_service import _block, _engine, _public_ref, _trip


@pytest.mark.parametrize("anchor", [0, 1, 2])
def test_insert_preserves_complete_prefix_and_other_dates(anchor):
    engine, _, _ = _engine(("a", "b", "c", "d", "next", "new"), duration=5)
    blocks = tuple(
        _block(key, i + 1, arrive=time(9 + i), depart=time(9 + i, 30), fixed=True)
        for i, key in enumerate(("a", "b", "c", "d"))
    ) + (_block("next", 1, arrive=time(9), depart=time(9, 30), day_no=2, fixed=True),)
    state = ScheduleState(blocks=blocks)
    result = engine.insert(
        InsertInput(
            trip=_trip(end_date=date(2026, 11, 3)),
            schedule=state,
            block=BlockDraft(place_ref=_public_ref("new"), is_fixed=False, stay_min=15, origin="USER"),
            from_block_id=blocks[anchor].id,
            to_block_id=blocks[anchor + 1].id,
            block_id="new",
        )
    )
    assert result.state.blocks[: anchor + 1] == blocks[: anchor + 1]
    assert result.state.blocks[-1] == blocks[-1]
    assert [b.seq for b in result.state.blocks[:-1]] == [1, 2, 3, 4, 5]
    for previous in blocks:
        after = next(b for b in result.state.blocks if b.id == previous.id)
        assert after.model_dump(exclude={"seq"}) == previous.model_dump(exclude={"seq"})


def test_legacy_normalization_is_explicit_separate_and_idempotent():
    engine, _, _ = _engine(("a", "b", "new"))
    state = ScheduleState(
        blocks=(
            _block("a", 10, arrive=time(9), depart=time(9, 30), fixed=True),
            _block("b", 20, arrive=time(11), depart=time(11, 30), fixed=True),
        )
    )
    command = InsertInput(
        trip=_trip(),
        schedule=state,
        block=BlockDraft(place_ref=_public_ref("new"), is_fixed=False, stay_min=30, origin="USER"),
        from_block_id="a",
        to_block_id="b",
    )
    before = state.model_dump_json()
    with pytest.raises(SequenceNormalizationRequiredError):
        engine.insert(command)
    assert state.model_dump_json() == before
    recomputed = engine.recompute(RecomputeInput(trip=_trip(), schedule=state, from_block_id="a"))
    assert [b.seq for b in recomputed.state.blocks] == [10, 20]
    migrated = engine.normalize_sequences(_trip(), state, day_no=1)
    assert [b.seq for b in migrated.blocks] == [1, 2]
    assert all(
        a.model_dump(exclude={"seq"}) == b.model_dump(exclude={"seq"})
        for a, b in zip(state.blocks, migrated.blocks, strict=True)
    )
    assert engine.normalize_sequences(_trip(), migrated, day_no=1) == migrated
    assert engine.insert(command.model_copy(update={"schedule": migrated})).state.blocks[0] == migrated.blocks[0]


def test_day_append_preserves_prefix_and_only_calculates_new_leg():
    client, repo, _, routes = setup_api()
    before = repo.get("trip")
    response = client.post("/api/trips/trip/blocks", json=insertion(fromBlockId=None, toBlockId=None, dayNo=1))
    assert response.status_code == 200
    after = repo.get("trip").schedule
    assert after.blocks[:-1] == before.schedule.blocks
    assert [b.seq for b in after.blocks] == [1, 2, 3]
    assert (after.blocks[-1].arrive_at, after.blocks[-1].depart_at) == (time(11, 45), time(12, 15))
    assert routes.calls == [("b", "new")]


@pytest.mark.parametrize("day_no", [1, 2, 3])
def test_first_block_on_empty_valid_day_does_not_guess_start_time(day_no):
    client, repo, _, routes = setup_api()
    record = repo.get("trip")
    other_day = 3 if day_no != 3 else 1
    existing = tuple(b.model_copy(update={"day_no": other_day}) for b in record.schedule.blocks)
    repo.save("trip", TripRecord(_trip(end_date=date(2026, 11, 4)), ScheduleState(blocks=existing)))
    response = client.post("/api/trips/trip/blocks", json=insertion(fromBlockId=None, toBlockId=None, dayNo=day_no))
    assert response.status_code == 200
    saved = repo.get("trip").schedule.blocks
    assert tuple(b for b in saved if b.day_no == other_day) == existing
    new = next(b for b in saved if b.day_no == day_no)
    assert new.seq == 1 and new.arrive_at is None and new.depart_at is None
    assert not routes.calls
    assert "TIME_NEEDS_CHECK" in {v["type"] for v in response.json()["violations"]}


def test_fixed_window_day_is_compatible_append_fallback():
    client, repo, _, _ = setup_api()
    repo.save("trip", TripRecord(_trip(), ScheduleState()))
    response = client.post(
        "/api/trips/trip/blocks",
        json=insertion(
            fromBlockId=None, toBlockId=None, isFixed=True, fixedWindow={"dayNo": 1, "start": "09:00", "end": "09:30"}
        ),
    )
    assert response.status_code == 200
    block = repo.get("trip").schedule.blocks[0]
    assert (block.seq, block.arrive_at, block.depart_at) == (1, time(9), time(9, 30))


@pytest.mark.parametrize(
    "patch",
    [
        {"dayNo": 2},
        {"dayNo": 0},
        {"dayNo": -1},
        {"fromBlockId": None, "toBlockId": None, "dayNo": 2},
        {"fromBlockId": None, "toBlockId": None},
        {"dayNo": 1, "isFixed": True, "fixedWindow": {"dayNo": 2, "start": "09:00", "end": "09:30"}},
    ],
)
def test_invalid_day_or_contradictory_anchor_never_saves(patch):
    client, repo, _, _ = setup_api()
    before = repo.get("trip")
    response = client.post("/api/trips/trip/blocks", json=insertion(**patch))
    assert response.status_code == 400 and response.json()["error"]["id"] == "ERR-001"
    assert repo.get("trip") == before


def test_http_legacy_seq_error_is_actionable_and_nonmutating():
    client, repo, _, _ = setup_api()
    record = repo.get("trip")
    legacy = record.schedule.model_copy(
        update={"blocks": tuple(b.model_copy(update={"seq": b.seq * 10}) for b in record.schedule.blocks)}
    )
    repo.save("trip", TripRecord(record.trip, legacy))
    response = client.post("/api/trips/trip/blocks", json=insertion())
    assert response.status_code == 400 and "정규화" in response.json()["error"]["message"]
    assert repo.get("trip").schedule == legacy


def test_unqueried_leg_is_unknown_without_fabricated_timestamp_or_wire_source():
    client, repo, _, routes = setup_api()
    record = repo.get("trip")
    a, b = record.schedule.blocks
    state = ScheduleState(blocks=(a.model_copy(update={"depart_at": None}), b))
    result = client.app.state.trip_service.engine.recompute(
        RecomputeInput(trip=record.trip, schedule=state, from_block_id="a")
    )
    leg = result.state.legs[0]
    assert leg.source == "UNKNOWN" and leg.duration_min is None and leg.computed_at is None
    assert not leg.lookup_failed and not routes.calls
    assert result.schedule.days[0].legs == ()
    assert "DEPARTURE_TIME_NEEDS_CHECK" in {v.type for v in result.schedule.violations}


@pytest.mark.parametrize("operation", ["delete", "reorder"])
def test_external_edit_contiguous_seq_is_preserved_by_recompute(operation):
    # Simulate the edit owner's output, without implementing their edit APIs.
    engine, _, _ = _engine(("a", "b", "c", "d"), duration=5)
    a = _block("a", 1, arrive=time(9), depart=time(9, 30), fixed=True)
    b = _block("b", 2, arrive=time(10), depart=time(10, 30))
    c = _block("c", 3, arrive=time(11), depart=time(11, 30))
    d = _block("d", 4, arrive=time(12), depart=time(12, 30), fixed=True)
    changed = (c, d) if operation == "delete" else (c, b, d)
    edited = (a,) + tuple(block.model_copy(update={"seq": i + 2}) for i, block in enumerate(changed))
    result = engine.recompute(RecomputeInput(trip=_trip(), schedule=ScheduleState(blocks=edited), from_block_id="a"))
    assert result.state.blocks[0] == a
    assert [(b.id, b.seq) for b in result.state.blocks] == [(b.id, b.seq) for b in edited]
    assert result.state.blocks[-1] == edited[-1]
