import { toApiError, tripsApi, type ApiError } from '@/api';
import { pinnedKey, planOf, toBlockPlaceInput, type PinnedPlace, type PinnedPlan } from '@/store/tripDraft';
import type { AddBlockRequest, TripConditions } from '@/types/api';
import { isLocalTime } from './conditions';

/** 장소별 방문 시간 오류. 키는 `pinnedKey` */
export type PlanErrors = Record<string, string>;

/** 시간을 정하기로 한 장소는 도착·출발 시각이 모두 있어야 고정할 수 있다. */
export function validatePlans(pinned: PinnedPlace[], plans: Record<string, PinnedPlan>, days: number): PlanErrors {
  const errors: PlanErrors = {};
  for (const place of pinned) {
    const key = pinnedKey(place);
    const { dayNo, fixed } = planOf(plans, key);
    if (dayNo < 1 || dayNo > days) errors[key] = '여행 기간 안의 일차를 골라 주세요.';
    else if (fixed && (!isLocalTime(fixed.start) || !isLocalTime(fixed.end))) errors[key] = '도착·출발 시각을 모두 정해 주세요.';
    else if (fixed && fixed.start >= fixed.end) errors[key] = '출발 시각은 도착 시각보다 늦어야 해요.';
  }
  return errors;
}

/** API-006 요청. 시간을 정한 장소만 고정 블록으로 보낸다(FR-003). */
export function toAddBlockRequest(place: PinnedPlace, plan: PinnedPlan): AddBlockRequest {
  const base = { dayNo: plan.dayNo, place: toBlockPlaceInput(place), origin: 'USER' as const };
  if (plan.fixed && isLocalTime(plan.fixed.start) && isLocalTime(plan.fixed.end)) {
    return { ...base, isFixed: true, fixedWindow: { dayNo: plan.dayNo, start: plan.fixed.start, end: plan.fixed.end } };
  }
  return { ...base, isFixed: false };
}

export interface CourseResult {
  tripId: string;
  /** 여행과 장소는 저장됐지만 일정 계산(API-009)이 실패한 경우의 오류. 예: 시간 부족 ERR-009 */
  scheduleError: ApiError | null;
}

/**
 * '코스 만들기': 여행 생성(API-002) → 담은 장소를 블록으로 추가(API-006) → 일정 계산(API-009).
 *
 * @provisional 현재 합의된 API만 쓴다. API-006은 일차(`dayNo`)가 필요해 화면에서 일차를 고르게 했다.
 * API-009가 담은 장소 목록을 한 번에 받아 배치하도록 바뀌면(PR #18 제안) 이 함수만 바꾸면 된다.
 *
 * 여행 생성이나 장소 추가가 실패하면 예외를 던진다. 다시 시도하면 새 여행을 만든다.
 */
export async function createCourse(
  conditions: TripConditions,
  pinned: PinnedPlace[],
  plans: Record<string, PinnedPlan>,
): Promise<CourseResult> {
  const { tripId } = await tripsApi.create(conditions);
  // 같은 날 안의 순서가 담은 순서대로 되도록 차례로 보낸다.
  for (const place of pinned) {
    await tripsApi.addBlock(tripId, toAddBlockRequest(place, planOf(plans, pinnedKey(place))));
  }
  try {
    await tripsApi.generateSchedule(tripId);
    return { tripId, scheduleError: null };
  } catch (error) {
    return { tripId, scheduleError: toApiError(error) };
  }
}
