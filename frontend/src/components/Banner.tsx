import type { ReactNode } from 'react';
import styles from './Banner.module.css';

export type BannerTone = 'info' | 'warn';

export interface BannerProps {
  tone?: BannerTone;
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}

export function Banner({ tone = 'info', title, children, action }: BannerProps) {
  return (
    <div className={`${styles.banner} ${styles[tone]}`} role={tone === 'warn' ? 'alert' : 'status'}>
      <div className={styles.content}>
        {title ? <p className={styles.title}>{title}</p> : null}
        <div>{children}</div>
      </div>
      {action ? <div className={styles.action}>{action}</div> : null}
    </div>
  );
}
