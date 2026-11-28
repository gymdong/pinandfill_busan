import { useCallback, useState } from 'react';
import { useParams } from 'react-router-dom';
import { accountApi, resolveBlockPlace, toApiError } from '@/api';
import { Banner, Button } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { blockRole, formatDayDate, formatDuration, legBetween, tripSummary } from '@/features/itinerary/format';
import { LegText } from '@/features/itinerary/LegText';
import { LockIcon } from '@/features/itinerary/icons';
import { useApi } from '@/hooks/useApi';
import timeline from '@/pages/timeline/TimelinePage.module.css';
import styles from './SharedTripPage.module.css';

/**
 * 공유 일정 열람(FR-011, API-020). 읽기 전용: 편집·경유지·플랜 B·되돌리기를 두지 않는다.
 * 카드 모양은 타임라인과 같다(핀 실선·필 점선, 고정 자물쇠, 예상 혼잡 배지).
 */
export default function SharedTripPage() {
  const { token = '' } = useParams();
  const fetchShared = useCallback((signal: AbortSignal) => accountApi.getSharedTrip(token, { signal }), [token]);
  const loaded = useApi(fetchShared);
  const [dayNo, setDayNo] = useState(1);

  if (loaded.status === 'loading') return <p role="status" className={timeline.status}>공유받은 일정을 불러오는 중…</p>;
  if (loaded.status === 'error') {
    const error = toApiError(loaded.error);
    return <main className={timeline.page}>
      <h1 className={styles.title}>공유 일정</h1>
      {error.status === 404
        ? <Banner tone="warn">링크가 없거나 만료되었어요. 일정을 공유한 사람에게 새 링크를 받아 주세요.</Banner>
        : <Banner tone="warn">일정을 불러오지 못했어요. <Button onClick={loaded.reload}>다시 시도</Button></Banner>}
    </main>;
  }

  const { trip, schedule } = loaded.data;
  const day = schedule.days.find((item) => item.dayNo === dayNo) ?? schedule.days[0];
  const blocks = [...(day?.blocks ?? [])].sort((a, b) => a.seq - b.seq);

  return <main className={timeline.page}>
    <header className={styles.header}>
      <p className={styles.badge}>공유받은 일정 · 보기 전용</p>
      <h1 className={styles.title}>{tripSummary(trip)}</h1>
      <p className={timeline.tripLine}>{day ? `${day.dayNo}일차 · ${formatDayDate(day.date)}` : '일정 없음'} · {trip.dayStart}–{trip.dayEnd}</p>
    </header>

    {schedule.days.length > 1 && <nav className={timeline.days} aria-label="여행 일차">
      {schedule.days.map((item) => <button key={item.dayNo} type="button" className={timeline.dayTab} aria-pressed={item.dayNo === day?.dayNo} onClick={() => setDayNo(item.dayNo)}>{item.dayNo}일차</button>)}
    </nav>}

    {blocks.length === 0 ? <p className={timeline.empty}>이 날은 장소가 없어요.</p> : <ol className={timeline.list} aria-label={`${day?.dayNo ?? 1}일차 일정`}>
      {blocks.map((block, index) => {
        const next = blocks[index + 1];
        const leg = day ? legBetween(day.legs, block, next) : undefined;
        const crowd = day?.crowd.find((item) => item.blockId === block.id);
        const resolved = resolveBlockPlace(block.place);
        const kakaoLink = !resolved && block.place.source === 'KAKAO' ? block.place.placeUrl : null;
        return <li key={block.id}>
          <article className={`${timeline.card} ${block.origin === 'SUGGESTED' ? timeline.cardFill : timeline.cardPin}`}>
            <div className={styles.cardMain}>
              <span className={timeline.times}><span>{block.arriveAt ?? '--:--'}</span><span>{block.departAt ?? '--:--'}</span></span>
              <span className={timeline.cardBody}>
                {/* 카카오 장소명은 저장하지 않는다(D6). 받은 사람에게는 카카오맵 링크만 보인다. */}
                <span className={timeline.placeName}>{resolved?.name ?? '카카오맵 장소'}{block.isFixed && <span className={timeline.lock}><LockIcon /><span className="sr-only">고정</span></span>}</span>
                <span className={timeline.meta}>{blockRole(block)} · 체류 {formatDuration(block.stayMin)}</span>
              </span>
            </div>
            <div className={timeline.cardExtras}>
              <CrowdBadge grade={crowd?.grade ?? null} confidence={crowd?.confidence} />
              {kakaoLink && <a className={timeline.placeLink} href={kakaoLink} target="_blank" rel="noopener noreferrer">카카오맵에서 장소 확인 (새 창)</a>}
            </div>
          </article>
          {next && <div className={timeline.between}><p className={timeline.leg}>{leg ? <LegText leg={leg} /> : '이동시간 확인 필요'}</p></div>}
        </li>;
      })}
    </ol>}
    <p className={styles.footnote}>예상 혼잡은 실시간이 아니라 통계로 계산한 예상이에요. 이동시간의 ≈ 표시는 추정값이에요.</p>
  </main>;
}
