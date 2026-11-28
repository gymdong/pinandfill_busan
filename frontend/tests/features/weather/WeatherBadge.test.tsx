import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WeatherBadge } from '@/features/weather';
import type { TripWeatherBlock } from '@/types/api';

const base: TripWeatherBlock = {
  blockId: 'b1', scope: 'SHORT', issuedAt: '2026-12-01T08:00:00+09:00', outdoor: true, warnings: [],
  forecast: { scope: 'SHORT', pop: 70, pty: '비', sky: '흐림', temp: 8, wind: 3, issuedAt: '2026-12-01T08:00:00+09:00', rain: true },
};

describe('WeatherBadge(FR-013)', () => {
  it('시간 단위 예보는 날씨·기온·강수확률과 예보 라벨·발표 시각을 보인다', () => {
    render(<WeatherBadge weather={base} />);
    expect(screen.getByText(/비 · 8° · 강수 70%/)).toBeInTheDocument();
    expect(screen.getByText('예보')).toBeInTheDocument();
    expect(screen.getByText(/기상청 .*발표/)).toBeInTheDocument();
  });

  it('일 단위 예보와 예보 없음', () => {
    const mid: TripWeatherBlock = { ...base, scope: 'MID', forecast: { ...base.forecast, scope: 'MID', sky: '흐리고 비', pop: 60, temp: null, tempMin: 4, tempMax: 12, rain: false } };
    const { rerender } = render(<WeatherBadge weather={mid} />);
    expect(screen.getByText('예보(일 단위)')).toBeInTheDocument();
    expect(screen.getByText(/흐리고 비 · 강수 60% · 4~12°/)).toBeInTheDocument();
    rerender(<WeatherBadge weather={null} />);
    expect(screen.getByText('예보 없음')).toBeInTheDocument();
  });
});
