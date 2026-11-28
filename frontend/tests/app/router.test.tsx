import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { placesApi, tripsApi } from '@/api';
import { taejongdaeDetail } from '@/api/mock/fixtures/places';
import { schedule, trip } from '@/api/mock/fixtures/schedule';
import { paths } from '@/app/paths';
import { routes } from '@/app/router';

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
}

describe('라우팅', () => {
  afterEach(() => vi.restoreAllMocks());
  it.each([
    [paths.tripStart(), '새 여행 · 1/2 단계'],
    [paths.timeline('t1'), '코스 타임라인'],
    [paths.placeDetail('p1', '2026-10-17'), '태종대'],
    [paths.mapView('t1'), '지도 보기'],
    [paths.moodSearch(), '분위기로 찾기'],
    [paths.admin(), 'UI-09 관리자'],
  ])('%s에 %s 자리를 연다', async (path, title) => {
    vi.spyOn(tripsApi, 'get').mockResolvedValue({ trip, schedule });
    vi.spyOn(placesApi, 'get').mockResolvedValue(taejongdaeDetail);
    renderAt(path);
    expect(await screen.findByText(title)).toBeInTheDocument();
  });

  it('없는 경로는 안내를 보여 준다', async () => {
    renderAt('/없는-경로');
    expect(await screen.findByText('페이지를 찾을 수 없어요')).toBeInTheDocument();
  });
});
