import type { ReactNode } from 'react';
import { ToastProvider } from '@/components';

/** 전역 Provider를 한곳에서 조립한다. */
export function AppProviders({ children }: { children: ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}
