import type {
  AdminSourcesResponse,
  PlaceOverrideRequest,
  PlaceOverrideResponse,
  RunSourceResponse,
  UpdateConfigRequest,
  UpdateConfigResponse,
} from '@/types/api';
import { apiRequest, type CallOptions } from '../client';

export const adminApi = {
  /** API-022 데이터 소스 상태·갱신 로그 */
  getSources: (options?: CallOptions) =>
    apiRequest<AdminSourcesResponse>({ method: 'GET', path: '/admin/sources', ...options }),

  /** API-023 가중치·임계값 수정. 검증 실패는 ERR-015 */
  updateConfig: (body: UpdateConfigRequest, options?: CallOptions) =>
    apiRequest<UpdateConfigResponse>({ method: 'PUT', path: '/admin/config', body, ...options }),

  /** API-024 영업시간·실내/야외·매칭 수동 보정 */
  overridePlace: (placeId: string, body: PlaceOverrideRequest, options?: CallOptions) =>
    apiRequest<PlaceOverrideResponse>({ method: 'PUT', path: `/admin/places/${placeId}/override`, body, ...options }),

  /** API-025 수동 수집 실행 */
  runSource: (sourceId: string, options?: CallOptions) =>
    apiRequest<RunSourceResponse>({ method: 'POST', path: `/admin/sources/${sourceId}/run`, ...options }),
};
