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
