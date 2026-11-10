import { render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { paths } from '@/app/paths';
import { routes } from '@/app/router';

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
}

describe('라우팅', () => {
  it.each([
    [paths.tripStart(), 'UI-01 여행 시작'],
    [paths.timeline('t1'), 'UI-02 코스 타임라인'],
    [paths.placeDetail('p1', '2026-10-17'), 'UI-04 장소 상세'],
    [paths.mapView('t1'), 'UI-06 지도 보기'],
    [paths.moodSearch(), 'UI-08 분위기로 찾기'],
    [paths.admin(), 'UI-09 관리자'],
  ])('%s에 %s 자리를 연다', async (path, title) => {
    renderAt(path);
    expect(await screen.findByText(title)).toBeInTheDocument();
  });

  it.each([paths.photoSearch(), paths.sharedTrip('token')])('P1 경로 %s는 비활성으로 표시한다', async (path) => {
    renderAt(path);
    expect(await screen.findByText(/P1 화면이에요/)).toBeInTheDocument();
  });

  it('없는 경로는 안내를 보여 준다', async () => {
    renderAt('/없는-경로');
    expect(await screen.findByText('페이지를 찾을 수 없어요')).toBeInTheDocument();
  });
});
