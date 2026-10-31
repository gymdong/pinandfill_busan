import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CrowdBadge } from '@/components';
import type { CrowdGrade } from '@/types/api';

function filledBars(container: HTMLElement) {
  return container.querySelector('[data-filled]')?.getAttribute('data-filled');
}

describe('CrowdBadge', () => {
  it.each<[CrowdGrade, string]>([
    ['여유', '1'],
    ['보통', '2'],
    ['붐빔', '3'],
    ['매우 붐빔', '4'],
  ])('%s은 글자와 막대 %s칸으로 표시한다', (grade, bars) => {
    const { container } = render(<CrowdBadge grade={grade} />);
    expect(screen.getByText(`예상 ${grade}`)).toBeInTheDocument();
    expect(filledBars(container)).toBe(bars);
  });

  it('근거 신호가 없으면 정보 부족으로 표시한다', () => {
    const { container } = render(<CrowdBadge grade={null} confidence="높음" />);
    expect(screen.getByText('정보 부족')).toBeInTheDocument();
    expect(filledBars(container)).toBe('0');
    expect(screen.queryByText(/신뢰/)).not.toBeInTheDocument();
  });

  it('신뢰도와 시간대를 함께 표시한다', () => {
    render(<CrowdBadge grade="보통" confidence="중간" hourLabel="18시" />);
    expect(screen.getByText('예상 보통 · 18시')).toBeInTheDocument();
    expect(screen.getByText('신뢰 중간')).toBeInTheDocument();
  });

  it("'실시간'이라는 표현을 쓰지 않는다", () => {
    const { container } = render(<CrowdBadge grade="붐빔" confidence="높음" />);
    expect(container.textContent).not.toContain('실시간');
  });
});
