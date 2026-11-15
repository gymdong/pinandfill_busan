import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toApiError, tripsApi } from '@/api';
import { resolveBlockPlace } from '@/api/kakaoSession';
import { paths } from '@/app/paths';
import { Banner, Button } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { BlockEditor } from '@/features/block-editor/BlockEditor';
import { blockRole, formatDayDate, formatDuration, legBetween, legLabel, scheduleLevelViolations, tripSummary } from '@/features/itinerary/format';
import { AlertIcon, BackIcon, LockIcon, MapIcon, PlusIcon, UndoIcon } from '@/features/itinerary/icons';
import { useApi } from '@/hooks/useApi';
import type { Block, BlockCrowd, Schedule, ScheduleDay, Violation } from '@/types/api';
import styles from './TimelinePage.module.css';

export default function TimelinePage() {
  const { tripId } = useParams();
  return <TimelineTrip key={tripId} tripId={tripId} />;
}

type Change = (action: () => Promise<{ schedule: Schedule; violations?: Violation[] }>, isUndo?: boolean) => Promise<void>;

function TimelineTrip({ tripId }: { tripId: string | undefined }) {
  const fetchTrip = useCallback((signal: AbortSignal) => tripsApi.get(tripId ?? '', { signal }), [tripId]);
  const loaded = useApi(fetchTrip);
  const [edited, setEdited] = useState<Schedule | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [dayNo, setDayNo] = useState(1);
  const [slot, setSlot] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [undoAvailable, setUndoAvailable] = useState(false);
  const [mutationViolations, setMutationViolations] = useState<Violation[]>([]);
  const addPanel = useRef<HTMLElement>(null);
  const schedule = edited ?? (loaded.status === 'success' ? loaded.data.schedule : null);
  // 고른 일차가 일정에 없으면(다시 불러온 일정 등) 첫 일차를 보여 준다.
  const day = schedule?.days.find((item) => item.dayNo === dayNo) ?? schedule?.days[0];
  // 보고 있는 날의 블록 카드에 이미 보이는 경고는 위 안내에서 뺀다(다른 날 경고는 남긴다).
  const warnings = scheduleLevelViolations([...(schedule?.violations ?? []), ...mutationViolations], day ? [day] : []);
  const notices = [...warnings.map((item) => item.cause), ...(schedule?.conflicts.map((item) => item.cause) ?? [])];

  // 추가 패널은 목록 끝에 열리므로 하단 버튼을 누른 사용자가 볼 수 있게 화면으로 끌어온다.
  useEffect(() => {
    if (adding) addPanel.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' });
  }, [adding]);

  /** 요청을 보내고 성공 여부를 돌려준다. 패널은 그 패널에서 보낸 추가가 성공했을 때만 닫는다. */
  const run = async (action: Parameters<Change>[0], isUndo = false) => {
    setPending(true);
    setError(null);
    try {
      const result = await action();
      setEdited(result.schedule);
      setMutationViolations(result.violations ?? []);
      setUndoAvailable(!isUndo);
      return true;
    } catch (cause) {
      setError(toApiError(cause).message);
      return false;
    } finally {
      setPending(false);
    }
  };
  const change: Change = async (action, isUndo) => { await run(action, isUndo); };
  const addAndClose: Change = async (action) => { if (await run(action)) setAdding(false); };
  const slotAndClose: Change = async (action) => { if (await run(action)) setSlot(null); };

  if (!tripId) return <Banner tone="warn">여행 ID가 없습니다.</Banner>;
  if (loaded.status === 'loading') return <p role="status" className={styles.status}>일정을 불러오는 중…</p>;
  if (loaded.status === 'error') return <Banner tone="warn">일정을 불러오지 못했습니다. <Button onClick={loaded.reload}>다시 시도</Button></Banner>;

  const selectDay = (next: number) => { setDayNo(next); setSelected(null); setSlot(null); };

  return <main className={styles.page}>
    <h1 className={styles.srOnly}>코스 타임라인</h1>
    <header className={styles.top}>
      <Link to={paths.tripStart()} className={styles.iconButton} aria-label="여행 시작으로"><BackIcon /></Link>
      <div className={styles.titles}>
        <p className={styles.tripLine}>{tripSummary(loaded.data.trip)}</p>
        <h2 className={styles.dayTitle}>{day ? `${day.dayNo}일차 · ${formatDayDate(day.date)}` : '일정 없음'}</h2>
      </div>
      <button type="button" className={styles.iconButton} aria-label="직전 편집 되돌리기" disabled={!undoAvailable || pending} onClick={() => change(() => tripsApi.undo(tripId), true)}>
        <UndoIcon />
      </button>
    </header>

    {schedule && schedule.days.length > 0 && <nav className={styles.days} aria-label="여행 일차">
      {schedule.days.map((item) => <button key={item.dayNo} type="button" className={styles.dayTab} aria-pressed={item.dayNo === day?.dayNo} onClick={() => selectDay(item.dayNo)}>{item.dayNo}일차</button>)}
    </nav>}

    {error && <Banner tone="warn">{error}</Banner>}
    {notices.length > 0 && <section role="alert" className={styles.notice} aria-label="일정 확인 필요">
      <p className={styles.noticeHead}><AlertIcon /><span>일정에서 확인할 것</span><span className={styles.countChip}>확인 필요 {notices.length}건</span></p>
      <ul>{notices.map((cause, index) => <li key={`${index}-${cause}`}>{cause}</li>)}</ul>
    </section>}

    {day ? <DayTimeline
      key={day.dayNo} tripId={tripId} day={day} selected={selected} slot={slot} pending={pending}
      onSelect={(id) => setSelected(selected === id ? null : id)} onSlot={(id) => setSlot(slot === id ? null : id)} onChange={change} onSlotChange={slotAndClose}
    /> : <p className={styles.empty}>표시할 일정이 없습니다.</p>}

    {adding && <section ref={addPanel} className={styles.addPanel}>
      <BlockEditor tripId={tripId} dayNo={day?.dayNo ?? 1} disabled={pending} onChange={addAndClose} />
    </section>}

    <footer className={styles.bottomBar}>
      <Link to={paths.mapView(tripId)} className={styles.mapLink}><MapIcon />지도로 보기</Link>
      <Button className={styles.addButton} aria-expanded={adding} onClick={() => setAdding(!adding)}>{adding ? '추가 닫기' : '장소 추가'}</Button>
    </footer>
  </main>;
}

function DayTimeline({ tripId, day, selected, slot, pending, onSelect, onSlot, onChange, onSlotChange }: {
  tripId: string;
  day: ScheduleDay;
  selected: string | null;
  slot: string | null;
  pending: boolean;
  onSelect(id: string): void;
  onSlot(id: string): void;
  onChange: Change;
  onSlotChange: Change;
}) {
  const blocks = [...day.blocks].sort((a, b) => a.seq - b.seq);
  if (blocks.length === 0) return <p className={styles.empty}>이 날은 아직 장소가 없어요. 아래 ‘장소 추가’로 담아 보세요.</p>;

  return <ol className={styles.list} aria-label={`${day.dayNo}일차 일정`}>{blocks.map((block, index) => {
    const next = blocks[index + 1];
    const leg = legBetween(day.legs, block, next);
    return <li key={block.id}>
      <BlockCard block={block} crowd={day.crowd.find((item) => item.blockId === block.id)} selected={selected === block.id} onSelect={() => onSelect(block.id)}>
        {selected === block.id && <BlockEditor key={block.id} tripId={tripId} block={block} disabled={pending} onChange={onChange} />}
      </BlockCard>
      {next && <div className={styles.between}>
        <p className={styles.leg}>{leg ? legLabel(leg) : '이동시간 확인 필요'}</p>
        <button type="button" className={styles.slotButton} aria-expanded={slot === block.id} onClick={() => onSlot(block.id)}>
          <PlusIcon />사이에 들를 곳 찾기
        </button>
        {slot === block.id && <BlockEditor key={`slot-${block.id}`} tripId={tripId} between={{ fromBlockId: block.id, toBlockId: next.id }} disabled={pending} onChange={onSlotChange} />}
      </div>}
    </li>;
  })}</ol>;
}

function BlockCard({ block, crowd, selected, onSelect, children }: {
  block: Block;
  crowd: BlockCrowd | undefined;
  selected: boolean;
  onSelect(): void;
  children: ReactNode;
}) {
  const resolved = resolveBlockPlace(block.place);
  const kakaoLink = !resolved && block.place.source === 'KAKAO' ? block.place.placeUrl : null;
  return <article className={`${styles.card} ${selected ? styles.cardSelected : ''}`}>
    <button type="button" className={styles.cardMain} aria-pressed={selected} onClick={onSelect}>
      <span className={styles.times}>
        <span>{block.arriveAt ?? '--:--'}</span>
        <span>{block.departAt ?? '--:--'}</span>
      </span>
      <span className={styles.cardBody}>
        <span className={styles.placeName}>{resolved?.name ?? '다시 선택 필요'}</span>
        <span className={styles.meta}>{blockRole(block)} · 체류 {formatDuration(block.stayMin)}</span>
      </span>
      {block.isFixed && <span className={styles.lock}><LockIcon /><span className={styles.srOnly}>고정</span></span>}
    </button>
    <div className={styles.cardExtras}>
      {/* 혼잡 신호가 없는 블록도 '정보 부족'으로 표시한다(NFR-012, 지도 화면과 같음). */}
      <CrowdBadge grade={crowd?.grade ?? null} confidence={crowd?.confidence} />
      {/* 화면을 열 때 모든 칩을 읽지 않도록 알림(role=alert)은 위 요약 카드에만 둔다. */}
      {block.warnings.map((item, i) => <span className={styles.warnChip} key={i}>{item.cause}</span>)}
      {/* D6: 이번 접속에서 고르지 않은 카카오 장소는 place_url을 외부 브라우저로 연다. */}
      {kakaoLink && <a className={styles.placeLink} href={kakaoLink} target="_blank" rel="noopener noreferrer">카카오맵에서 장소 확인 (새 창)</a>}
    </div>
    {children}
  </article>;
}
