import { beforeEach, describe, expect, it } from 'vitest';
import type { ApiRequest } from '@/api';
import { INTERPRETABLE_TEXT, STAY_REQUIRED_MESSAGE, mockRequest, resetMockSchedule } from '@/api/mock';
import { PLACE_IDS, mockKakaoKey } from '@/api/mock/fixtures/places';
import { schedule as fixtureSchedule } from '@/api/mock/fixtures/schedule';
import type { CreateTripResponse, InitialScheduleResponse, MoodResponse, PlaceDetailResponse, PlaceSearchResponse, PlacesAtResponse, Schedule, ScheduleMutationResponse, SuggestWaypointsResponse, TripDetailResponse, UndoResponse } from '@/types/api';

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

  it('같은 값으로 바꾸는 편집은 저장도 되돌리기 지점 기록도 하지 않는다', async () => {
    const original = await mockRequest<{ schedule: Schedule }>({ method: 'GET', path: TRIP });
    const [first, second] = original.schedule.days[0]!.blocks;
    await mockRequest({ method: 'PATCH', path: BLOCK, body: { stayMin: 55 } });
    const afterEdit = await mockRequest<{ schedule: Schedule }>({ method: 'GET', path: TRIP });
    const sameStay = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: BLOCK, body: { stayMin: 55 } });
    const sameSeq = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: BLOCK, body: { seq: 2 } });
    const sameFixed = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: `${TRIP}/blocks/${first!.id}`, body: { isFixed: true } });
    for (const result of [sameStay, sameSeq, sameFixed]) expect(result.schedule).toEqual(afterEdit.schedule);
    expect(second!.id).toBe(BLOCK_ID);
    // 되돌리기는 마지막 실제 편집(stayMin 55)을 취소한다.
    const undone = await mockRequest<UndoResponse>({ method: 'POST', path: `${TRIP}/undo` });
    expect(undone.schedule).toEqual(original.schedule);
  });

  it('고정 해제는 도착 시각을 유지하고 출발을 도착+체류로 다시 정해 뒤 블록만 재계산한다', async () => {
    const original = await mockRequest<{ schedule: Schedule }>({ method: 'GET', path: TRIP });
    const [first, second] = original.schedule.days[0]!.blocks;
    const result = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: `${TRIP}/blocks/${first!.id}`, body: { isFixed: false } });
    const [unfixed, next] = result.schedule.days[0]!.blocks;
    expect(unfixed).toMatchObject({ isFixed: false, fixedStart: null, fixedEnd: null, arriveAt: first!.arriveAt, departAt: '11:30' });
    expect(next).toMatchObject({ id: second!.id, arriveAt: null, departAt: null });
    await mockRequest({ method: 'POST', path: `${TRIP}/undo` });
  });

  it('고정 해제 후 출발이 자정을 넘기면 출발을 비운다', async () => {
    const late = structuredClone(fixtureSchedule);
    Object.assign(late.days[0]!.blocks[0]!, { arriveAt: '23:00', stayMin: 90 });
    resetMockSchedule(late);
    const result = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: `${TRIP}/blocks/${late.days[0]!.blocks[0]!.id}`, body: { isFixed: false } });
    expect(result.schedule.days[0]!.blocks[0]).toMatchObject({ arriveAt: '23:00', departAt: null });
  });

  it('지정 시각이 없는 블록을 고정하면 ERR-001이고 되돌리기 지점을 남기지 않는다', async () => {
    await expect(mockRequest({ method: 'PATCH', path: BLOCK, body: { isFixed: true } })).rejects.toMatchObject({ id: 'ERR-001' });
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/undo` })).rejects.toMatchObject({ id: 'ERR-001' });
  });

  it('지정 시각이 있는 블록을 고정하면 지정 시각을 도착·출발 시각으로 쓴다', async () => {
    const windowed = structuredClone(fixtureSchedule);
    Object.assign(windowed.days[0]!.blocks[1]!, { isFixed: false, fixedStart: '13:00', fixedEnd: '14:00', arriveAt: null, departAt: null });
    resetMockSchedule(windowed);
    const result = await mockRequest<ScheduleMutationResponse>({ method: 'PATCH', path: BLOCK, body: { isFixed: true } });
    expect(result.schedule.days[0]!.blocks[1]).toMatchObject({ isFixed: true, arriveAt: '13:00', departAt: '14:00' });
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

  it('추가 요청에 체류시간이 있으면 그 값을 쓰고, 양의 정수가 아니면 ERR-001이다', async () => {
    const body = { place: mockKakaoKey(1), isFixed: false, origin: 'USER', dayNo: 1 };
    const added = await mockRequest<ScheduleMutationResponse>({ method: 'POST', path: `${TRIP}/blocks`, body: { ...body, stayMin: 120 } });
    expect(added.schedule.days[0]!.blocks.at(-1)).toMatchObject({ place: { source: 'KAKAO' }, stayMin: 120 });
    for (const stayMin of [0, -30, 1.5, 1441]) {
      await expect(mockRequest({ method: 'POST', path: `${TRIP}/blocks`, body: { ...body, stayMin } })).rejects.toMatchObject({ id: 'ERR-001' });
    }
  });

  it('백엔드처럼 체류시간 근거가 없는 카카오 장소는 fields.stayMin으로 거절하고, 공공 장소는 장소 값을 쓴다', async () => {
    const kakao = { place: mockKakaoKey(1), isFixed: false, origin: 'USER', dayNo: 1 };
    const rejected = mockRequest({ method: 'POST', path: `${TRIP}/blocks`, body: kakao });
    await expect(rejected).rejects.toMatchObject({ id: 'ERR-001', status: 400, message: STAY_REQUIRED_MESSAGE, fields: { stayMin: STAY_REQUIRED_MESSAGE } });
    // 거절된 요청은 되돌리기 지점을 남기지 않는다.
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/undo` })).rejects.toMatchObject({ id: 'ERR-001' });

    const added = await mockRequest<ScheduleMutationResponse>({ method: 'POST', path: `${TRIP}/blocks`, body: { ...kakao, place: { placeId: PLACE_IDS.jagalchi } } });
    expect(added.schedule.days[0]!.blocks.at(-1)).toMatchObject({ place: { id: PLACE_IDS.jagalchi }, stayMin: 40 });
  });

  it('시간창과 체류시간을 함께 보내면 길이가 같아야 한다', async () => {
    const body = { place: mockKakaoKey(1), isFixed: true, origin: 'USER', dayNo: 1, fixedWindow: { dayNo: 1, start: '15:00', end: '16:30' } };
    await expect(mockRequest({ method: 'POST', path: `${TRIP}/blocks`, body: { ...body, stayMin: 60 } })).rejects.toMatchObject({ id: 'ERR-001' });
    const added = await mockRequest<ScheduleMutationResponse>({ method: 'POST', path: `${TRIP}/blocks`, body: { ...body, stayMin: 90 } });
    expect(added.schedule.days[0]!.blocks.at(-1)).toMatchObject({ isFixed: true, stayMin: 90, arriveAt: '15:00', departAt: '16:30' });
  });

  it('지도 길게 누르기(API-004)는 공공 DB 장소와 공공 DB에 없는 카카오 장소를 함께 돌려준다', async () => {
    const result = await mockRequest<PlacesAtResponse>({ method: 'GET', path: '/places/at', query: { lat: 35, lng: 129 } });
    expect(result.places.map((place) => place.placeId === null)).toEqual([false, true]);
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

  it('여행을 만들면 입력한 조건과 빈 일정에서 시작하고, 담은 장소가 그 일정에 들어간다', async () => {
    const conditions = { dates: { start: '2026-11-20', end: '2026-11-21' }, dayStart: '09:00', dayEnd: '18:00', mode: 'CAR' };
    const { tripId } = await mockRequest<CreateTripResponse>({ method: 'POST', path: '/trips', body: conditions });
    const created = await mockRequest<TripDetailResponse>({ method: 'GET', path: `/trips/${tripId}` });
    expect(created.trip).toMatchObject({ id: tripId, ...conditions });
    expect(created.schedule?.days).toEqual([]);

    const body = { place: { placeId: PLACE_IDS.jagalchi }, isFixed: false, origin: 'USER' as const };
    const added = await mockRequest<ScheduleMutationResponse>({ method: 'POST', path: `/trips/${tripId}/blocks`, body: { ...body, dayNo: 2 } });
    expect(added.schedule.days.map((day) => [day.dayNo, day.date, day.blocks.length])).toEqual([[2, '2026-11-21', 1]]);
    // 만든 여행의 기간 밖 일차는 거절한다.
    await expect(mockRequest({ method: 'POST', path: `/trips/${tripId}/blocks`, body: { ...body, dayNo: 3 } })).rejects.toMatchObject({ id: 'ERR-001' });
    // 다른 여행 ID는 예시 일정을 그대로 본다.
    const other = await mockRequest<TripDetailResponse>({ method: 'GET', path: '/trips/t2' });
    expect(other.schedule?.days[0]!.blocks).toHaveLength(fixtureSchedule.days[0]!.blocks.length);
  });

  describe('API-009 최초 생성(initial, PR #35 계약)', () => {
    const conditions = { dates: { start: '2026-11-20', end: '2026-11-21' }, dayStart: '09:00', dayEnd: '18:00', mode: 'CAR' };
    const park = { clientId: 'public:park', place: { placeId: PLACE_IDS.jagalchi }, dayNo: 2 };
    const fixedCafe = {
      clientId: 'kakao:1',
      place: mockKakaoKey(1),
      fixedWindow: { dayNo: 1, start: '10:00', end: '11:30' },
    };
    const initial = (selections: unknown[]) => ({ initial: { policy: 'FIRST_FEASIBLE', selections } });

    async function newTrip() {
      return (await mockRequest<CreateTripResponse>({ method: 'POST', path: '/trips', body: conditions })).tripId;
    }

    it('모두 넣으면 저장하고, 되돌리기 지점은 만들지 않는다', async () => {
      const tripId = await newTrip();
      const result = await mockRequest<InitialScheduleResponse>({ method: 'POST', path: `/trips/${tripId}/schedule`, body: initial([park, fixedCafe]) });
      expect(result.generation).toEqual({ saved: true, confirmed: false, unplaced: [] });
      const saved = await mockRequest<TripDetailResponse>({ method: 'GET', path: `/trips/${tripId}` });
      expect(saved.schedule!.days.map((day) => [day.dayNo, day.blocks.map((block) => [block.isFixed, block.stayMin, block.arriveAt])]))
        .toEqual([[1, [[true, 90, '10:00']]], [2, [[false, 40, null]]]]);
      await expect(mockRequest({ method: 'POST', path: `/trips/${tripId}/undo` })).rejects.toMatchObject({ id: 'ERR-001' });
      // 이미 저장된 여행에 다시 보내면 덮어쓰지 않고 거절한다.
      await expect(mockRequest({ method: 'POST', path: `/trips/${tripId}/schedule`, body: initial([park]) })).rejects.toMatchObject({ id: 'ERR-001' });
    });

    it('체류시간 근거가 없는 카카오 장소는 미배치하고 저장하지 않는다', async () => {
      const tripId = await newTrip();
      const cafe = { clientId: 'kakao:2', place: mockKakaoKey(2) };
      const result = await mockRequest<InitialScheduleResponse>({ method: 'POST', path: `/trips/${tripId}/schedule`, body: initial([park, cafe]) });
      expect(result.generation).toEqual({
        saved: false,
        confirmed: false,
        unplaced: [{ clientId: 'kakao:2', reason: { type: 'STAY_NEEDS_CHECK', cause: '체류시간 근거 확인이 필요합니다.' } }],
      });
      const unchanged = await mockRequest<TripDetailResponse>({ method: 'GET', path: `/trips/${tripId}` });
      expect(unchanged.schedule!.days).toEqual([]);
      // 저장되지 않았으니 같은 여행에 다시 보낼 수 있다.
      const retried = await mockRequest<InitialScheduleResponse>({ method: 'POST', path: `/trips/${tripId}/schedule`, body: initial([park, { ...cafe, stayMin: 60 }]) });
      expect(retried.generation.saved).toBe(true);
    });

    it.each([
      ['options 와 함께 보냄', { ...initial([park]), options: {} }],
      ['빈 선택', initial([])],
      ['중복 clientId', initial([park, { ...park, dayNo: 1 }])],
      ['dayNo 와 시간창 일차가 다름', initial([{ ...fixedCafe, dayNo: 2 }])],
      ['체류시간이 시간창 길이와 다름', initial([{ ...fixedCafe, stayMin: 60 }])],
      ['기간 밖 일차', initial([{ ...park, dayNo: 3 }])],
      ['시간창 길이가 0', initial([{ ...fixedCafe, fixedWindow: { dayNo: 1, start: '10:00', end: '10:00' } }])],
    ])('%s 이면 ERR-001 이다', async (_name, body) => {
      const tripId = await newTrip();
      await expect(mockRequest({ method: 'POST', path: `/trips/${tripId}/schedule`, body })).rejects.toMatchObject({ id: 'ERR-001' });
    });
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
