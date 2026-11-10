import styles from './Badge.module.css';

export type BadgeKind = 'detail' | 'basic' | 'needsCheck' | 'estimated' | 'expected';

const DEFAULT_LABEL: Record<BadgeKind, string> = {
  detail: '상세 정보 있음',
  basic: '기본 정보만',
  needsCheck: '확인 필요',
  estimated: '추정',
  expected: '예상',
};

export interface BadgeProps {
  kind: BadgeKind;
  /** 기본 문구를 구체화할 때만 쓴다. 예: '영업시간 확인 필요', '확인 필요 2건' */
  label?: string;
}

export function Badge({ kind, label }: BadgeProps) {
  return (
    <span className={`${styles.badge} ${styles[kind]}`}>
      {kind === 'detail' ? <span aria-hidden="true">✓</span> : null}
      {label ?? DEFAULT_LABEL[kind]}
    </span>
  );
}
