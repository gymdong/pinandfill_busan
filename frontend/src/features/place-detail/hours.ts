import type { DayType, IsoDate, PlaceHours } from '@/types/api';

const DAY_TYPES: DayType[] = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'];
export const WEEK_ORDER: DayType[] = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN', 'HOLIDAY'];
export const DAY_LABEL: Record<DayType, string> = {
  MON: '월', TUE: '화', WED: '수', THU: '목', FRI: '금', SAT: '토', SUN: '일', HOLIDAY: '공휴일',
};

/**
 * '2026-10-17' → 'SAT'. 형식이 다르거나 달력에 없는 날짜('2026-02-30')면 null.
 * 화면에서는 공휴일 여부를 알 수 없어 요일로만 본다. 그래서 'HOLIDAY'는 돌려주지 않으며,
 * 공휴일 영업시간은 요일별 표에만 보이고 그날 영업시간을 고르는 데는 쓰이지 않는다.
 */
export function dayTypeOf(date: IsoDate | null | undefined): DayType | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  const time = Date.parse(`${date}T00:00:00Z`);
  if (Number.isNaN(time)) return null;
  const parsed = new Date(time);
  // 엔진에 따라 없는 날짜를 다음 달로 넘겨 읽을 수 있어, 다시 적은 값이 입력과 같을 때만 받는다.
  return parsed.toISOString().slice(0, 10) === date ? DAY_TYPES[parsed.getUTCDay()]! : null;
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
