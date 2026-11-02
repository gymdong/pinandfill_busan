/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, fileURLToPath(new URL('.', import.meta.url)), '');
  // `npm run dev:mock`은 셸 환경변수 문법 차이(Windows·POSIX)를 피하려고 mode로 mock을 켠다.
  const apiMode = mode === 'mock' ? 'mock' : (env.VITE_API_MODE ?? 'server');

  return {
    plugins: [react()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    define: {
      'import.meta.env.VITE_API_MODE': JSON.stringify(apiMode),
    },
    server: {
      port: 5173,
      proxy: {
        // 백엔드 포트는 잠정값이다. compose 확정 시 VITE_API_PROXY_TARGET으로 바꾼다.
        '/api': env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
      },
    },
    test: {
      environment: 'jsdom',
      include: ['tests/**/*.test.{ts,tsx}'],
      setupFiles: ['tests/setup.ts'],
      css: { modules: { classNameStrategy: 'non-scoped' } },
    },
  };
});
