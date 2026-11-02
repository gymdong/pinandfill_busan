import { create } from 'zustand';
import type { Coords, TripConditions, Uuid } from '@/types/api';

/**
 * '꼭 갈 곳'에 담긴 장소. UI-01 검색, UI-06 지도, UI-08 추천이 같은 목록을 쓴다.
 * 공공 DB 장소만 담는다(D6). 이름·좌표는 화면 표시용이며 브라우저 저장소에 남기지 않는다.
 */
export interface PinnedPlace {
  placeId: Uuid;
  name: string;
  coords: Coords;
}

interface TripDraftState {
  conditions: Partial<TripConditions>;
  pinned: PinnedPlace[];
  setConditions: (conditions: Partial<TripConditions>) => void;
  addPinned: (place: PinnedPlace) => void;
  removePinned: (placeId: Uuid) => void;
  reset: () => void;
}

/** 여행을 만들기 전까지의 임시 상태. 카카오 응답을 보관하지 않도록 브라우저 저장소에 남기지 않는다. */
export const useTripDraft = create<TripDraftState>((set) => ({
  conditions: {},
  pinned: [],
  setConditions: (conditions) => set((state) => ({ conditions: { ...state.conditions, ...conditions } })),
  addPinned: (place) =>
    set((state) =>
      state.pinned.some((item) => item.placeId === place.placeId) ? state : { pinned: [...state.pinned, place] },
    ),
  removePinned: (placeId) => set((state) => ({ pinned: state.pinned.filter((item) => item.placeId !== placeId) })),
  reset: () => set({ conditions: {}, pinned: [] }),
}));
