import { create } from 'zustand';
import { rememberKakaoPlace } from '@/api/kakaoSession';
import type { BlockPlaceInput, Coords, LocalTime, ThemeTag, TripConditions, TripPreferences, Uuid } from '@/types/api';

/**
 * UI-08에서 고른 분위기(FR-015). 여행 조건의 `prefs.tags`·`prefs.avoid`로 함께 보낸다.
 * 태그는 UI-01에 표시명으로 보여 주려고 코드와 표시명을 함께 둔다.
 */
export interface MoodSelection {
  tags: ThemeTag[];
  avoid: string[];
}

/** 기존 취향(`note` 등)은 두고 분위기 항목만 바꾼다. 남는 값이 없으면 `prefs`를 뺀다. */
function withMood(prefs: TripPreferences | undefined, mood: MoodSelection | null): TripPreferences | undefined {
  const next: TripPreferences = { ...prefs };
  delete next.tags;
  delete next.avoid;
  if (mood && mood.tags.length > 0) next.tags = mood.tags.map((tag) => tag.code);
  if (mood && mood.avoid.length > 0) next.avoid = [...mood.avoid];
  return Object.keys(next).length > 0 ? next : undefined;
}

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
  /**
   * 갈 일차. null이면 '알아서'로, 서버(API-009 최초 생성)가 여행 기간의 날짜를 차례로 시도한다.
   * 시간을 정한(`fixed`) 장소는 일차가 있어야 한다.
   */
  dayNo: number | null;
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

const DEFAULT_PLAN: PinnedPlan = { dayNo: null, fixed: null };

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
  /** UI-08에서 고른 분위기. 고르지 않았거나 지웠으면 null */
  mood: MoodSelection | null;
  setConditions: (conditions: Partial<TripConditions>) => void;
  /** 분위기를 저장하고 `conditions.prefs`에 반영한다. 태그·피할 조건이 모두 비면 지운다. */
  setMood: (mood: MoodSelection | null) => void;
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
  mood: null,
  setConditions: (conditions) =>
    set((state) => {
      const next = { ...state.conditions, ...conditions };
      // prefs 를 통째로 바꿔도 분위기 항목은 고른 분위기(mood)를 따른다. 화면과 보내는 값이 어긋나지 않게 한다.
      if ('prefs' in conditions) {
        const prefs = withMood(conditions.prefs, state.mood);
        if (prefs) next.prefs = prefs;
        else delete next.prefs;
      }
      return { conditions: next };
    }),
  setMood: (mood) =>
    set((state) => {
      const kept = mood && (mood.tags.length > 0 || mood.avoid.length > 0) ? mood : null;
      const conditions = { ...state.conditions };
      const prefs = withMood(conditions.prefs, kept);
      if (prefs) conditions.prefs = prefs;
      else delete conditions.prefs;
      return { mood: kept, conditions };
    }),
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
  reset: () => set({ conditions: {}, pinned: [], plans: {}, mood: null }),
}));
