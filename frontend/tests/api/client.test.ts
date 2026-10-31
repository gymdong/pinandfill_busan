import { describe, expect, it, vi } from 'vitest';
import { ApiError, SESSION_HEADER, placesApi, tripsApi } from '@/api';
import { clearSessionKey, getSessionKey } from '@/api/session';

function stubFetch(status: number, body?: unknown) {
  const fetchMock = vi.fn(async () =>
    new Response(body === undefined ? null : JSON.stringify(body), { status }),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function sentRequest(fetchMock: ReturnType<typeof stubFetch>) {
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  return { url, init, headers: init.headers as Record<string, string> };
}

describe('apiRequest', () => {
  it('/api 접두사와 쿼리를 붙이고 값이 없는 쿼리는 뺀다', async () => {
    const fetchMock = stubFetch(200, { places: [] });
    await placesApi.search({ q: '민락' });
    expect(sentRequest(fetchMock).url).toBe('/api/places/search?q=%EB%AF%BC%EB%9D%BD');
  });

  it('여행 생성 시 받은 세션 키를 저장하고 다음 요청에 붙인다', async () => {
    clearSessionKey();
    stubFetch(200, { tripId: 't1', sessionKey: 'key-1' });
    await tripsApi.create({
      dates: { start: '2026-10-17', end: '2026-10-19' },
      dayStart: '10:00',
      dayEnd: '19:00',
      mode: 'TRANSIT',
    });
    expect(getSessionKey()).toBe('key-1');

    const fetchMock = stubFetch(200, {});
    await tripsApi.get('t1');
    expect(sentRequest(fetchMock).headers[SESSION_HEADER]).toBe('key-1');
  });

  it('세션 키가 없으면 헤더를 보내지 않는다', async () => {
    clearSessionKey();
    const fetchMock = stubFetch(200, { places: [] });
    await placesApi.search({ q: '민락' });
    expect(sentRequest(fetchMock).headers).not.toHaveProperty(SESSION_HEADER);
  });

  it('오류 본문의 ID·문구·항목별 오류를 그대로 쓴다', async () => {
    stubFetch(400, { error: { id: 'ERR-001', message: '날짜를 확인해 주세요', fields: { dates: '필수' } } });
    const error = await tripsApi.interpret({ text: '' }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ id: 'ERR-001', status: 400, message: '날짜를 확인해 주세요', fields: { dates: '필수' } });
  });

  it('같은 503이어도 서버가 보낸 ID를 우선한다', async () => {
    stubFetch(503, { error: { id: 'ERR-003' } });
    await expect(placesApi.search({ q: '민락' })).rejects.toMatchObject({ id: 'ERR-003' });
  });

  it('본문이 JSON이 아니면 상태 코드로 오류 ID를 정한다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Bad Gateway</html>', { status: 409 })));
    await expect(tripsApi.generateSchedule('t1')).rejects.toMatchObject({ id: 'ERR-009', status: 409 });
  });

  it('알 수 없는 상태 코드는 UNKNOWN으로 처리한다', async () => {
    stubFetch(500);
    await expect(placesApi.search({ q: '민락' })).rejects.toMatchObject({ id: 'UNKNOWN', status: 500 });
  });

  it('연결 실패는 NETWORK로 처리한다', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch'); }));
    await expect(placesApi.search({ q: '민락' })).rejects.toMatchObject({ id: 'NETWORK' });
  });

  it('호출자가 취소하면 ApiError로 바꾸지 않는다', async () => {
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init: RequestInit) => {
      init.signal?.throwIfAborted();
      return new Response('{}');
    }));
    const controller = new AbortController();
    controller.abort();
    const error = await placesApi.search({ q: '민락' }, { signal: controller.signal }).catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it('시간 초과는 TIMEOUT으로 처리한다', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) =>
      new Promise((_resolve, reject) => {
        init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      }),
    ));
    const pending = placesApi.search({ q: '민락' }).catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(15_000);
    await expect(pending).resolves.toMatchObject({ id: 'TIMEOUT' });
    vi.useRealTimers();
  });
});
