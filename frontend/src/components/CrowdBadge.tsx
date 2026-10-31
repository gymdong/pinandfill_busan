import type { CrowdConfidence, CrowdGrade } from '@/types/api';
import styles from './CrowdBadge.module.css';

const TOTAL_BARS = 4;

const GRADE_STYLE: Record<CrowdGrade, { bars: number; className: string | undefined }> = {
  여유: { bars: 1, className: styles.free },
  보통: { bars: 2, className: styles.normal },
  붐빔: { bars: 3, className: styles.busy },
  '매우 붐빔': { bars: 4, className: styles.veryBusy },
};

export interface CrowdBadgeProps {
  /** null이면 근거 신호가 없다는 뜻이며 '정보 부족'으로 표시한다(NFR-012). */
  grade: CrowdGrade | null;
  confidence?: CrowdConfidence;
  /** '18시'처럼 뒤에 붙는 시간대 문구 */
  hourLabel?: string;
}

/**
 * 예상 혼잡 표시 전용 컴포넌트. 색·글자·막대 칸 수를 함께 쓴다(NFR-008).
 * 데이터 조회와 시간대 그래프는 `features/crowd`가 맡는다.
 */
export function CrowdBadge({ grade, confidence, hourLabel }: CrowdBadgeProps) {
  const style = grade ? GRADE_STYLE[grade] : null;
  const filled = style?.bars ?? 0;
  const label = grade ? `예상 ${grade}` : '정보 부족';
  const showConfidence = grade !== null && confidence !== undefined && confidence !== '없음';

  return (
    <span className={`${styles.badge} ${style?.className ?? styles.unknown}`}>
      <span className={styles.bars} aria-hidden="true" data-filled={filled}>
        {Array.from({ length: TOTAL_BARS }, (_, index) => (
          <span key={index} className={index < filled ? styles.barFilled : styles.bar} />
        ))}
      </span>
      <span>
        {label}
        {hourLabel ? ` · ${hourLabel}` : ''}
      </span>
      {showConfidence ? <span className={styles.confidence}>신뢰 {confidence}</span> : null}
    </span>
  );
}
