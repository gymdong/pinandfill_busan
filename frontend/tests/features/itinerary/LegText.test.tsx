import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { LegText } from '@/features/itinerary/LegText';
import type { Leg } from '@/types/api';

const leg = {
  id: 'l1',
  fromBlockId: 'a',
  toBlockId: 'b',
  mode: 'TRANSIT',
  durationMin: 30,
  source: 'TMAP',
  computedAt: '2026-11-27T00:00:00Z',
} as unknown as Leg;

describe('LegText', () => {
  it('실제 경로는 표시 없이 시간만 보여 준다', () => {
    const { container } = render(<LegText leg={leg} />);
    expect(container).toHaveTextContent('대중교통 · 30분');
    expect(screen.queryByRole('button')).toBeNull();
  });

  it('추정 구간은 ≈ 표시이고 화면 읽기에는 (추정)으로 읽히며, 누르면 설명이 펼쳐진다', async () => {
    render(<LegText leg={{ ...leg, source: 'ESTIMATED' }} />);
    const mark = screen.getByRole('button', { name: '30분 (추정)' });
    expect(mark).toHaveTextContent('≈30분');
    expect(mark).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/직선거리로 계산/)).toBeNull();
    await userEvent.click(mark);
    expect(mark).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText(/직선거리로 계산/)).toBeInTheDocument();
  });

  it('이동시간이 없으면 추정 표시 없이 확인 필요다', () => {
    const { container } = render(<LegText leg={{ ...leg, source: 'ESTIMATED', durationMin: null }} />);
    expect(container).toHaveTextContent('대중교통 · 이동시간 확인 필요');
    expect(screen.queryByRole('button')).toBeNull();
  });
});
