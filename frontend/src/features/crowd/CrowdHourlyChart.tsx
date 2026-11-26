import { useId, useState } from 'react';
import { Button } from '@/components';
import type { PlaceCrowdResponse } from '@/types/api';
import { formatDateTime } from '@/utils/format';
import { CrowdBadge } from './CrowdBadge';
import styles from './CrowdHourlyChart.module.css';

export interface CrowdHourlyChartProps {
  /** null이면 불러오지 못했거나 근거가 없다는 뜻이며 '정보 부족'으로 표시한다(NFR-012). */
  crowd: PlaceCrowdResponse | null;
  /** 불러오지 못했을 때만 넘긴다. 있으면 '다시 시도' 버튼을 보인다. */
  onRetry?: () => void;
}

/**
 * UI-04 시간대별 예상 혼잡(FR-008, AC-008). 시간대마다 등급 글자·막대 칸 수·색을 함께 쓰고(NFR-008),
 * 세로 목록이라 화면 읽기 도구에도 그대로 읽힌다. 신뢰도·기준 시각·출처를 함께 보이고 '근거 보기'로 신호를 펼친다.
 */
export function CrowdHourlyChart({ crowd, onRetry }: CrowdHourlyChartProps) {
  const [open, setOpen] = useState(false);
  const signalsId = useId();
  const hours = crowd?.hours.filter((hour) => hour.grade !== null) ?? [];
  const available = crowd !== null && crowd.confidence !== '없음' && hours.length > 0;

  return (
    <section className={styles.chart} aria-label="시간대별 예상 혼잡">
      <div className={styles.head}>
        <h2 className={styles.title}>시간대별 혼잡</h2>
        <span className={styles.estimate}>예상</span>
      </div>

      {!available ? (
        <div className={styles.empty}>
          <p>정보 부족</p>
          {onRetry && (
            <Button variant="ghost" onClick={onRetry}>
              다시 시도
            </Button>
          )}
        </div>
      ) : (
        <>
          <ol className={styles.hours} aria-label="시간대별 예상 등급">
            {crowd.hours.map(({ h, grade }) => (
              <li key={h} className={styles.hour}>
                <span className={styles.hourLabel}>{h}시</span>
                <CrowdBadge grade={grade} />
              </li>
            ))}
          </ol>

          <dl className={styles.meta}>
            <div>
              <dt>신뢰도</dt>
              <dd>{crowd.confidence}</dd>
            </div>
            <div>
              <dt>기준 시각</dt>
              <dd>{crowd.asOf ? formatDateTime(crowd.asOf) : '확인 필요'}</dd>
            </div>
            <div>
              <dt>출처</dt>
              <dd>{crowd.sources.length > 0 ? crowd.sources.join(', ') : '확인 필요'}</dd>
            </div>
          </dl>

          {crowd.signals.length > 0 && (
            <>
              <Button
                variant="ghost"
                className={styles.toggle}
                aria-expanded={open}
                aria-controls={signalsId}
                onClick={() => setOpen(!open)}
              >
                {open ? '근거 접기' : '근거 보기'}
              </Button>
              {open && (
                <ul id={signalsId} className={styles.signals} aria-label="혼잡 근거">
                  {crowd.signals.map((signal, index) => (
                    // 같은 자료 코드가 기간을 달리해 여러 번 올 수 있어 순서를 key에 섞는다.
                    <li key={`${index}-${signal.source}`}>
                      <span className={styles.signalLabel}>{signal.label}</span>
                      <span className={styles.signalMeta}>
                        {[signal.refPeriod ? `${signal.refPeriod} 기준` : '기준 기간 확인 필요', signal.detail]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}
