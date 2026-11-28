import { beforeEach, describe, expect, it } from 'vitest';
import { forgetTrip, recentTrips, rememberTrip } from '@/store/recentTrips';

const KEY = 'pinandfill:recent-trips';

beforeEach(() => localStorage.clear());

describe('이 기기에서 본 일정(FR-011 비회원 임시 저장)', () => {
  it('최근 순으로 5개까지 기억하고 지울 수 있다', () => {
    for (const n of [1, 2, 3, 4, 5, 6]) rememberTrip(`t${n}`, { dates: { start: '2026-12-05', end: '2026-12-05' }, mode: 'TRANSIT' });
    rememberTrip('t3', { dates: { start: '2026-12-05', end: '2026-12-06' }, mode: 'WALK' });
    expect(recentTrips().map((item) => item.id)).toEqual(['t3', 't6', 't5', 't4', 't2']);
    forgetTrip('t6');
    expect(recentTrips().map((item) => item.id)).toEqual(['t3', 't5', 't4', 't2']);
  });

  it('모양이 맞지 않는 저장값은 버린다', () => {
    localStorage.setItem(KEY, JSON.stringify([{ id: 'old' }, { id: 'x', dates: { start: '2026-12-05', end: '2026-12-05' }, mode: 'BOAT' }, null, 'junk']));
    expect(recentTrips()).toEqual([]);
    localStorage.setItem(KEY, '{not json');
    expect(recentTrips()).toEqual([]);
  });
});
