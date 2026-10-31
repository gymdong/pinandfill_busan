# 핀앤필 부산 프런트엔드

React + TypeScript + Vite 기반 모바일 웹(360px 기준). 관리자는 박범찬이며, `src/app`, `components`, `api`를 고칠 때는 박범찬을 리뷰어로 지정한다.

## 실행

Node 20.19 이상이 필요하다.

```bash
cd frontend
npm install
npm run dev:mock   # 서버 없이 fixture로 실행 (http://localhost:5173)
npm run dev        # 실제 API 사용. /api를 localhost:8000으로 프록시
```

- 공통 컴포넌트와 전체 화면 경로는 개발 서버의 `/__dev`에서 확인한다. 운영 빌드에는 포함되지 않는다.
- 프록시 대상은 `.env.example`을 `.env.local`로 복사해 `VITE_API_PROXY_TARGET`으로 바꾼다. 포트 8000은 잠정값이다.

| 명령 | 내용 |
| --- | --- |
| `npm run build` | 타입 검사 후 운영 빌드 |
| `npm run lint` | ESLint |
| `npm test` | Vitest 1회 실행 (`npm run test:watch`는 감시 모드) |

## 폴더와 담당

| 위치 | 내용 | 담당 |
| --- | --- | --- |
| `src/app` | 라우팅, 전역 Provider, 레이아웃 | 박범찬 |
| `src/components` | 공통 UI | 박범찬 |
| `src/api`, `src/types/api.ts` | API 클라이언트, 요청·응답 타입, mock | 박범찬 |
| `src/pages/*` | 화면. `index.tsx`의 default export를 라우터가 불러온다 | 화면별 담당 |
| `src/features/*`, `src/map` | 기능 컴포넌트, 카카오맵 래퍼 | 기능별 담당 |
| `src/features/crowd` | 혼잡 배지·그래프. `CrowdBadge`는 초안이며 담당자가 이어받는다 | 홍민지 |

각 페이지의 `PagePlaceholder`는 담당자가 구현하면서 지운다. 새 화면 경로는 `src/app/paths.ts`와 `src/app/router.tsx`에 함께 추가한다.

| 경로 | 화면 | 담당 |
| --- | --- | --- |
| `/` | UI-01 여행 시작 | 박범찬 |
| `/trips/:tripId` | UI-02 코스 타임라인 | 김동현 |
| `/trips/:tripId/map` | UI-06 지도 보기 | 김동현 |
| `/places/:placeId?date=` | UI-04 장소 상세 | 박범찬 |
| `/mood` | UI-08 분위기로 찾기 | 박범찬 |
| `/admin` | UI-09 관리자 | 홍민지 |
| `/photo`, `/shared/:token` | P1 비활성 자리표시 | 미배분 |

UI-03(경유지)과 UI-05(플랜 B)는 경로 없이 `BottomSheet`로 연다.

## API 클라이언트

경로를 직접 쓰지 않고 `@/api`의 함수를 호출한다. 각 함수의 주석에 SDD API ID가 적혀 있다.

```tsx
import { useCallback } from 'react';
import { placesApi } from '@/api';
import { ErrorState, LoadingState } from '@/components';
import { CrowdBadge } from '@/features/crowd';
import { useApi } from '@/hooks/useApi';

export function PlaceSummaryCard({ placeId }: { placeId: string }) {
  // fetcher는 useCallback으로 감싼다. placeId가 바뀌면 이전 요청을 취소하고 다시 불러온다.
  const load = useCallback((signal: AbortSignal) => placesApi.get(placeId, undefined, { signal }), [placeId]);
  const { status, data, error, reload } = useApi(load);

  if (status === 'loading') return <LoadingState />;
  if (status === 'error') return <ErrorState message={error.message} onRetry={reload} />;
  return <CrowdBadge grade={data.crowd?.grade ?? null} />;
}
```

버튼으로 실행하는 변경 요청은 함수를 직접 호출한다.

```ts
import { ApiError, tripsApi } from '@/api';

try {
  const schedule = await tripsApi.generateSchedule(tripId);
} catch (error) {
  if (error instanceof ApiError && error.id === 'ERR-009') {
    // 시간 부족: 날짜 분리 안내
  }
}
```

### 오류 처리

- HTTP 오류는 모두 `ApiError`로 던진다. `id`, `status`, `message`(사용자 문구), `fields`(항목별 오류)를 가진다.
- `ERROR_CATALOG`에서 ERR-001~017의 기본 문구를 찾을 수 있다. 서버 문구가 있으면 서버 문구가 우선이다.
- `delivery: 'inline'`인 항목(ERR-002, ERR-010 등)은 200 응답 안의 값으로 표현되므로 예외가 아니라 화면 상태로 처리한다.
- 클라이언트가 붙이는 ID는 `NETWORK`, `TIMEOUT`, `UNKNOWN`이다.

### mock 모드

- 데이터는 `src/api/mock/fixtures`, 경로 처리는 `src/api/mock/index.ts`에 있다. 화면에 필요한 사례는 여기에 추가한다.
- mock 코드는 운영 빌드에 포함되지 않는다.
- 응답은 고정값이다. 블록을 추가·삭제해도 일정이 바뀌지 않는다.
- 주소에 `?mockError=ERR-003`을 붙이면 그 페이지의 API 호출이 해당 오류로 실패한다.
- API-001은 `10/17~19 2박 3일 대중교통`만 해석에 성공하고, 나머지 문장은 폼 전환(`needsForm`)으로 응답한다.
- API-013은 SD-03 순서대로 문장을 보내면 태그만, 태그를 보내면 추천을 돌려준다.
- API-014~021(P1)은 타입만 있고 mock은 없다.
- fixture는 목업의 예시 값이며 실제 공공 DB 값이 아니다. 좌표는 근사값이고, 태그 3종은 확정된 테마 태그 사전이 아니다.

### 잠정 항목

`src/types/api.ts`에서 `@provisional`을 찾으면 SDD에 형식이 없어 유도했거나 제안한 항목을 볼 수 있다. 합의되면 타입과 mock을 함께 바꾼다.

| 항목 | 현재 값 | 확인할 사람 |
| --- | --- | --- |
| 오류 응답 본문 | `{error: {id, message, fields?}}` | 정현빈 |
| 세션 키 전달 | `X-Session-Key` 헤더, localStorage 보관 | 정현빈 |
| API-009 일정 응답 | SDD 5.2·4.1에서 유도 | 정현빈 |
| API-002 시작·종료 위치 | `startPlaceId`, `endPlaceId` 추가 제안 | 정현빈 |
| API-003 배지 | `badge`와 `hoursStatus` 분리, `placeId`·`category`·`address` 추가 | 박범찬 |
| API-006 미매칭 장소 | D6 확정 전 잠정 | 팀 |
| API-013 `avoid` 요청 필드 | 피할 조건 수정을 위해 추가 제안 | 박범찬 |

## 화면 규칙 (NFR-007·008·012)

- 360px 폭에서 가로 스크롤이 없어야 한다. 탭 영역은 44px 이상이며 `--tap-min` 토큰을 쓴다.
- 혼잡은 `@/features/crowd`의 `CrowdBadge`로 표시한다. 색·글자·막대 칸 수를 함께 보여 주며 '실시간'이라는 표현을 쓰지 않는다.
- 데이터가 없으면 값을 만들지 않고 '확인 필요', '정보 부족', '사진 없음', '정보 없음'으로 표시한다.
- 장소와 사진에는 출처, 기준일, 저작권 유형을 함께 표시한다.
- 색은 `src/styles/tokens.css`의 토큰을 쓴다. 표시 문구는 API 응답을 기준으로 렌더링한다.
- `VITE_`로 시작하는 환경변수는 브라우저에 노출된다. 도메인 제한된 카카오맵 JS 키 외의 키를 넣지 않는다.
