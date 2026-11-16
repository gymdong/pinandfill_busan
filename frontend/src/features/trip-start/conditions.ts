import type { IsoDate, LocalTime, TransportMode, TripConditions } from '@/types/api';

/**
 * 서비스 대상이 부산 1~3일 여행이라(README) 그보다 긴 기간은 받지 않는다.
 * @provisional SRS에 상한이 명시되어 있지 않아 API-002 검증과 함께 확정한다.
 */
export const MAX_TRIP_DAYS = 3;

/** 시안(UI-01)의 초기 표시값. 사용자가 바꿀 수 있다. */
export const DEFAULT_CONDITIONS = { dayStart: '10:00', dayEnd: '19:00', mode: 'TRANSIT' } as const satisfies Pick<
  TripConditions,
  'dayStart' | 'dayEnd' | 'mode'
>;

export const MODE_OPTIONS: { mode: TransportMode; label: string }[] = [
  { mode: 'TRANSIT', label: '대중교통' },
  { mode: 'CAR', label: '자동차' },
  { mode: 'WALK', label: '도보 위주' },
];

export type ConditionField = 'dates' | 'hours' | 'budget';
export type ConditionErrors = Partial<Record<ConditionField, string>>;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const LOCAL_TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

export function isLocalTime(value: string | undefined | null): value is LocalTime {
  return typeof value === 'string' && LOCAL_TIME.test(value);
}

function dayNumber(date: IsoDate | undefined): number | null {
  if (!date || !ISO_DATE.test(date)) return null;
  const time = Date.parse(`${date}T00:00:00Z`);
  return Number.isNaN(time) ? null : Math.round(time / 86_400_000);
}

/** 여행 일수. 날짜가 비었거나 순서가 뒤집히면 null */
export function tripDays(dates: Partial<TripConditions['dates']> | undefined): number | null {
  const start = dayNumber(dates?.start);
  const end = dayNumber(dates?.end);
  if (start === null || end === null || end < start) return null;
  return end - start + 1;
}

/** 여행 n일차의 날짜. 시작일이 없거나 형식이 다르면 null */
export function dayDate(start: IsoDate | undefined, dayNo: number): IsoDate | null {
  const first = dayNumber(start);
  return first === null ? null : new Date((first + dayNo - 1) * 86_400_000).toISOString().slice(0, 10);
}

/** 1 → '당일', 3 → '2박 3일' */
export function tripLengthLabel(days: number): string {
  return days === 1 ? '당일' : `${days - 1}박 ${days}일`;
}

export type ConditionsResult =
  | { ok: true; value: TripConditions }
  | { ok: false; errors: ConditionErrors };

/** 입력 중인 조건을 API-002 요청으로 바꾼다. 빈 선택 항목은 보내지 않는다. */
export function validateConditions(draft: Partial<TripConditions>): ConditionsResult {
  const errors: ConditionErrors = {};
  const { dates, dayStart, dayEnd, mode } = { ...DEFAULT_CONDITIONS, ...draft };

  const days = tripDays(dates);
  if (!dates?.start || !dates.end) errors.dates = '여행 날짜를 정해 주세요.';
  else if (days === null) errors.dates = '종료일이 시작일보다 빠를 수 없어요.';
  else if (days > MAX_TRIP_DAYS) errors.dates = `여행 기간은 ${MAX_TRIP_DAYS}일까지 정할 수 있어요.`;

  if (!isLocalTime(dayStart) || !isLocalTime(dayEnd)) errors.hours = '하루 일정의 시작·종료 시각을 정해 주세요.';
  else if (dayStart >= dayEnd) errors.hours = '하루 종료 시각은 시작 시각보다 늦어야 해요.';

  const budget = draft.budget;
  if (budget !== undefined && (!Number.isInteger(budget) || budget < 0)) errors.budget = '예산은 0 이상의 숫자로 적어 주세요.';

  if (Object.keys(errors).length > 0) return { ok: false, errors };

  const companions = draft.companions?.trim();
  return {
    ok: true,
    value: {
      dates: { start: dates!.start, end: dates!.end },
      dayStart,
      dayEnd,
      mode,
      ...(companions ? { companions } : {}),
      ...(draft.prefs ? { prefs: draft.prefs } : {}),
      ...(budget !== undefined ? { budget } : {}),
      ...(draft.startPlaceId ? { startPlaceId: draft.startPlaceId } : {}),
      ...(draft.endPlaceId ? { endPlaceId: draft.endPlaceId } : {}),
    },
  };
}
