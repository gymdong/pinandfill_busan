import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  clearKakaoSession,
  getSessionCoords,
  rememberKakaoPlace,
  resolveBlockPlace,
  tripsApi,
} from '@/api';
import { placeSummaries } from '@/api/mock/fixtures/places';

function stubFetch() {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ schedule: {}, violations: [] }), { status: 200 }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function sentBody(fetchMock: ReturnType<typeof stubFetch>) {
  const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  return init.body === undefined ? undefined : JSON.parse(String(init.body));
}

describe('kakaoSession', () => {
  beforeEach(() => clearKakaoSession());

  it('기억한 장소가 없으면 좌표를 붙이지 않는다', () => {
    expect(getSessionCoords()).toBeUndefined();
  });

  it('좌표만 모으고 이름은 넣지 않는다', () => {
    rememberKakaoPlace('k1', { name: '카페', coords: { lat: 35.1, lng: 129.1 } });
    expect(getSessionCoords()).toEqual({ k1: { lat: 35.1, lng: 129.1 } });
    expect(JSON.stringify(getSessionCoords())).not.toContain('카페');
  });

  it('브라우저 저장소에 남기지 않는다', () => {
    rememberKakaoPlace('k1', { name: '카페', coords: { lat: 35.1, lng: 129.1 } });
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it('공공 DB 장소는 응답 값으로 이름·좌표를 찾는다', () => {
    expect(resolveBlockPlace(placeSummaries.taejongdae)).toEqual({
      name: '태종대',
      coords: { lat: placeSummaries.taejongdae.lat, lng: placeSummaries.taejongdae.lng },
    });
  });

  it('이번 접속에서 고르지 않은 카카오 장소는 찾지 못한다', () => {
    const place = { source: 'KAKAO', kakaoPlaceId: 'k9', placeUrl: 'https://example.com/k9' } as const;
    expect(resolveBlockPlace(place)).toBeNull();
    rememberKakaoPlace('k9', { name: '카페', coords: { lat: 35.1, lng: 129.1 } });
    expect(resolveBlockPlace(place)?.name).toBe('카페');
  });
});

describe('일정 계산 요청의 sessionCoords', () => {
  beforeEach(() => clearKakaoSession());

  it('기억한 카카오 장소의 좌표를 붙인다', async () => {
    rememberKakaoPlace('k1', { name: '카페', coords: { lat: 35.1, lng: 129.1 } });
    const fetchMock = stubFetch();
    await tripsApi.addBlock('t1', {
      place: { kakaoPlaceId: 'k1', placeUrl: 'https://example.com/k1' },
      isFixed: false,
      origin: 'USER',
    });
    const body = sentBody(fetchMock);
    expect(body.sessionCoords).toEqual({ k1: { lat: 35.1, lng: 129.1 } });
    expect(JSON.stringify(body)).not.toContain('카페');
  });

  it('기억한 장소가 없으면 본문 없는 요청에 본문을 만들지 않는다', async () => {
    const fetchMock = stubFetch();
    await tripsApi.deleteBlock('t1', 'b1');
    expect(sentBody(fetchMock)).toBeUndefined();
  });

  it('삭제·되돌리기에도 좌표를 붙인다', async () => {
    rememberKakaoPlace('k1', { name: '카페', coords: { lat: 35.1, lng: 129.1 } });
    const fetchMock = stubFetch();
    await tripsApi.undo('t1');
    expect(sentBody(fetchMock)).toEqual({ sessionCoords: { k1: { lat: 35.1, lng: 129.1 } } });
  });
});
