/**
 * 개발용 예시 일정. 목업 UI-02의 1일차 앞부분을 옮겼다.
 * 마지막 블록은 공공 DB에 없는 카카오 장소다. 서버가 이름·좌표를 모르는 재접속 상태를 재현하며,
 * 같은 접속에서 검색해 담으면 `resolveBlockPlace`로 이름이 보인다.
 */
import type { Block, Leg, Schedule, Trip } from '@/types/api';
import { crowd, mockKakaoKey, placeSummaries } from './places';

export const TRIP_ID = '00000000-0000-4000-8000-000000000001';
export const MOCK_SESSION_KEY = 'mock-session-key';

const BLOCK_IDS = {
  gamcheon: '00000000-0000-4000-8000-000000000301',
  huinnyeoul: '00000000-0000-4000-8000-000000000302',
  taejongdae: '00000000-0000-4000-8000-000000000303',
  kakaoCafe: '00000000-0000-4000-8000-000000000304',
} as const;

const COMPUTED_AT = '2026-10-17T09:00:00+09:00';

const blocks: Block[] = [
  {
    id: BLOCK_IDS.gamcheon,
    dayNo: 1,
    seq: 1,
    place: placeSummaries.gamcheon,
    isFixed: true,
    fixedStart: '10:00',
    fixedEnd: '11:30',
    stayMin: 90,
    arriveAt: '10:00',
    departAt: '11:30',
    origin: 'USER',
    warnings: [],
  },
  {
    id: BLOCK_IDS.huinnyeoul,
    dayNo: 1,
    seq: 2,
    place: placeSummaries.huinnyeoul,
    isFixed: false,
    fixedStart: null,
    fixedEnd: null,
    stayMin: 40,
    arriveAt: '11:55',
    departAt: '12:35',
    origin: 'SUGGESTED',
    warnings: [{ type: 'HOURS_UNKNOWN', cause: '영업시간 확인 필요' }],
  },
  {
    id: BLOCK_IDS.taejongdae,
    dayNo: 1,
    seq: 3,
    place: placeSummaries.taejongdae,
    isFixed: true,
    fixedStart: '13:30',
    fixedEnd: '15:00',
    stayMin: 90,
    arriveAt: '13:30',
    departAt: '15:00',
    origin: 'USER',
    warnings: [],
  },
  {
    id: BLOCK_IDS.kakaoCafe,
    dayNo: 1,
    seq: 4,
    place: { source: 'KAKAO', ...mockKakaoKey('3') },
    isFixed: true,
    fixedStart: '16:00',
    fixedEnd: '17:00',
    stayMin: 60,
    arriveAt: '16:00',
    departAt: '17:00',
    origin: 'USER',
    // @provisional 경고 유형은 정현빈의 엔진 스키마를 따른다.
    warnings: [{ type: 'PLACE_UNRESOLVED', cause: '다시 선택이 필요한 장소예요' }],
  },
];

const legs: Leg[] = [
  {
    id: '00000000-0000-4000-8000-000000000401',
    fromBlockId: BLOCK_IDS.gamcheon,
    toBlockId: BLOCK_IDS.huinnyeoul,
    mode: 'TRANSIT',
    durationMin: 25,
    computedAt: COMPUTED_AT,
    source: 'TMAP',
  },
  {
    // '추정' 표시 확인용
    id: '00000000-0000-4000-8000-000000000402',
    fromBlockId: BLOCK_IDS.huinnyeoul,
    toBlockId: BLOCK_IDS.taejongdae,
    mode: 'TRANSIT',
    durationMin: 30,
    computedAt: COMPUTED_AT,
    source: 'ESTIMATED',
  },
  {
    // 좌표를 모르는 카카오 장소로 가는 구간: '이동시간 확인 필요'
    id: '00000000-0000-4000-8000-000000000403',
    fromBlockId: BLOCK_IDS.taejongdae,
    toBlockId: BLOCK_IDS.kakaoCafe,
    mode: 'TRANSIT',
    durationMin: null,
    computedAt: COMPUTED_AT,
    source: 'ESTIMATED',
  },
];

export const schedule: Schedule = {
  days: [
    {
      dayNo: 1,
      date: '2026-10-17',
      blocks,
      legs,
      crowd: [
        { blockId: BLOCK_IDS.gamcheon, ...crowd('보통', '중간') },
        { blockId: BLOCK_IDS.huinnyeoul, ...crowd('여유', '중간') },
        { blockId: BLOCK_IDS.taejongdae, ...crowd('붐빔', '중간') },
        { blockId: BLOCK_IDS.kakaoCafe, ...crowd(null, '없음') },
      ],
      weather: [],
    },
  ],
  violations: [],
  conflicts: [],
};

export const trip: Trip = {
  id: TRIP_ID,
  dates: { start: '2026-10-17', end: '2026-10-19' },
  dayStart: '10:00',
  dayEnd: '19:00',
  mode: 'TRANSIT',
  detourThresholdMin: 15,
};
