import { useState } from 'react';
import { Link } from 'react-router-dom';
import { paths } from '@/app/paths';
import { formatDayDate, tripSummary } from '@/features/itinerary/format';
import { forgetTrip, recentTrips } from '@/store/recentTrips';
import styles from './RecentTrips.module.css';

/** 비회원 임시 저장(FR-011): 이 브라우저에서 연 일정을 다시 연다. 서버가 재시작되면 열리지 않을 수 있다. */
export function RecentTrips() {
  const [items, setItems] = useState(recentTrips);
  if (items.length === 0) return null;
  return <section className={styles.section} aria-labelledby="recent-trips-title">
    <h2 id="recent-trips-title" className={styles.title}>이 기기에서 본 일정</h2>
    <ul className={styles.list}>
      {items.map((item) => <li key={item.id} className={styles.item}>
        <Link className={styles.link} to={paths.timeline(item.id)}>
          <span>{tripSummary(item)}</span>
          <span className={styles.date}>{formatDayDate(item.dates.start)}</span>
        </Link>
        <button type="button" className={styles.forget} aria-label={`${formatDayDate(item.dates.start)} 일정 목록에서 지우기`} onClick={() => { forgetTrip(item.id); setItems(recentTrips()); }}>지우기</button>
      </li>)}
    </ul>
  </section>;
}
