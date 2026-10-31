/** SDD 8장 ERR-001~017. `http`는 오류 응답, `inline`은 200 안에서 화면 상태로 표현되는 항목이다. */
export const ERROR_CATALOG = {
  'ERR-001': { delivery: 'http', statuses: [400], message: '입력한 내용을 다시 확인해 주세요.' },
  'ERR-002': { delivery: 'inline', statuses: [200], message: '설명을 불러오지 못해 기본 문구를 보여 드려요.' },
  'ERR-003': { delivery: 'http', statuses: [503], message: '장소 검색이 잠시 안 돼요. 지도에서 직접 골라 주세요.' },
  'ERR-004': { delivery: 'inline', statuses: [200], message: '이동시간을 추정값으로 보여 드려요.' },
  'ERR-005': { delivery: 'inline', statuses: [200], message: '최신 데이터를 가져오지 못해 이전 기준일 정보를 보여 드려요.' },
  'ERR-006': { delivery: 'inline', statuses: [200], message: '데이터 수집이 다음 주기로 미뤄졌어요.' },
  'ERR-007': { delivery: 'inline', statuses: [200], message: '영업시간은 확인이 필요해요.' },
  'ERR-008': { delivery: 'inline', statuses: [200], message: '일정에 맞지 않는 시간이 있어요.' },
  'ERR-009': { delivery: 'http', statuses: [409], message: '시간 안에 모두 넣을 수 없어요. 날짜를 나눠 보세요.' },
  'ERR-010': { delivery: 'inline', statuses: [200], message: '추가할 곳이 없어요. 우회 허용 시간을 늘려 보세요.' },
  'ERR-011': { delivery: 'inline', statuses: [200], message: '혼잡 정보가 부족해요.' },
  'ERR-012': { delivery: 'inline', statuses: [200], message: '예보를 확인할 수 없어요.' },
  'ERR-013': { delivery: 'inline', statuses: [200], message: '사진 없음' },
  'ERR-014': { delivery: 'http', statuses: [400, 413], message: '사진 형식이나 크기를 확인해 주세요.' },
  'ERR-015': { delivery: 'http', statuses: [422], message: '설정값을 저장할 수 없어요.' },
  'ERR-016': { delivery: 'http', statuses: [401, 403, 404], message: '볼 수 없거나 찾을 수 없는 페이지예요.' },
  'ERR-017': { delivery: 'http', statuses: [503], message: '잠시 후 다시 시도해 주세요.' },
} as const satisfies Record<string, { delivery: 'http' | 'inline'; statuses: number[]; message: string }>;

export type ErrorId = keyof typeof ERROR_CATALOG;
/** 서버 응답을 받지 못했거나 해석할 수 없을 때 클라이언트가 붙이는 ID */
export type ClientErrorId = 'NETWORK' | 'TIMEOUT' | 'UNKNOWN';
export type ApiErrorId = ErrorId | ClientErrorId;

const CLIENT_MESSAGE: Record<ClientErrorId, string> = {
  NETWORK: '인터넷 연결을 확인해 주세요.',
  TIMEOUT: '응답이 늦어지고 있어요. 다시 시도해 주세요.',
  UNKNOWN: '문제가 생겼어요. 다시 시도해 주세요.',
};

/** 본문에 오류 ID가 없을 때 상태 코드로 추정한다. 503은 ERR-003도 쓰므로 서버 ID가 우선이다. */
const STATUS_FALLBACK: Record<number, ErrorId> = {
  400: 'ERR-001',
  401: 'ERR-016',
  403: 'ERR-016',
  404: 'ERR-016',
  409: 'ERR-009',
  413: 'ERR-014',
  422: 'ERR-015',
  503: 'ERR-017',
};

export function isErrorId(value: unknown): value is ErrorId {
  return typeof value === 'string' && value in ERROR_CATALOG;
}

export function defaultMessage(id: ApiErrorId): string {
  return isErrorId(id) ? ERROR_CATALOG[id].message : CLIENT_MESSAGE[id];
}

export interface ApiErrorInit {
  id: ApiErrorId;
  status?: number;
  message?: string;
  /** ERR-001의 항목별 오류 메시지 */
  fields?: Record<string, string>;
}

export class ApiError extends Error {
  readonly id: ApiErrorId;
  readonly status: number | undefined;
  readonly fields: Record<string, string> | undefined;

  constructor({ id, status, message, fields }: ApiErrorInit) {
    super(message ?? defaultMessage(id));
    this.name = 'ApiError';
    this.id = id;
    this.status = status;
    this.fields = fields;
  }
}

/**
 * 오류 응답 본문을 ApiError로 바꾼다.
 * @provisional 본문 형식 `{error: {id, message, fields?}}`는 SDD에 없어 제안한 것이다(정현빈과 합의 필요).
 */
export function parseErrorResponse(status: number, body: unknown): ApiError {
  const error = (body as { error?: { id?: unknown; message?: unknown; fields?: unknown } } | null)?.error;
  const id = isErrorId(error?.id) ? error.id : (STATUS_FALLBACK[status] ?? 'UNKNOWN');
  return new ApiError({
    id,
    status,
    message: typeof error?.message === 'string' ? error.message : undefined,
    fields: error?.fields as Record<string, string> | undefined,
  });
}

export function toApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError({ id: 'UNKNOWN' });
}
