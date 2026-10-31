/** 개발용 예시 일정. 목업 UI-02의 1일차 앞부분을 옮겼다. */
import type { Block, Leg, Schedule, Trip } from '@/types/api';
import { crowd, placeSummaries } from './places';

export const TRIP_ID = '00000000-0000-4000-8000-000000000001';
export const MOCK_SESSION_KEY = 'mock-session-key';

const BLOCK_IDS = {
  gamcheon: '00000000-0000-4000-8000-000000000301',
  huinnyeoul: '00000000-0000-4000-8000-000000000302',
  taejongdae: '00000000-0000-4000-8000-000000000303',
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
