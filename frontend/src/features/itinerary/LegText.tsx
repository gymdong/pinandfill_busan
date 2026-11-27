import type { Leg } from '@/types/api';
import { modeLabel } from './format';
import styles from './LegText.module.css';

const ESTIMATE_TIP = '추정 이동시간: 경로 API 결과가 없어 직선거리로 계산한 값이에요';

/**
 * 구간 표시. 추정(ESTIMATED) 구간은 시간 앞에 작은 '≈' 표시를 두고,
 * 마우스를 올리거나 눌러(포커스) 설명을 본다. 화면 읽기 프로그램에는 '(추정)'으로 읽힌다.
 */
export function LegText({ leg }: { leg: Leg }) {
  const estimated = leg.source === 'ESTIMATED';
  const duration = leg.durationMin === null ? '이동시간 확인 필요' : `${leg.durationMin}분`;
  return (
    <>
      {modeLabel(leg.mode)} ·{' '}
      {estimated ? (
        <span className={styles.estimate} tabIndex={0} data-tip={ESTIMATE_TIP} title={ESTIMATE_TIP}>
          <span aria-hidden="true">≈</span>
          {duration}
          <span className="sr-only"> (추정)</span>
        </span>
      ) : (
        duration
      )}
    </>
  );
}
