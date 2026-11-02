import { beforeEach, describe, expect, it } from 'vitest';
import { useTripDraft, type PinnedPlace } from '@/store/tripDraft';

const taejongdae: PinnedPlace = { placeId: 'p1', name: '태종대', coords: { lat: 35, lng: 129 } };
const gamcheon: PinnedPlace = { placeId: 'p2', name: '감천문화마을', coords: { lat: 35.1, lng: 129.1 } };

describe('useTripDraft', () => {
  beforeEach(() => useTripDraft.getState().reset());

  it('공공 DB 장소를 담는다', () => {
    useTripDraft.getState().addPinned(taejongdae);
    expect(useTripDraft.getState().pinned).toEqual([taejongdae]);
  });

  it('같은 장소는 한 번만 담는다', () => {
    const { addPinned } = useTripDraft.getState();
    addPinned(taejongdae);
    addPinned({ ...taejongdae });
    addPinned(gamcheon);
    expect(useTripDraft.getState().pinned).toHaveLength(2);
  });

  it('담은 장소를 뺀다', () => {
    const { addPinned, removePinned } = useTripDraft.getState();
    addPinned(taejongdae);
    addPinned(gamcheon);
    removePinned(taejongdae.placeId);
    expect(useTripDraft.getState().pinned).toEqual([gamcheon]);
  });

  it('브라우저 저장소에 남기지 않는다', () => {
    useTripDraft.getState().addPinned(taejongdae);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('조건은 항목별로 합친다', () => {
    const { setConditions } = useTripDraft.getState();
    setConditions({ mode: 'TRANSIT' });
    setConditions({ dayStart: '10:00' });
    expect(useTripDraft.getState().conditions).toEqual({ mode: 'TRANSIT', dayStart: '10:00' });
  });
});
