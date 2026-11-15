import { describe, expect, it } from 'vitest';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import {
  formatDayDate,
  formatDuration,
  legBetween,
  legLabel,
  scheduleLevelViolations,
  tripSummary,
} from '@/features/itinerary/format';

const day = schedule.days[0]!;
const leg = day.legs[0]!;

describe('일정 표기', () => {
  it('날짜에 요일을 붙인다', () => {
    expect(formatDayDate('2026-10-17')).toBe('10월 17일 (토)');
    expect(formatDayDate('2026-11-01')).toBe('11월 1일 (일)');
    expect(formatDayDate('잘못된 값')).toBe('잘못된 값');
  });

  it('여행 기간을 박·일로, 하루 여행은 당일로 쓴다', () => {
    expect(tripSummary(trip)).toBe('부산 2박 3일 · 대중교통');
    expect(tripSummary({ ...trip, dates: { start: '2026-10-17', end: '2026-10-17' }, mode: 'CAR' })).toBe('부산 당일 · 자동차');
  });

  it('체류시간을 시간·분으로 쓴다', () => {
    expect(formatDuration(40)).toBe('40분');
    expect(formatDuration(60)).toBe('1시간');
    expect(formatDuration(90)).toBe('1시간 30분');
    expect(formatDuration(0)).toBe('0분');
  });

  it('구간의 이동시간이 없거나 추정이면 그대로 알린다', () => {
    expect(legLabel({ ...leg, mode: 'WALK', durationMin: 12, source: 'TMAP' })).toBe('도보 · 12분');
    expect(legLabel({ ...leg, durationMin: 30, source: 'ESTIMATED' })).toBe('대중교통 · 30분 (추정)');
    expect(legLabel({ ...leg, durationMin: null, source: 'ESTIMATED' })).toBe('대중교통 · 이동시간 확인 필요 (추정)');
  });

  it('인접한 두 블록 사이 구간만 찾는다', () => {
    const [a, b, c] = day.blocks;
    expect(legBetween(day.legs, a, b)?.fromBlockId).toBe(a!.id);
    expect(legBetween(day.legs, a, c)).toBeUndefined();
    expect(legBetween(day.legs, undefined, a)).toBeUndefined();
  });

  it('보이는 날의 블록 카드에 있는 경고는 일정 안내에서 빼고, 같은 경고는 한 번만 남긴다', () => {
    const onBlock = day.blocks.flatMap((block) => block.warnings)[0]!;
    const other = { type: 'HOURS', cause: '일정 전체 경고' };
    expect(scheduleLevelViolations([onBlock, other, other], [day])).toEqual([other]);
    expect(scheduleLevelViolations([onBlock], [])).toEqual([onBlock]);
  });
});
