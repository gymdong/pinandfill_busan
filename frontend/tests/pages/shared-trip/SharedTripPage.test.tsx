import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, accountApi } from '@/api';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import SharedTripPage from '@/pages/shared-trip';

afterEach(() => vi.restoreAllMocks());

function renderAt(token: string) {
  return render(<MemoryRouter initialEntries={[`/shared/${token}`]}><Routes><Route path="/shared/:token" element={<SharedTripPage />} /></Routes></MemoryRouter>);
}

describe('공유 일정 열람(FR-011)', () => {
  it('일정을 보기 전용으로 보여 주고 편집 동작은 두지 않는다', async () => {
    const get = vi.spyOn(accountApi, 'getSharedTrip').mockResolvedValue({ trip, schedule });
    renderAt('token-abcdefghijklmnopqrstuvwxyz');
    expect(await screen.findByText('공유받은 일정 · 보기 전용')).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith('token-abcdefghijklmnopqrstuvwxyz', { signal: expect.any(AbortSignal) });
    const [first] = [...schedule.days[0]!.blocks].sort((a, b) => a.seq - b.seq);
    expect(screen.getAllByText(first!.arriveAt ?? '--:--').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /되돌리기|장소 추가|추천받기|플랜 B/ })).not.toBeInTheDocument();
  });

  it('없거나 만료된 링크는 새 링크를 받으라고 안내한다', async () => {
    vi.spyOn(accountApi, 'getSharedTrip').mockRejectedValue(new ApiError({ id: 'ERR-016', status: 404 }));
    renderAt('missing-token-abcdefghijklmnop');
    expect(await screen.findByText(/링크가 없거나 만료되었어요/)).toBeInTheDocument();
  });
});
