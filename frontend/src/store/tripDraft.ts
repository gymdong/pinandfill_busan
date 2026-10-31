import { create } from 'zustand';
import type { Coords, PlaceBadge, TripConditions, Uuid } from '@/types/api';

/** '꼭 갈 곳'에 담긴 장소. UI-01 검색, UI-06 지도, UI-08 추천이 같은 목록을 쓴다. */
export interface PinnedPlace {
  /** 공공 DB에 매칭되지 않은 장소는 null */
  placeId: Uuid | null;
  name: string;
  coords: Coords;
  badge: PlaceBadge;
}

interface TripDraftState {
  conditions: Partial<TripConditions>;
  pinned: PinnedPlace[];
  setConditions: (conditions: Partial<TripConditions>) => void;
  addPinned: (place: PinnedPlace) => void;
  removePinned: (place: PinnedPlace) => void;
  reset: () => void;
}

function isSamePlace(a: PinnedPlace, b: PinnedPlace): boolean {
  if (a.placeId || b.placeId) return a.placeId === b.placeId;
  return a.name === b.name && a.coords.lat === b.coords.lat && a.coords.lng === b.coords.lng;
}

/** 여행을 만들기 전까지의 임시 상태. 카카오 응답을 보관하지 않도록 브라우저 저장소에 남기지 않는다. */
export const useTripDraft = create<TripDraftState>((set) => ({
  conditions: {},
  pinned: [],
  setConditions: (conditions) => set((state) => ({ conditions: { ...state.conditions, ...conditions } })),
  addPinned: (place) =>
    set((state) =>
      state.pinned.some((item) => isSamePlace(item, place)) ? state : { pinned: [...state.pinned, place] },
    ),
  removePinned: (place) => set((state) => ({ pinned: state.pinned.filter((item) => !isSamePlace(item, place)) })),
  reset: () => set({ conditions: {}, pinned: [] }),
}));
