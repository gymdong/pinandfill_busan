import { beforeEach, describe, expect, it } from 'vitest';
import { useTripDraft, type PinnedPlace } from '@/store/tripDraft';

const matched: PinnedPlace = { placeId: 'p1', name: '태종대', coords: { lat: 35, lng: 129 }, badge: 'DETAIL' };
const unmatched: PinnedPlace = { placeId: null, name: '카페', coords: { lat: 35.1, lng: 129.1 }, badge: 'BASIC' };

describe('useTripDraft', () => {
  beforeEach(() => useTripDraft.getState().reset());

  it('매칭되지 않은 장소도 담는다', () => {
    useTripDraft.getState().addPinned(unmatched);
    expect(useTripDraft.getState().pinned).toEqual([unmatched]);
  });

  it('같은 장소는 한 번만 담는다', () => {
    const { addPinned } = useTripDraft.getState();
    addPinned(matched);
    addPinned(matched);
    addPinned(unmatched);
    addPinned({ ...unmatched });
    expect(useTripDraft.getState().pinned).toHaveLength(2);
  });

  it('이름이 같아도 좌표가 다른 미매칭 장소는 따로 담는다', () => {
    const { addPinned } = useTripDraft.getState();
    addPinned(unmatched);
    addPinned({ ...unmatched, coords: { lat: 35.2, lng: 129.2 } });
    expect(useTripDraft.getState().pinned).toHaveLength(2);
  });

  it('담은 장소를 뺀다', () => {
    const { addPinned, removePinned } = useTripDraft.getState();
    addPinned(matched);
    addPinned(unmatched);
    removePinned(matched);
    expect(useTripDraft.getState().pinned).toEqual([unmatched]);
  });

  it('조건은 항목별로 합친다', () => {
    const { setConditions } = useTripDraft.getState();
    setConditions({ mode: 'TRANSIT' });
    setConditions({ dayStart: '10:00' });
    expect(useTripDraft.getState().conditions).toEqual({ mode: 'TRANSIT', dayStart: '10:00' });
  });
});
