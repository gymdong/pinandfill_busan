import { create } from 'zustand';
import { rememberKakaoPlace } from '@/api/kakaoSession';
import type { BlockPlaceInput, Coords, TripConditions, Uuid } from '@/types/api';

/**
 * '꼭 갈 곳'에 담긴 장소. UI-01 검색, UI-06 지도, UI-08 추천이 같은 목록을 쓴다.
 * 공공 DB 장소와 공공 DB에 없는 카카오 장소를 함께 담는다(D6).
 */
export type PinnedPlace =
  | { kind: 'PUBLIC'; placeId: Uuid; name: string; coords: Coords }
  | { kind: 'KAKAO'; kakaoPlaceId: string; placeUrl: string; name: string; coords: Coords };

/** 같은 장소인지 가리는 키 */
export function pinnedKey(place: PinnedPlace): string {
  return place.kind === 'PUBLIC' ? `public:${place.placeId}` : `kakao:${place.kakaoPlaceId}`;
}

/** API-006 요청의 `place`. 카카오 장소의 이름은 보내지 않는다. */
export function toBlockPlaceInput(place: PinnedPlace): BlockPlaceInput {
  return place.kind === 'PUBLIC'
    ? { placeId: place.placeId }
    : { kakaoPlaceId: place.kakaoPlaceId, placeUrl: place.placeUrl };
}

interface TripDraftState {
  conditions: Partial<TripConditions>;
  pinned: PinnedPlace[];
  setConditions: (conditions: Partial<TripConditions>) => void;
  addPinned: (place: PinnedPlace) => void;
  removePinned: (key: string) => void;
  reset: () => void;
}

/** 여행을 만들기 전까지의 임시 상태. 카카오 응답을 보관하지 않도록 브라우저 저장소에 남기지 않는다. */
export const useTripDraft = create<TripDraftState>((set) => ({
  conditions: {},
  pinned: [],
  setConditions: (conditions) => set((state) => ({ conditions: { ...state.conditions, ...conditions } })),
  addPinned: (place) => {
    // 카카오 장소의 이름·좌표는 이번 접속 동안 일정 계산과 표시에 쓰도록 기억한다.
    if (place.kind === 'KAKAO') rememberKakaoPlace(place.kakaoPlaceId, { name: place.name, coords: place.coords });
    set((state) =>
      state.pinned.some((item) => pinnedKey(item) === pinnedKey(place)) ? state : { pinned: [...state.pinned, place] },
    );
  },
  removePinned: (key) => set((state) => ({ pinned: state.pinned.filter((item) => pinnedKey(item) !== key) })),
  reset: () => set({ conditions: {}, pinned: [] }),
}));
