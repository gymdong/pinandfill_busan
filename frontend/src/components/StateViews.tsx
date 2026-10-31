import type { ReactNode } from 'react';
import { Button } from './Button';
import styles from './StateViews.module.css';

export function LoadingState({ message = '불러오는 중이에요' }: { message?: string }) {
  return (
    <div className={styles.state} role="status">
      <span className={styles.spinner} aria-hidden="true" />
      <p className={styles.description}>{message}</p>
    </div>
  );
}

export interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className={styles.state}>
      <p className={styles.title}>{title}</p>
      {description ? <p className={styles.description}>{description}</p> : null}
      {action}
    </div>
  );
}

export interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
  /** 재시도 대신 보여 줄 행동. 예: ERR-003의 '지도에서 직접 고르기' */
  action?: ReactNode;
}

export function ErrorState({ message, onRetry, action }: ErrorStateProps) {
  return (
    <div className={styles.state} role="alert">
      <p className={styles.title}>문제가 생겼어요</p>
      <p className={styles.description}>{message}</p>
      {action ?? (onRetry ? <Button variant="outline" onClick={onRetry}>다시 시도</Button> : null)}
    </div>
  );
}
