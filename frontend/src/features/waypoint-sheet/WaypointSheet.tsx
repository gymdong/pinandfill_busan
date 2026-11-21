import { useCallback, useRef, useState } from 'react';
import { toApiError, tripsApi } from '@/api';
import { BottomSheet, Button } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
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
}

/** Mount for the selected adjacent pair; no timeline or global state is changed here. */
export function WaypointSheet(props: WaypointSheetProps) {
  return <WaypointContent key={JSON.stringify([props.tripId, props.between.fromBlockId, props.between.toBlockId])} {...props} />;
}

function WaypointContent({ tripId, between: { fromBlockId, toBlockId }, disabled, onChange, onClose, onDirectSearch }: WaypointSheetProps) {
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

  return <BottomSheet open onClose={onClose} title="경유지 추천" description="두 장소 사이에 들를 곳을 비교해 보세요.">
    {insertionError && <p role="alert">{insertionError}</p>}
    {onDirectSearch && <Button variant="outline" disabled={busy} onClick={onDirectSearch}>직접 검색해서 넣기</Button>}
    <fieldset className={styles.threshold} disabled={busy}>
      <legend>우회 허용 시간</legend>
      {([10, 15, 30] as const).map((value) => <label key={value}>
        <input type="radio" name="waypoint-threshold" checked={thresholdMin === value} onChange={() => {
          setInsertionError(null);
          setThresholdMin(value);
        }} />
        {value}분
      </label>)}
    </fieldset>
    {loaded.status === 'loading' && <p role="status">경유지를 찾는 중…</p>}
    {loaded.status === 'error' && <div role="alert">
      <p>경유지를 불러오지 못했어요. {loaded.error.message}</p>
      <Button variant="outline" disabled={busy} onClick={loaded.reload}>다시 시도</Button>
    </div>}
    {loaded.status === 'success' && candidates.length === 0 && <div role="status">
      <p>추가할 곳 없음</p>
      <p>{thresholdMin < 30 ? '우회 허용 시간을 늘려 다시 찾아보세요.' : '다른 구간에서 찾아보세요.'}</p>
    </div>}
    <ul className={styles.candidates} aria-label="경유지 후보">
      {candidates.map((candidate) => <li key={candidate.place.id} className={styles.candidate}>
        <h3>{candidate.place.name}</h3>
        <p>추가 이동 {candidate.detourMin}분 · 체류 {candidate.stayMin}분</p>
        <CrowdBadge grade={candidate.crowd?.grade ?? null} confidence={candidate.crowd?.confidence} />
        <p>{candidate.reason}</p>
        <p className={styles.source}>공공 데이터 · 기준일 {candidate.place.refDate}</p>
        <Button disabled={busy} aria-label={`${candidate.place.name} 경유지로 추가`} onClick={() => { void insert(candidate); }}>경유지로 추가</Button>
      </li>)}
    </ul>
  </BottomSheet>;
}
