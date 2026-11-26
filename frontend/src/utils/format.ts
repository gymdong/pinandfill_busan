const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'];

/** 90 → '1시간 30분' */
export function formatDuration(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest}분`;
  return rest === 0 ? `${hours}시간` : `${hours}시간 ${rest}분`;
}

/** '2026-10-17' → '10월 17일 (토)'. 시간대 영향을 받지 않도록 문자열을 그대로 나눠 계산한다. */
export function formatDate(isoDate: string): string {
  const [year = 0, month = 1, day = 1] = isoDate.split('-').map(Number);
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  return `${month}월 ${day}일 (${weekday})`;
}

const KST_PARTS = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul',
  month: 'numeric',
  day: 'numeric',
  weekday: 'short',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

/** ISO 일시 → 한국 시각 '10월 17일 (토) 05:00'. 보는 기기의 시간대와 관계없이 KST로 고정한다. */
export function formatDateTime(isoDateTime: string): string {
  const parts = Object.fromEntries(
    KST_PARTS.formatToParts(new Date(isoDateTime)).map((part) => [part.type, part.value]),
  ) as Partial<Record<Intl.DateTimeFormatPartTypes, string>>;
  return `${parts.month}월 ${parts.day}일 (${parts.weekday}) ${parts.hour}:${parts.minute}`;
}
