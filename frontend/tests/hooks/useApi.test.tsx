import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api';
import { useApi, type ApiFetcher } from '@/hooks/useApi';

describe('useApi', () => {
  it('불러온 값을 돌려준다', async () => {
    const fetcher: ApiFetcher<string> = async () => '값';
    const { result } = renderHook(() => useApi(fetcher));
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.status).toBe('success'));
    expect(result.current.data).toBe('값');
  });

  it('실패를 ApiError로 돌려주고 다시 시도할 수 있다', async () => {
    const fetcher = vi
      .fn<ApiFetcher<string>>()
      .mockRejectedValueOnce(new ApiError({ id: 'ERR-003' }))
      .mockResolvedValueOnce('복구');
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.error?.id).toBe('ERR-003');

    act(() => result.current.reload());
    expect(result.current.status).toBe('loading');
    await waitFor(() => expect(result.current.data).toBe('복구'));
  });

  it('조건이 바뀌면 이전 요청을 취소하고 늦게 온 응답을 버린다', async () => {
    const signals: AbortSignal[] = [];
    let resolveFirst: (value: string) => void = () => {};
    const first: ApiFetcher<string> = (signal) => {
      signals.push(signal);
      return new Promise((resolve) => {
        resolveFirst = resolve;
      });
    };
    const second: ApiFetcher<string> = async () => '둘째';

    const { result, rerender } = renderHook(({ fetcher }) => useApi(fetcher), { initialProps: { fetcher: first } });
    rerender({ fetcher: second });
    await waitFor(() => expect(result.current.data).toBe('둘째'));
    expect(signals[0]?.aborted).toBe(true);

    await act(async () => resolveFirst('첫째'));
    expect(result.current.data).toBe('둘째');
  });
});
