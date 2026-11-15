# UI-03 경유지 시트 인수인계

TEAM.md의 정현빈 담당 UI-03 컴포넌트다. 타임라인 페이지는 수정하지 않았다.

```tsx
<WaypointSheet
  tripId={tripId}
  between={{ fromBlockId, toBlockId }}
  disabled={pending}
  onChange={change}
  onClose={() => setSlot(null)}
/>
```

김동현 담당 타임라인에서 인접 구간을 선택한 동안만 마운트한다. `onChange`는 기존
타임라인의 change 함수와 호환되며 일정 교체·오류 표시·pending·undo 상태를 부모가 관리한다.
삽입이 성공하면 부모는 시트를 닫아 기존 anchor 사이의 추천 결과를 재사용하지 않아야 한다.
일정이 다른 편집으로 변경되거나 일차·구간이 없어져도 시트를 닫는다.

- API-011: 기본 15분, 10/15/30 선택, 순위를 유지하며 PUBLIC 후보 최대 3개 표시.
- API-006: 명시적 from/to, placeId, origin=SUGGESTED, isFixed=false만 전송한다.
  후보 stayMin은 표시값이며 현재 API-006이 받지 않으므로 비공식 요청 필드를 추가하지 않는다.
- 기존 API 클라이언트가 sessionCoords를 붙인다. 컴포넌트는 카카오 좌표·이름을 읽거나 저장하지 않는다.
- useApi가 구간/임계값 변경·닫기 시 조회를 취소하고 늦은 응답을 무시한다.
- 실제 타임라인 연결, 브라우저 실서버 검증은 담당자 통합 후 필요하다.

## 컴포넌트 검증 (2026-11-15)

Node 24.22.1, 기존 package-lock.json 유지. 전체 Vitest 142개(신규 9개),
ESLint, TypeScript, Vite build 통과. 신규 테스트는 15분 기본값·10/30 변경,
후보 0개·최대 3개, PUBLIC 삽입 요청, 편집 중 비활성화, 오류 재시도,
구간/임계값 변경의 늦은 응답 무시, 닫기와 요청 취소를 검증한다.
컴포넌트는 아직 앱 라우트에 연결되지 않아 build 성공은 실제 화면 연동의 증명이 아니다.
실서버·브라우저 시각 검증은 수행하지 않았다.
