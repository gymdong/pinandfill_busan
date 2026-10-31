import type { LoginRequest, LoginResponse, SharedTripResponse } from '@/types/api';
import { apiRequest, type CallOptions } from '../client';

export const accountApi = {
  /** API-020 공유 일정 열람 (P1) */
  getSharedTrip: (token: string, options?: CallOptions) =>
    apiRequest<SharedTripResponse>({ method: 'GET', path: `/shared/${token}`, ...options }),

  /** API-021 회원 로그인 (P1) */
  login: (body: LoginRequest, options?: CallOptions) =>
    apiRequest<LoginResponse>({ method: 'POST', path: '/auth/login', body, ...options }),
};
