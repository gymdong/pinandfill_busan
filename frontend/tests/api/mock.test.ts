import { beforeEach, describe, expect, it } from 'vitest';
import type { ApiRequest } from '@/api';
import { INTERPRETABLE_TEXT, mockRequest, resetMockSchedule } from '@/api/mock';
import { PLACE_IDS } from '@/api/mock/fixtures/places';
import { schedule as fixtureSchedule } from '@/api/mock/fixtures/schedule';
import type { MoodResponse, PlaceDetailResponse, PlaceSearchResponse, Schedule, ScheduleMutationResponse, SuggestWaypointsResponse, UndoResponse } from '@/types/api';

const TRIP = '/trips/t1';
const BLOCK_ID = '00000000-0000-4000-8000-000000000302';
const BLOCK = `${TRIP}/blocks/${BLOCK_ID}`;

describe('mockRequest', () => {
  beforeEach(() => resetMockSchedule());
  it.each<[string, ApiRequest]>([
    ['API-001', { method: 'POST', path: '/trips/interpret', body: { text: '아무 문장' } }],
    ['API-002', { method: 'POST', path: '/trips' }],
    ['API-003', { method: 'GET', path: '/places/search', query: { q: '민락' } }],
    ['API-004', { method: 'GET', path: '/places/at', query: { lat: 35, lng: 129 } }],
    ['API-005', { method: 'GET', path: `/places/${PLACE_IDS.taejongdae}` }],
    ['API-006', { method: 'POST', path: `${TRIP}/blocks`, body: { place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'USER', dayNo: 1 } }],
    ['API-007', { method: 'PATCH', path: BLOCK, body: { stayMin: 55 } }],
    ['API-008', { method: 'DELETE', path: BLOCK }],
    ['API-009', { method: 'POST', path: `${TRIP}/schedule` }],
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

  it('편집 결과가 조회되고 직전 한 단계만 되돌린다', async () => {
    const original = await mockRequest<{ schedule: Schedule }>({ method: 'GET', path: TRIP });
    const changed = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: BLOCK, body: { stayMin: 55 } });
    expect(changed.schedule.days[0]?.blocks[1]?.stayMin).toBe(55);
    expect(changed.schedule.days[0]?.blocks[0]).toEqual(original.schedule.days[0]?.blocks[0]);
    expect(changed.violations[0]?.type).toBe('MOCK_RECALC_PENDING');
    expect(changed.schedule.days[0]?.legs).toEqual([]);
    expect((await mockRequest<{ schedule: Schedule }>({ method: 'GET', path: TRIP })).schedule).toEqual(changed.schedule);
    const undone = await mockRequest<UndoResponse>({ method: 'POST', path: `${TRIP}/undo` });
    expect(undone.schedule).toEqual(original.schedule);
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/undo` })).rejects.toMatchObject({ id: 'ERR-001' });
  });

  it('추가·순서변경·삭제를 반영하고 잘못된 편집은 원본을 보존한다', async () => {
    const added = await mockRequest<ScheduleMutationResponse>({ method: 'POST', path: `${TRIP}/blocks`, body: { place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'USER', dayNo: 1 } });
    const id = added.schedule.days[0]!.blocks.at(-1)!.id;
    expect(added.schedule.days[0]!.blocks).toHaveLength(5);
    const moved = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: `${TRIP}/blocks/${id}`, body: { seq: 2 } });
    expect(moved.schedule.days[0]!.blocks[1]!.id).toBe(id);
    expect(moved.schedule.days[0]!.blocks.map((block) => block.seq)).toEqual([1, 2, 3, 4, 5]);
    await expect(mockRequest({ method: 'PATCH', path: `${TRIP}/blocks/${id}`, body: { seq: 99 } })).rejects.toMatchObject({ id: 'ERR-001' });
    const removed = await mockRequest<ScheduleMutationResponse>({ method: 'DELETE', path: `${TRIP}/blocks/${id}` });
    expect(removed.schedule.days[0]!.blocks).toHaveLength(4);
    const undone = await mockRequest<UndoResponse>({ method: 'POST', path: `${TRIP}/undo` });
    expect(undone.schedule).toEqual(moved.schedule);
  });

  it('여행별 목 편집 상태를 분리한다', async () => {
    await mockRequest({ method: 'PATCH', path: BLOCK, body: { stayMin: 55 } });
    const other = await mockRequest<{ schedule: Schedule }>({ method: 'GET', path: '/trips/t2' });
    expect(other.schedule.days[0]!.blocks[1]!.stayMin).toBe(40);
  });

  it('같은 날 변경 전 구간은 유지하고 뒤 구간만 무효화한다', async () => {
    const original = structuredClone(fixtureSchedule);
    const changed = await mockRequest<ScheduleMutationResponse>({
      method: 'PATCH', path: `${TRIP}/blocks/${original.days[0]!.blocks[2]!.id}`, body: { stayMin: 100 },
    });
    expect(changed.schedule.days[0]!.legs).toEqual(original.days[0]!.legs.slice(0, 1));
    expect(changed.schedule.days[0]!.blocks.slice(0, 2)).toEqual(original.days[0]!.blocks.slice(0, 2));
    expect(changed.schedule.days[0]!.blocks[2]!.stayMin).toBe(100);
  });

  it('2일차 인접 블록 사이에 경유지를 넣고 한 단계 되돌린다', async () => {
    const initial = structuredClone(fixtureSchedule);
    const dayTwo = structuredClone(initial.days[0]!);
    dayTwo.dayNo = 2;
    dayTwo.date = '2026-10-18';
    dayTwo.blocks = dayTwo.blocks.slice(0, 2).map((block, index) => ({ ...block, id: `${block.id}-day2`, dayNo: 2, seq: index + 1 }));
    dayTwo.legs = [];
    dayTwo.crowd = [];
    initial.days.push(dayTwo);
    resetMockSchedule(initial);
    const first = dayTwo.blocks[0]!.id;
    const second = dayTwo.blocks[1]!.id;
    const inserted = await mockRequest<ScheduleMutationResponse>({
      method: 'POST', path: `${TRIP}/blocks`,
      body: { place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'SUGGESTED', fromBlockId: first, toBlockId: second },
    });
    expect(inserted.schedule.days[0]!.blocks).toHaveLength(4);
    expect(inserted.schedule.days[0]!.legs).toEqual(initial.days[0]!.legs);
    expect(inserted.schedule.days[0]!.blocks).toEqual(initial.days[0]!.blocks);
    expect(inserted.schedule.days[1]!.blocks.map((block) => block.id)).toEqual([first, expect.any(String), second]);
    expect(inserted.schedule.days[1]!.blocks[1]!.dayNo).toBe(2);
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/blocks`, body: {
      place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'SUGGESTED', fromBlockId: first,
      toBlockId: initial.days[0]!.blocks[1]!.id,
    } })).rejects.toMatchObject({ id: 'ERR-001' });
    const undone = await mockRequest<UndoResponse>({ method: 'POST', path: `${TRIP}/undo` });
    expect(undone.schedule).toEqual(initial);
  });

  it('dayNo만 주면 해당 일차의 끝에 추가하고 빈 일차에도 추가한다', async () => {
    const initial = structuredClone(fixtureSchedule);
    initial.days.push({ ...structuredClone(initial.days[0]!), dayNo: 2, date: '2026-10-18', blocks: [], legs: [], crowd: [] });
    resetMockSchedule(initial);
    const add = (dayNo: number) => mockRequest<ScheduleMutationResponse>({
      method: 'POST', path: `${TRIP}/blocks`, body: { place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'USER', dayNo },
    });
    const empty = await add(2);
    expect(empty.schedule.days[1]!.blocks.map((block) => [block.dayNo, block.seq])).toEqual([[2, 1]]);
    const second = await add(2);
    expect(second.schedule.days[1]!.blocks.map((block) => block.seq)).toEqual([1, 2]);
    expect(second.schedule.days[0]!.blocks).toHaveLength(initial.days[0]!.blocks.length);
    const first = await add(1);
    expect(first.schedule.days[0]!.blocks.map((block) => block.seq)).toEqual([1, 2, 3, 4, 5]);
    await expect(add(9)).rejects.toMatchObject({ id: 'ERR-001' });
  });

  it('일정에 아직 없는 날이라도 여행 기간 안이면 그날을 만들어 추가한다', async () => {
    resetMockSchedule(structuredClone(fixtureSchedule));
    const add = (dayNo: number) => mockRequest<ScheduleMutationResponse>({
      method: 'POST', path: `${TRIP}/blocks`, body: { place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'USER', dayNo },
    });
    const result = await add(3);
    expect(result.schedule.days.map((day) => [day.dayNo, day.date])).toEqual([[1, '2026-10-17'], [3, '2026-10-19']]);
    expect(result.schedule.days[1]!.blocks.map((block) => [block.dayNo, block.seq])).toEqual([[3, 1]]);
    // 여행 기간(10/17~19) 밖은 거절하고 일정을 바꾸지 않는다.
    await expect(add(4)).rejects.toMatchObject({ id: 'ERR-001' });
    await expect(add(0)).rejects.toMatchObject({ id: 'ERR-001' });
  });

  it('앵커와 다른 dayNo이거나 위치 정보가 없으면 거절한다', async () => {
    const initial = structuredClone(fixtureSchedule);
    const [first, second] = initial.days[0]!.blocks;
    const body = { place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'USER' as const };
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/blocks`, body: { ...body, dayNo: 2, fromBlockId: first!.id, toBlockId: second!.id } })).rejects.toMatchObject({ id: 'ERR-001' });
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/blocks`, body })).rejects.toMatchObject({ id: 'ERR-001' });
    const ok = await mockRequest<ScheduleMutationResponse>({ method: 'POST', path: `${TRIP}/blocks`, body: { ...body, dayNo: 1, fromBlockId: first!.id, toBlockId: second!.id } });
    expect(ok.schedule.days[0]!.blocks[1]!.seq).toBe(2);
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
