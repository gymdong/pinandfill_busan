import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { CrowdHourlyChart } from '@/features/crowd';
import type { PlaceCrowdResponse } from '@/types/api';

const CROWD: PlaceCrowdResponse = {
  hours: [
    { h: 9, grade: '여유', score: 0.2 },
    { h: 12, grade: '보통', score: 0.5 },
    { h: 14, grade: '붐빔', score: 0.8 },
    { h: 15, grade: '매우 붐빔', score: 0.95 },
  ],
  confidence: '중간',
  asOf: '2026-11-26T05:00:00Z',
  sources: ['시험 자료 A', '시험 자료 B'],
  signals: [
    { source: 'DATA-04', label: '시험 신호 A', refPeriod: '2026-10', detail: '영도구 · 주말 시간대별 상대값' },
    { source: 'DATA-06', label: '시험 신호 B', refPeriod: null, detail: null },
  ],
};

const EMPTY: PlaceCrowdResponse = { hours: [], confidence: '없음', asOf: null, sources: [], signals: [] };

describe('CrowdHourlyChart (UI-04, AC-008)', () => {
  it('시간대마다 등급을 글자와 막대 칸 수로 함께 보여 준다(NFR-008)', () => {
    render(<CrowdHourlyChart crowd={CROWD} />);
    const rows = within(screen.getByRole('list', { name: '시간대별 예상 등급' })).getAllByRole('listitem');

    expect(rows.map((row) => row.textContent)).toEqual(['9시예상 여유', '12시예상 보통', '14시예상 붐빔', '15시예상 매우 붐빔']);
    expect(rows.map((row) => row.querySelector('[data-filled]')?.getAttribute('data-filled'))).toEqual(['1', '2', '3', '4']);
  });

  it('근거가 없는 시간대는 막대 없이 정보 부족 글자만 흐리게 보인다', () => {
    const { container } = render(
      <CrowdHourlyChart crowd={{ ...CROWD, hours: [CROWD.hours[0]!, { h: 10, grade: null, score: null }] }} />,
    );
    const rows = within(screen.getByRole('list', { name: '시간대별 예상 등급' })).getAllByRole('listitem');

    expect(rows.map((row) => row.textContent)).toEqual(['9시예상 여유', '10시정보 부족']);
    expect(rows[1]!.querySelector('[data-filled]')).toBeNull();
    expect(rows[1]!.className).toMatch(/hourMissing/);
    expect(container.querySelectorAll('[data-filled]')).toHaveLength(1);
  });

  it("'예상' 라벨, 신뢰도, 한국 시각 기준 시각, 출처를 보인다", () => {
    render(<CrowdHourlyChart crowd={CROWD} />);
    const chart = screen.getByRole('region', { name: '시간대별 예상 혼잡' });

    expect(within(chart).getByText('예상')).toBeInTheDocument();
    expect(within(chart).getByText('신뢰도').nextSibling).toHaveTextContent('중간');
    expect(within(chart).getByText('기준 시각').nextSibling).toHaveTextContent('11월 26일 (목) 14:00');
    expect(within(chart).getByText('출처').nextSibling).toHaveTextContent('시험 자료 A, 시험 자료 B');
  });

  it('기준 시각을 읽을 수 없으면 화면을 깨뜨리지 않고 확인 필요로 둔다', () => {
    render(<CrowdHourlyChart crowd={{ ...CROWD, asOf: 'not-a-date' }} />);
    expect(screen.getByText('기준 시각').nextSibling).toHaveTextContent('확인 필요');
  });

  it("'근거 보기'로 신호 목록을 펼치고 접는다", async () => {
    render(<CrowdHourlyChart crowd={CROWD} />);
    const toggle = screen.getByRole('button', { name: '근거 보기' });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('list', { name: '혼잡 근거' })).not.toBeInTheDocument();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const signals = within(screen.getByRole('list', { name: '혼잡 근거' })).getAllByRole('listitem');
    expect(signals[0]).toHaveTextContent('시험 신호 A2026-10 기준 · 영도구 · 주말 시간대별 상대값');
    expect(signals[1]).toHaveTextContent('시험 신호 B기준 기간 확인 필요');

    await userEvent.click(screen.getByRole('button', { name: '근거 접기' }));
    expect(screen.queryByRole('list', { name: '혼잡 근거' })).not.toBeInTheDocument();
  });

  it('근거 보기 버튼은 44px 탭 영역 버튼 스타일을 쓴다', () => {
    render(<CrowdHourlyChart crowd={CROWD} />);
    // CSS 모듈 클래스 이름은 시험에서 그대로 남는다. Button 의 .button 은 min-height: var(--tap-min)(44px).
    expect(screen.getByRole('button', { name: '근거 보기' }).className).toMatch(/button/);
  });

  it.each<[string, PlaceCrowdResponse | null]>([
    ['근거 신호가 없으면', EMPTY],
    ['등급이 모두 비어 있으면', { ...CROWD, hours: [{ h: 9, grade: null, score: null }] }],
    ['불러오지 못했으면', null],
  ])('%s 정보 부족으로 표시하고 등급·근거 보기를 만들지 않는다', (_, crowd) => {
    render(<CrowdHourlyChart crowd={crowd} />);
    expect(screen.getByText('정보 부족')).toBeInTheDocument();
    expect(screen.queryByRole('list', { name: '시간대별 예상 등급' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '근거 보기' })).not.toBeInTheDocument();
  });

  it('불러오지 못했을 때 다시 시도를 누르면 다시 부른다', async () => {
    const onRetry = vi.fn();
    render(<CrowdHourlyChart crowd={null} onRetry={onRetry} />);
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("'실시간'이라는 표현을 쓰지 않는다", async () => {
    const { container } = render(<CrowdHourlyChart crowd={CROWD} />);
    await userEvent.click(screen.getByRole('button', { name: '근거 보기' }));
    expect(container.textContent).not.toContain('실시간');
  });
});
