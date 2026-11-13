import { useCallback, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toApiError, tripsApi } from '@/api';
import { resolveBlockPlace } from '@/api/kakaoSession';
import { paths } from '@/app/paths';
import { Banner, Button } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { BlockEditor } from '@/features/block-editor/BlockEditor';
import { useApi } from '@/hooks/useApi';
import type { Schedule, Violation } from '@/types/api';
import styles from './TimelinePage.module.css';

export default function TimelinePage() {
  const { tripId } = useParams();
  return <TimelineTrip key={tripId} tripId={tripId} />;
}

function TimelineTrip({ tripId }: { tripId: string | undefined }) {
  const fetchTrip = useCallback((signal: AbortSignal) => tripsApi.get(tripId ?? '', { signal }), [tripId]);
  const loaded = useApi(fetchTrip);
  const [edited, setEdited] = useState<Schedule | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [addDayNo, setAddDayNo] = useState(1);
  const [slot, setSlot] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [undoAvailable, setUndoAvailable] = useState(false);
  const [mutationViolations, setMutationViolations] = useState<Violation[]>([]);
  const schedule = edited ?? (loaded.status === 'success' ? loaded.data.schedule : null);
  // 고른 일차가 일정에 없으면(다시 불러온 일정 등) 첫 일차로 보정한다.
  const addDay = schedule?.days.some((day) => day.dayNo === addDayNo) ? addDayNo : (schedule?.days[0]?.dayNo ?? 1);
  const warnings = [...new Map(
    [...(schedule?.violations ?? []), ...mutationViolations].map((item) => [`${item.type}\u0000${item.cause}`, item]),
  ).values()];

  async function change(action: () => Promise<{ schedule: Schedule; violations?: Violation[] }>, isUndo = false) {
    setPending(true);
    setError(null);
    try {
      const result = await action();
      setEdited(result.schedule);
      setMutationViolations(result.violations ?? []);
      setUndoAvailable(!isUndo);
    } catch (cause) {
      setError(toApiError(cause).message);
    } finally {
      setPending(false);
    }
  }

  if (!tripId) return <Banner tone="warn">여행 ID가 없습니다.</Banner>;
  if (loaded.status === 'loading') return <p role="status">일정을 불러오는 중…</p>;
  if (loaded.status === 'error') return <Banner tone="warn">일정을 불러오지 못했습니다. <Button onClick={loaded.reload}>다시 시도</Button></Banner>;

  return <main className={styles.page}>
    <header className={styles.header}><h1>코스 타임라인</h1><Link to={paths.mapView(tripId)}>지도 보기</Link></header>
    {error && <Banner tone="warn">{error}</Banner>}
    {warnings.map((item) => <Banner key={`${item.type}\u0000${item.cause}`} tone="warn">{item.cause}</Banner>)}
    {schedule?.conflicts.map((item, i) => <Banner key={i} tone="warn">{item.cause}</Banner>)}
    <Button variant="outline" disabled={!undoAvailable || pending} onClick={() => change(() => tripsApi.undo(tripId), true)}>직전 편집 되돌리기</Button>
    {schedule?.days.map((day) => {
      const blocks = [...day.blocks].sort((a, b) => a.seq - b.seq);
      const selectedBlock = blocks.find((block) => block.id === selected);
      return <section className={styles.day} aria-label={`${day.dayNo}일차`} key={day.dayNo}>
        <h2>{day.dayNo}일차 · {day.date}</h2>
        <ol className={styles.list}>{blocks.map((block, index) => {
          const resolved = resolveBlockPlace(block.place);
          const name = resolved?.name ?? '다시 선택 필요';
          const crowd = day.crowd.find((item) => item.blockId === block.id);
          const leg = day.legs.find((item) => item.fromBlockId === block.id && item.toBlockId === blocks[index + 1]?.id);
          return <li key={block.id}>
            <button className={styles.block} aria-pressed={selected === block.id} onClick={() => setSelected(selected === block.id ? null : block.id)}>
              <strong>{name}</strong><span>{block.arriveAt ?? '시각 미정'} – {block.departAt ?? '시각 미정'} · 체류 {block.stayMin}분 {block.isFixed && '· 고정'}</span>
            </button>
            {/* D6: 이번 접속에서 고르지 않은 카카오 장소는 place_url을 외부 브라우저로 연다. */}
            {!resolved && block.place.source === 'KAKAO' && <a className={styles.placeLink} href={block.place.placeUrl} target="_blank" rel="noopener noreferrer">카카오맵에서 장소 확인 (새 창)</a>}
            {crowd && <CrowdBadge grade={crowd.grade} confidence={crowd.confidence} />}
            {block.warnings.map((item, i) => <p role="alert" key={i}>{item.cause}</p>)}
            {leg && <p className={styles.leg}>{leg.mode === 'TRANSIT' ? '대중교통' : leg.mode === 'WALK' ? '도보' : '자동차'} · {leg.durationMin === null ? '이동시간 확인 필요' : `${leg.durationMin}분`}{leg.source === 'ESTIMATED' && ' (추정)'}</p>}
            {blocks[index + 1] && <>
              <Button variant="ghost" onClick={() => setSlot(slot === block.id ? null : block.id)}>이 구간에 경유지 추가</Button>
              {slot === block.id && <BlockEditor key={`slot-${block.id}`} tripId={tripId} between={{ fromBlockId: block.id, toBlockId: blocks[index + 1]!.id }} disabled={pending} onChange={change} />}
            </>}
          </li>;
        })}</ol>
        {selectedBlock && <BlockEditor key={selectedBlock.id} tripId={tripId} block={selectedBlock} disabled={pending} onChange={change} />}
      </section>;
    })}
    {!schedule?.days.length && <p>표시할 일정이 없습니다.</p>}
    {schedule && schedule.days.length > 1 && <label>추가할 일차 <select value={addDay} onChange={(event) => setAddDayNo(Number(event.target.value))}>{schedule.days.map((day) => <option key={day.dayNo} value={day.dayNo}>{day.dayNo}일차</option>)}</select></label>}
    <BlockEditor tripId={tripId} dayNo={addDay} disabled={pending} onChange={change} />
  </main>;
}
