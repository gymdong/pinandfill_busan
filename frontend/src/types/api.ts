/**
 * SDD 6장 API-001~026의 요청·응답 타입. 필드 이름은 SDD 6장 표기(camelCase)를 따른다.
 *
 * `@provisional`이 붙은 항목은 SDD에 형식이 없어 5.2 테이블·4.1 클래스 다이어그램에서 유도했거나
 * 제안한 것이다. 담당자 합의 시 바뀔 수 있다.
 *
 * D6(카카오 공식 답변, 2026-11-02 팀 결정):
 * - 공공 DB에 없는 카카오 장소도 일정에 담는다. 서버에는 카카오 장소 ID와 place_url만 저장한다.
 * - 카카오 장소의 이름·좌표는 이번 접속 동안 브라우저 메모리(`@/api/kakaoSession`)에만 둔다.
 *   좌표는 일정 계산 요청 때 `sessionCoords`로 보내고, 서버는 계산에만 쓰고 저장·캐시·로그하지 않는다.
 */

export type Uuid = string;
/** YYYY-MM-DD */
export type IsoDate = string;
/** HH:mm */
export type LocalTime = string;
/** ISO 8601 일시 */
export type IsoDateTime = string;

export interface Coords {
  lat: number;
  lng: number;
}

export type TransportMode = 'TRANSIT' | 'CAR' | 'WALK';
export type CrowdGrade = '여유' | '보통' | '붐빔' | '매우 붐빔';
export type CrowdConfidence = '높음' | '중간' | '낮음' | '없음';
export type IndoorOutdoor = '실내' | '야외' | '반야외';
/** places 테이블의 장소는 공공 DB만 해당한다. SDD 5.2의 USER_SELECTED는 D6 결정으로 쓰지 않는다. */
export type PlaceSource = 'PUBLIC';
export type BlockOrigin = 'USER' | 'SUGGESTED';
export type LegSource = 'TMAP' | 'ODSAY' | 'CACHE' | 'ESTIMATED';
export type DayType = 'MON' | 'TUE' | 'WED' | 'THU' | 'FRI' | 'SAT' | 'SUN' | 'HOLIDAY';
export type WaypointThresholdMin = 10 | 15 | 30;

/* ---------- 장소 ---------- */

/** @provisional SDD는 `badge` 이름만 정의한다. 값은 '상세 정보 있음'/'기본 정보만'에 대응한다. */
export type PlaceBadge = 'DETAIL' | 'BASIC';
/** @provisional 영업시간 없음('확인 필요')은 매칭 배지와 동시에 나올 수 있어 분리한다. */
export type HoursStatus = 'KNOWN' | 'NEEDS_CHECK';

/** @provisional 카카오 장소 키. D6에 따라 서버에 저장할 수 있는 값은 이 둘뿐이다. */
export interface KakaoPlaceKey {
  kakaoPlaceId: string;
  /** 앱 안이 아니라 외부 브라우저로 연다. */
  placeUrl: string;
}

/**
 * 카카오 장소별 좌표. 키는 `kakaoPlaceId`.
 * @provisional 일정 계산 요청에 함께 보내며, 서버는 저장·캐시·로그하지 않는다.
 */
export type SessionCoords = Record<string, Coords>;

/** @provisional 서버에 좌표가 없는 카카오 장소를 계산하기 위해 요청에 붙는 필드 */
export interface WithSessionCoords {
  sessionCoords?: SessionCoords;
}

export interface PlaceSearchItem extends KakaoPlaceKey {
  /** @provisional 공공 DB 매칭 시 places.id, 미매칭이면 null */
  placeId: Uuid | null;
  /** 카카오 응답 값이다. 미매칭 장소는 메모리에서만 쓴다. */
  name: string;
  coords: Coords;
  /** @provisional 목업 UI-01에 표시되어 추가 */
  category: string | null;
  /** @provisional 목업 UI-01에 표시되어 추가 */
  address: string | null;
  badge: PlaceBadge;
  /** @provisional */
  hoursStatus: HoursStatus;
}

/** API-003 */
export interface PlaceSearchQuery {
  q: string;
  category?: string;
}
export interface PlaceSearchResponse {
  places: PlaceSearchItem[];
}

/** API-004 */
export type PlacesAtQuery = Coords;
export interface PlacesAtResponse {
  places: PlaceSearchItem[];
  nearbyCount: number;
}

/** SDD 5.2 places 중 화면에 내보내는 필드 */
export interface Place {
  id: Uuid;
  name: string;
  lat: number;
  lng: number;
  category: string;
  source: PlaceSource;
  description: string | null;
  closedDaysText: string | null;
  defaultStayMin: number;
  indoorOutdoor: IndoorOutdoor;
  rating: number | null;
  refDate: IsoDate;
}

/** 일정·추천 카드에서 쓰는 축약 장소 정보 */
export type PlaceSummary = Pick<Place, 'id' | 'name' | 'lat' | 'lng' | 'category' | 'source' | 'refDate'>;

export interface PlaceHours {
  dayType: DayType;
  /** null이면 '확인 필요' */
  openTime: LocalTime | null;
  closeTime: LocalTime | null;
  breakStart: LocalTime | null;
  breakEnd: LocalTime | null;
  isClosed: boolean;
}

export interface PlacePhoto {
  id: Uuid;
  url: string;
  sourceOrg: string;
  licenseType: string | null;
  isPrimary: boolean;
}

/** @provisional SDD는 `sources` 이름만 정의한다. places에는 기관 필드가 없다. */
export interface SourceInfo {
  org: string;
  refDate: IsoDate;
}

/** @provisional 장소 상세·추천 카드의 혼잡 요약. API-012 필드에서 유도했다. */
export interface CrowdSummary {
  /** null이면 '정보 부족' */
  grade: CrowdGrade | null;
  confidence: CrowdConfidence;
  asOf: IsoDateTime | null;
  sources: string[];
}

export interface WeatherForecast {
  pop: number | null;
  pty: string | null;
  sky: string | null;
  temp: number | null;
  wind: number | null;
  issuedAt: IsoDateTime;
  scope: 'SHORT' | 'MID';
}

/** API-005 */
export interface PlaceDetailResponse {
  place: Place;
  hours: PlaceHours[];
  photos: PlacePhoto[];
  /** P1(FR-013). P0에서는 null */
  weather: WeatherForecast | null;
  crowd: CrowdSummary | null;
  sources: SourceInfo[];
}

/** API-012 */
export interface PlaceCrowdResponse {
  hours: { h: number; grade: CrowdGrade | null; score: number | null }[];
  confidence: CrowdConfidence;
  asOf: IsoDateTime | null;
  sources: string[];
}

/* ---------- 여행 조건 ---------- */

/** @provisional SDD 5.2 trips.preferences(JSONB)의 내부 형식이 없어 설명에서 유도했다. */
export interface TripPreferences {
  /** theme_tags.code */
  tags?: string[];
  avoid?: string[];
  note?: string;
}

/** API-002 요청이자 API-001 해석 결과. FR-002의 항목별 입력과 대응한다. */
export interface TripConditions {
  dates: { start: IsoDate; end: IsoDate };
  dayStart: LocalTime;
  dayEnd: LocalTime;
  mode: TransportMode;
  companions?: string;
  prefs?: TripPreferences;
  budget?: number;
  /** @provisional FR-002와 trips.start_place_id에는 있으나 SDD API-002 요청에는 없다. */
  startPlaceId?: Uuid;
  /** @provisional 위와 같다. */
  endPlaceId?: Uuid;
}

/** API-001 */
export interface InterpretRequest {
  text: string;
}
export interface InterpretResponse {
  /** 해석된 항목만 담긴다. 나머지는 사용자가 폼에서 채운다. */
  conditions: Partial<TripConditions>;
  needsForm: boolean;
}

/** API-002 */
export interface CreateTripResponse {
  tripId: Uuid;
  sessionKey: string;
}

export interface Trip extends TripConditions {
  id: Uuid;
  detourThresholdMin: number;
}

/* ---------- 일정 ---------- */

/** @provisional 정현빈의 일정 응답 스키마(API-009)가 공유되면 이 절을 교체한다. */
export interface Violation {
  type: string;
  cause: string;
}

/**
 * @provisional 카카오 장소 블록. 서버는 이름·좌표를 모르므로 화면에서
 * `resolveBlockPlace`로 이번 접속의 메모리를 찾고, 없으면 '다시 선택 필요'로 표시한다.
 */
export interface KakaoBlockPlace extends KakaoPlaceKey {
  source: 'KAKAO';
}

/** 공공 DB 장소는 `source: 'PUBLIC'`, 카카오 장소는 `source: 'KAKAO'`로 구분한다. */
export type BlockPlace = PlaceSummary | KakaoBlockPlace;

export interface Block {
  id: Uuid;
  dayNo: number;
  seq: number;
  place: BlockPlace;
  isFixed: boolean;
  fixedStart: LocalTime | null;
  fixedEnd: LocalTime | null;
  stayMin: number;
  arriveAt: LocalTime | null;
  departAt: LocalTime | null;
  origin: BlockOrigin;
  warnings: Violation[];
}

export interface Leg {
  id: Uuid;
  fromBlockId: Uuid;
  toBlockId: Uuid;
  mode: TransportMode;
  /** null이면 '이동시간 확인 필요' */
  durationMin: number | null;
  computedAt: IsoDateTime;
  /** ESTIMATED는 화면에 '추정'으로 표시한다. */
  source: LegSource;
}

/** @provisional */
export interface BlockCrowd extends CrowdSummary {
  blockId: Uuid;
}

/** @provisional */
export interface BlockWeather extends WeatherForecast {
  blockId: Uuid;
}

export interface ScheduleDay {
  dayNo: number;
  date: IsoDate;
  blocks: Block[];
  legs: Leg[];
  crowd: BlockCrowd[];
  /** P1(FR-013). P0에서는 빈 배열 */
  weather: BlockWeather[];
}

/** @provisional */
export interface ScheduleConflict {
  cause: string;
  blockIds: Uuid[];
}

/** API-009 */
export interface Schedule {
  days: ScheduleDay[];
  violations: Violation[];
  conflicts: ScheduleConflict[];
}

/** API-006·007·008 */
export interface ScheduleMutationResponse {
  schedule: Schedule;
  violations: Violation[];
}

/** @provisional 공공 DB 장소는 ID로, 카카오 장소는 키로 담는다. 카카오 장소의 이름은 보내지 않는다. */
export type BlockPlaceInput = { placeId: Uuid } | KakaoPlaceKey;

/** API-006. 클라이언트가 `sessionCoords`를 자동으로 붙인다. */
export interface AddBlockRequest extends WithSessionCoords {
  place: BlockPlaceInput;
  isFixed: boolean;
  fixedWindow?: { dayNo: number; start: LocalTime; end: LocalTime };
  origin: BlockOrigin;
  /**
   * @provisional 경유지를 넣을 인접한 두 블록(정현빈 제안). 이웃하지 않으면 ERR-001.
   * 핵심지 추가처럼 위치를 엔진이 정할 때는 생략한다.
   */
  fromBlockId?: Uuid;
  toBlockId?: Uuid;
}

/** API-007. 클라이언트가 `sessionCoords`를 자동으로 붙인다. */
export type UpdateBlockRequest = ({ isFixed: boolean } | { seq: number } | { stayMin: number }) & WithSessionCoords;

/** API-009. 클라이언트가 `sessionCoords`를 자동으로 붙인다. */
export interface GenerateScheduleRequest extends WithSessionCoords {
  options?: Record<string, unknown>;
}

/** API-010 */
export interface UndoResponse {
  schedule: Schedule;
}

/** API-011. 클라이언트가 `sessionCoords`를 자동으로 붙인다. */
export interface SuggestWaypointsRequest extends WithSessionCoords {
  fromBlockId: Uuid;
  toBlockId: Uuid;
  thresholdMin: WaypointThresholdMin;
}
export interface WaypointCandidate {
  place: PlaceSummary;
  detourMin: number;
  stayMin: number;
  crowd: CrowdSummary | null;
  reason: string;
}
export interface SuggestWaypointsResponse {
  /** 최대 3개. 빈 배열이면 '추가할 곳 없음'(ERR-010) */
  candidates: WaypointCandidate[];
}

/** API-026 */
export interface TripDetailResponse {
  trip: Trip;
  schedule: Schedule | null;
}

/* ---------- 분위기 추천 ---------- */

export interface ThemeTag {
  code: string;
  label: string;
}

/** API-013. SD-03처럼 문장 해석과 태그 확정 후 추천을 나눠 호출한다. */
export type MoodRequest = {
  date: IsoDate;
  limit?: number;
} & ({ text: string; tags?: never; avoid?: never } | { tags: string[]; text?: never; avoid?: string[] });

/** @provisional SDD는 `evidence` 이름만 정의한다. 발췌는 장소 설명 원문 그대로여야 한다. */
export interface MoodEvidence {
  matchedTags: string[];
  excerpt: string | null;
}

export interface MoodPlace {
  place: PlaceSummary;
  photo: PlacePhoto | null;
  evidence: MoodEvidence;
  crowd: CrowdSummary | null;
}

export interface MoodResponse {
  tags: ThemeTag[];
  avoid: string[];
  /** 0개면 태그 칩을 직접 고르도록 안내한다(FR-015). */
  places: MoodPlace[];
}

/* ---------- P1: 플랜 B·날씨·사진·저장·공유·회원 ---------- */

/** API-014 */
export interface PlanBOption {
  id: string;
  kind: string;
  extraMinutes: number;
  hoursConflict: boolean;
}
export interface PlanBResponse {
  trigger: string;
  options: PlanBOption[];
}

/** API-015 */
export interface ApplyPlanBRequest {
  optionId: string;
}
export interface ApplyPlanBResponse {
  schedule: Schedule;
}

/** API-016 */
export interface TripWeatherResponse {
  blocks: { blockId: Uuid; forecast: WeatherForecast; issuedAt: IsoDateTime; scope: 'SHORT' | 'MID' }[];
}

/** API-017 */
export interface PhotoSearchResponse {
  candidates: { place: PlaceSummary; confidence: number }[];
  notFound: boolean;
}

/** API-018 */
export interface SaveTripResponse {
  savedAt: IsoDateTime;
}

/** API-019 */
export interface ShareTripRequest {
  expiresAt?: IsoDateTime;
}
export interface ShareTripResponse {
  url: string;
  token: string;
}

/** API-020 */
export interface SharedTripResponse {
  schedule: Schedule;
}

/** API-021 */
export interface LoginRequest {
  credentials: unknown;
}
export interface LoginResponse {
  accessToken: string;
}

/* ---------- 관리자 ---------- */

/** API-022 */
export interface AdminSourcesResponse {
  sources: { id: string; asOf: IsoDateTime | null; status: 'SUCCESS' | 'FAILED' | 'SKIPPED'; calls: number }[];
}

/** API-023 */
export interface UpdateConfigRequest {
  key: string;
  value: unknown;
}
export type UpdateConfigResponse = { ok: true } | { errors: string[] };

/** API-024 */
export interface PlaceOverrideRequest {
  hours?: PlaceHours[];
  indoorOutdoor?: IndoorOutdoor;
  matchTo?: Uuid;
}
export interface PlaceOverrideResponse {
  place: Place;
}

/** API-025 */
export interface RunSourceResponse {
  runId: Uuid;
}
