import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, tripsApi } from '@/api';
import { ShareSheet } from '@/features/share/ShareSheet';

afterEach(() => vi.restoreAllMocks());

describe('ShareSheet(FR-011)', () => {
  it('열면 링크를 만들고 전체 주소를 복사한다', async () => {
    const share = vi.spyOn(tripsApi, 'share').mockResolvedValue({ url: '/shared/abc_DEF-123', token: 'abc_DEF-123' });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(<ShareSheet tripId="t1" onClose={vi.fn()} />);
    const field = await screen.findByLabelText('공유 링크');
    expect(field).toHaveValue(`${window.location.origin}/shared/abc_DEF-123`);
    expect(share).toHaveBeenCalledWith('t1', {}, { signal: expect.any(AbortSignal) });
    await userEvent.click(screen.getByRole('button', { name: '링크 복사' }));
    expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/shared/abc_DEF-123`);
    expect(await screen.findByText(/링크를 복사했어요/)).toBeInTheDocument();
  });

  it('실패하면 오류와 다시 시도를 보인다', async () => {
    const share = vi.spyOn(tripsApi, 'share')
      .mockRejectedValueOnce(new ApiError({ id: 'ERR-016', status: 404, message: '여행을 찾을 수 없습니다.' }))
      .mockResolvedValueOnce({ url: '/shared/x', token: 'x' });
    render(<ShareSheet tripId="t1" onClose={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('여행을 찾을 수 없습니다.');
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(await screen.findByLabelText('공유 링크')).toBeInTheDocument();
    expect(share).toHaveBeenCalledTimes(2);
  });
});
