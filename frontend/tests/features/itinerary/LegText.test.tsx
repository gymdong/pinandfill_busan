import { render, screen } from '@testing-library/react';
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
    expect(screen.queryByTitle(/추정/)).toBeNull();
  });

  it('추정 구간은 작은 표시와 설명을 두고 화면 읽기에는 (추정)으로 읽힌다', () => {
    render(<LegText leg={{ ...leg, source: 'ESTIMATED' }} />);
    const mark = screen.getByTitle(/추정 이동시간/);
    expect(mark).toHaveTextContent('≈30분 (추정)');
    expect(mark).toHaveAttribute('tabindex', '0');
    expect(screen.getByText('(추정)', { exact: false })).toHaveClass('sr-only');
  });
});
