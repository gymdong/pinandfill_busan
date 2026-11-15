import type { Block, IsoDate, Leg, TransportMode, Trip } from '@/types/api';

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'] as const;

const MODE_LABEL: Record<TransportMode, string> = { TRANSIT: '대중교통', CAR: '자동차', WALK: '도보' };

export function modeLabel(mode: TransportMode): string {
  return MODE_LABEL[mode];
}

/** '2026-10-17' → '10월 17일 (토)'. 시간대 영향을 받지 않도록 UTC 기준으로 요일을 계산한다. */
export function formatDayDate(date: IsoDate): string {
  const [year, month, day] = date.split('-').map(Number);
  if (!year || !month || !day) return date;
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  return `${month}월 ${day}일 (${weekday})`;
}

/** 여행 기간과 이동수단. 예: '부산 2박 3일 · 대중교통' */
export function tripSummary(trip: Trip): string {
  const start = Date.parse(`${trip.dates.start}T00:00:00Z`);
  const end = Date.parse(`${trip.dates.end}T00:00:00Z`);
  const days = Number.isNaN(start) || Number.isNaN(end) ? 1 : Math.round((end - start) / 86_400_000) + 1;
  const length = days > 1 ? `${days - 1}박 ${days}일` : '당일';
  return `부산 ${length} · ${modeLabel(trip.mode)}`;
}

/** 90 → '1시간 30분', 40 → '40분', 120 → '2시간' */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest}분`;
  return rest === 0 ? `${hours}시간` : `${hours}시간 ${rest}분`;
}

/** 구간 표시. 예: '대중교통 · 25분', '대중교통 · 30분 (추정)', '대중교통 · 이동시간 확인 필요' */
export function legLabel(leg: Leg): string {
  const duration = leg.durationMin === null ? '이동시간 확인 필요' : `${leg.durationMin}분`;
  return `${modeLabel(leg.mode)} · ${duration}${leg.source === 'ESTIMATED' ? ' (추정)' : ''}`;
}

/** 블록 역할. 사용자가 담은 곳은 핵심지, 제안으로 들어온 곳은 경유지다. */
export function blockRole(block: Block): string {
  return block.origin === 'SUGGESTED' ? '경유지' : '핵심지';
}

export function legBetween(legs: Leg[], from: Block | undefined, to: Block | undefined): Leg | undefined {
  if (!from || !to) return undefined;
  return legs.find((leg) => leg.fromBlockId === from.id && leg.toBlockId === to.id);
}
