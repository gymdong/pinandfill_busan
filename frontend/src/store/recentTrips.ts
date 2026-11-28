import type { Trip } from '@/types/api';

/**
 * 비회원 임시 저장(FR-011): 이 브라우저에서 연 일정 몇 개를 기억한다.
 * 여행 ID 와 화면 요약(날짜·이동수단)만 남기고, 장소·좌표는 저장하지 않는다(NFR-006).
 * 저장이 막혀 있으면(사생활 보호 모드 등) 조용히 건너뛴다.
 */
const KEY = 'pinandfill:recent-trips';
const LIMIT = 5;

export interface RecentTrip {
  id: string;
  dates: Trip['dates'];
  mode: Trip['mode'];
  openedAt: string;
}

export function recentTrips(): RecentTrip[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(value) ? (value as RecentTrip[]).filter((item) => typeof item?.id === 'string').slice(0, LIMIT) : [];
  } catch {
    return [];
  }
}

export function rememberTrip(id: string, trip: Pick<Trip, 'dates' | 'mode'>) {
  const entry: RecentTrip = { id, dates: trip.dates, mode: trip.mode, openedAt: new Date().toISOString() };
  try {
    localStorage.setItem(KEY, JSON.stringify([entry, ...recentTrips().filter((item) => item.id !== id)].slice(0, LIMIT)));
  } catch {
    /* 저장 불가: 기억하지 않는다 */
  }
}

export function forgetTrip(id: string) {
  try {
    localStorage.setItem(KEY, JSON.stringify(recentTrips().filter((item) => item.id !== id)));
  } catch {
    /* 저장 불가 */
  }
}
