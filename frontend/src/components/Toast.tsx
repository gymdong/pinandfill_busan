import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import styles from './Toast.module.css';

const TOAST_DURATION_MS = 3500;

interface ToastItem {
  id: number;
  message: string;
}

interface ToastContextValue {
  showToast: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());

  const showToast = useCallback((message: string) => {
    const id = nextId.current++;
    setItems((current) => [...current, { id, message }]);
    const timer = setTimeout(() => {
      timers.current.delete(timer);
      setItems((current) => current.filter((item) => item.id !== id));
    }, TOAST_DURATION_MS);
    timers.current.add(timer);
  }, []);

  useEffect(() => {
    const pending = timers.current;
    return () => {
      pending.forEach(clearTimeout);
      pending.clear();
    };
  }, []);

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.viewport} role="status" aria-live="polite">
        {items.map((item) => (
          <p key={item.id} className={styles.toast}>
            {item.message}
          </p>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error('useToast는 ToastProvider 안에서만 쓸 수 있습니다');
  }
  return value;
}
