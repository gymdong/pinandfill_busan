import { describe, expect, it } from 'vitest';
import {
  MAX_TRIP_DAYS,
  dayDate,
  tripDays,
  tripLengthLabel,
  validateConditions,
} from '@/features/trip-start/conditions';

const dates = { start: '2026-10-17', end: '2026-10-19' };

describe('여행 조건', () => {
  it('여행 일수를 날짜로 계산하고, 비었거나 뒤집힌 날짜는 계산하지 않는다', () => {
    expect(tripDays(dates)).toBe(3);
    expect(tripDays({ start: '2026-10-17', end: '2026-10-17' })).toBe(1);
    expect(tripDays({ start: '2026-10-31', end: '2026-11-01' })).toBe(2);
    expect(tripDays({ start: '2026-10-19', end: '2026-10-17' })).toBeNull();
    expect(tripDays({ start: '', end: '2026-10-17' })).toBeNull();
    expect(tripDays(undefined)).toBeNull();
  });

  it('기간을 당일·n박 n일로 적는다', () => {
    expect(tripLengthLabel(1)).toBe('당일');
    expect(tripLengthLabel(3)).toBe('2박 3일');
  });

  it('일차의 날짜를 달을 넘겨서도 계산한다', () => {
    expect(dayDate('2026-10-31', 1)).toBe('2026-10-31');
    expect(dayDate('2026-10-31', 2)).toBe('2026-11-01');
    expect(dayDate(undefined, 1)).toBeNull();
  });

  it('날짜만 정하면 하루 일정과 이동수단은 시안의 초기값으로 보낸다', () => {
    expect(validateConditions({ dates })).toEqual({
      ok: true,
      value: { dates, dayStart: '10:00', dayEnd: '19:00', mode: 'TRANSIT' },
    });
  });

  it('선택 항목은 입력한 것만 보내고 빈 동행은 뺀다', () => {
    const result = validateConditions({ dates, mode: 'CAR', companions: '  ', budget: 0, prefs: { tags: ['sea'] } });
    expect(result).toEqual({
      ok: true,
      value: { dates, dayStart: '10:00', dayEnd: '19:00', mode: 'CAR', budget: 0, prefs: { tags: ['sea'] } },
    });
  });

  it.each([
    ['날짜 없음', {}, 'dates'],
    ['종료일만 없음', { dates: { start: '2026-10-17', end: '' } }, 'dates'],
    ['종료일이 시작일보다 빠름', { dates: { start: '2026-10-19', end: '2026-10-17' } }, 'dates'],
    ['기간 초과', { dates: { start: '2026-10-17', end: '2026-10-20' } }, 'dates'],
    ['하루 종료가 시작보다 빠름', { dates, dayStart: '19:00', dayEnd: '10:00' }, 'hours'],
    ['시각 형식이 아님', { dates, dayStart: '' }, 'hours'],
    ['음수 예산', { dates, budget: -1 }, 'budget'],
    ['숫자가 아닌 예산', { dates, budget: Number.NaN }, 'budget'],
  ] as const)('%s이면 해당 항목 오류를 낸다', (_name, draft, field) => {
    const result = validateConditions(draft);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(Object.keys(result.errors)).toEqual([field]);
  });

  it(`${MAX_TRIP_DAYS}일 여행까지 받는다`, () => {
    expect(validateConditions({ dates }).ok).toBe(true);
  });
});
