import { useCallback, useRef, useState } from 'react';
import { toApiError, tripsApi } from '@/api';
import { BottomSheet, Button } from '@/components';
import { CrowdBadge } from '@/features/crowd/CrowdBadge';
import { useApi } from '@/hooks/useApi';
import type { PlanBOption, ScheduleMutationResponse } from '@/types/api';
import styles from './PlanBSheet.module.css';

export interface PlanBSheetProps {
  tripId: string;
  blockId: string;
  /** 대상 장소 이름(시트 제목). */
  placeName: string;
  disabled: boolean;
  /** 부모가 일정 교체·오류·되돌리기 상태를 맡는다. 두 번째 인자는 알림 문구다. */
  onChange: (action: () => Promise<ScheduleMutationResponse>, message: string) => Promise<void>;
  onClose: () => void;
}

const TITLES: Record<PlanBOption['kind'], string> = { KEEP: '그대로 가기', REORDER: '순서 바꾸기', REPLACE: '대체 장소' };

function travel(minutes: number | null): string {
  if (minutes === null) return '이동시간 확인 필요';
  if (minutes === 0) return '이동시간 그대로';
  return minutes > 0 ? `이동 +${minutes}분` : `이동 ${minutes}분`;
}

/**
 * UI 플랜 B(FR-010, UC-007): 강행 / 순서 바꾸기 / 대체 장소 3안. 고르기 전에는 일정을 바꾸지 않는다(원칙 5).
 * 고정한 장소는 대상이 아니고, 어떤 안도 고정 시각을 바꾸지 않는다(서버가 그런 안을 내지 않는다).
 */
export function PlanBSheet(props: PlanBSheetProps) {
  return <PlanBContent key={`${props.tripId}:${props.blockId}`} {...props} />;
}

function PlanBContent({ tripId, blockId, placeName, disabled, onChange, onClose }: PlanBSheetProps) {
  const [applyError, setApplyError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  const busy = disabled || submitting;
  const fetchOptions = useCallback((signal: AbortSignal) => tripsApi.getPlanB(tripId, blockId, { signal }), [tripId, blockId]);
  const loaded = useApi(fetchOptions);

  async function choose(option: PlanBOption) {
    if (option.kind === 'KEEP') { onClose(); return; }
    if (disabled || inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setApplyError(null);
    const message = option.kind === 'REPLACE'
      ? `${placeName} 대신 ${option.place?.name ?? '대체 장소'}로 바꿨어요 · 되돌리기 버튼으로 취소할 수 있어요.`
      : `${placeName} 순서를 바꿨어요 · 되돌리기 버튼으로 취소할 수 있어요.`;
    try {
      await onChange(() => tripsApi.applyPlanB(tripId, { optionId: option.id }), message);
    } catch (cause) {
      setApplyError(toApiError(cause).message);
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  const current = loaded.status === 'success' ? loaded.data : null;
  const description = current?.crowd?.grade
    ? `지금 시각은 예상 ${current.crowd.grade}이에요. 고르기 전에는 일정을 바꾸지 않아요.`
    : '고르기 전에는 일정을 바꾸지 않아요.';

  return <BottomSheet open onClose={onClose} title={`${placeName} 플랜 B`} description={description}>
    {applyError && <p role="alert" className={styles.error}>{applyError}</p>}
    {loaded.status === 'loading' && <p role="status" className={styles.status}>다른 방법을 계산하는 중…</p>}
    {loaded.status === 'error' && <div role="alert" className={styles.status}>
      <p>플랜 B를 불러오지 못했어요. {toApiError(loaded.error).message}</p>
      <Button variant="outline" disabled={busy} onClick={loaded.reload}>다시 시도</Button>
    </div>}
    {current && current.trigger === null && <p role="status" className={styles.status}>지금은 바꿀 필요가 없어요. 예상 혼잡이 높지 않거나 근거가 부족해요.</p>}
    {current && current.trigger !== null && <ul className={styles.options} aria-label="플랜 B 3안">
      {current.options.map((option) => <li key={option.kind} className={`${styles.option} ${option.available ? '' : styles.optionOff}`}>
        <div className={styles.head}>
          <h3 className={styles.name}>{TITLES[option.kind]}{option.kind === 'REPLACE' && option.place ? `: ${option.place.name}` : ''}</h3>
          {option.available && option.arriveAt && <p className={styles.time}>{option.arriveAt}–{option.departAt ?? '--:--'}</p>}
        </div>
        {option.available ? <>
          <CrowdBadge grade={option.crowd?.grade ?? null} confidence={option.crowd?.confidence} />
          <p className={styles.meta}>
            {option.kind === 'KEEP' ? '지금 일정 그대로' : travel(option.extraMinutes)}
            {' · '}
            {option.hoursConflict ? <span className={styles.conflict}>영업시간 충돌 있음</span> : '영업시간 충돌 없음'}
          </p>
          {option.kind === 'REPLACE' && option.place && <p className={styles.source}>공공 데이터 · 기준일 {option.place.refDate}</p>}
          <Button
            variant={option.kind === 'KEEP' ? 'outline' : 'primary'} disabled={busy && option.kind !== 'KEEP'}
            aria-label={option.kind === 'KEEP' ? '그대로 가기' : `${TITLES[option.kind]} 적용`}
            onClick={() => { void choose(option); }}
          >{option.kind === 'KEEP' ? '그대로 두기' : '이렇게 바꾸기'}</Button>
        </> : <p className={styles.meta}>{option.note ?? '지금은 고를 수 없어요.'}</p>}
      </li>)}
    </ul>}
  </BottomSheet>;
}
