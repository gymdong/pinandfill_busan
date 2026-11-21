import { describe, expect, it, vi } from 'vitest';
import { ApiError, tripsApi } from '@/api';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import {
  CourseFailedError,
  createCourse,
  stayRequired,
  toInitialSelection,
  validatePlans,
} from '@/features/trip-start/createCourse';
import type { PinnedPlace } from '@/store/tripDraft';
import type { InitialScheduleResponse, Schedule, TripConditions } from '@/types/api';

const conditions: TripConditions = {
  dates: { start: '2026-10-17', end: '2026-10-18' },
  dayStart: '10:00',
  dayEnd: '19:00',
  mode: 'TRANSIT',
};
const park: PinnedPlace = { kind: 'PUBLIC', placeId: 'p1', name: '공원', coords: { lat: 35, lng: 129 } };
const cafe: PinnedPlace = {
  kind: 'KAKAO',
  kakaoPlaceId: '123',
  placeUrl: 'https://place.map.kakao.com/123',
  name: '카페',
  coords: { lat: 35.1, lng: 129.1 },
};
const EMPTY: Schedule = { days: [], violations: [], conflicts: [] };

function generated(saved: boolean, unplaced: InitialScheduleResponse['generation']['unplaced'] = []): InitialScheduleResponse {
  return { ...schedule, generation: { saved, confirmed: false, unplaced } };
}

function mockApis() {
  return {
    create: vi.spyOn(tripsApi, 'create').mockResolvedValue({ tripId: 't9', sessionKey: 'k' }),
    initial: vi.spyOn(tripsApi, 'createInitialSchedule').mockResolvedValue(generated(true)),
    get: vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule: EMPTY }),
    addBlock: vi.spyOn(tripsApi, 'addBlock'),
  };
}

describe('코스 만들기 (API-002 → API-009 최초 생성)', () => {
  it('여행을 만들고 담은 장소 전체를 최초 생성 한 번으로 보낸다', async () => {
    const { create, initial, addBlock } = mockApis();
    const plans = {
      'public:p1': { dayNo: null, fixed: null },
      'kakao:123': { dayNo: 2, fixed: { start: '12:00', end: '13:00' } },
    } as const;

    await expect(createCourse(conditions, [park, cafe], plans)).resolves.toEqual({ kind: 'saved', tripId: 't9', earlier: false });

    expect(create).toHaveBeenCalledWith(conditions);
    expect(initial).toHaveBeenCalledTimes(1);
    expect(initial.mock.calls[0]!.slice(0, 2)).toEqual([
      't9',
      {
        policy: 'FIRST_FEASIBLE',
        selections: [
          // '알아서'는 dayNo 를 보내지 않는다. 공공 DB 장소는 체류시간을 서버가 정한다.
          { clientId: 'public:p1', place: { placeId: 'p1' } },
          {
            clientId: 'kakao:123',
            place: { kakaoPlaceId: '123', placeUrl: 'https://place.map.kakao.com/123' },
            dayNo: 2,
            fixedWindow: { dayNo: 2, start: '12:00', end: '13:00' },
            stayMin: 60,
          },
        ],
      },
    ]);
    // 장소마다 API-006 으로 넣던 예전 흐름은 쓰지 않는다.
    expect(addBlock).not.toHaveBeenCalled();
  });

  it('카카오 장소의 이름과 좌표는 요청에 넣지 않는다', () => {
    expect(JSON.stringify(toInitialSelection(cafe, { dayNo: 1, fixed: null, stayMin: 30 }))).not.toMatch(/카페|35\.1|129\.1/);
  });

  it('넣지 못한 장소가 있으면 저장되지 않았다고 알리고 이유를 pinnedKey 로 돌려준다', async () => {
    const { initial } = mockApis();
    const reason = { type: 'STAY_NEEDS_CHECK', cause: '체류시간 근거 확인이 필요합니다.' };
    initial.mockResolvedValue(generated(false, [{ clientId: 'public:p1', reason }]));
    await expect(createCourse(conditions, [park], {})).resolves.toEqual({
      kind: 'unplaced',
      tripId: 't9',
      reasons: { 'public:p1': reason },
    });
  });

  it('여행 생성이 실패하면 그 오류를 그대로 알리고 일정을 만들지 않는다', async () => {
    const { create, initial } = mockApis();
    create.mockRejectedValue(new ApiError({ id: 'NETWORK' }));
    await expect(createCourse(conditions, [park], {})).rejects.toMatchObject({ id: 'NETWORK' });
    expect(initial).not.toHaveBeenCalled();
  });

  it('고정 시각 충돌(ERR-009)이면 만든 여행과 오류를 함께 알린다', async () => {
    const { initial, get } = mockApis();
    initial.mockRejectedValue(new ApiError({ id: 'ERR-009', status: 409 }));
    const error = await createCourse(conditions, [park], {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CourseFailedError);
    expect(error).toMatchObject({ tripId: 't9', apiError: { id: 'ERR-009' } });
    // 응답을 받은 실패라 저장 여부를 다시 확인하지 않는다.
    expect(get).not.toHaveBeenCalled();
  });

  it('응답을 못 받았으면 여행 조회로 확인하고, 이미 저장됐으면 저장된 것으로 본다', async () => {
    const { initial, get } = mockApis();
    initial.mockRejectedValue(new ApiError({ id: 'TIMEOUT' }));
    get.mockResolvedValue({ trip, schedule });
    // 응답만 못 받았을 뿐 이번 요청이 저장한 것이다.
    await expect(createCourse(conditions, [park], {})).resolves.toEqual({ kind: 'saved', tripId: 't9', earlier: false });
    expect(get).toHaveBeenCalledWith('t9');
  });

  it('응답을 못 받았고 저장되지도 않았으면 다시 시도할 여행과 함께 실패를 알린다', async () => {
    const { initial } = mockApis();
    initial.mockRejectedValue(new ApiError({ id: 'NETWORK' }));
    await expect(createCourse(conditions, [park], {})).rejects.toMatchObject({ tripId: 't9', apiError: { id: 'NETWORK' } });
  });

  it('다시 시도하면 여행을 새로 만들지 않고 같은 빈 여행에 전체를 다시 보낸다', async () => {
    const { create, initial, get } = mockApis();
    await expect(createCourse(conditions, [park, cafe], { 'kakao:123': { dayNo: null, fixed: null, stayMin: 90 } }, { retryTripId: 't7' }))
      .resolves.toEqual({ kind: 'saved', tripId: 't7', earlier: false });
    expect(create).not.toHaveBeenCalled();
    expect(get).toHaveBeenCalledWith('t7');
    expect(initial.mock.calls[0]![1].selections.map((item) => item.clientId)).toEqual(['public:p1', 'kakao:123']);
  });

  it('다시 시도할 때 이전 요청이 이미 저장됐으면 다시 보내지 않는다(덮어쓰기 방지)', async () => {
    const { initial, get } = mockApis();
    get.mockResolvedValue({ trip, schedule });
    await expect(createCourse(conditions, [park], {}, { retryTripId: 't7' })).resolves.toEqual({ kind: 'saved', tripId: 't7', earlier: true });
    expect(initial).not.toHaveBeenCalled();
  });

  it('다시 보낸 사이 이전 요청이 저장을 마쳐 덮어쓰기 방지(fields.initial)가 오면, 저장을 확인하고 이전 요청의 저장으로 본다', async () => {
    const { initial, get } = mockApis();
    const message = '기존 일정이 있어 최초 자동 생성으로 덮어쓸 수 없습니다.';
    initial.mockRejectedValue(new ApiError({ id: 'ERR-001', status: 400, message, fields: { initial: message } }));
    // 다시 시도 전 확인 때는 아직 비어 있었고, 400 뒤 확인 때는 저장돼 있다.
    get.mockResolvedValueOnce({ trip, schedule: EMPTY }).mockResolvedValueOnce({ trip, schedule });
    await expect(createCourse(conditions, [park], {}, { retryTripId: 't7' })).resolves.toEqual({ kind: 'saved', tripId: 't7', earlier: true });
    expect(get).toHaveBeenCalledTimes(2);
  });

  it('덮어쓰기 방지가 왔는데 여행 조회로도 저장을 확인하지 못하면 실패로 알린다', async () => {
    const { initial } = mockApis();
    const message = '기존 일정이 있어 최초 자동 생성으로 덮어쓸 수 없습니다.';
    initial.mockRejectedValue(new ApiError({ id: 'ERR-001', status: 400, message, fields: { initial: message } }));
    await expect(createCourse(conditions, [park], {})).rejects.toMatchObject({ tripId: 't9', apiError: { fields: { initial: message } } });
  });
});

describe('장소별 방문 시간 검증', () => {
  it("일차 '알아서'와 시간을 정하지 않은 장소, 올바른 시간은 통과한다", () => {
    const plans = {
      'public:p1': { dayNo: null, fixed: null },
      'kakao:123': { dayNo: 2, fixed: { start: '12:00', end: '13:00' } },
    } as const;
    expect(validatePlans([park, cafe], plans, 2)).toEqual({});
  });

  it.each([
    ['한쪽 시각만 정함', { dayNo: 1, fixed: { start: '12:00', end: '' } }],
    ['출발이 도착보다 빠름', { dayNo: 1, fixed: { start: '13:00', end: '12:00' } }],
    ['기간 밖 일차', { dayNo: 3, fixed: null }],
    ['시간을 정했는데 일차가 알아서', { dayNo: null, fixed: { start: '12:00', end: '13:00' } }],
  ] as const)('%s이면 그 장소에 오류를 낸다', (_name, plan) => {
    const plans = { 'public:p1': plan, 'kakao:123': { dayNo: 1, fixed: null, stayMin: 60 } };
    expect(Object.keys(validatePlans([park, cafe], plans, 2))).toEqual(['public:p1']);
  });

  it('체류시간 근거가 없는 카카오 장소는 시간을 정하거나 머무를 시간을 골라야 한다', () => {
    expect(validatePlans([park, cafe], {}, 2)).toEqual({ 'kakao:123': '머무를 시간을 골라 주세요.' });
    expect(validatePlans([cafe], { 'kakao:123': { dayNo: 1, fixed: null, stayMin: 90 } }, 1)).toEqual({});
    // 공공 DB 장소는 서버가 장소별 체류시간을 쓰므로 고르지 않아도 된다.
    expect(validatePlans([park], {}, 1)).toEqual({});
  });
});

describe('서버가 체류시간을 요구한 장소(STAY_NEEDS_CHECK)', () => {
  const asked = new Set(['public:p1']);

  it('공공 DB 장소라도 요구받으면 시간을 정하거나 머무를 시간을 골라야 한다', () => {
    expect(stayRequired(park)).toBe(false);
    expect(stayRequired(park, asked)).toBe(true);
    expect(validatePlans([park], {}, 1, asked)).toEqual({ 'public:p1': '머무를 시간을 골라 주세요.' });
    expect(validatePlans([park], { 'public:p1': { dayNo: 1, fixed: null, stayMin: 60 } }, 1, asked)).toEqual({});
  });

  it('요구받은 장소에는 고른 체류시간을, 시간을 정했으면 시간창 길이를 붙인다', () => {
    expect(toInitialSelection(park, { dayNo: null, fixed: null, stayMin: 60 }, asked)).toEqual({
      clientId: 'public:p1',
      place: { placeId: 'p1' },
      stayMin: 60,
    });
    expect(toInitialSelection(park, { dayNo: 1, fixed: { start: '10:00', end: '10:45' }, stayMin: 60 }, asked))
      .toMatchObject({ stayMin: 45, fixedWindow: { dayNo: 1, start: '10:00', end: '10:45' } });
  });

  it('요구받지 않은 공공 DB 장소에는 고른 값이 있어도 체류시간을 붙이지 않는다', () => {
    expect(toInitialSelection(park, { dayNo: 1, fixed: null, stayMin: 90 })).not.toHaveProperty('stayMin');
  });

  it('createCourse 가 요구받은 장소 목록을 요청에 반영한다', async () => {
    const { initial } = mockApis();
    await createCourse(conditions, [park], { 'public:p1': { dayNo: null, fixed: null, stayMin: 90 } }, { asked });
    expect(initial.mock.calls[0]![1].selections[0]).toMatchObject({ clientId: 'public:p1', stayMin: 90 });
  });
});
