import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, tripsApi } from '@/api';
import { ShareSheet } from '@/features/share/ShareSheet';

beforeEach(() => sessionStorage.clear());
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

  it('다시 열면 만든 링크를 다시 쓰고, 복사가 막히면 직접 복사하도록 안내한다', async () => {
    const share = vi.spyOn(tripsApi, 'share').mockResolvedValue({ url: '/shared/again', token: 'again', expiresAt: '2099-12-09T15:00:00Z' });
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) }, configurable: true });
    const first = render(<ShareSheet tripId="t2" onClose={vi.fn()} />);
    expect(await screen.findByText('12월 9일까지 열려요.')).toBeInTheDocument();
    first.unmount();
    render(<ShareSheet tripId="t2" onClose={vi.fn()} />);
    expect(screen.getByLabelText('공유 링크')).toHaveValue(`${window.location.origin}/shared/again`);
    expect(share).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole('button', { name: '링크 복사' }));
    expect(await screen.findByText(/길게 눌러 복사해 주세요/)).toBeInTheDocument();
  });
});
