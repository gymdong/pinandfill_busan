import type {
  AdminSourcesResponse,
  CreateTripResponse,
  InterpretRequest,
  InterpretResponse,
  MoodRequest,
  MoodResponse,
  PlaceDetailResponse,
  PlaceSearchResponse,
  PlacesAtResponse,
  ScheduleMutationResponse,
  SuggestWaypointsRequest,
  SuggestWaypointsResponse,
  TripDetailResponse,
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

const mutation: ScheduleMutationResponse = { schedule, violations: schedule.violations };

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
  ['POST', /^\/trips\/[^/]+\/blocks$/, () => mutation],
  ['PATCH', /^\/trips\/[^/]+\/blocks\/[^/]+$/, () => mutation],
  ['DELETE', /^\/trips\/[^/]+\/blocks\/[^/]+$/, () => mutation],
  ['POST', /^\/trips\/[^/]+\/schedule$/, () => schedule],
  ['POST', /^\/trips\/[^/]+\/undo$/, () => ({ schedule })],
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
  ['GET', /^\/trips\/[^/]+$/, (): TripDetailResponse => ({ trip, schedule })],
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
