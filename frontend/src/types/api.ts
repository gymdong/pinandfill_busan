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

/** 카카오 장소 키. D6에 따라 서버에 저장할 수 있는 값은 이 둘뿐이다. */
export interface KakaoPlaceKey {
  /** 숫자로만 된 카카오 장소 ID */
  kakaoPlaceId: string;
  /** 백엔드는 `https://place.map.kakao.com/{kakaoPlaceId}` 형식만 받는다. 앱 안이 아니라 외부 브라우저로 연다. */
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
  /** null이면 공공 데이터에 기본 체류시간이 없다(API-006은 `fields.stayMin`으로 입력을 요구한다). */
  defaultStayMin: number | null;
  /** null이면 실내외 정보 없음 */
  indoorOutdoor: IndoorOutdoor | null;
  rating: number | null;
  /** null이면 기준일 정보 없음. 출처·기준일 표시는 `PlaceDetailResponse.sources`를 쓴다. */
  refDate: IsoDate | null;
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
  /** null이면 기준일 정보가 없다. 기관명은 보여 주고 기준일은 '확인 필요'로 둔다. */
  refDate: IsoDate | null;
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

/** API-012 '근거 보기'의 근거 신호 하나. @provisional SDD API-012 응답에 없는 추가 필드(spec A-6). */
export interface CrowdSignal {
  /** 자료 코드. 예: 'DATA-04' */
  source: string;
  label: string;
  /** 자료 기준 기간. 예: '2026-10'(월), '2026-11-28'(일) */
  refPeriod: string | null;
  detail: string | null;
}

/** API-012 */
export interface PlaceCrowdResponse {
  hours: { h: number; grade: CrowdGrade | null; score: number | null }[];
  confidence: CrowdConfidence;
  asOf: IsoDateTime | null;
  sources: string[];
  /** 정보 부족이면 빈 배열 */
  signals: CrowdSignal[];
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
  /**
   * 블록을 넣을 일차. `fromBlockId`·`toBlockId`가 없으면 그날 마지막에 붙는다(백엔드 API-006).
   * 화면에서 보고 있는 일차를 보낸다.
   */
  dayNo?: number;
  place: BlockPlaceInput;
  isFixed: boolean;
  fixedWindow?: { dayNo: number; start: LocalTime; end: LocalTime };
  origin: BlockOrigin;
  /**
   * 사용자가 정한 체류시간(분, 정수 1~1440). 보내면 공공 장소 값보다 먼저 쓴다(#18 PM 결정 4, 백엔드 #25).
   * - 서버는 기본값을 만들지 않는다. 보내지 않았는데 공공 장소 값도 없으면 400 ERR-001, `fields.stayMin`이다.
   * - `fixedWindow`와 함께 보내면 시간창 길이와 같아야 한다(다르면 400 ERR-001).
   * - 화면이 보내는 경우: 체류시간 근거가 없는 장소(공공 DB에 없는 카카오 장소, 서버가 `fields.stayMin`으로 알려 준 장소)에
   *   사용자가 고른 값, 그리고 경유지 시트(UI-03)가 공공 후보를 넣을 때 API-011 후보의 `stayMin`(추천과 삽입 체류시간을 맞춘다).
   * - 여행 시작(UI-01)의 최초 생성은 이 요청이 아니라 API-009 `InitialSelection.stayMin`을 쓴다.
   */
  stayMin?: number;
  /**
   * 경유지를 넣을 인접한 두 블록. 둘을 함께 보내야 하며 이웃하지 않으면 ERR-001.
   * 생략하면 `dayNo`의 마지막에 붙는다.
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

/**
 * API-009 최초 생성의 선택 한 곳(PR #35, docs/initial-schedule-api.md). 이름·좌표는 넣지 않는다(D6).
 * - `clientId`: 요청 안에서 유일한 화면 쪽 식별자. 서버 블록 ID가 아니다.
 * - `dayNo`: 없으면 서버가 여행 기간의 날짜를 차례로 시도한다. `fixedWindow`가 있으면 그 `dayNo`와 같아야 한다.
 * - `fixedWindow`: 있을 때만 고정 블록이 된다. `stayMin`을 함께 보내면 시간창 길이와 같아야 한다.
 * - `stayMin`: 사용자 지정 → 공공 장소 값 순서로 쓴다. 근거가 없으면 `STAY_NEEDS_CHECK`로 미배치된다.
 */
export interface InitialSelection {
  clientId: string;
  place: BlockPlaceInput;
  dayNo?: number;
  fixedWindow?: { dayNo: number; start: LocalTime; end: LocalTime };
  stayMin?: number;
}

/** API-009 최초 생성 요청. `options`와 함께 보내지 않고, 이미 블록이 있는 여행에는 보내지 않는다(400). */
export interface InitialScheduleRequest extends WithSessionCoords {
  initial: { policy: 'FIRST_FEASIBLE'; selections: InitialSelection[] };
}

/** 최초 생성 결과. `saved=false`면 저장되지 않은 미리보기라 그 블록 ID를 편집에 쓰지 않는다. */
export interface InitialGeneration {
  saved: boolean;
  /** 경고 없이 엔진이 확정했는지. 저장 여부와 별개다(경로·영업시간 미확인이면 false여도 저장된다). */
  confirmed: boolean;
  unplaced: { clientId: string; reason: Violation }[];
  /**
   * 저장되지 않았을 때(`saved=false`)만 채운다. 미리보기의 서버 블록 ID → 요청 `clientId`(#39). 저장됐으면 `{}`.
   * UI-01은 미리보기를 그리지 않아 쓰지 않는다.
   */
  previewClientIds: Record<string, string>;
}

export type InitialScheduleResponse = Schedule & { generation: InitialGeneration };

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
  /** 지금 되돌릴 수 있는 편집이 있는가. 화면을 다시 열어도 되돌리기 버튼 상태를 맞춘다(FR-006). 옛 서버는 보내지 않는다. */
  canUndo?: boolean;
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
  /** 근거 문장(장소 설명)의 출처 기관·기준일. 발췌가 없거나 기관을 모르면 null(NFR-007) */
  source: SourceInfo | null;
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

/** API-014. SDD 는 {trigger, options[3]} 만 정한다. 나머지 필드는 백엔드 잠정 계약과 같다. */
export type PlanBKind = 'KEEP' | 'REORDER' | 'REPLACE';
export interface PlanBOption {
  id: string;
  kind: PlanBKind;
  /** false 면 고를 수 없고 note 가 이유다. */
  available: boolean;
  /** 그 날 총 이동시간 변화(분, 음수면 줄어듦). 모르면 null */
  extraMinutes: number | null;
  hoursConflict: boolean;
  arriveAt?: LocalTime | null;
  departAt?: LocalTime | null;
  crowd?: CrowdSummary | null;
  /** REPLACE 의 대체 장소 */
  place?: PlaceSummary | null;
  note?: string | null;
}
export interface PlanBResponse {
  blockId: Uuid;
  /** null 이면 플랜 B 를 띄울 조건이 아니다. */
  trigger: 'CROWD' | 'RAIN' | null;
  crowd: CrowdSummary | null;
  /** 안의 이동시간이 직선거리 추정인가. 적용하면 실제 경로로 다시 계산한다. */
  estimated?: boolean;
  options: PlanBOption[];
}

/** API-015 */
export interface ApplyPlanBRequest {
  optionId: string;
}
export type ApplyPlanBResponse = ScheduleMutationResponse;

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
