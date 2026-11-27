import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toApiError, tripsApi } from '@/api';
import { resolveBlockPlace } from '@/api/kakaoSession';
import { paths } from '@/app/paths';
import { Banner, Button, useOptionalToast } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { BlockEditor } from '@/features/block-editor/BlockEditor';
import { WaypointSheet } from '@/features/waypoint-sheet/WaypointSheet';
import { blockRole, formatDayDate, formatDuration, legBetween, scheduleLevelViolations, tripSummary } from '@/features/itinerary/format';
import { LegText } from '@/features/itinerary/LegText';
import { AlertIcon, BackIcon, LockIcon, MapIcon, PlusIcon, UndoIcon } from '@/features/itinerary/icons';
import { useApi } from '@/hooks/useApi';
import type { Block, BlockCrowd, IsoDate, Schedule, ScheduleDay, Violation } from '@/types/api';
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
  // null 이면 이 화면에서 아직 편집하지 않았다: 서버가 알려 준 값(다른 화면에 다녀와도 유지)을 쓴다.
  const [undoState, setUndoAvailable] = useState<boolean | null>(null);
  const [mutationViolations, setMutationViolations] = useState<Violation[]>([]);
  // 방금 들어간 블록. 그 카드로 스크롤하고 잠깐 강조한다(무엇이 바뀌었는지 보이게).
  const [flashId, setFlashId] = useState<string | null>(null);
  const { showToast } = useOptionalToast();
  const addPanel = useRef<HTMLElement>(null);
  const schedule = edited ?? (loaded.status === 'success' ? loaded.data.schedule : null);
  const undoAvailable = undoState ?? (loaded.status === 'success' ? Boolean(loaded.data.canUndo) : false);
  // 고른 일차가 일정에 없으면(다시 불러온 일정 등) 첫 일차를 보여 준다.
  const day = schedule?.days.find((item) => item.dayNo === dayNo) ?? schedule?.days[0];
  // 보고 있는 날의 블록 카드에 이미 보이는 경고는 위 안내에서 뺀다(다른 날 경고는 남긴다).
  const warnings = scheduleLevelViolations([...(schedule?.violations ?? []), ...mutationViolations], day ? [day] : []);
  const notices = [...warnings.map((item) => item.cause), ...(schedule?.conflicts.map((item) => item.cause) ?? [])];
  // 카드 칩은 알림으로 읽지 않으므로, 이 날 카드에 붙은 경고 수도 요약 건수에 넣어 한 번에 알린다.
  const onCards = day?.blocks.reduce((count, block) => count + block.warnings.length, 0) ?? 0;
  const noticeCount = notices.length + onCards;

  // 추가 패널은 목록 끝에 열리므로 하단 버튼을 누른 사용자가 볼 수 있게 화면으로 끌어온다.
  useEffect(() => {
    if (adding) addPanel.current?.scrollIntoView?.({ block: 'end', behavior: 'smooth' });
  }, [adding]);

  useEffect(() => {
    if (!flashId) return undefined;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    document.getElementById(`block-${flashId}`)?.scrollIntoView?.({ block: 'center', behavior: reduce ? 'auto' : 'smooth' });
    const timer = setTimeout(() => setFlashId(null), 1600);
    return () => clearTimeout(timer);
  }, [flashId]);

  /** 요청을 보내고 성공 여부를 돌려준다. 패널은 그 패널에서 보낸 추가가 성공했을 때만 닫는다. */
  const run = async (action: Parameters<Change>[0], isUndo = false) => {
    setPending(true);
    setError(null);
    try {
      const before = schedule;
      const result = await action();
      setEdited(result.schedule);
      setMutationViolations(result.violations ?? []);
      setUndoAvailable(!isUndo);
      announce(before, result.schedule, isUndo);
      return true;
    } catch (cause) {
      setError(toApiError(cause).message);
      return false;
    } finally {
      setPending(false);
    }
  };
  /** 바뀐 내용을 알림(화면 읽기 프로그램에도 읽힘)으로 알리고, 새로 들어간 블록을 강조한다. */
  const announce = (before: Schedule | null, after: Schedule, isUndo: boolean) => {
    const beforeIds = new Set(before?.days.flatMap((d) => d.blocks.map((b) => b.id)) ?? []);
    const afterBlocks = after.days.flatMap((d) => d.blocks);
    const afterIds = new Set(afterBlocks.map((b) => b.id));
    const added = afterBlocks.find((b) => !beforeIds.has(b.id));
    const removed = before?.days.flatMap((d) => d.blocks).find((b) => !afterIds.has(b.id));
    const nameOf = (block: Block) => resolveBlockPlace(block.place)?.name ?? '장소';
    if (isUndo) showToast('직전 편집을 되돌렸어요.');
    else if (added) {
      setFlashId(added.id);
      showToast(`일정에 넣었어요: ${nameOf(added)} · 되돌리기 버튼으로 취소할 수 있어요.`);
    } else if (removed) showToast(`일정에서 뺐어요: ${nameOf(removed)} · 되돌리기 버튼으로 취소할 수 있어요.`);
    else showToast('일정을 고쳤어요.');
  };
  const change: Change = async (action, isUndo) => { await run(action, isUndo); };
  const addAndClose: Change = async (action) => { if (await run(action)) setAdding(false); };
  const slotAndClose: Change = async (action) => { if (await run(action)) setSlot(null); };

  if (!tripId) return <Banner tone="warn">여행 정보를 찾을 수 없어요.</Banner>;
  if (loaded.status === 'loading') return <p role="status" className={styles.status}>일정을 불러오는 중…</p>;
  if (loaded.status === 'error') return <Banner tone="warn">일정을 불러오지 못했어요. <Button onClick={loaded.reload}>다시 시도</Button></Banner>;

  const selectDay = (next: number) => { setDayNo(next); setSelected(null); setSlot(null); };

  return <main className={styles.page}>
    <h1 className="sr-only">코스 타임라인</h1>
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

    {schedule && schedule.days.length > 1 && <nav className={styles.days} aria-label="여행 일차">
      {schedule.days.map((item) => <button key={item.dayNo} type="button" className={styles.dayTab} aria-pressed={item.dayNo === day?.dayNo} onClick={() => selectDay(item.dayNo)}>{item.dayNo}일차</button>)}
    </nav>}

    {error && <Banner tone="warn">{error}</Banner>}
    {noticeCount > 0 && <section role="alert" className={styles.notice} aria-label="일정 확인 필요">
      <p className={styles.noticeHead}><AlertIcon /><span>일정에서 확인할 것</span><span className={styles.countChip}>확인 필요 {noticeCount}건</span></p>
      <ul>
        {notices.map((cause, index) => <li key={`${index}-${cause}`}>{cause}</li>)}
        {onCards > 0 && <li>아래 장소 카드에 표시된 {onCards}건</li>}
      </ul>
    </section>}

    {day ? <DayTimeline
      key={day.dayNo} tripId={tripId} day={day} selected={selected} slot={slot} pending={pending} flashId={flashId}
      onSelect={(id) => setSelected(selected === id ? null : id)} onSlot={(id) => setSlot(slot === id ? null : id)} onChange={change} onSlotChange={slotAndClose}
    /> : <p className={styles.empty}>표시할 일정이 없어요.</p>}

    {adding && <section ref={addPanel} className={styles.addPanel}>
      <BlockEditor tripId={tripId} dayNo={day?.dayNo ?? 1} disabled={pending} onChange={addAndClose} />
    </section>}

    <footer className={styles.bottomBar}>
      <Link to={paths.mapView(tripId)} className={styles.mapLink}><MapIcon />지도로 보기</Link>
      <Button className={styles.addButton} aria-expanded={adding} onClick={() => setAdding(!adding)}>{adding ? '추가 닫기' : '장소 추가'}</Button>
    </footer>
  </main>;
}

function DayTimeline({ tripId, day, selected, slot, pending, flashId, onSelect, onSlot, onChange, onSlotChange }: {
  tripId: string;
  day: ScheduleDay;
  selected: string | null;
  slot: string | null;
  pending: boolean;
  flashId: string | null;
  onSelect(id: string): void;
  onSlot(id: string): void;
  onChange: Change;
  onSlotChange: Change;
}) {
  // 경유지 추천 시트(UI-03)를 연 구간의 앞 블록 ID. 조기 return보다 앞에서 항상 같은 순서로 호출한다.
  const [recommendedSlot, setRecommendedSlot] = useState<string | null>(null);
  const blocks = [...day.blocks].sort((a, b) => a.seq - b.seq);
  if (blocks.length === 0) return <p className={styles.empty}>이 날은 아직 장소가 없어요. 아래 ‘장소 추가’로 담아 보세요.</p>;

  return <ol className={styles.list} aria-label={`${day.dayNo}일차 일정`}>{blocks.map((block, index) => {
    const next = blocks[index + 1];
    const leg = legBetween(day.legs, block, next);
    return <li key={block.id}>
      <BlockCard block={block} date={day.date} crowd={day.crowd.find((item) => item.blockId === block.id)} selected={selected === block.id} flash={flashId === block.id} onSelect={() => onSelect(block.id)}>
        {selected === block.id && <BlockEditor key={block.id} tripId={tripId} block={block} disabled={pending} onChange={onChange} />}
      </BlockCard>
      {next && <div className={styles.between}>
        <p className={styles.leg}>{leg ? <LegText leg={leg} /> : '이동시간 확인 필요'}</p>
        {/* 구간 진입점은 하나다. 직접 검색은 추천 시트 안에서 연다. */}
        {slot === block.id
          // 직접 찾기 편집기가 열려 있으면 같은 자리 버튼이 그것을 닫는다.
          ? <button type="button" className={styles.slotButton} aria-expanded="true" disabled={pending} onClick={() => onSlot(block.id)}>직접 찾기 닫기</button>
          : <button type="button" className={styles.slotButton} aria-haspopup="dialog" disabled={pending} onClick={() => setRecommendedSlot(block.id)}>
            <PlusIcon />사이에 들를 곳 추천받기
          </button>}
        {slot === block.id && <BlockEditor key={`slot-${block.id}`} tripId={tripId} between={{ fromBlockId: block.id, toBlockId: next.id }} disabled={pending} onChange={onSlotChange} />}
        {recommendedSlot === block.id && <WaypointSheet
          tripId={tripId} between={{ fromBlockId: block.id, toBlockId: next.id }} disabled={pending}
          fromName={resolveBlockPlace(block.place)?.name} toName={resolveBlockPlace(next.place)?.name}
          excludePlaceIds={blocks.flatMap((item) => (item.place.source === 'PUBLIC' ? [item.place.id] : []))}
          keptFixed={blocks.slice(index + 1).filter((item) => item.isFixed && item.fixedStart).map((item) => ({ name: resolveBlockPlace(item.place)?.name ?? '고정 장소', start: item.fixedStart ?? '' }))}
          onClose={() => setRecommendedSlot(null)}
          onDirectSearch={() => {
            setRecommendedSlot(null);
            if (slot !== block.id) onSlot(block.id);
          }}
          onChange={async (action) => {
            await onChange(async () => {
              const result = await action(); // 실패하면 아래 닫기를 건너뛰어 시트와 후보·오류가 남는다.
              // 요청 중 시트를 닫고 다른 구간을 열었으면 그 시트는 닫지 않는다.
              setRecommendedSlot((current) => (current === block.id ? null : current));
              return result;
            });
          }}
        />}
      </div>}
    </li>;
  })}</ol>;
}

function BlockCard({ block, date, crowd, selected, flash, onSelect, children }: {
  block: Block;
  flash: boolean;
  /** 그 블록이 있는 날. 장소 상세가 이 날의 영업시간·예상 혼잡을 보이게 넘긴다. */
  date: IsoDate;
  crowd: BlockCrowd | undefined;
  selected: boolean;
  onSelect(): void;
  children: ReactNode;
}) {
  const resolved = resolveBlockPlace(block.place);
  const kakaoLink = !resolved && block.place.source === 'KAKAO' ? block.place.placeUrl : null;
  // 핀(사용자가 담은 곳)은 실선, 필(추천으로 채운 곳)은 점선 카드로 구분한다. 고정은 이름 옆 자물쇠(지도와 같은 자리).
  const variant = block.origin === 'SUGGESTED' ? styles.cardFill : styles.cardPin;
  return <article id={`block-${block.id}`} className={`${styles.card} ${variant} ${selected ? styles.cardSelected : ''} ${flash ? styles.cardFlash : ''}`}>
    <button type="button" className={styles.cardMain} aria-pressed={selected} onClick={onSelect}>
      <span className={styles.times}>
        <span>{block.arriveAt ?? '--:--'}</span>
        <span>{block.departAt ?? '--:--'}</span>
      </span>
      <span className={styles.cardBody}>
        <span className={styles.placeName}>{resolved?.name ?? '다시 선택 필요'}{block.isFixed && <span className={styles.lock}><LockIcon /><span className="sr-only">고정</span></span>}</span>
        <span className={styles.meta}>{blockRole(block)} · 체류 {formatDuration(block.stayMin)}</span>
      </span>
    </button>
    <div className={styles.cardExtras}>
      {/* 혼잡 신호가 없는 블록도 '정보 부족'으로 표시한다(NFR-012, 지도 화면과 같음). */}
      <CrowdBadge grade={crowd?.grade ?? null} confidence={crowd?.confidence} />
      {/* 화면을 열 때 모든 칩을 읽지 않도록 알림(role=alert)은 위 요약 카드에만 둔다. */}
      {block.warnings.map((item, i) => <span className={styles.warnChip} key={i}>{item.cause}</span>)}
      {/* D6: 이번 접속에서 고르지 않은 카카오 장소는 place_url을 외부 브라우저로 연다. */}
      {block.place.source === 'PUBLIC' && <Link className={styles.placeLink} to={paths.placeDetail(block.place.id, date)} aria-label={`${block.place.name} 장소 상세 보기`}>장소 상세 보기</Link>}
      {kakaoLink && <a className={styles.placeLink} href={kakaoLink} target="_blank" rel="noopener noreferrer">카카오맵에서 장소 확인 (새 창)</a>}
    </div>
    {children}
  </article>;
}
