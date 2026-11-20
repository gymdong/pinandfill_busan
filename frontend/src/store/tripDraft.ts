import { create } from 'zustand';
import { rememberKakaoPlace } from '@/api/kakaoSession';
import type { BlockPlaceInput, Coords, LocalTime, TripConditions, Uuid } from '@/types/api';

/**
 * '꼭 갈 곳'에 담긴 장소. UI-01 검색, UI-06 지도, UI-08 추천이 같은 목록을 쓴다.
 * 공공 DB 장소와 공공 DB에 없는 카카오 장소를 함께 담는다(D6).
 */
export type PinnedPlace =
  | { kind: 'PUBLIC'; placeId: Uuid; name: string; coords: Coords }
  | { kind: 'KAKAO'; kakaoPlaceId: string; placeUrl: string; name: string; coords: Coords };

/**
 * 담은 장소를 어느 날 갈지와 방문 시간. `fixed`가 있으면 그 시간에 고정한다(FR-003).
 * 시각은 입력 중일 수 있어 빈 문자열을 허용하고, 보내기 전에 화면에서 검증한다.
 */
export interface PinnedPlan {
  dayNo: number;
  fixed: { start: LocalTime | ''; end: LocalTime | '' } | null;
  /**
   * 사용자가 고른 체류시간(분). 체류시간 근거가 없는 장소(공공 DB에 없는 카카오 장소)만 고른다.
   * 서버는 기본값을 만들지 않으므로(#18 PM 결정 4) 비어 있으면 화면에서 막는다.
   */
  stayMin?: number | null;
}

/** 공공 DB 장소는 서버가 장소별 체류시간을 쓴다. 카카오 장소는 근거가 없어 사용자가 정해야 한다. */
export function needsStayInput(place: PinnedPlace): boolean {
  return place.kind === 'KAKAO';
}

const DEFAULT_PLAN: PinnedPlan = { dayNo: 1, fixed: null };

/** 같은 장소인지 가리는 키 */
export function pinnedKey(place: PinnedPlace): string {
  return place.kind === 'PUBLIC' ? `public:${place.placeId}` : `kakao:${place.kakaoPlaceId}`;
}

/** 계획을 따로 정하지 않은 장소는 1일차·시간 미정이다. */
export function planOf(plans: Record<string, PinnedPlan>, key: string): PinnedPlan {
  return plans[key] ?? DEFAULT_PLAN;
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
  /** `pinnedKey`별 계획. 없는 키는 `planOf`의 기본값을 쓴다. */
  plans: Record<string, PinnedPlan>;
  setConditions: (conditions: Partial<TripConditions>) => void;
  addPinned: (place: PinnedPlace) => void;
  removePinned: (key: string) => void;
  setPlan: (key: string, plan: Partial<PinnedPlan>) => void;
  reset: () => void;
}

/** 여행을 만들기 전까지의 임시 상태. 카카오 응답을 보관하지 않도록 브라우저 저장소에 남기지 않는다. */
export const useTripDraft = create<TripDraftState>((set) => ({
  conditions: {},
  pinned: [],
  plans: {},
  setConditions: (conditions) => set((state) => ({ conditions: { ...state.conditions, ...conditions } })),
  addPinned: (place) => {
    // 카카오 장소의 이름·좌표는 이번 접속 동안 일정 계산과 표시에 쓰도록 기억한다.
    if (place.kind === 'KAKAO') rememberKakaoPlace(place.kakaoPlaceId, { name: place.name, coords: place.coords });
    set((state) =>
      state.pinned.some((item) => pinnedKey(item) === pinnedKey(place)) ? state : { pinned: [...state.pinned, place] },
    );
  },
  removePinned: (key) =>
    set((state) => ({
      pinned: state.pinned.filter((item) => pinnedKey(item) !== key),
      plans: Object.fromEntries(Object.entries(state.plans).filter(([planKey]) => planKey !== key)),
    })),
  setPlan: (key, plan) =>
    set((state) => ({ plans: { ...state.plans, [key]: { ...planOf(state.plans, key), ...plan } } })),
  reset: () => set({ conditions: {}, pinned: [], plans: {} }),
}));
