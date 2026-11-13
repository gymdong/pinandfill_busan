import type {
  AddBlockRequest,
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
  Schedule,
  ScheduleMutationResponse,
  SuggestWaypointsRequest,
  SuggestWaypointsResponse,
  TripDetailResponse,
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
import { MOCK_SESSION_KEY, schedule, trip, TRIP_ID } from './fixtures/schedule';

const MOCK_DELAY_MS = 150;
/** API-001 mock이 해석에 성공하는 유일한 문장. 그 외 입력은 폼 전환(needsForm)을 확인하는 데 쓴다. */
export const INTERPRETABLE_TEXT = '10/17~19 2박 3일 대중교통';

type Handler = (request: ApiRequest, params: string[]) => unknown;

interface MockTripState { schedule: Schedule; previous: Schedule | null; nextBlockNumber: number }
const tripStates = new Map<string, MockTripState>();
let initialSchedule: Schedule = schedule;

function state(tripId: string): MockTripState {
  let value = tripStates.get(tripId);
  if (!value) {
    value = { schedule: structuredClone(initialSchedule), previous: null, nextBlockNumber: 500 };
    tripStates.set(tripId, value);
  }
  return value;
}

/** 테스트 간 상태를 격리한다. 실제 서버의 일정 엔진 대신 쓰지 않는다. */
export function resetMockSchedule(initial: Schedule = schedule): void {
  tripStates.clear();
  initialSchedule = structuredClone(initial);
}

function snapshot(tripId: string): Schedule {
  return structuredClone(state(tripId).schedule);
}

function invalid(): never {
  throw new ApiError({ id: 'ERR-001', status: 400 });
}

interface AffectedRange { dayNo: number; startIndex: number }

function mutate(tripId: string, change: (draft: Schedule, state: MockTripState) => AffectedRange): ScheduleMutationResponse {
  const tripState = state(tripId);
  const draft = snapshot(tripId);
  const affected = change(draft, tripState);
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

function addBlock(tripId: string, body: AddBlockRequest): ScheduleMutationResponse {
  if (!body?.place) return invalid();
  return mutate(tripId, (draft, tripState) => {
    const anchored = body.fromBlockId ? findBlock(draft, body.fromBlockId) : null;
    // 백엔드와 동일: 앵커가 있으면 앵커의 일차, 없으면 dayNo → fixedWindow.dayNo, 모두 없으면 ERR-001
    const dayNo = anchored?.day.dayNo ?? body.dayNo ?? body.fixedWindow?.dayNo;
    if (dayNo === undefined) return invalid();
    if (anchored && body.dayNo !== undefined && body.dayNo !== dayNo) return invalid();
    const day = draft.days.find((item) => item.dayNo === dayNo);
    if (!day) return invalid();
    if (body.fixedWindow && body.fixedWindow.dayNo !== dayNo) return invalid();
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
      stayMin: 40, arriveAt: body.fixedWindow?.start ?? null,
      departAt: body.fixedWindow?.end ?? null, origin: body.origin, warnings: [],
    };
    day.blocks.splice(index, 0, block);
    return { dayNo, startIndex: index };
  });
}

function updateBlock(tripId: string, blockId: string, body: UpdateBlockRequest): ScheduleMutationResponse {
  if (!body || !Object.keys(body).some((key) => ['isFixed', 'seq', 'stayMin'].includes(key))) return invalid();
  return mutate(tripId, (draft) => {
    const { day, index, block } = findBlock(draft, blockId);
    if ('seq' in body) {
      if (!Number.isInteger(body.seq) || body.seq < 1 || body.seq > day.blocks.length) return invalid();
      day.blocks.splice(index, 1);
      day.blocks.splice(body.seq - 1, 0, block);
      return { dayNo: day.dayNo, startIndex: Math.min(index, body.seq - 1) };
    } else if ('stayMin' in body) {
      if (!Number.isInteger(body.stayMin) || body.stayMin <= 0) return invalid();
      block.stayMin = body.stayMin;
    } else if ('isFixed' in body) {
      block.isFixed = body.isFixed;
      if (!body.isFixed) { block.fixedStart = null; block.fixedEnd = null; }
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
  ['POST', /^\/trips$/, (): CreateTripResponse => ({ tripId: TRIP_ID, sessionKey: MOCK_SESSION_KEY })],
  [
    'GET',
    /^\/places\/search$/,
    ({ query }): PlaceSearchResponse => {
      const q = String((query as { q?: string } | undefined)?.q ?? '').trim();
      if (!q) throw new ApiError({ id: 'ERR-001', status: 400, fields: { q: '검색어를 입력해 주세요.' } });
      return { places: searchItems.filter((item) => item.name.includes(q)) };
    },
  ],
  ['GET', /^\/places\/at$/, (): PlacesAtResponse => ({ places: searchItems.slice(0, 1), nearbyCount: 4 })],
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
  ['POST', /^\/trips\/([^/]+)\/schedule$/, (_request, [tripId]) => snapshot(tripId ?? '')],
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
  ['GET', /^\/trips\/([^/]+)$/, (_request, [tripId]): TripDetailResponse => ({ trip, schedule: snapshot(tripId ?? '') })],
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
  // API-014~021(P1)은 타입만 두고 mock을 만들지 않는다.
  throw new ApiError({ id: 'UNKNOWN', message: `mock이 없는 API입니다: ${request.method} ${request.path}` });
}
