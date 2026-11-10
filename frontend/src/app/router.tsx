import type { ComponentType } from 'react';
import { createBrowserRouter, type RouteObject } from 'react-router-dom';
import { AppLayout } from './AppLayout';
import { NotFoundPage, RouteErrorPage } from './RouteFallbacks';

/** 페이지는 `pages/<이름>/index.tsx`의 default export로 두고 경로별로 나눠 불러온다. */
function page(load: () => Promise<{ default: ComponentType }>): Pick<RouteObject, 'lazy'> {
  return {
    lazy: async () => ({ Component: (await load()).default }),
  };
}

export const routes: RouteObject[] = [
  {
    element: <AppLayout />,
    errorElement: <RouteErrorPage />,
    hydrateFallbackElement: null,
    children: [
      { path: '/', ...page(() => import('@/pages/trip-start')) },
      { path: '/trips/:tripId', ...page(() => import('@/pages/timeline')) },
      { path: '/trips/:tripId/map', ...page(() => import('@/pages/map-view')) },
      { path: '/places/:placeId', ...page(() => import('@/pages/place-detail')) },
      { path: '/mood', ...page(() => import('@/pages/mood-search')) },
      { path: '/admin', ...page(() => import('@/pages/admin')) },
      // P1: P0 검증이 끝나기 전에는 비활성 자리표시만 둔다.
      { path: '/photo', ...page(() => import('@/pages/photo-search')) },
      { path: '/shared/:token', ...page(() => import('@/pages/shared-trip')) },
      ...(import.meta.env.DEV ? [{ path: '/__dev', ...page(() => import('./DevGallery')) }] : []),
      { path: '*', element: <NotFoundPage /> },
    ],
  },
];

export const router = createBrowserRouter(routes);
