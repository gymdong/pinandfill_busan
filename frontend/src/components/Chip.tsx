import type { ButtonHTMLAttributes } from 'react';
import styles from './Chip.module.css';

export interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  /** 점선 테두리. '+ 태그'처럼 항목을 더하는 칩에 쓴다. */
  dashed?: boolean;
}

/** 선택형 칩. 선택 상태는 색뿐 아니라 굵기·체크 표시와 aria-pressed로도 전달한다. */
export function Chip({ selected = false, dashed = false, className, children, type = 'button', ...rest }: ChipProps) {
  const classes = [styles.chip, selected ? styles.selected : '', dashed ? styles.dashed : '', className ?? '']
    .filter(Boolean)
    .join(' ');
  return (
    <button type={type} className={classes} aria-pressed={selected} {...rest}>
      {selected ? (
        <span className={styles.check} aria-hidden="true">
          ✓
        </span>
      ) : null}
      {children}
    </button>
  );
}
