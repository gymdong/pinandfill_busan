import type {
  AddBlockRequest,
  ApplyPlanBRequest,
  ApplyPlanBResponse,
  CreateTripResponse,
  GenerateScheduleRequest,
  InterpretRequest,
  InterpretResponse,
  PlanBResponse,
  SaveTripResponse,
  Schedule,
  ScheduleMutationResponse,
  ShareTripRequest,
  ShareTripResponse,
  SuggestWaypointsRequest,
  SuggestWaypointsResponse,
  TripConditions,
  TripDetailResponse,
  TripWeatherResponse,
  UndoResponse,
  UpdateBlockRequest,
} from '@/types/api';
import { apiRequest, type CallOptions } from '../client';
import { setSessionKey } from '../session';

export const tripsApi = {
  /** API-001 한 줄 텍스트를 여행 조건으로 해석 */
  interpret: (body: InterpretRequest, options?: CallOptions) =>
    apiRequest<InterpretResponse>({ method: 'POST', path: '/trips/interpret', body, ...options }),

  /** API-002 여행 생성. 받은 세션 키를 저장해 이후 요청에 붙인다. */
  create: async (body: TripConditions, options?: CallOptions) => {
    const response = await apiRequest<CreateTripResponse>({ method: 'POST', path: '/trips', body, ...options });
    setSessionKey(response.sessionKey);
    return response;
  },

  /** API-026 여행·일정 조회 */
  get: (tripId: string, options?: CallOptions) =>
    apiRequest<TripDetailResponse>({ method: 'GET', path: `/trips/${tripId}`, ...options }),

  /** API-006 블록 추가 */
  addBlock: (tripId: string, body: AddBlockRequest, options?: CallOptions) =>
    apiRequest<ScheduleMutationResponse>({ method: 'POST', path: `/trips/${tripId}/blocks`, body, ...options }),

  /** API-007 블록 편집(고정·순서·체류시간) */
  updateBlock: (tripId: string, blockId: string, body: UpdateBlockRequest, options?: CallOptions) =>
    apiRequest<ScheduleMutationResponse>({
      method: 'PATCH',
      path: `/trips/${tripId}/blocks/${blockId}`,
      body,
      ...options,
    }),

  /** API-008 블록 삭제 */
  deleteBlock: (tripId: string, blockId: string, options?: CallOptions) =>
    apiRequest<ScheduleMutationResponse>({ method: 'DELETE', path: `/trips/${tripId}/blocks/${blockId}`, ...options }),

  /** API-009 일정 생성·검증. 시간 부족은 ERR-009(409)로 온다. */
  generateSchedule: (tripId: string, body: GenerateScheduleRequest = {}, options?: CallOptions) =>
    apiRequest<Schedule>({ method: 'POST', path: `/trips/${tripId}/schedule`, body, ...options }),

  /** API-010 직전 편집 1단계 되돌리기 */
  undo: (tripId: string, options?: CallOptions) =>
    apiRequest<UndoResponse>({ method: 'POST', path: `/trips/${tripId}/undo`, ...options }),

  /** API-011 경유지 후보 제안 */
  suggestWaypoints: (tripId: string, body: SuggestWaypointsRequest, options?: CallOptions) =>
    apiRequest<SuggestWaypointsResponse>({
      method: 'POST',
      path: `/trips/${tripId}/waypoints/suggest`,
      body,
      ...options,
    }),

  /** API-014 플랜 B 3안 조회 (P1) */
  getPlanB: (tripId: string, blockId: string, options?: CallOptions) =>
    apiRequest<PlanBResponse>({ method: 'GET', path: `/trips/${tripId}/plan-b`, query: { blockId }, ...options }),

  /** API-015 플랜 B 적용 (P1) */
  applyPlanB: (tripId: string, body: ApplyPlanBRequest, options?: CallOptions) =>
    apiRequest<ApplyPlanBResponse>({ method: 'POST', path: `/trips/${tripId}/plan-b/apply`, body, ...options }),

  /** API-016 블록 시각별 예보 (P1) */
  getWeather: (tripId: string, options?: CallOptions) =>
    apiRequest<TripWeatherResponse>({ method: 'GET', path: `/trips/${tripId}/weather`, ...options }),

  /** API-018 회원 일정 저장 (P1) */
  save: (tripId: string, options?: CallOptions) =>
    apiRequest<SaveTripResponse>({ method: 'POST', path: `/trips/${tripId}/save`, ...options }),

  /** API-019 읽기 전용 공유 링크 생성 (P1) */
  share: (tripId: string, body: ShareTripRequest = {}, options?: CallOptions) =>
    apiRequest<ShareTripResponse>({ method: 'POST', path: `/trips/${tripId}/share`, body, ...options }),
};
