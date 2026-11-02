import { beforeEach, describe, expect, it } from 'vitest';
import { clearKakaoSession, getKakaoPlace } from '@/api/kakaoSession';
import { pinnedKey, toBlockPlaceInput, useTripDraft, type PinnedPlace } from '@/store/tripDraft';

const taejongdae: PinnedPlace = { kind: 'PUBLIC', placeId: 'p1', name: '태종대', coords: { lat: 35, lng: 129 } };
const cafe: PinnedPlace = {
  kind: 'KAKAO',
  kakaoPlaceId: 'k1',
  placeUrl: 'https://example.com/k1',
  name: '카페',
  coords: { lat: 35.1, lng: 129.1 },
};

describe('useTripDraft', () => {
  beforeEach(() => {
    useTripDraft.getState().reset();
    clearKakaoSession();
  });

  it('공공 DB 장소와 카카오 장소를 함께 담는다', () => {
    const { addPinned } = useTripDraft.getState();
    addPinned(taejongdae);
    addPinned(cafe);
    expect(useTripDraft.getState().pinned).toEqual([taejongdae, cafe]);
  });

  it('카카오 장소를 담으면 이번 접속 메모리에 이름·좌표를 기억한다', () => {
    useTripDraft.getState().addPinned(cafe);
    expect(getKakaoPlace('k1')).toEqual({ name: '카페', coords: { lat: 35.1, lng: 129.1 } });
  });

  it('같은 장소는 한 번만 담는다', () => {
    const { addPinned } = useTripDraft.getState();
    addPinned(taejongdae);
    addPinned({ ...taejongdae });
    addPinned(cafe);
    addPinned({ ...cafe, name: '다른 이름' });
    expect(useTripDraft.getState().pinned).toHaveLength(2);
  });

  it('담은 장소를 키로 뺀다', () => {
    const { addPinned, removePinned } = useTripDraft.getState();
    addPinned(taejongdae);
    addPinned(cafe);
    removePinned(pinnedKey(cafe));
    expect(useTripDraft.getState().pinned).toEqual([taejongdae]);
  });

  it('브라우저 저장소에 남기지 않는다', () => {
    useTripDraft.getState().addPinned(cafe);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('블록 추가 요청에는 카카오 장소의 이름을 넣지 않는다', () => {
    expect(toBlockPlaceInput(taejongdae)).toEqual({ placeId: 'p1' });
    expect(toBlockPlaceInput(cafe)).toEqual({ kakaoPlaceId: 'k1', placeUrl: 'https://example.com/k1' });
  });

  it('조건은 항목별로 합친다', () => {
    const { setConditions } = useTripDraft.getState();
    setConditions({ mode: 'TRANSIT' });
    setConditions({ dayStart: '10:00' });
    expect(useTripDraft.getState().conditions).toEqual({ mode: 'TRANSIT', dayStart: '10:00' });
  });
});
