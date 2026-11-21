import { describe, expect, it, vi } from 'vitest';
import { ApiError, tripsApi } from '@/api';
import { schedule } from '@/api/mock/fixtures/schedule';
import {
  CourseIncompleteError,
  createCourse,
  stayRequired,
  toAddBlockRequest,
  validatePlans,
} from '@/features/trip-start/createCourse';
import type { PinnedPlace } from '@/store/tripDraft';
import type { TripConditions } from '@/types/api';

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

function mockApis() {
  return {
    create: vi.spyOn(tripsApi, 'create').mockResolvedValue({ tripId: 't9', sessionKey: 'k' }),
    addBlock: vi.spyOn(tripsApi, 'addBlock').mockResolvedValue({ schedule, violations: [] }),
    generate: vi.spyOn(tripsApi, 'generateSchedule').mockResolvedValue(schedule),
  };
}

describe('코스 만들기', () => {
  it('여행을 만들고 담은 순서대로 블록을 추가한 뒤 일정을 계산한다', async () => {
    const { create, addBlock, generate } = mockApis();
    const plans = { 'kakao:123': { dayNo: 2, fixed: { start: '12:00', end: '13:00' } } } as const;

    await expect(createCourse(conditions, [park, cafe], plans)).resolves.toEqual({ tripId: 't9', scheduleError: null });

    expect(create).toHaveBeenCalledWith(conditions);
    expect(addBlock.mock.calls).toEqual([
      ['t9', { dayNo: 1, place: { placeId: 'p1' }, origin: 'USER', isFixed: false }],
      [
        't9',
        {
          dayNo: 2,
          place: { kakaoPlaceId: '123', placeUrl: 'https://place.map.kakao.com/123' },
          origin: 'USER',
          // 시간을 정한 카카오 장소는 도착~출발 시간을 체류시간으로 보낸다.
          stayMin: 60,
          isFixed: true,
          fixedWindow: { dayNo: 2, start: '12:00', end: '13:00' },
        },
      ],
    ]);
    expect(generate).toHaveBeenCalledWith('t9');
    expect(create.mock.invocationCallOrder[0]!).toBeLessThan(addBlock.mock.invocationCallOrder[0]!);
    expect(addBlock.mock.invocationCallOrder[1]!).toBeLessThan(generate.mock.invocationCallOrder[0]!);
  });

  it('카카오 장소의 이름과 좌표는 요청에 넣지 않는다', () => {
    expect(JSON.stringify(toAddBlockRequest(cafe, { dayNo: 1, fixed: null }))).not.toMatch(/카페|35\.1|129\.1/);
  });

  it('일정 계산만 실패하면 여행 ID와 오류를 함께 돌려준다', async () => {
    const { generate } = mockApis();
    const error = new ApiError({ id: 'ERR-009', status: 409 });
    generate.mockRejectedValue(error);
    await expect(createCourse(conditions, [park], {})).resolves.toEqual({ tripId: 't9', scheduleError: error });
  });

  it('여행 생성이 실패하면 그 오류를 그대로 알리고 장소를 추가하지 않는다', async () => {
    const { create, addBlock } = mockApis();
    create.mockRejectedValue(new ApiError({ id: 'NETWORK' }));
    await expect(createCourse(conditions, [park], {})).rejects.toMatchObject({ name: 'ApiError', id: 'NETWORK' });
    expect(addBlock).not.toHaveBeenCalled();
  });

  it('장소 추가가 중간에 실패하면 일정 계산을 하지 않고, 만든 여행과 추가된 장소를 함께 알린다', async () => {
    const { addBlock, generate } = mockApis();
    addBlock
      .mockResolvedValueOnce({ schedule, violations: [] })
      .mockRejectedValue(new ApiError({ id: 'ERR-001', status: 400 }));

    const error = await createCourse(conditions, [park, cafe], {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CourseIncompleteError);
    expect(error).toMatchObject({
      progress: { tripId: 't9', addedKeys: ['public:p1'] },
      apiError: { id: 'ERR-001' },
      // 어느 장소에서 실패했는지 알려 줘 그 장소에 머무를 시간을 입력받을 수 있게 한다.
      failedKey: 'kakao:123',
    });
    expect(addBlock).toHaveBeenCalledTimes(2);
    expect(generate).not.toHaveBeenCalled();
  });

  it('이어서 시도하면 여행을 새로 만들지 않고 남은 장소만 추가한다', async () => {
    const { create, addBlock, generate } = mockApis();
    const result = await createCourse(conditions, [park, cafe], {}, { tripId: 't7', addedKeys: ['public:p1'] });

    expect(result).toEqual({ tripId: 't7', scheduleError: null });
    expect(create).not.toHaveBeenCalled();
    expect(addBlock.mock.calls.map(([tripId, body]) => [tripId, body.place])).toEqual([
      ['t7', { kakaoPlaceId: '123', placeUrl: 'https://place.map.kakao.com/123' }],
    ]);
    expect(generate).toHaveBeenCalledWith('t7');
  });
});

describe('장소별 방문 시간 검증', () => {
  it('시간을 정하지 않은 장소와 올바른 시간은 통과한다', () => {
    const plans = { 'kakao:123': { dayNo: 2, fixed: { start: '12:00', end: '13:00' } } } as const;
    expect(validatePlans([park, cafe], plans, 2)).toEqual({});
  });

  it.each([
    ['한쪽 시각만 정함', { dayNo: 1, fixed: { start: '12:00', end: '' } }],
    ['출발이 도착보다 빠름', { dayNo: 1, fixed: { start: '13:00', end: '12:00' } }],
    ['기간 밖 일차', { dayNo: 3, fixed: null }],
  ] as const)('%s이면 그 장소에 오류를 낸다', (_name, plan) => {
    const plans = { 'public:p1': plan, 'kakao:123': { dayNo: 1, fixed: null, stayMin: 60 } };
    expect(Object.keys(validatePlans([park, cafe], plans, 2))).toEqual(['public:p1']);
  });

  it('체류시간 근거가 없는 카카오 장소는 시간을 정하거나 머무를 시간을 골라야 한다', () => {
    expect(validatePlans([park, cafe], {}, 2)).toEqual({ 'kakao:123': '머무를 시간을 골라 주세요.' });
    expect(validatePlans([cafe], { 'kakao:123': { dayNo: 1, fixed: null, stayMin: null } }, 1)).toEqual({
      'kakao:123': '머무를 시간을 골라 주세요.',
    });
    expect(validatePlans([cafe], { 'kakao:123': { dayNo: 1, fixed: null, stayMin: 90 } }, 1)).toEqual({});
    // 공공 DB 장소는 서버가 장소별 체류시간을 쓰므로 고르지 않아도 된다.
    expect(validatePlans([park], {}, 1)).toEqual({});
  });
});

describe('서버가 체류시간을 요구한 장소(fields.stayMin)', () => {
  const asked = new Set(['public:p1']);

  it('공공 DB 장소라도 요구받으면 시간을 정하거나 머무를 시간을 골라야 한다', () => {
    expect(stayRequired(park)).toBe(false);
    expect(stayRequired(park, asked)).toBe(true);
    expect(validatePlans([park], {}, 1, asked)).toEqual({ 'public:p1': '머무를 시간을 골라 주세요.' });
    expect(validatePlans([park], { 'public:p1': { dayNo: 1, fixed: null, stayMin: 60 } }, 1, asked)).toEqual({});
  });

  it('요구받은 공공 DB 장소에는 고른 체류시간을, 시간을 정했으면 시간창 길이를 붙인다', () => {
    expect(toAddBlockRequest(park, { dayNo: 1, fixed: null, stayMin: 60 }, asked)).toEqual({
      dayNo: 1, place: { placeId: 'p1' }, origin: 'USER', stayMin: 60, isFixed: false,
    });
    expect(toAddBlockRequest(park, { dayNo: 1, fixed: { start: '10:00', end: '10:45' }, stayMin: 60 }, asked))
      .toMatchObject({ stayMin: 45, isFixed: true });
  });

  it('이어서 시도할 때 요구받은 장소 목록을 요청에 반영한다', async () => {
    const { addBlock } = mockApis();
    await createCourse(conditions, [park], { 'public:p1': { dayNo: 1, fixed: null, stayMin: 90 } }, { tripId: 't7', addedKeys: [] }, asked);
    expect(addBlock.mock.calls[0]![1]).toMatchObject({ place: { placeId: 'p1' }, stayMin: 90 });
  });
});

describe('체류시간 보내기', () => {
  it('고른 체류시간은 카카오 장소에만 붙이고, 공공 DB 장소에는 붙이지 않는다', () => {
    expect(toAddBlockRequest(cafe, { dayNo: 1, fixed: null, stayMin: 90 })).toEqual({
      dayNo: 1,
      place: { kakaoPlaceId: '123', placeUrl: 'https://place.map.kakao.com/123' },
      origin: 'USER',
      stayMin: 90,
      isFixed: false,
    });
    expect(toAddBlockRequest(park, { dayNo: 1, fixed: null, stayMin: 90 })).not.toHaveProperty('stayMin');
  });

  it('시간을 정한 카카오 장소는 고른 값 대신 도착~출발 시간을 쓴다', () => {
    const plan = { dayNo: 1, fixed: { start: '10:30', end: '12:00' }, stayMin: 30 } as const;
    expect(toAddBlockRequest(cafe, plan)).toMatchObject({ stayMin: 90, isFixed: true });
  });
});
