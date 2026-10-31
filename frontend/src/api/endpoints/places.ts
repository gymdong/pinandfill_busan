import type {
  IsoDate,
  PhotoSearchResponse,
  PlaceCrowdResponse,
  PlaceDetailResponse,
  PlaceSearchQuery,
  PlaceSearchResponse,
  PlacesAtQuery,
  PlacesAtResponse,
} from '@/types/api';
import { apiRequest, type CallOptions } from '../client';

export const placesApi = {
  /** API-003 장소 검색(카카오 조회 + 공공 DB 매칭). 실패 시 ERR-003 */
  search: (query: PlaceSearchQuery, options?: CallOptions) =>
    apiRequest<PlaceSearchResponse>({ method: 'GET', path: '/places/search', query, ...options }),

  /** API-004 지도에서 길게 누른 위치의 장소 찾기 */
  at: (query: PlacesAtQuery, options?: CallOptions) =>
    apiRequest<PlacesAtResponse>({ method: 'GET', path: '/places/at', query, ...options }),

  /** API-005 장소 상세 */
  get: (placeId: string, date?: IsoDate, options?: CallOptions) =>
    apiRequest<PlaceDetailResponse>({ method: 'GET', path: `/places/${placeId}`, query: { date }, ...options }),

  /** API-012 시간대별 예상 혼잡 */
  getCrowd: (placeId: string, date?: IsoDate, options?: CallOptions) =>
    apiRequest<PlaceCrowdResponse>({ method: 'GET', path: `/places/${placeId}/crowd`, query: { date }, ...options }),

  /** API-017 사진으로 장소 찾기 (P1) */
  photoSearch: (image: File, options?: CallOptions) => {
    const formData = new FormData();
    formData.append('image', image);
    return apiRequest<PhotoSearchResponse>({ method: 'POST', path: '/places/photo-search', formData, ...options });
  },
};
