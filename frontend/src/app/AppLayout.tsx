import { Suspense } from 'react';
import { Outlet } from 'react-router-dom';
import { LoadingState } from '@/components';
import styles from './AppLayout.module.css';

export function AppLayout() {
  return (
    <div className={styles.shell}>
      <Suspense fallback={<LoadingState />}>
        <Outlet />
      </Suspense>
    </div>
  );
}
