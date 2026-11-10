import type { MoodRequest, MoodResponse } from '@/types/api';
import { apiRequest, type CallOptions } from '../client';

export const recommendApi = {
  /** API-013 분위기·컨셉 해석 및 추천 */
  mood: (body: MoodRequest, options?: CallOptions) =>
    apiRequest<MoodResponse>({ method: 'POST', path: '/recommend/mood', body, ...options }),
};
