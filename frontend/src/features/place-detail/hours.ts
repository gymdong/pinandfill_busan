import type { DayType, IsoDate, PlaceHours } from '@/types/api';

const DAY_TYPES: DayType[] = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
export const WEEK_ORDER: DayType[] = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN', 'HOLIDAY'];
export const DAY_LABEL: Record<DayType, string> = {
  MON: '월', TUE: '화', WED: '수', THU: '목', FRI: '금', SAT: '토', SUN: '일', HOLIDAY: '공휴일',
};

/** '2026-10-17' → 'SAT'. 형식이 다르면 null. 공휴일 여부는 화면에서 알 수 없어 요일로만 본다. */
export function dayTypeOf(date: IsoDate | null | undefined): DayType | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const time = Date.parse(`${date}T00:00:00Z`);
  return Number.isNaN(time) ? null : DAY_TYPES[new Date(time).getUTCDay()]!;
}

export type HoursStatus =
  | { kind: 'open'; text: string }
  | { kind: 'closed'; text: string }
  /** 영업시간 데이터가 없거나 비어 있다. 값을 지어내지 않고 '확인 필요'로 표시한다(NFR-012). */
  | { kind: 'unknown'; text: string };

/** 하루치 영업시간 표시. 휴게시간이 있으면 함께 적는다. */
export function describeHours(hours: PlaceHours | undefined): HoursStatus {
  if (!hours) return { kind: 'unknown', text: '영업시간 확인 필요' };
  if (hours.isClosed) return { kind: 'closed', text: '휴무' };
  if (!hours.openTime || !hours.closeTime) return { kind: 'unknown', text: '영업시간 확인 필요' };
  const rest = hours.breakStart && hours.breakEnd ? ` (휴게 ${hours.breakStart} – ${hours.breakEnd})` : '';
  return { kind: 'open', text: `${hours.openTime} – ${hours.closeTime}${rest}` };
}

export function hoursFor(all: PlaceHours[], dayType: DayType | null): PlaceHours | undefined {
  return dayType ? all.find((item) => item.dayType === dayType) : undefined;
}
