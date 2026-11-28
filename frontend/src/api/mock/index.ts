import type {
  AddBlockRequest,
  GenerateScheduleRequest,
  InitialScheduleRequest,
  InitialScheduleResponse,
  InitialSelection,
  AdminSourcesResponse,
  Block,
  CreateTripResponse,
  InterpretRequest,
  InterpretResponse,
  MoodRequest,
  MoodResponse,
  PlaceDetailResponse,
  PlaceSearchResponse,
  PlacesAtResponse,
  PlanBResponse,
  Schedule,
  ScheduleDay,
  ScheduleMutationResponse,
  SuggestWaypointsRequest,
  SuggestWaypointsResponse,
  Trip,
  TripConditions,
  TripDetailResponse,
  Violation,
  UpdateBlockRequest,
} from '@/types/api';
import type { ApiRequest, HttpMethod } from '../client';
import { ApiError, isErrorId } from '../errors';
import {
  moodAvoid,
  moodPlaces,
  moodTags,
  PLACE_IDS,
  placeSummaries,
  searchItems,
  sparseDetail,
  taejongdaeCrowd,
  taejongdaeDetail,
  waypointCandidates,
} from './fixtures/places';
import { MOCK_SESSION_KEY, schedule, trip as fixtureTrip, TRIP_ID } from './fixtures/schedule';

const MOCK_DELAY_MS = 150;
/** API-001 mock이 해석에 성공하는 유일한 문장. 그 외 입력은 폼 전환(needsForm)을 확인하는 데 쓴다. */
export const INTERPRETABLE_TEXT = '10/17~19 2박 3일 대중교통';

type Handler = (request: ApiRequest, params: string[]) => unknown;

interface MockTripState { trip: Trip; schedule: Schedule; previous: Schedule | null; nextBlockNumber: number }
const tripStates = new Map<string, MockTripState>();
let initialSchedule: Schedule = schedule;

function state(tripId: string): MockTripState {
  let value = tripStates.get(tripId);
  if (!value) {
    value = { trip: fixtureTrip, schedule: structuredClone(initialSchedule), previous: null, nextBlockNumber: 500 };
    tripStates.set(tripId, value);
  }
  return value;
}

/** 테스트 간 상태를 격리한다. 실제 서버의 일정 엔진 대신 쓰지 않는다. */
export function resetMockSchedule(initial: Schedule = schedule): void {
  tripStates.clear();
  initialSchedule = structuredClone(initial);
}

/**
 * API-002. 입력한 조건으로 여행을 만들고 빈 일정에서 시작한다. 이어지는 API-006이 담은 장소를 채운다.
 * 여행 ID는 하나뿐이라 새로 만들면 이전 mock 여행을 덮어쓴다. 본문이 없으면 예시 여행 조건을 쓴다.
 */
function createTrip(body: TripConditions | undefined): CreateTripResponse {
  const trip: Trip = { ...fixtureTrip, ...body, id: TRIP_ID };
  tripStates.set(TRIP_ID, { trip, schedule: { days: [], violations: [], conflicts: [] }, previous: null, nextBlockNumber: 500 });
  return { tripId: TRIP_ID, sessionKey: MOCK_SESSION_KEY };
}

function snapshot(tripId: string): Schedule {
  return structuredClone(state(tripId).schedule);
}

function invalid(): never {
  throw new ApiError({ id: 'ERR-001', status: 400 });
}

/** 백엔드(#25·#28)와 같은 '체류시간 근거 없음' 응답. 화면은 `fields.stayMin`을 보고 머무를 시간을 입력받는다. */
export const STAY_REQUIRED_MESSAGE = '체류시간을 정할 수 없는 장소예요. 머무를 시간을 골라 주세요.';

function stayRequired(): never {
  throw new ApiError({ id: 'ERR-001', status: 400, message: STAY_REQUIRED_MESSAGE, fields: { stayMin: STAY_REQUIRED_MESSAGE } });
}

function minutesOf(time: string): number {
  const [hour = 0, minute = 0] = time.split(':').map(Number);
  return hour * 60 + minute;
}

interface AffectedRange { dayNo: number; startIndex: number }

function mutate(tripId: string, change: (draft: Schedule, state: MockTripState) => AffectedRange | null): ScheduleMutationResponse {
  const tripState = state(tripId);
  const draft = snapshot(tripId);
  const affected = change(draft, tripState);
  // 백엔드와 같이 값이 그대로인 편집은 저장도 되돌리기 지점 기록도 하지 않고 현재 일정을 돌려준다.
  if (!affected) return { schedule: snapshot(tripId), violations: structuredClone(draft.violations) };
  tripState.previous = snapshot(tripId);
  // The mock cannot calculate travel/opening hours. Preserve only the unaffected prefix.
  draft.violations = [{ type: 'MOCK_RECALC_PENDING', cause: '목업에서는 변경 후 이동·영업시간을 재계산하지 않습니다.' }];
  const day = draft.days.find((item) => item.dayNo === affected.dayNo)!;
  const prefixIds = new Set(day.blocks.slice(0, affected.startIndex).map((block) => block.id));
  day.blocks.forEach((block, index) => {
    block.seq = index + 1;
    if (index >= affected.startIndex && !block.isFixed) {
      block.arriveAt = null;
      block.departAt = null;
    }
  });
  day.legs = day.legs.filter((leg) => prefixIds.has(leg.fromBlockId) && prefixIds.has(leg.toBlockId));
  tripState.schedule = draft;
  return { schedule: snapshot(tripId), violations: structuredClone(draft.violations) };
}

function findBlock(draft: Schedule, blockId: string) {
  for (const day of draft.days) {
    const index = day.blocks.findIndex((block) => block.id === blockId);
    if (index >= 0) return { day, index, block: day.blocks[index]! };
  }
  return invalid();
}

/** 백엔드와 같이 여행 기간 안의 빈 날에도 추가할 수 있게 그날을 만든다. 기간 밖이면 ERR-001 */
function addEmptyDay(draft: Schedule, dayNo: number, trip: Trip): ScheduleDay {
  const start = Date.parse(`${trip.dates.start}T00:00:00Z`);
  const days = Math.round((Date.parse(`${trip.dates.end}T00:00:00Z`) - start) / 86_400_000) + 1;
  if (!Number.isInteger(dayNo) || dayNo < 1 || dayNo > days) return invalid();
  const date = new Date(start + (dayNo - 1) * 86_400_000).toISOString().slice(0, 10);
  const day: ScheduleDay = { dayNo, date, blocks: [], legs: [], crowd: [], weather: [] };
  draft.days.push(day);
  draft.days.sort((a, b) => a.dayNo - b.dayNo);
  return day;
}

function addBlock(tripId: string, body: AddBlockRequest): ScheduleMutationResponse {
  if (!body?.place) return invalid();
  // 백엔드와 같이 체류시간은 정수 1~1440이고, 시간창과 함께 보내면 길이가 같아야 한다.
  if (body.stayMin !== undefined && (!Number.isInteger(body.stayMin) || body.stayMin <= 0 || body.stayMin > 1440)) return invalid();
  if (body.stayMin !== undefined && body.fixedWindow
    && minutesOf(body.fixedWindow.end) - minutesOf(body.fixedWindow.start) !== body.stayMin) return invalid();
  // 공공 DB에 없는 카카오 장소는 체류시간 근거가 없다. 서버는 기본값을 만들지 않는다(#18 PM 결정 4).
  if (!('placeId' in body.place) && body.stayMin === undefined) return stayRequired();
  return mutate(tripId, (draft, tripState) => {
    const anchored = body.fromBlockId ? findBlock(draft, body.fromBlockId) : null;
    // 백엔드와 동일: 앵커가 있으면 앵커의 일차, 없으면 dayNo → fixedWindow.dayNo, 모두 없으면 ERR-001
    const dayNo = anchored?.day.dayNo ?? body.dayNo ?? body.fixedWindow?.dayNo;
    if (dayNo === undefined) return invalid();
    if (anchored && body.dayNo !== undefined && body.dayNo !== dayNo) return invalid();
    if (body.fixedWindow && body.fixedWindow.dayNo !== dayNo) return invalid();
    const day = draft.days.find((item) => item.dayNo === dayNo) ?? addEmptyDay(draft, dayNo, tripState.trip);
    const input = body.place;
    const place = 'placeId' in input
      ? Object.values(placeSummaries).find((item) => item.id === input.placeId)
      : { source: 'KAKAO' as const, ...input };
    if (!place) return invalid();
    let index = day.blocks.length;
    if (body.fromBlockId || body.toBlockId) {
      if (!anchored || !body.toBlockId) return invalid();
      index = anchored.index + 1;
      if (day.blocks[index]?.id !== body.toBlockId) return invalid();
    }
    const block: Block = {
      id: `00000000-0000-4000-8000-${String(tripState.nextBlockNumber++).padStart(12, '0')}`,
      dayNo, seq: index + 1, place, isFixed: body.isFixed,
      fixedStart: body.fixedWindow?.start ?? null, fixedEnd: body.fixedWindow?.end ?? null,
      // 사용자가 정한 체류시간이 있으면 쓰고, 없으면 공공 장소의 목업 값(40분)을 쓴다.
      stayMin: body.stayMin ?? 40, arriveAt: body.fixedWindow?.start ?? null,
      departAt: body.fixedWindow?.end ?? null, origin: body.origin, warnings: [],
    };
    day.blocks.splice(index, 0, block);
    return { dayNo, startIndex: index };
  });
}

const STAY_NEEDS_CHECK: Violation = { type: 'STAY_NEEDS_CHECK', cause: '체류시간 근거 확인이 필요합니다.' };
/** 목업 fixture의 공공 장소에는 기본 체류시간이 없어 쓰는 목업 값이다(실제 값 아님). API-006 mock과 같은 40분이다. */
const MOCK_PUBLIC_STAY_MIN = 40;
/** 백엔드 `MAX_INITIAL_SELECTIONS`(#39) */
const MOCK_MAX_SELECTIONS = 30;
/** 백엔드 409 ERR-009 문구(`trips/router.py`) */
const FIXED_CONFLICT_MESSAGE = '고정 장소의 지정 시각을 지킬 수 없습니다. 날짜 분리를 검토해 주세요.';

/**
 * API-009. `initial`이 없으면 지금 일정을 그대로 돌려준다(목업은 재계산하지 않는다).
 * `initial`이 있으면 PR #35 계약대로 최초 생성을 흉내 낸다. 시각·이동시간은 계산하지 않는다.
 * - 이미 블록이 있는 여행, `options`와 함께 보냄, 빈 선택, 중복 clientId, dayNo·시간창·체류시간 모순은 ERR-001
 * - 체류시간 근거가 없는 카카오 장소(stayMin·시간창 없음)는 STAY_NEEDS_CHECK로 미배치하고 저장하지 않는다.
 * - 모두 넣으면 저장한다. 일차를 정하지 않은 장소는 1일차에 넣는다(목업은 날짜를 고르지 않는다).
 */
function generateSchedule(tripId: string, body: GenerateScheduleRequest | InitialScheduleRequest | undefined): Schedule | InitialScheduleResponse {
  if (!body || !('initial' in body)) return snapshot(tripId);
  if ('options' in body) return invalid();
  const tripState = state(tripId);
  if (tripState.schedule.days.some((day) => day.blocks.length > 0)) return invalid();
  const selections = body.initial?.selections ?? [];
  // 백엔드처럼 선택은 30개까지다(MAX_INITIAL_SELECTIONS, #39).
  if (body.initial?.policy !== 'FIRST_FEASIBLE' || selections.length === 0 || selections.length > MOCK_MAX_SELECTIONS) return invalid();
  if (new Set(selections.map((item) => item.clientId)).size !== selections.length) return invalid();
  selections.forEach(checkSelection);
  // 백엔드처럼 고정 선택이 날짜·시각순이 아니면 겹치지 않아도 고정 순서 충돌이다. 충돌한 선택을 fields 로 싣는다(#39).
  const outOfOrder = fixedOutOfOrder(selections);
  if (outOfOrder.length > 0) {
    throw new ApiError({
      id: 'ERR-009',
      status: 409,
      message: FIXED_CONFLICT_MESSAGE,
      fields: Object.fromEntries(outOfOrder.map((clientId) => [`selections.${clientId}`, FIXED_CONFLICT_MESSAGE])),
    });
  }

  const draft: Schedule = { days: [], violations: [], conflicts: [] };
  const unplaced: { clientId: string; reason: Violation }[] = [];
  // 미리보기 블록 ID → clientId. 저장되지 않았을 때만 돌려준다(#39).
  const previewClientIds: Record<string, string> = {};
  let nextBlockNumber = tripState.nextBlockNumber;
  for (const selection of selections) {
    const input = selection.place;
    if (!('placeId' in input) && selection.stayMin === undefined && !selection.fixedWindow) {
      unplaced.push({ clientId: selection.clientId, reason: STAY_NEEDS_CHECK });
      continue;
    }
    const place = 'placeId' in input
      ? Object.values(placeSummaries).find((item) => item.id === input.placeId)
      : { source: 'KAKAO' as const, ...input };
    if (!place) return invalid();
    const dayNo = selection.fixedWindow?.dayNo ?? selection.dayNo ?? 1;
    const day = draft.days.find((item) => item.dayNo === dayNo) ?? addEmptyDay(draft, dayNo, tripState.trip);
    const window = selection.fixedWindow;
    const id = `00000000-0000-4000-8000-${String(nextBlockNumber++).padStart(12, '0')}`;
    previewClientIds[id] = selection.clientId;
    day.blocks.push({
      id,
      dayNo, seq: day.blocks.length + 1, place, isFixed: Boolean(window),
      fixedStart: window?.start ?? null, fixedEnd: window?.end ?? null,
      stayMin: selection.stayMin ?? (window ? minutesOf(window.end) - minutesOf(window.start) : MOCK_PUBLIC_STAY_MIN),
      arriveAt: window?.start ?? null, departAt: window?.end ?? null, origin: 'USER', warnings: [],
    });
  }
  const saved = unplaced.length === 0;
  draft.violations = saved
    ? [{ type: 'MOCK_RECALC_PENDING', cause: '목업에서는 이동·영업시간을 계산하지 않습니다.' }]
    : unplaced.map((item) => item.reason);
  if (saved) {
    // 최초 생성은 되돌리기 지점을 만들지 않는다(PR #35).
    tripState.schedule = draft;
    tripState.previous = null;
    tripState.nextBlockNumber = nextBlockNumber;
  }
  return {
    ...structuredClone(draft),
    generation: { saved, confirmed: false, unplaced, previewClientIds: saved ? {} : previewClientIds },
  };
}

function checkSelection(selection: InitialSelection): void {
  if (!selection.clientId || !selection.place) return invalid();
  const window = selection.fixedWindow;
  // 백엔드처럼 시간창 길이가 0 이하이면 거절한다.
  if (window && minutesOf(window.end) - minutesOf(window.start) <= 0) return invalid();
  if (window && selection.dayNo !== undefined && selection.dayNo !== window.dayNo) return invalid();
  if (selection.stayMin !== undefined) {
    if (!Number.isInteger(selection.stayMin) || selection.stayMin <= 0 || selection.stayMin > 1440) return invalid();
    if (window && minutesOf(window.end) - minutesOf(window.start) !== selection.stayMin) return invalid();
  }
}

/** 앞선 고정 선택보다 이른 날짜·시각의 고정 선택(`clientId`). 비어 있으면 순서대로다. */
function fixedOutOfOrder(selections: InitialSelection[]): string[] {
  let latest = -Infinity;
  const late: string[] = [];
  for (const item of selections) {
    if (!item.fixedWindow) continue;
    const key = item.fixedWindow.dayNo * 24 * 60 + minutesOf(item.fixedWindow.start);
    if (key < latest) late.push(item.clientId);
    else latest = key;
  }
  return late;
}

function visitEnd(arriveAt: string | null, stayMin: number): string | null {
  if (!arriveAt) return null;
  const [hour = 0, minute = 0] = arriveAt.split(':').map(Number);
  const end = hour * 60 + minute + stayMin;
  return end < 24 * 60 ? `${String(Math.floor(end / 60)).padStart(2, '0')}:${String(end % 60).padStart(2, '0')}` : null;
}

function updateBlock(tripId: string, blockId: string, body: UpdateBlockRequest): ScheduleMutationResponse {
  if (!body || !Object.keys(body).some((key) => ['isFixed', 'seq', 'stayMin'].includes(key))) return invalid();
  return mutate(tripId, (draft) => {
    const { day, index, block } = findBlock(draft, blockId);
    if ('seq' in body) {
      if (!Number.isInteger(body.seq) || body.seq < 1 || body.seq > day.blocks.length) return invalid();
      if (body.seq === index + 1) return null;
      day.blocks.splice(index, 1);
      day.blocks.splice(body.seq - 1, 0, block);
      return { dayNo: day.dayNo, startIndex: Math.min(index, body.seq - 1) };
    } else if ('stayMin' in body) {
      if (!Number.isInteger(body.stayMin) || body.stayMin <= 0) return invalid();
      if (body.stayMin === block.stayMin) return null;
      block.stayMin = body.stayMin;
    } else if ('isFixed' in body) {
      if (body.isFixed === block.isFixed) return null;
      if (body.isFixed) {
        // 지정 시각이 없으면 고정할 수 없다(백엔드 ERR-001).
        if (!block.fixedStart || !block.fixedEnd) return invalid();
        // 백엔드처럼 지정 시각을 도착·출발 시각으로 쓴다.
        block.isFixed = true;
        block.arriveAt = block.fixedStart;
        block.departAt = block.fixedEnd;
      } else {
        // 지정 시각만 지우고 도착 시각은 유지한다. 출발 = 도착 + 체류, 자정을 넘기면 null. 뒤 블록만 다시 계산한다.
        block.isFixed = false;
        block.fixedStart = null;
        block.fixedEnd = null;
        block.departAt = visitEnd(block.arriveAt, block.stayMin);
        return { dayNo: day.dayNo, startIndex: index + 1 };
      }
    }
    return { dayNo: day.dayNo, startIndex: index };
  });
}

function placeDetail(placeId: string): PlaceDetailResponse {
  if (placeId === PLACE_IDS.taejongdae) return taejongdaeDetail;
  const place = Object.values(placeSummaries).find((item) => item.id === placeId);
  if (!place) throw new ApiError({ id: 'ERR-016', status: 404 });
  return sparseDetail(place);
}

const routes: [HttpMethod, RegExp, Handler][] = [
  [
    'POST',
    /^\/trips\/interpret$/,
    ({ body }): InterpretResponse => {
      const { text } = body as InterpretRequest;
      return text.trim() === INTERPRETABLE_TEXT
        ? {
            conditions: { dates: { start: '2026-10-17', end: '2026-10-19' }, mode: 'TRANSIT' },
            needsForm: false,
          }
        : { conditions: {}, needsForm: true };
    },
  ],
  ['POST', /^\/trips$/, ({ body }) => createTrip(body as TripConditions | undefined)],
  [
    'GET',
    /^\/places\/search$/,
    ({ query }): PlaceSearchResponse => {
      const q = String((query as { q?: string } | undefined)?.q ?? '').trim();
      if (!q) throw new ApiError({ id: 'ERR-001', status: 400, fields: { q: '검색어를 입력해 주세요.' } });
      return { places: searchItems.filter((item) => item.name.includes(q)) };
    },
  ],
  // 공공 DB 장소와 공공 DB에 없는 카카오 장소를 함께 돌려줘 지도(UI-06)의 '머무를 시간' 칸을 볼 수 있게 한다.
  ['GET', /^\/places\/at$/, (): PlacesAtResponse => ({ places: [searchItems[0]!, searchItems[2]!], nearbyCount: 4 })],
  ['GET', /^\/places\/([^/]+)\/crowd$/, () => taejongdaeCrowd],
  ['GET', /^\/places\/([^/]+)$/, (_request, [placeId]) => placeDetail(placeId ?? '')],
  ['POST', /^\/trips\/([^/]+)\/blocks$/, ({ body }, [tripId]) => addBlock(tripId ?? '', body as AddBlockRequest)],
  ['PATCH', /^\/trips\/([^/]+)\/blocks\/([^/]+)$/, ({ body }, [tripId, blockId]) => updateBlock(tripId ?? '', blockId ?? '', body as UpdateBlockRequest)],
  ['DELETE', /^\/trips\/([^/]+)\/blocks\/([^/]+)$/, (_request, [tripId, blockId]) => mutate(tripId ?? '', (draft) => {
    const { day, index } = findBlock(draft, blockId ?? '');
    day.blocks.splice(index, 1);
    day.crowd = day.crowd.filter((item) => item.blockId !== blockId);
    return { dayNo: day.dayNo, startIndex: index };
  })],
  ['POST', /^\/trips\/([^/]+)\/schedule$/, (request, [tripId]) => generateSchedule(tripId ?? '', request.body as GenerateScheduleRequest | InitialScheduleRequest | undefined)],
  ['POST', /^\/trips\/([^/]+)\/undo$/, (_request, [tripId]) => {
    const tripState = state(tripId ?? '');
    if (!tripState.previous) return invalid();
    tripState.schedule = tripState.previous;
    tripState.previous = null;
    return { schedule: snapshot(tripId ?? '') };
  }],
  [
    'POST',
    /^\/trips\/[^/]+\/waypoints\/suggest$/,
    ({ body }): SuggestWaypointsResponse => {
      const { thresholdMin } = body as SuggestWaypointsRequest;
      return { candidates: waypointCandidates.filter((item) => item.detourMin <= thresholdMin) };
    },
  ],
  // API-014·015 플랜 B: 강행만 고를 수 있는 단순 mock. 실제 3안 계산은 백엔드가 한다.
  ['GET', /^\/trips\/([^/]+)\/plan-b$/, ({ query }): PlanBResponse => ({
    blockId: String((query as { blockId?: string } | undefined)?.blockId ?? ''),
    trigger: 'CROWD',
    crowd: null,
    options: [
      { id: 'KEEP', kind: 'KEEP', available: true, extraMinutes: 0, hoursConflict: false },
      { id: 'REORDER', kind: 'REORDER', available: false, extraMinutes: null, hoursConflict: false, note: '고정 시각을 지키면서 덜 붐비게 되는 순서가 없어요.' },
      { id: 'REPLACE', kind: 'REPLACE', available: false, extraMinutes: null, hoursConflict: false, note: '근처에 덜 붐비는 대체 장소가 없어요.' },
    ],
  })],
  ['POST', /^\/trips\/([^/]+)\/plan-b\/apply$/, (_request, [tripId]): ScheduleMutationResponse => ({ schedule: snapshot(tripId ?? ''), violations: [] })],
  [
    'POST',
    /^\/recommend\/mood$/,
    ({ body }): MoodResponse => {
      const request = body as MoodRequest;
      // SD-03: 문장은 태그로 해석만 하고, 태그를 확정해 다시 호출하면 추천을 돌려준다.
      if (request.text !== undefined) return { tags: moodTags, avoid: moodAvoid, places: [] };
      const selected = request.tags ?? [];
      return {
        tags: moodTags.filter((tag) => selected.includes(tag.code)),
        avoid: request.avoid ?? [],
        places: moodPlaces.filter((item) => item.evidence.matchedTags.some((tag) => selected.includes(tag))),
      };
    },
  ],
  ['GET', /^\/trips\/([^/]+)$/, (_request, [tripId]): TripDetailResponse => ({
    trip: state(tripId ?? '').trip, schedule: snapshot(tripId ?? ''), canUndo: state(tripId ?? '').previous !== null,
  })],
  [
    'GET',
    /^\/admin\/sources$/,
    (): AdminSourcesResponse => ({
      sources: [{ id: 'tourapi', asOf: '2026-10-13T03:00:00+09:00', status: 'SUCCESS', calls: 0 }],
    }),
  ],
  ['PUT', /^\/admin\/config$/, () => ({ ok: true })],
  ['PUT', /^\/admin\/places\/([^/]+)\/override$/, (_request, [placeId]) => ({ place: placeDetail(placeId ?? '').place })],
  ['POST', /^\/admin\/sources\/[^/]+\/run$/, () => ({ runId: '00000000-0000-4000-8000-000000000501' })],
];

/** 주소에 `?mockError=ERR-003`을 붙이면 모든 mock 호출이 그 오류로 실패한다. */
function forcedError(): ApiError | null {
  const id = new URLSearchParams(window.location.search).get('mockError');
  return isErrorId(id) ? new ApiError({ id, status: 503 }) : null;
}

export async function mockRequest<T>(request: ApiRequest): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_DELAY_MS));

  const error = forcedError();
  if (error) throw error;

  for (const [method, pattern, handler] of routes) {
    const match = method === request.method ? pattern.exec(request.path) : null;
    if (match) return handler(request, match.slice(1)) as T;
  }
  // API-016~021(P1)은 타입만 두고 mock을 만들지 않는다.
  throw new ApiError({ id: 'UNKNOWN', message: `mock이 없는 API입니다: ${request.method} ${request.path}` });
}
