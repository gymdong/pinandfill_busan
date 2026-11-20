# UI-03 연결 인수인계 — PM F1/F2 반영

컴포넌트: `frontend/src/features/waypoint-sheet/WaypointSheet.tsx`.
기존 직접 검색 BlockEditor를 삭제하지 않는다. 아래는 김동현 담당
`frontend/src/pages/timeline/index.tsx`의 `DayTimeline`에 적용할 예시이며,
이번 PR은 그 파일을 수정하지 않는다.

## 두 진입점

```tsx
import { WaypointSheet } from '@/features/waypoint-sheet/WaypointSheet';
// DayTimeline 안. React useState를 기존 import에 추가하고,
// blocks.length === 0 조기 return보다 앞에서 항상 같은 순서로 호출한다.
const [recommendedSlot, setRecommendedSlot] = useState<string | null>(null);
// blocks.map의 next가 있는 구간 안:
<Button disabled={pending} onClick={() => setRecommendedSlot(block.id)}>
  추천 보기
</Button>
// 기존 '사이에 들를 곳 찾기' 버튼의 라벨·aria-expanded·스타일은 그대로 두고
// disabled={pending}만 추가한다. 기존 between BlockEditor도 유지한다.
<button type="button" className={styles.slotButton} aria-expanded={slot === block.id}
  disabled={pending} onClick={() => onSlot(block.id)}>
  <PlusIcon />사이에 들를 곳 찾기
</button>
{slot === block.id && <BlockEditor tripId={tripId}
  between={{ fromBlockId: block.id, toBlockId: next.id }}
  disabled={pending} onChange={onSlotChange} />}
{recommendedSlot === block.id && <WaypointSheet tripId={tripId}
  between={{ fromBlockId: block.id, toBlockId: next.id }} disabled={pending}
  onClose={() => setRecommendedSlot(null)}
  onDirectSearch={() => {
    setRecommendedSlot(null);
    if (slot !== block.id) onSlot(block.id);
  }}
  onChange={async (action) => {
    await onChange(async () => {
      const result = await action(); // 실패하면 아래 닫기 실행 안 됨
      setRecommendedSlot(null);
      return result; // 기존 TimelineTrip.run이 일정/경고/undo 갱신
    });
  }}
/>}
```

현재 DayTimeline은 dayNo를 key로 마운트하므로 일차 전환 때 추천 상태도 초기화된다.
다른 편집으로 선택 구간이 더 이상 인접하지 않으면 추천 시트를 닫거나 렌더링하지 않는다.
요청 중에는 슬롯 전환 버튼을 disabled=pending으로 막는다. Esc로 닫고 다시 열 수 있는
구현에서는 성공 callback이 다른 구간의 시트를 닫지 않도록 요청 구간 ID도 대조한다.
기존 직접 검색 테스트 `TimelinePage.test.tsx`의 인접 블록 사이 검색 삽입은 유지한다.

## Props와 책임

- tripId: string
- between: { fromBlockId: string; toBlockId: string }
- disabled: boolean (부모 pending)
- onChange: (action: () => Promise<ScheduleMutationResponse>) => Promise<void>
- onClose: () => void
- onDirectSearch?: () => void (추천 시트를 닫고 기존 검색으로 전환)

마운트/10·15·30분 변경 시 API-011을 조회한다. 수락 클릭 시 API-006 실행 함수를 부모에
전달한다. 부모는 기존 run처럼 await action 후 일정/경고/undo를 갱신하고 오류를 처리한다.
시트는 그 action의 실패를 직접 포착해 정제된 오류를 내부 role=alert로 표시한 뒤 부모에도
실패를 전달한다. 따라서 부모가 예외를 삼켜도 시트 내부 오류가 사라지지 않는다.
실패 시 시트와 후보를 유지하고 같은 수락 버튼으로 재시도한다. 재시도 시 오류를 지운다.
삽입 중 시트 자체도 중복 클릭을 막는다. 부모 외부 오류 Banner를 제거할 필요는 없다.

## 기존 API 계약

API-006은 #25의 선택적 stayMin을 사용해 서버 후보의 표시된 체류시간을 그대로 전달한다.
숫자 기본값을 만들지 않는다. placeId·from/to·isFixed=false·origin=SUGGESTED 유지.
서버의 요청 stayMin 우선 적용으로 추천과 삽입 체류시간을 맞춘다. 최신 dev의 공통
AddBlockRequest에 stayMin이 있으므로 그대로 사용한다. types/api.ts의 이전 잠정 주석은
실제 타임라인 연결 PR에서 확정 계약에 맞게 정리한다.
카카오 sessionCoords는 공통 클라이언트가 처리하며 이 컴포넌트는 저장하지 않는다.
API-011 기본 CandidateProvider는 아직 미설정이므로 실서버 추천 완료를 주장하지 않는다.

## 검증

F2 오류 표시와 stayMin 전달 테스트는 변경 전 실패, 변경 후 통과를 확인했다.
추천 없음에서 직접 검색 callback, 임계값·순위·취소·늦은 응답·삽입 실패/재시도를 검증한다.
명령: npm test; npm run lint; npm run typecheck; npm run build.
연결 담당 후속 테스트: 직접 검색 기존 흐름 유지, 추천 열기→수락→일정/undo 갱신→닫기,
실패 시 dialog 내부 alert와 재시도, 일차 전환, 요청 중 다른 구간 전환 방지.
실제 페이지 연결 및 브라우저·실서버 검증은 아직 수행하지 않았다.

2026-11-19 검증: 기능 브랜치144개, 별도 최신 dev040ad76+컴포넌트256개 테스트 통과. 양쪽 lint/typecheck/build 통과. 기존 직접 검색 TimelinePage 회귀도 통과. 최신 dev 자동 병합은 하지 않았다.
