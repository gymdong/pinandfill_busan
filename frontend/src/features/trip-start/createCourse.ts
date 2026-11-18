import { toApiError, tripsApi, type ApiError } from '@/api';
import { needsStayInput, pinnedKey, planOf, toBlockPlaceInput, type PinnedPlace, type PinnedPlan } from '@/store/tripDraft';
import type { AddBlockRequest, TripConditions } from '@/types/api';
import { isLocalTime } from './conditions';

/** 장소별 방문 시간 오류. 키는 `pinnedKey` */
export type PlanErrors = Record<string, string>;

/** 체류시간 근거가 없는 장소에 고를 수 있는 값(분). 기본값은 두지 않는다. */
export const STAY_OPTIONS = [30, 60, 90, 120, 180, 240] as const;

function minutesOf(time: string): number {
  const [hour = 0, minute = 0] = time.split(':').map(Number);
  return hour * 60 + minute;
}

/**
 * 시간을 정하기로 한 장소는 도착·출발 시각이 모두 있어야 고정할 수 있다.
 * 체류시간 근거가 없는 장소는 시간을 정하거나 머무를 시간을 골라야 한다.
 */
export function validatePlans(pinned: PinnedPlace[], plans: Record<string, PinnedPlan>, days: number): PlanErrors {
  const errors: PlanErrors = {};
  for (const place of pinned) {
    const key = pinnedKey(place);
    const { dayNo, fixed } = planOf(plans, key);
    if (dayNo < 1 || dayNo > days) errors[key] = '여행 기간 안의 일차를 골라 주세요.';
    else if (fixed && (!isLocalTime(fixed.start) || !isLocalTime(fixed.end))) errors[key] = '도착·출발 시각을 모두 정해 주세요.';
    else if (fixed && fixed.start >= fixed.end) errors[key] = '출발 시각은 도착 시각보다 늦어야 해요.';
    else if (!fixed && needsStayInput(place) && !planOf(plans, key).stayMin) errors[key] = '머무를 시간을 골라 주세요.';
  }
  return errors;
}

/**
 * API-006 요청. 시간을 정한 장소만 고정 블록으로 보낸다(FR-003).
 * 체류시간 근거가 없는 장소는 `stayMin`을 함께 보낸다. 시간을 정했으면 도착~출발 시간이 체류시간이다.
 * 공공 DB 장소에는 붙이지 않아 서버가 장소별 값을 쓴다.
 */
export function toAddBlockRequest(place: PinnedPlace, plan: PinnedPlan): AddBlockRequest {
  const base = { dayNo: plan.dayNo, place: toBlockPlaceInput(place), origin: 'USER' as const };
  const fixed = plan.fixed && isLocalTime(plan.fixed.start) && isLocalTime(plan.fixed.end) ? plan.fixed : null;
  const stayMin = !needsStayInput(place)
    ? undefined
    : fixed
      ? minutesOf(fixed.end) - minutesOf(fixed.start)
      : (plan.stayMin ?? undefined);
  const stay = stayMin ? { stayMin } : {};
  if (fixed) {
    return { ...base, ...stay, isFixed: true, fixedWindow: { dayNo: plan.dayNo, start: fixed.start, end: fixed.end } };
  }
  return { ...base, ...stay, isFixed: false };
}

export interface CourseResult {
  tripId: string;
  /** 여행과 장소는 저장됐지만 일정 계산(API-009)이 실패한 경우의 오류. 예: 시간 부족 ERR-009 */
  scheduleError: ApiError | null;
}

/** 만들다 만 여행. 다시 시도할 때 넘기면 같은 여행에 남은 장소만 이어서 추가한다. */
export interface CourseProgress {
  tripId: string;
  /** 이미 블록으로 추가한 장소의 `pinnedKey` */
  addedKeys: string[];
}

/** 여행은 만들었지만 장소 추가(API-006)가 중간에 실패했다. `progress`로 이어서 시도할 수 있다. */
export class CourseIncompleteError extends Error {
  readonly progress: CourseProgress;
  readonly apiError: ApiError;

  constructor(progress: CourseProgress, apiError: ApiError) {
    super(apiError.message);
    this.name = 'CourseIncompleteError';
    this.progress = progress;
    this.apiError = apiError;
  }
}

/**
 * '코스 만들기': 여행 생성(API-002) → 담은 장소를 블록으로 추가(API-006) → 일정 계산(API-009).
 *
 * @provisional 현재 합의된 API만 쓴다. API-006은 일차(`dayNo`)가 필요해 화면에서 일차를 고르게 했다.
 * API-009가 담은 장소 목록을 한 번에 받아 배치하도록 바뀌면(PR #18 제안) 이 함수만 바꾸면 된다.
 *
 * 여행 생성이 실패하면 그 오류를 그대로 던진다. 장소 추가가 중간에 실패하면 `CourseIncompleteError`를 던지며,
 * 그 `progress`를 `resume`으로 넘기면 여행을 새로 만들지 않고 남은 장소부터 이어 간다.
 * 이어 가기는 조건과 담은 장소가 실패했을 때와 같을 때만 쓴다(호출한 쪽이 보장한다).
 */
export async function createCourse(
  conditions: TripConditions,
  pinned: PinnedPlace[],
  plans: Record<string, PinnedPlan>,
  resume?: CourseProgress,
): Promise<CourseResult> {
  const tripId = resume?.tripId ?? (await tripsApi.create(conditions)).tripId;
  const addedKeys = [...(resume?.addedKeys ?? [])];
  // 같은 날 안의 순서가 담은 순서대로 되도록 차례로 보낸다.
  for (const place of pinned) {
    const key = pinnedKey(place);
    if (addedKeys.includes(key)) continue;
    try {
      await tripsApi.addBlock(tripId, toAddBlockRequest(place, planOf(plans, key)));
    } catch (error) {
      throw new CourseIncompleteError({ tripId, addedKeys }, toApiError(error));
    }
    addedKeys.push(key);
  }
  try {
    await tripsApi.generateSchedule(tripId);
    return { tripId, scheduleError: null };
  } catch (error) {
    return { tripId, scheduleError: toApiError(error) };
  }
}
