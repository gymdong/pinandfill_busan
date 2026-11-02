import { ApiError, parseErrorResponse } from './errors';
import { getSessionKey } from './session';

const API_BASE = '/api';
const DEFAULT_TIMEOUT_MS = 15_000;
/** @provisional 전달 방식이 SDD에 없어 정한 헤더명이다(정현빈과 합의 필요). */
export const SESSION_HEADER = 'X-Session-Key';

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type QueryValue = string | number | boolean | undefined;

export interface ApiRequest {
  method: HttpMethod;
  /** `/api`를 뺀 경로. 예: `/places/search` */
  path: string;
  query?: object;
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  timeoutMs?: number;
}

export interface CallOptions {
  signal?: AbortSignal;
  /** 기본 15초. 사진 업로드나 AI 해석처럼 오래 걸리는 호출에서 늘린다. */
  timeoutMs?: number;
}

/** 본문이 비었거나 JSON이 아님을 나타낸다. */
const NO_JSON = Symbol('no-json');

function buildUrl(path: string, query: ApiRequest['query']): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {}) as [string, QueryValue][]) {
    if (value !== undefined) params.set(key, String(value));
  }
  const search = params.toString();
  return `${API_BASE}${path}${search ? `?${search}` : ''}`;
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return NO_JSON;
  try {
    return JSON.parse(text);
  } catch {
    return NO_JSON;
  }
}

async function serverRequest<T>({ method, path, query, body, formData, signal, timeoutMs }: ApiRequest): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const forwardAbort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  signal?.addEventListener('abort', forwardAbort, { once: true });

  const headers: Record<string, string> = { Accept: 'application/json' };
  const sessionKey = getSessionKey();
  if (sessionKey) headers[SESSION_HEADER] = sessionKey;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  try {
    const response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: formData ?? (body === undefined ? undefined : JSON.stringify(body)),
      signal: controller.signal,
    });
    const payload = await readJson(response);
    if (!response.ok) throw parseErrorResponse(response.status, payload === NO_JSON ? undefined : payload);
    if (response.status === 204) return undefined as T;
    // 프록시가 HTML 오류 페이지를 200으로 돌려주는 경우 등은 성공으로 넘기지 않는다.
    if (payload === NO_JSON) throw new ApiError({ id: 'UNKNOWN', status: response.status });
    return payload as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (timedOut) throw new ApiError({ id: 'TIMEOUT' });
    if (signal?.aborted) throw error;
    throw new ApiError({ id: 'NETWORK' });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', forwardAbort);
  }
}

/** 모든 API 호출의 진입점. mock 모드에서는 fixture로 응답하고 운영 빌드에는 mock 코드가 들어가지 않는다. */
export async function apiRequest<T>(request: ApiRequest): Promise<T> {
  if (import.meta.env.VITE_API_MODE === 'mock') {
    const { mockRequest } = await import('./mock');
    return mockRequest<T>(request);
  }
  return serverRequest<T>(request);
}
