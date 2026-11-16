import { describe, expect, it, vi } from 'vitest';
import { ApiError, tripsApi } from '@/api';
import { schedule } from '@/api/mock/fixtures/schedule';
import { createCourse, toAddBlockRequest, validatePlans } from '@/features/trip-start/createCourse';
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

  it('장소 추가가 실패하면 일정 계산을 하지 않고 실패를 알린다', async () => {
    const { addBlock, generate } = mockApis();
    addBlock.mockRejectedValue(new ApiError({ id: 'ERR-001', status: 400 }));
    await expect(createCourse(conditions, [park, cafe], {})).rejects.toMatchObject({ id: 'ERR-001' });
    expect(addBlock).toHaveBeenCalledTimes(1);
    expect(generate).not.toHaveBeenCalled();
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
    expect(Object.keys(validatePlans([park, cafe], { 'public:p1': plan }, 2))).toEqual(['public:p1']);
  });
});
