import { describe, expect, it } from 'vitest';
import type { ApiRequest } from '@/api';
import { INTERPRETABLE_TEXT, mockRequest } from '@/api/mock';
import { PLACE_IDS } from '@/api/mock/fixtures/places';
import type { MoodResponse, PlaceDetailResponse, PlaceSearchResponse, SuggestWaypointsResponse } from '@/types/api';

const TRIP = '/trips/t1';
const BLOCK = `${TRIP}/blocks/b1`;

describe('mockRequest', () => {
  it.each<[string, ApiRequest]>([
    ['API-001', { method: 'POST', path: '/trips/interpret', body: { text: '아무 문장' } }],
    ['API-002', { method: 'POST', path: '/trips' }],
    ['API-003', { method: 'GET', path: '/places/search', query: { q: '민락' } }],
    ['API-004', { method: 'GET', path: '/places/at', query: { lat: 35, lng: 129 } }],
    ['API-005', { method: 'GET', path: `/places/${PLACE_IDS.taejongdae}` }],
    ['API-006', { method: 'POST', path: `${TRIP}/blocks` }],
    ['API-007', { method: 'PATCH', path: BLOCK }],
    ['API-008', { method: 'DELETE', path: BLOCK }],
    ['API-009', { method: 'POST', path: `${TRIP}/schedule` }],
    ['API-010', { method: 'POST', path: `${TRIP}/undo` }],
    ['API-011', { method: 'POST', path: `${TRIP}/waypoints/suggest`, body: { thresholdMin: 15 } }],
    ['API-012', { method: 'GET', path: `/places/${PLACE_IDS.taejongdae}/crowd` }],
    ['API-013', { method: 'POST', path: '/recommend/mood', body: { text: '조용한 바다', date: '2026-10-17' } }],
    ['API-022', { method: 'GET', path: '/admin/sources' }],
    ['API-023', { method: 'PUT', path: '/admin/config' }],
    ['API-024', { method: 'PUT', path: `/admin/places/${PLACE_IDS.taejongdae}/override` }],
    ['API-025', { method: 'POST', path: '/admin/sources/tourapi/run' }],
    ['API-026', { method: 'GET', path: TRIP }],
  ])('P0 %s에 응답한다', async (_id, request) => {
    await expect(mockRequest(request)).resolves.toBeDefined();
  });

  it('P1 API는 mock을 두지 않는다', async () => {
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/save` })).rejects.toMatchObject({ id: 'UNKNOWN' });
  });

  it('한 줄 해석 실패 시 폼 전환을 알린다', async () => {
    const ok = await mockRequest({ method: 'POST', path: '/trips/interpret', body: { text: INTERPRETABLE_TEXT } });
    const failed = await mockRequest({ method: 'POST', path: '/trips/interpret', body: { text: '???' } });
    expect(ok).toMatchObject({ needsForm: false });
    expect(failed).toMatchObject({ needsForm: true });
  });

  it('검색에는 미매칭 장소도 포함된다', async () => {
    const { places } = await mockRequest<PlaceSearchResponse>({
      method: 'GET',
      path: '/places/search',
      query: { q: '민락' },
    });
    expect(places.some((place) => place.placeId === null && place.badge === 'BASIC')).toBe(true);
  });

  it('근거가 없는 장소는 값을 만들지 않는다', async () => {
    const detail = await mockRequest<PlaceDetailResponse>({ method: 'GET', path: `/places/${PLACE_IDS.gamcheon}` });
    expect(detail).toMatchObject({ hours: [], photos: [], crowd: { grade: null } });
  });

  it('우회 임계값을 넘는 후보는 제외한다', async () => {
    const { candidates } = await mockRequest<SuggestWaypointsResponse>({
      method: 'POST',
      path: `${TRIP}/waypoints/suggest`,
      body: { thresholdMin: 10 },
    });
    expect(candidates.map((item) => item.detourMin)).toEqual([9]);
  });

  it('SD-03 순서대로 문장 해석 후 태그로 추천한다', async () => {
    const parsed = await mockRequest<MoodResponse>({
      method: 'POST',
      path: '/recommend/mood',
      body: { text: '조용한 바다 감성', date: '2026-10-17' },
    });
    expect(parsed.places).toEqual([]);

    const recommended = await mockRequest<MoodResponse>({
      method: 'POST',
      path: '/recommend/mood',
      body: { tags: parsed.tags.map((tag) => tag.code), avoid: parsed.avoid, date: '2026-10-17' },
    });
    expect(recommended.places.length).toBeGreaterThan(0);

    const empty = await mockRequest<MoodResponse>({
      method: 'POST',
      path: '/recommend/mood',
      body: { tags: [], date: '2026-10-17' },
    });
    expect(empty.places).toEqual([]);
  });

  it('mockError 쿼리로 오류 상태를 재현한다', async () => {
    window.history.pushState({}, '', '/?mockError=ERR-003');
    await expect(mockRequest({ method: 'GET', path: '/admin/sources' })).rejects.toMatchObject({ id: 'ERR-003' });
    window.history.pushState({}, '', '/');
  });

  it('없는 장소는 404로 응답한다', async () => {
    await expect(mockRequest({ method: 'GET', path: '/places/none' })).rejects.toMatchObject({
      id: 'ERR-016',
      status: 404,
    });
  });
});
