import { useCallback, useEffect, useMemo, useState } from 'react';
import { toApiError, type ApiError } from '@/api';

export type ApiFetcher<T> = (signal: AbortSignal) => Promise<T>;

export type ApiState<T> =
  | { status: 'loading'; data: undefined; error: undefined }
  | { status: 'success'; data: T; error: undefined }
  | { status: 'error'; data: undefined; error: ApiError };

interface Settled<T> {
  source: object;
  state: ApiState<T>;
}

/**
 * 화면 진입 시 데이터를 불러온다. `fetcher`는 useCallback으로 감싸 값이 바뀔 때만 다시 호출되게 한다.
 * 화면을 떠나거나 조건이 바뀌면 진행 중인 요청을 취소한다.
 */
export function useApi<T>(fetcher: ApiFetcher<T>): ApiState<T> & { reload: () => void } {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const source = useMemo(() => ({ fetcher, attempt }), [fetcher, attempt]);

  useEffect(() => {
    const controller = new AbortController();
    source.fetcher(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) {
          setSettled({ source, state: { status: 'success', data, error: undefined } });
        }
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setSettled({ source, state: { status: 'error', data: undefined, error: toApiError(error) } });
        }
      },
    );
    return () => controller.abort();
  }, [source]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  const state: ApiState<T> =
    settled?.source === source ? settled.state : { status: 'loading', data: undefined, error: undefined };

  return { ...state, reload };
}
