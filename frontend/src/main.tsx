import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '@/app/App';
// 글꼴은 저장소 안에서 내려받아 쓴다(외부 CDN 없음). Pretendard 는 쓰인 글자 범위만 받는 가변 글꼴,
// IBM Plex Mono 는 시각·숫자에만 쓰므로 라틴 400 만 받는다. 둘 다 font-display: swap.
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css';
import '@fontsource/ibm-plex-mono/latin-400.css';
import '@/styles/global.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('#root 요소를 찾을 수 없습니다');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
