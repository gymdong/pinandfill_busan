import { toApiError, tripsApi, type ApiError } from '@/api';
import { needsStayInput, pinnedKey, planOf, toBlockPlaceInput, type PinnedPlace, type PinnedPlan } from '@/store/tripDraft';
import type { InitialSelection, TripConditions, Violation } from '@/types/api';
import { isLocalTime } from './conditions';

/** 장소별 방문 시간 오류. 키는 `pinnedKey` */
export type PlanErrors = Record<string, string>;

function minutesOf(time: string): number {
  const [hour = 0, minute = 0] = time.split(':').map(Number);
  return hour * 60 + minute;
}

/**
 * 서버가 체류시간 근거가 없다고 알려 준(API-009 `STAY_NEEDS_CHECK`) 장소의 `pinnedKey`.
 * 공공 DB 장소라도 기본 체류시간이 없으면 여기에 들어가고, 카카오 장소처럼 머무를 시간을 고른다.
 */
export type StayAsked = ReadonlySet<string>;

const NONE: StayAsked = new Set();

/** 체류시간 근거가 없어 미배치될 때 서버가 주는 이유 코드 */
export const STAY_NEEDS_CHECK = 'STAY_NEEDS_CHECK';

/** 사용자가 체류시간을 정해야 하는 장소: 공공 DB에 없는 카카오 장소, 또는 서버가 근거가 없다고 알려 준 장소 */
export function stayRequired(place: PinnedPlace, asked: StayAsked = NONE): boolean {
  return needsStayInput(place) || asked.has(pinnedKey(place));
}

/**
 * 시간을 정하기로 한 장소는 일차와 도착·출발 시각이 모두 있어야 고정할 수 있다.
 * 체류시간 근거가 없는 장소는 시간을 정하거나 머무를 시간을 골라야 한다. 일차는 비워 두면 '알아서'다.
 */
export function validatePlans(
  pinned: PinnedPlace[],
  plans: Record<string, PinnedPlan>,
  days: number,
  asked: StayAsked = NONE,
): PlanErrors {
  const errors: PlanErrors = {};
  for (const place of pinned) {
    const key = pinnedKey(place);
    const { dayNo, fixed: opened, stayMin } = planOf(plans, key);
    // '시간 정하기'를 열기만 하고 두 칸을 비워 두면 고정하지 않은 것으로 본다(제출을 막지 않는다).
    const fixed = opened && (opened.start || opened.end) ? opened : null;
    if (dayNo !== null && (dayNo < 1 || dayNo > days)) errors[key] = '여행 기간 안의 일차를 골라 주세요.';
    // 시각을 먼저 묻는다: 시각 한 칸만 채운 장소에 일차부터 물으면 엉뚱한 칸을 고치게 된다.
    else if (fixed && (!isLocalTime(fixed.start) || !isLocalTime(fixed.end))) errors[key] = '도착·출발 시각을 모두 정해 주세요.';
    else if (fixed && dayNo === null) errors[key] = '시간을 정한 장소는 일차를 골라 주세요.';
    else if (fixed && fixed.start >= fixed.end) errors[key] = '출발 시각은 도착 시각보다 늦어야 해요.';
    else if (!fixed && stayRequired(place, asked) && !stayMin) errors[key] = '머무를 시간을 골라 주세요.';
  }
  return errors;
}

/**
 * API-009 최초 생성의 선택 한 곳. `clientId`는 `pinnedKey`라 응답의 미배치 항목을 담은 장소에 바로 잇는다.
 * - 시간을 정한 장소만 `fixedWindow`로 고정한다(FR-003). 일차를 '알아서'로 두면 `dayNo`를 보내지 않는다.
 * - 체류시간 근거가 없는 장소는 `stayMin`을 보낸다. 시간을 정했으면 도착~출발 시간이다(서버는 길이가 다르면 거절).
 *   그 밖의 공공 DB 장소에는 붙이지 않아 서버가 장소별 값을 쓴다.
 * - 카카오 장소의 이름·좌표는 넣지 않는다(D6). 좌표는 `sessionCoords`로 계산에만 쓰인다.
 */
export function toInitialSelection(place: PinnedPlace, plan: PinnedPlan, asked: StayAsked = NONE): InitialSelection {
  const fixed = plan.fixed && isLocalTime(plan.fixed.start) && isLocalTime(plan.fixed.end) ? plan.fixed : null;
  const stayMin = !stayRequired(place, asked)
    ? undefined
    : fixed
      ? minutesOf(fixed.end) - minutesOf(fixed.start)
      : (plan.stayMin ?? undefined);
  return {
    clientId: pinnedKey(place),
    place: toBlockPlaceInput(place),
    ...(plan.dayNo === null ? {} : { dayNo: plan.dayNo }),
    ...(fixed && plan.dayNo !== null ? { fixedWindow: { dayNo: plan.dayNo, start: fixed.start, end: fixed.end } } : {}),
    ...(stayMin ? { stayMin } : {}),
  };
}

type FixedSelection = InitialSelection & { fixedWindow: NonNullable<InitialSelection['fixedWindow']> };

/**
 * 시간창이 있는 선택끼리만 (일차, 도착 시각) 순으로 안정 정렬해, 원래 고정 선택이 있던 자리에 차례로 다시 넣는다.
 * 서버는 고정 선택의 요청 순서를 방문 순서로 지키고, 역순이면 겹치지 않아도 409 ERR-009로 거절한다(#35 `docs/initial-schedule-api.md`).
 * 유연 장소의 상대 순서와 자리는 그대로다(`FIRST_FEASIBLE`은 입력 순서로 처리한다). 시각이 같으면 담은 순서를 지킨다.
 */
export function orderFixedSelections(selections: InitialSelection[]): InitialSelection[] {
  const fixed = selections
    .filter((item): item is FixedSelection => Boolean(item.fixedWindow))
    .sort((a, b) => a.fixedWindow.dayNo - b.fixedWindow.dayNo || minutesOf(a.fixedWindow.start) - minutesOf(b.fixedWindow.start));
  let next = 0;
  return selections.map((item) => (item.fixedWindow ? (fixed[next++] ?? item) : item));
}

export type CourseOutcome =
  /**
   * 일정이 저장됐다. 경로·영업시간 확인 필요 경고는 타임라인이 보여 준다.
   * `earlier`가 참이면 이번 요청이 아니라 응답을 못 받은 이전 요청이 저장한 것이다. 그 뒤 고친 선택은 반영되지 않았을 수 있다.
   */
  | { kind: 'saved'; tripId: string; earlier: boolean }
  /** 넣지 못한 장소가 있어 저장되지 않았다. 키는 `pinnedKey`. 같은 빈 여행(`tripId`)에 다시 보낼 수 있다. */
  | { kind: 'unplaced'; tripId: string; reasons: Record<string, Violation> };

/** 여행은 만들었지만 일정 생성이 실패했다. 일정은 저장되지 않았거나 확인할 수 없으며, `tripId`로 다시 시도한다. */
export class CourseFailedError extends Error {
  readonly tripId: string;
  readonly apiError: ApiError;

  constructor(tripId: string, apiError: ApiError) {
    super(apiError.message);
    this.name = 'CourseFailedError';
    this.tripId = tripId;
    this.apiError = apiError;
  }
}

const SELECTION_FIELD = 'selections.';

/**
 * 고정 시각 충돌(409 ERR-009)에서 서버가 충돌한 선택마다 실어 준 문구(`fields["selections.<clientId>"]`, #39)를
 * `clientId`(= `pinnedKey`)별로 돌려준다. 다른 오류나 `fields`가 없으면 빈 객체다.
 */
export function conflictsOf(error: ApiError): Record<string, string> {
  if (error.id !== 'ERR-009') return {};
  return Object.fromEntries(
    Object.entries(error.fields ?? {})
      .filter(([key]) => key.startsWith(SELECTION_FIELD) && key.length > SELECTION_FIELD.length)
      .map(([key, message]) => [key.slice(SELECTION_FIELD.length), message]),
  );
}

/** 응답을 받지 못해 서버가 저장했는지 알 수 없는 오류 */
const UNCERTAIN = new Set(['NETWORK', 'TIMEOUT', 'UNKNOWN']);

/** 이미 일정이 있는 여행에 최초 생성을 보냈다(덮어쓰기 방지, 400 ERR-001 `fields.initial`). 이전 요청이 저장한 경우다. */
function isOverwriteRejected(error: ApiError): boolean {
  return error.id === 'ERR-001' && Boolean(error.fields?.initial);
}

async function alreadySaved(tripId: string): Promise<boolean> {
  const { schedule } = await tripsApi.get(tripId);
  return schedule?.days.some((day) => day.blocks.length > 0) ?? false;
}

/**
 * '코스 만들기': 여행 생성(API-002) → 담은 장소 전체로 최초 일정 생성(API-009 `initial`) 한 번.
 *
 * - 담은 순서로 보내되, 고정 선택끼리는 날짜·시각순으로 맞춘다(`orderFixedSelections`).
 * - 여행 생성이 실패하면 그 오류를 그대로 던진다.
 * - `retryTripId`를 넘기면 여행을 새로 만들지 않고 그 빈 여행에 다시 보낸다(미배치·충돌·네트워크 실패 뒤).
 *   이전 요청이 응답 없이 저장됐을 수 있어 먼저 여행 조회(API-026)로 확인한다. 그 사이 저장이 끝나 덮어쓰기 방지 400이
 *   오면 다시 확인한다. 두 경우 모두 이전 요청이 저장한 것이라 `earlier: true`다.
 * - 일정 생성이 실패하면 `CourseFailedError`다. 응답을 못 받은 경우에는 여행 조회로 저장됐는지 확인한다.
 * - 호출한 쪽은 여행 조건이 그대로일 때만 `retryTripId`를 넘긴다. 담은 장소·계획은 바뀌어도 된다(전체를 다시 보냄).
 */
export async function createCourse(
  conditions: TripConditions,
  pinned: PinnedPlace[],
  plans: Record<string, PinnedPlan>,
  { retryTripId, asked = NONE }: { retryTripId?: string; asked?: StayAsked } = {},
): Promise<CourseOutcome> {
  let tripId: string;
  if (retryTripId) {
    tripId = retryTripId;
    try {
      if (await alreadySaved(tripId)) return { kind: 'saved', tripId, earlier: true };
    } catch (error) {
      throw new CourseFailedError(tripId, toApiError(error));
    }
  } else {
    tripId = (await tripsApi.create(conditions)).tripId;
  }

  const selections = orderFixedSelections(
    pinned.map((place) => toInitialSelection(place, planOf(plans, pinnedKey(place)), asked)),
  );
  try {
    // 경로 조회가 여러 번 일어날 수 있어 시간 제한을 늘린다.
    const result = await tripsApi.createInitialSchedule(
      tripId,
      { policy: 'FIRST_FEASIBLE', selections },
      { timeoutMs: 30_000 },
    );
    if (result.generation.saved) return { kind: 'saved', tripId, earlier: false };
    const reasons = Object.fromEntries(result.generation.unplaced.map((item) => [item.clientId, item.reason]));
    return { kind: 'unplaced', tripId, reasons };
  } catch (error) {
    const apiError = toApiError(error);
    // 응답을 못 받았으면 이번 요청이 저장했을 수 있고, 덮어쓰기 방지면 이전 요청이 이미 저장한 것이다.
    if (UNCERTAIN.has(apiError.id) || isOverwriteRejected(apiError)) {
      const saved = await alreadySaved(tripId).catch(() => false);
      if (saved) return { kind: 'saved', tripId, earlier: isOverwriteRejected(apiError) };
    }
    throw new CourseFailedError(tripId, apiError);
  }
}
