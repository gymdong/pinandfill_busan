import { useCallback, useRef, useState } from 'react';
import { toApiError, tripsApi } from '@/api';
import { BottomSheet, Button } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { formatDuration } from '@/features/itinerary/format';
import { useApi } from '@/hooks/useApi';
import type { AddBlockRequest, ScheduleMutationResponse, WaypointCandidate, WaypointThresholdMin } from '@/types/api';
import styles from './WaypointSheet.module.css';

export interface WaypointSheetProps {
  tripId: string;
  between: { fromBlockId: string; toBlockId: string };
  disabled: boolean;
  /** Parent owns mutation errors, schedule replacement and undo availability. */
  onChange: (action: () => Promise<ScheduleMutationResponse>) => Promise<void>;
  onClose: () => void;
  /** Close recommendation and open the existing manual search entry. */
  onDirectSearch?: () => void;
  /** 구간 양 끝 장소 이름(시트 제목). 모르면 일반 제목을 쓴다. */
  fromName?: string;
  toName?: string;
  /** 이 구간 뒤에 있는 고정 장소. 넣어도 고정 시각은 바뀌지 않는다는 근거로 보여 준다(원칙 1·5). */
  keptFixed?: readonly { name: string; start: string }[];
}

const THRESHOLDS = [10, 15, 30] as const;

/** Mount for the selected adjacent pair; no timeline or global state is changed here. */
export function WaypointSheet(props: WaypointSheetProps) {
  return <WaypointContent key={JSON.stringify([props.tripId, props.between.fromBlockId, props.between.toBlockId])} {...props} />;
}

function WaypointContent({ tripId, between: { fromBlockId, toBlockId }, disabled, onChange, onClose, onDirectSearch, fromName, toName, keptFixed = [] }: WaypointSheetProps) {
  const [insertionError, setInsertionError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  const busy = disabled || submitting;
  const [thresholdMin, setThresholdMin] = useState<WaypointThresholdMin>(15);
  const fetchCandidates = useCallback((signal: AbortSignal) => tripsApi.suggestWaypoints(
    tripId, { fromBlockId, toBlockId, thresholdMin }, { signal },
  ), [tripId, fromBlockId, toBlockId, thresholdMin]);
  const loaded = useApi(fetchCandidates);
  const candidates = loaded.status === 'success'
    ? loaded.data.candidates.filter((candidate) => candidate.place.source === 'PUBLIC').slice(0, 3)
    : [];

  async function insert(candidate: WaypointCandidate) {
    if (disabled || inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setInsertionError(null);
    // #25 accepts stayMin; use the displayed server candidate value, never a default.
    const body: AddBlockRequest = {
      place: { placeId: candidate.place.id }, fromBlockId, toBlockId,
      isFixed: false, origin: 'SUGGESTED', stayMin: candidate.stayMin,
    };
    try {
      await onChange(async () => {
        try { return await tripsApi.addBlock(tripId, body); }
        catch (cause) { setInsertionError(toApiError(cause).message); throw cause; }
      });
    } catch (cause) {
      setInsertionError(toApiError(cause).message);
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  const title = fromName && toName ? `${fromName} → ${toName} 사이` : '사이에 들를 곳';
  const kept = keptFixed.map((item) => `${item.name} ${item.start}`).join(', ');

  return <BottomSheet open onClose={onClose} title={title} description="우회가 적은 곳부터 보여 드려요. 넣어도 고정한 시각은 그대로예요.">
    {insertionError && <p role="alert" className={styles.error}>{insertionError}</p>}
    {/* 기본 radio 를 쓰고(방향키·Tab 동작은 브라우저 그대로) 모양만 둥근 세그먼트로 꾸민다. */}
    <fieldset className={styles.threshold} disabled={busy}>
      <legend className={styles.thresholdLabel}>우회는 최대</legend>
      <span className={styles.segments}>
        {THRESHOLDS.map((value) => <label key={value} className={`${styles.segment} ${thresholdMin === value ? styles.segmentOn : ''}`}>
          <input
            type="radio" className="sr-only" name={`waypoint-threshold-${fromBlockId}`} value={value}
            checked={thresholdMin === value}
            onChange={() => { setInsertionError(null); setThresholdMin(value); }}
          />
          {value}분
        </label>)}
      </span>
    </fieldset>
    {kept && <p className={styles.kept}>넣어도 그대로: {kept}</p>}
    {loaded.status === 'loading' && <p role="status" className={styles.status}>들를 곳을 찾는 중…</p>}
    {loaded.status === 'error' && <div role="alert" className={styles.status}>
      <p>들를 곳을 불러오지 못했어요. {toApiError(loaded.error).message}</p>
      <Button variant="outline" disabled={busy} onClick={loaded.reload}>다시 시도</Button>
    </div>}
    {loaded.status === 'success' && candidates.length === 0 && <div role="status" className={styles.status}>
      <p className={styles.emptyTitle}>{thresholdMin}분 안에 들를 곳이 없어요</p>
      <p>{thresholdMin < 30 ? '우회 시간을 늘려 다시 찾아보세요.' : '다른 구간에서 찾아보세요.'}</p>
    </div>}
    <ul className={styles.candidates} aria-label="들를 곳 후보">
      {candidates.map((candidate) => <li key={candidate.place.id} className={styles.candidate}>
        <div className={styles.candidateHead}>
          <h3 className={styles.name}>{candidate.place.name}</h3>
          <p className={styles.detour}><span className={styles.detourValue}>+{candidate.detourMin}분</span> 우회</p>
        </div>
        <p className={styles.meta}>머무는 시간 {formatDuration(candidate.stayMin)}</p>
        <CrowdBadge grade={candidate.crowd?.grade ?? null} confidence={candidate.crowd?.confidence} />
        <p className={styles.reason}>{candidate.reason}</p>
        <div className={styles.candidateFoot}>
          <p className={styles.source}>공공 데이터 · 기준일 {candidate.place.refDate}</p>
          <Button variant="outline" disabled={busy} aria-label={`${candidate.place.name} 일정에 넣기`} onClick={() => { void insert(candidate); }}>넣기</Button>
        </div>
      </li>)}
    </ul>
    {onDirectSearch && <button type="button" className={styles.direct} disabled={busy} onClick={onDirectSearch}>원하는 곳 직접 찾아 넣기</button>}
  </BottomSheet>;
}
