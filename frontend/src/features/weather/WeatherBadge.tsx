import type { TripWeatherBlock } from '@/types/api';
import styles from './WeatherBadge.module.css';

function issued(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat('ko-KR', { month: 'numeric', day: 'numeric', hour: 'numeric', timeZone: 'Asia/Seoul' }).format(date);
}

/** 블록 시각의 예보(FR-013). 항상 '예보' 라벨과 발표 시각을 붙인다. 예보가 없으면 '예보 없음'. */
export function WeatherBadge({ weather }: { weather: TripWeatherBlock | undefined | null }) {
  if (!weather) return <span className={`${styles.badge} ${styles.none}`}>예보 없음</span>;
  const { forecast } = weather;
  const parts: string[] = [];
  if (weather.scope === 'SHORT') {
    const sky = forecast.pty && forecast.pty !== '없음' ? forecast.pty : forecast.sky;
    if (sky) parts.push(sky);
    if (forecast.temp !== null) parts.push(`${forecast.temp}°`);
    if (forecast.pop !== null) parts.push(`강수 ${forecast.pop}%`);
  } else {
    if (forecast.sky) parts.push(forecast.sky);
    if (forecast.pop !== null) parts.push(`강수 ${forecast.pop}%`);
    if (forecast.tempMin != null && forecast.tempMax != null) parts.push(`${forecast.tempMin}~${forecast.tempMax}°`);
  }
  const label = weather.scope === 'SHORT' ? '예보' : '예보(일 단위)';
  const when = issued(weather.issuedAt);
  return <span className={`${styles.badge} ${forecast.rain ? styles.rain : ''}`}>
    <span className={styles.label}>{label}</span> {parts.join(' · ') || '정보 없음'}
    {forecast.rain && <span className="sr-only">, 비 예보</span>}
    {when && <span className="sr-only">, 기상청 {when} 발표</span>}
  </span>;
}
