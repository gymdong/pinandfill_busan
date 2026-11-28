import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toApiError, tripsApi } from '@/api';
import { resolveBlockPlace } from '@/api/kakaoSession';
import { paths } from '@/app/paths';
import { Banner, Button, useOptionalToast } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { BlockEditor } from '@/features/block-editor/BlockEditor';
import { WaypointSheet } from '@/features/waypoint-sheet/WaypointSheet';
import { PlanBSheet } from '@/features/plan-b-sheet/PlanBSheet';
import { blockRole, formatDayDate, formatDuration, legBetween, scheduleLevelViolations, tripSummary } from '@/features/itinerary/format';
import { LegText } from '@/features/itinerary/LegText';
import { AlertIcon, BackIcon, LockIcon, MapIcon, PlusIcon, UndoIcon } from '@/features/itinerary/icons';
import { useApi } from '@/hooks/useApi';
import type { Block, BlockCrowd, IsoDate, Schedule, ScheduleDay, Violation } from '@/types/api';
import styles from './TimelinePage.module.css';

/** 플랜 B 를 띄울 블록(FR-010): 고정하지 않았고, 도착 시각 예상 '붐빔' 이상, 신뢰도 '중간' 이상. 서버가 다시 판정한다. */
function needsPlanB(block: Block, crowd: BlockCrowd | undefined): boolean {
  return !block.isFixed
    && (crowd?.grade === '붐빔' || crowd?.grade === '매우 붐빔')
    && (crowd.confidence === '중간' || crowd.confidence === '높음');
}

/** 플랜 B 알림은 여행·블록마다 한 번만 띄운다(FR-010 '알림 1회'). 저장이 막혀도 화면은 그대로 동작한다. */
function seenKey(tripId: string) { return `pinandfill:planb-seen:${tripId}`; }
function readSeen(tripId: string): string[] {
  try { return JSON.parse(sessionStorage.getItem(seenKey(tripId)) ?? '[]') as string[]; } catch { return []; }
}
function writeSeen(tripId: string, ids: string[]) {
  try { sessionStorage.setItem(seenKey(tripId), JSON.stringify(ids)); } catch { /* 저장 불가: 이번 화면에서만 기억 */ }
}

function pad(value: number) { return String(value).padStart(2, '0'); }
function localToday(): IsoDate { const now = new Date(); return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`; }
function localNow(): string { const now = new Date(); return `${pad(now.getHours())}:${pad(now.getMinutes())}`; }

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
  // 플랜 B 시트를 연 블록, 알림을 이미 본 블록.
  const [planBBlock, setPlanBBlock] = useState<string | null>(null);
  const [seen, setSeen] = useState<string[]>(() => (tripId ? readSeen(tripId) : []));
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
  /** `rethrow` 면 오류를 위 배너 대신 호출한 쪽(예: 모달 시트)으로 넘긴다. 모달 뒤 배너는 보이지 않는다. */
  const run = async (action: Parameters<Change>[0], isUndo = false, message?: string, rethrow = false) => {
    setPending(true);
    setError(null);
    try {
      const before = schedule;
      const result = await action();
      setEdited(result.schedule);
      setMutationViolations(result.violations ?? []);
      setUndoAvailable(!isUndo);
      announce(before, result.schedule, isUndo, message);
      return true;
    } catch (cause) {
      if (rethrow) throw cause;
      setError(toApiError(cause).message);
      return false;
    } finally {
      setPending(false);
    }
  };
  /** 바뀐 내용을 알림(화면 읽기 프로그램에도 읽힘)으로 알리고, 새로 들어간 블록을 강조한다. */
  const announce = (before: Schedule | null, after: Schedule, isUndo: boolean, message?: string) => {
    const beforeIds = new Set(before?.days.flatMap((d) => d.blocks.map((b) => b.id)) ?? []);
    const afterBlocks = after.days.flatMap((d) => d.blocks);
    const afterIds = new Set(afterBlocks.map((b) => b.id));
    const added = afterBlocks.find((b) => !beforeIds.has(b.id));
    const removed = before?.days.flatMap((d) => d.blocks).find((b) => !afterIds.has(b.id));
    const nameOf = (block: Block) => resolveBlockPlace(block.place)?.name ?? '장소';
    if (isUndo) showToast('직전 편집을 되돌렸어요.');
    else if (message) {
      if (added) setFlashId(added.id);
      showToast(message);
    } else if (added) {
      setFlashId(added.id);
      showToast(`일정에 넣었어요: ${nameOf(added)} · 되돌리기 버튼으로 취소할 수 있어요.`);
    } else if (removed) showToast(`일정에서 뺐어요: ${nameOf(removed)} · 되돌리기 버튼으로 취소할 수 있어요.`);
    else showToast('일정을 고쳤어요.');
  };
  const change: Change = async (action, isUndo) => { await run(action, isUndo); };
  const addAndClose: Change = async (action) => { if (await run(action)) setAdding(false); };
  const slotAndClose: Change = async (action) => { if (await run(action)) setSlot(null); };

  const markSeen = (blockId: string) => {
    if (!tripId || seen.includes(blockId)) return;
    const next = [...seen, blockId];
    setSeen(next);
    writeSeen(tripId, next);
  };
  const openPlanB = (blockId: string) => { markSeen(blockId); setPlanBBlock(blockId); };

  if (!tripId) return <Banner tone="warn">여행 정보를 찾을 수 없어요.</Banner>;
  if (loaded.status === 'loading') return <p role="status" className={styles.status}>일정을 불러오는 중…</p>;
  if (loaded.status === 'error') return <Banner tone="warn">일정을 불러오지 못했어요. <Button onClick={loaded.reload}>다시 시도</Button></Banner>;

  const selectDay = (next: number) => { setDayNo(next); setSelected(null); setSlot(null); };
  const crowdOf = (block: Block) => day?.crowd.find((item) => item.blockId === block.id);
  const planBIds = new Set(day?.blocks.filter((block) => needsPlanB(block, crowdOf(block))).map((block) => block.id) ?? []);
  // '다음 블록'(UC-007): 여행 당일이면 지금 이후 블록만, 그 전이면 그날 첫 블록부터 본다.
  const upcoming = (block: Block) => day?.date !== localToday() || (block.arriveAt ?? '') > localNow();
  const alertBlock = [...(day?.blocks ?? [])].sort((a, b) => a.seq - b.seq).find((block) => planBIds.has(block.id) && upcoming(block) && !seen.includes(block.id));
  const planBTarget = day?.blocks.find((block) => block.id === planBBlock);

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

    {alertBlock && <section className={styles.planBAlert} aria-label="플랜 B 알림">
      <p className={styles.planBText}>
        <strong>{resolveBlockPlace(alertBlock.place)?.name ?? '다음 장소'} {alertBlock.arriveAt ?? ''}</strong>
        {` 예상 ${crowdOf(alertBlock)?.grade ?? '붐빔'}이에요. 다른 방법도 볼까요?`}
      </p>
      <span className={styles.planBActions}>
        <Button variant="outline" onClick={() => markSeen(alertBlock.id)}>괜찮아요</Button>
        <Button aria-haspopup="dialog" onClick={() => openPlanB(alertBlock.id)}>플랜 B 보기</Button>
      </span>
    </section>}

    {day ? <DayTimeline
      key={day.dayNo} tripId={tripId} day={day} selected={selected} slot={slot} pending={pending} flashId={flashId}
      planBIds={planBIds} onPlanB={openPlanB}
      onSelect={(id) => setSelected(selected === id ? null : id)} onSlot={(id) => setSlot(slot === id ? null : id)} onChange={change} onSlotChange={slotAndClose}
    /> : <p className={styles.empty}>표시할 일정이 없어요.</p>}

    {planBTarget && <PlanBSheet
      tripId={tripId} blockId={planBTarget.id} placeName={resolveBlockPlace(planBTarget.place)?.name ?? '이 장소'} disabled={pending}
      onClose={() => setPlanBBlock(null)}
      onChange={async (action, message) => {
        // 실패하면 오류가 시트로 넘어가 시트 안에 보인다. 시트는 열어 둔다.
        if (await run(action, false, message, true)) setPlanBBlock(null);
      }}
    />}

    {adding && <section ref={addPanel} className={styles.addPanel}>
      <BlockEditor tripId={tripId} dayNo={day?.dayNo ?? 1} disabled={pending} onChange={addAndClose} />
    </section>}

    <footer className={styles.bottomBar}>
      <Link to={paths.mapView(tripId)} className={styles.mapLink}><MapIcon />지도로 보기</Link>
      <Button className={styles.addButton} aria-expanded={adding} onClick={() => setAdding(!adding)}>{adding ? '추가 닫기' : '장소 추가'}</Button>
    </footer>
  </main>;
}

function DayTimeline({ tripId, day, selected, slot, pending, flashId, planBIds, onPlanB, onSelect, onSlot, onChange, onSlotChange }: {
  tripId: string;
  day: ScheduleDay;
  selected: string | null;
  slot: string | null;
  pending: boolean;
  flashId: string | null;
  /** 플랜 B 를 볼 수 있는 블록(붐빔·신뢰 중간 이상, 고정 아님). */
  planBIds: ReadonlySet<string>;
  onPlanB(id: string): void;
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
      <BlockCard block={block} date={day.date} crowd={day.crowd.find((item) => item.blockId === block.id)} selected={selected === block.id} flash={flashId === block.id} onSelect={() => onSelect(block.id)}
        onPlanB={planBIds.has(block.id) ? () => onPlanB(block.id) : undefined} planBDisabled={pending}>
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

function BlockCard({ block, date, crowd, selected, flash, onSelect, onPlanB, planBDisabled, children }: {
  block: Block;
  /** 있으면 '플랜 B' 버튼을 보인다. */
  onPlanB?: () => void;
  planBDisabled?: boolean;
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
      {onPlanB && <button type="button" className={styles.planBButton} aria-haspopup="dialog" disabled={planBDisabled} onClick={onPlanB}>플랜 B</button>}
      {/* D6: 이번 접속에서 고르지 않은 카카오 장소는 place_url을 외부 브라우저로 연다. */}
      {block.place.source === 'PUBLIC' && <Link className={styles.placeLink} to={paths.placeDetail(block.place.id, date)} aria-label={`${block.place.name} 장소 상세 보기`}>장소 상세 보기</Link>}
      {kakaoLink && <a className={styles.placeLink} href={kakaoLink} target="_blank" rel="noopener noreferrer">카카오맵에서 장소 확인 (새 창)</a>}
    </div>
    {children}
  </article>;
}
