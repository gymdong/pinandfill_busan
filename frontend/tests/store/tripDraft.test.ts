import { beforeEach, describe, expect, it } from 'vitest';
import { clearKakaoSession, getKakaoPlace } from '@/api/kakaoSession';
import { pinnedKey, planOf, toBlockPlaceInput, useTripDraft, type PinnedPlace } from '@/store/tripDraft';

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

  it("장소별 일차와 방문 시간을 따로 정하고, 정하지 않은 장소는 일차 '알아서'·시간 미정이다", () => {
    const { addPinned, setPlan } = useTripDraft.getState();
    addPinned(taejongdae);
    addPinned(cafe);
    setPlan(pinnedKey(cafe), { dayNo: 2 });
    setPlan(pinnedKey(cafe), { fixed: { start: '12:00', end: '13:00' } });
    const { plans } = useTripDraft.getState();
    expect(planOf(plans, pinnedKey(cafe))).toEqual({ dayNo: 2, fixed: { start: '12:00', end: '13:00' } });
    expect(planOf(plans, pinnedKey(taejongdae))).toEqual({ dayNo: null, fixed: null });
  });

  it('장소를 빼면 그 장소의 계획도 지운다', () => {
    const { addPinned, setPlan, removePinned } = useTripDraft.getState();
    addPinned(cafe);
    setPlan(pinnedKey(cafe), { dayNo: 2 });
    removePinned(pinnedKey(cafe));
    addPinned(cafe);
    expect(planOf(useTripDraft.getState().plans, pinnedKey(cafe))).toEqual({ dayNo: null, fixed: null });
  });

  it('조건은 항목별로 합친다', () => {
    const { setConditions } = useTripDraft.getState();
    setConditions({ mode: 'TRANSIT' });
    setConditions({ dayStart: '10:00' });
    expect(useTripDraft.getState().conditions).toEqual({ mode: 'TRANSIT', dayStart: '10:00' });
  });
});

describe('분위기 선택(FR-015)', () => {
  const sea = { code: 'SEA_VIEW', label: '바다 전망' };
  const alley = { code: 'ALLEY_WALK', label: '골목·산책' };

  beforeEach(() => useTripDraft.getState().reset());

  it('고른 태그 코드와 피할 조건을 여행 조건의 prefs 로 담는다', () => {
    useTripDraft.getState().setMood({ tags: [sea, alley], avoid: ['실내 제외'] });
    const state = useTripDraft.getState();
    expect(state.mood).toEqual({ tags: [sea, alley], avoid: ['실내 제외'] });
    expect(state.conditions.prefs).toEqual({ tags: ['SEA_VIEW', 'ALLEY_WALK'], avoid: ['실내 제외'] });
  });

  it('다시 고르면 분위기 항목만 바꾸고 다른 취향 값은 남긴다', () => {
    const { setConditions, setMood } = useTripDraft.getState();
    setConditions({ mode: 'CAR', prefs: { note: '천천히', tags: ['OLD'] } });
    setMood({ tags: [sea], avoid: [] });
    expect(useTripDraft.getState().conditions).toEqual({ mode: 'CAR', prefs: { note: '천천히', tags: ['SEA_VIEW'] } });
    setMood(null);
    expect(useTripDraft.getState().conditions).toEqual({ mode: 'CAR', prefs: { note: '천천히' } });
  });

  it('prefs 를 통째로 바꿔도 분위기 항목은 고른 분위기를 따른다', () => {
    const { setConditions, setMood } = useTripDraft.getState();
    setMood({ tags: [sea], avoid: ['실내 제외'] });
    setConditions({ prefs: { note: '천천히', tags: ['OTHER'] } });
    expect(useTripDraft.getState().conditions.prefs).toEqual({ note: '천천히', tags: ['SEA_VIEW'], avoid: ['실내 제외'] });
    setConditions({ prefs: undefined });
    expect(useTripDraft.getState().conditions.prefs).toEqual({ tags: ['SEA_VIEW'], avoid: ['실내 제외'] });
  });

  it('태그와 피할 조건이 모두 비면 분위기를 지우고 prefs 도 뺀다', () => {
    const { setMood } = useTripDraft.getState();
    setMood({ tags: [sea], avoid: [] });
    setMood({ tags: [], avoid: [] });
    expect(useTripDraft.getState().mood).toBeNull();
    expect(useTripDraft.getState().conditions).toEqual({});
  });

  it('초기화하면 분위기도 지운다', () => {
    useTripDraft.getState().setMood({ tags: [sea], avoid: [] });
    useTripDraft.getState().reset();
    expect(useTripDraft.getState().mood).toBeNull();
    expect(useTripDraft.getState().conditions).toEqual({});
  });
});
