/**
 * 개발용 예시 데이터. 이름·설명·시각·등급은 SRS 6.2 목업에 나온 값만 쓰고, 좌표는 화면 개발용 근사값이다.
 * 실제 공공 DB 값이 아니며, 태그 3종도 목업 표기일 뿐 확정된 테마 태그 사전이 아니다.
 */
import type {
  CrowdSummary,
  MoodPlace,
  PlaceCrowdResponse,
  PlaceDetailResponse,
  PlacePhoto,
  PlaceSearchItem,
  PlaceSummary,
  ThemeTag,
  WaypointCandidate,
} from '@/types/api';

export const PLACE_IDS = {
  gamcheon: '00000000-0000-4000-8000-000000000101',
  huinnyeoul: '00000000-0000-4000-8000-000000000102',
  taejongdae: '00000000-0000-4000-8000-000000000103',
  millakPark: '00000000-0000-4000-8000-000000000104',
  millakFish: '00000000-0000-4000-8000-000000000105',
  kkangkkangi: '00000000-0000-4000-8000-000000000106',
  jagalchi: '00000000-0000-4000-8000-000000000107',
  cheongsapo: '00000000-0000-4000-8000-000000000108',
  ibagu: '00000000-0000-4000-8000-000000000109',
} as const;

const REF_DATE = '2026-10-13';
const AS_OF = '2026-10-17T05:00:00+09:00';
const KTO = '한국관광공사';
const BUSAN = '부산광역시';
const LICENSE = '공공누리 제1유형';

function summary(id: string, name: string, lat: number, lng: number, category: string): PlaceSummary {
  return { id, name, lat, lng, category, source: 'PUBLIC', refDate: REF_DATE };
}

export const placeSummaries = {
  gamcheon: summary(PLACE_IDS.gamcheon, '감천문화마을', 35.0975, 129.0106, '관광지'),
  huinnyeoul: summary(PLACE_IDS.huinnyeoul, '흰여울문화마을', 35.0784, 129.0453, '관광지'),
  taejongdae: summary(PLACE_IDS.taejongdae, '태종대', 35.0517, 129.0855, '자연 명소'),
  millakPark: summary(PLACE_IDS.millakPark, '민락수변공원', 35.1548, 129.1313, '공원'),
  millakFish: summary(PLACE_IDS.millakFish, '민락회타운', 35.1555, 129.1305, '시장'),
  kkangkkangi: summary(PLACE_IDS.kkangkkangi, '깡깡이예술마을', 35.0935, 129.0355, '전시·문화'),
  jagalchi: summary(PLACE_IDS.jagalchi, '자갈치시장', 35.0966, 129.0306, '시장'),
  cheongsapo: summary(PLACE_IDS.cheongsapo, '청사포', 35.1606, 129.1913, '관광지'),
  ibagu: summary(PLACE_IDS.ibagu, '초량 이바구길', 35.1146, 129.0395, '관광지'),
};

function photo(id: string, color: string, sourceOrg: string, isPrimary = true): PlacePhoto {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="240"><rect width="480" height="240" fill="${color}"/></svg>`;
  return {
    id,
    url: `data:image/svg+xml,${encodeURIComponent(svg)}`,
    sourceOrg,
    licenseType: LICENSE,
    isPrimary,
  };
}

export function crowd(grade: CrowdSummary['grade'], confidence: CrowdSummary['confidence']): CrowdSummary {
  return grade === null
    ? { grade, confidence: '없음', asOf: null, sources: [] }
    : { grade, confidence, asOf: AS_OF, sources: ['행정동 생활인구', '도시철도 승하차'] };
}

export const searchItems: PlaceSearchItem[] = [
  {
    placeId: PLACE_IDS.millakPark,
    name: '민락수변공원',
    coords: { lat: 35.1548, lng: 129.1313 },
    category: '공원',
    address: '수영구 광안해변로',
    badge: 'DETAIL',
    hoursStatus: 'NEEDS_CHECK',
  },
  {
    placeId: PLACE_IDS.millakFish,
    name: '민락회타운',
    coords: { lat: 35.1555, lng: 129.1305 },
    category: '시장',
    address: '수영구 민락동',
    badge: 'DETAIL',
    hoursStatus: 'NEEDS_CHECK',
  },
  {
    // 미매칭 사례: 공공 DB에 없어 placeId가 없다.
    placeId: null,
    name: '민락 바다뷰 카페 (예시)',
    coords: { lat: 35.1561, lng: 129.1298 },
    category: '카페',
    address: '수영구 민락동',
    badge: 'BASIC',
    hoursStatus: 'NEEDS_CHECK',
  },
];

export const taejongdaeDetail: PlaceDetailResponse = {
  place: {
    ...placeSummaries.taejongdae,
    description: null,
    closedDaysText: null,
    defaultStayMin: 90,
    indoorOutdoor: '야외',
    rating: null,
  },
  hours: (['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'] as const).map((dayType) => ({
    dayType,
    openTime: '09:00',
    closeTime: '18:00',
    breakStart: null,
    breakEnd: null,
    isClosed: false,
  })),
  photos: [
    photo('00000000-0000-4000-8000-000000000201', '#9cbad6', KTO),
    photo('00000000-0000-4000-8000-000000000202', '#a9b2ad', KTO, false),
  ],
  weather: null,
  crowd: crowd('붐빔', '중간'),
  sources: [{ org: KTO, refDate: REF_DATE }],
};

/** 영업시간·사진·혼잡 근거가 없는 장소('확인 필요'·'사진 없음'·'정보 부족' 확인용) */
export function sparseDetail(place: PlaceSummary): PlaceDetailResponse {
  return {
    place: {
      ...place,
      description: null,
      closedDaysText: null,
      defaultStayMin: 60,
      indoorOutdoor: '야외',
      rating: null,
    },
    hours: [],
    photos: [],
    weather: null,
    crowd: crowd(null, '없음'),
    sources: [{ org: KTO, refDate: REF_DATE }],
  };
}

export const taejongdaeCrowd: PlaceCrowdResponse = {
  hours: [
    { h: 9, grade: '여유', score: 0.2 },
    { h: 10, grade: '여유', score: 0.25 },
    { h: 11, grade: '보통', score: 0.45 },
    { h: 12, grade: '보통', score: 0.55 },
    { h: 13, grade: '붐빔', score: 0.75 },
    { h: 14, grade: '붐빔', score: 0.85 },
    { h: 15, grade: '붐빔', score: 0.78 },
    { h: 16, grade: '보통', score: 0.5 },
    { h: 17, grade: '여유', score: 0.3 },
  ],
  confidence: '중간',
  asOf: AS_OF,
  sources: ['행정동 생활인구', '도시철도 승하차'],
};

export const waypointCandidates: WaypointCandidate[] = [
  {
    place: placeSummaries.huinnyeoul,
    detourMin: 12,
    stayMin: 40,
    crowd: crowd('여유', '중간'),
    reason: "'바다 전망' 취향, 태종대와 같은 영도구",
  },
  {
    place: placeSummaries.kkangkkangi,
    detourMin: 9,
    stayMin: 30,
    crowd: crowd('여유', '낮음'),
    reason: "우회가 가장 짧고 '전시·문화' 공공미술",
  },
  {
    place: placeSummaries.jagalchi,
    detourMin: 14,
    stayMin: 50,
    crowd: crowd('보통', '중간'),
    reason: '가는 길에 있는 시장',
  },
];

export const moodTags: ThemeTag[] = [
  { code: 'SEA_VIEW', label: '바다 전망' },
  { code: 'ALLEY_WALK', label: '골목·산책' },
];
export const moodAvoid = ['덜 붐비는 곳'];

export const moodPlaces: MoodPlace[] = [
  {
    place: placeSummaries.huinnyeoul,
    photo: photo('00000000-0000-4000-8000-000000000203', '#c7d8e7', KTO),
    evidence: { matchedTags: ['SEA_VIEW', 'ALLEY_WALK'], excerpt: '해안 절벽 위로 이어진 좁은 골목' },
    crowd: crowd('여유', '중간'),
  },
  {
    place: placeSummaries.cheongsapo,
    photo: photo('00000000-0000-4000-8000-000000000204', '#9cbad6', BUSAN),
    evidence: { matchedTags: ['SEA_VIEW'], excerpt: '등대가 보이는 작은 포구 마을' },
    crowd: crowd('보통', '중간'),
  },
  {
    place: placeSummaries.ibagu,
    photo: null,
    evidence: { matchedTags: ['ALLEY_WALK'], excerpt: '168계단 위에서 내려다보는 항구' },
    crowd: crowd('여유', '낮음'),
  },
];
