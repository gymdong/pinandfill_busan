import { useMemo, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toApiError, tripsApi } from '@/api';
import { paths } from '@/app/paths';
import { Badge, Banner, Button } from '@/components';
import { PlaceSearch, STAY_OPTIONS, pinnedBadgeKind, toPinnedPlace } from '@/features/place-search';
import {
  DEFAULT_CONDITIONS,
  MODE_OPTIONS,
  dayDate,
  tripDays,
  tripLengthLabel,
  validateConditions,
} from '@/features/trip-start/conditions';
import {
  CourseFailedError,
  STAY_NEEDS_CHECK,
  conflictsOf,
  createCourse,
  stayRequired,
  validatePlans,
  type StayAsked,
} from '@/features/trip-start/createCourse';
import {
  PINNED_LIMIT,
  PINNED_LIMIT_MESSAGE,
  pinnedKey,
  planOf,
  useTripDraft,
  type PinnedPlace,
  type PinnedPlan,
} from '@/store/tripDraft';
import { formatDate, formatDuration } from '@/utils/format';
import styles from './TripStartPage.module.css';

type InterpretStatus = 'idle' | 'loading' | 'done' | 'needsForm';

const MAP_HINT = '찾는 곳이 없으면 코스를 만든 뒤 지도 보기에서 직접 고를 수 있어요.';

/** UI-01 여행 시작: 여행 조건 입력(FR-002)과 꼭 갈 곳 담기(FR-001) */
export default function TripStartPage() {
  const navigate = useNavigate();
  const { conditions: draft, pinned, plans, mood, setConditions, setMood, addPinned, removePinned, setPlan, reset } =
    useTripDraft();
  const conditions = { ...DEFAULT_CONDITIONS, ...draft };
  const days = tripDays(conditions.dates);
  const dayCount = days ?? 1;

  const [text, setText] = useState('');
  const [interpretStatus, setInterpretStatus] = useState<InterpretStatus>('idle');
  const [showErrors, setShowErrors] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const startDateRef = useRef<HTMLInputElement>(null);
  // 일정을 저장하지 못한 빈 여행. 여행 조건이 그대로면 다시 누를 때 새로 만들지 않고 이 여행에 다시 보낸다.
  // `selectionKey`는 그때 보낸 담은 장소·계획이다. 이전 요청이 뒤늦게 저장됐을 때 그 뒤 고친 내용이 있는지 가린다.
  const unsaved = useRef<{ tripId: string; conditionsKey: string; selectionKey: string } | null>(null);
  // 응답을 못 받은 이전 요청이 이미 저장해서, 그 뒤 고친 내용이 반영되지 않은 여행
  const [savedEarlier, setSavedEarlier] = useState<string | null>(null);
  // 서버가 체류시간 근거가 없다고 알려 준(STAY_NEEDS_CHECK) 장소. 공공 DB 장소라도 머무를 시간을 고른다.
  const [stayAsked, setStayAsked] = useState<StayAsked>(new Set());
  // 서버가 장소별로 알려 준 문제: 일정에 넣지 못한 이유(API-009 generation.unplaced)와
  // 고정 시각 충돌(409 ERR-009 fields, #39). 키는 pinnedKey
  const [unplaced, setUnplaced] = useState<Record<string, string>>({});

  // 당일 여행은 1일차뿐이다. 여행 기간을 줄이면 사라진 일차에 둔 장소는 마지막 날로 옮겨 보여 준다.
  const effectivePlans = useMemo(() => {
    const entries = pinned.map((place) => {
      const key = pinnedKey(place);
      const plan = planOf(plans, key);
      const dayNo = dayCount === 1 ? 1 : plan.dayNo === null ? null : Math.min(Math.max(plan.dayNo, 1), dayCount);
      return [key, { ...plan, dayNo }] as const;
    });
    return Object.fromEntries(entries) as Record<string, PinnedPlan>;
  }, [pinned, plans, dayCount]);

  const pickedKeys = useMemo(() => new Set(pinned.map(pinnedKey)), [pinned]);
  const validation = validateConditions(draft);
  const errors = showErrors && !validation.ok ? validation.errors : {};
  const planErrors = showErrors ? validatePlans(pinned, effectivePlans, dayCount, stayAsked) : {};
  const conditionsKey = JSON.stringify(validation.ok ? validation.value : draft);
  const selectionKey = JSON.stringify([pinned.map(pinnedKey), effectivePlans]);
  // 제출 오류는 그때의 조건·담은 장소에 대한 것이다. 사용자가 고치면(키가 바뀌면) 배너를 감춘다.
  const formKey = `${conditionsKey}|${selectionKey}`;
  const [submitErrorKey, setSubmitErrorKey] = useState<string | null>(null);
  const visibleSubmitError = submitError && submitErrorKey === formKey ? submitError : null;

  // 장소의 계획을 고치거나 빼면 그 장소의 미배치 이유는 지난 결과라 지운다.
  function clearUnplaced(key: string) {
    setUnplaced((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  async function interpret(event: FormEvent) {
    event.preventDefault();
    const value = text.trim();
    if (!value) return;
    setInterpretStatus('loading');
    try {
      // AI 해석은 오래 걸릴 수 있어 시간 제한을 늘린다.
      const response = await tripsApi.interpret({ text: value }, { timeoutMs: 30_000 });
      setConditions(response.conditions);
      setInterpretStatus(response.needsForm ? 'needsForm' : 'done');
      if (response.needsForm) startDateRef.current?.focus();
    } catch {
      // 해석 실패·AI 장애는 항목별 입력으로 이어 간다(FR-002, AI-REQ-05).
      setInterpretStatus('needsForm');
      startDateRef.current?.focus();
    }
  }

  function changeDates(change: { start?: string; end?: string }) {
    const start = change.start ?? conditions.dates?.start ?? '';
    let end = change.end ?? conditions.dates?.end ?? '';
    // 시작일을 종료일 뒤로 옮기면 당일 여행으로 맞춘다.
    if (change.start !== undefined && start && (!end || end < start)) end = start;
    setConditions({ dates: { start, end } });
  }

  function goToTimeline(tripId: string) {
    reset();
    navigate(paths.timeline(tripId));
  }

  async function submit() {
    setShowErrors(true);
    setSubmitError(null);
    setSubmitErrorKey(formKey);
    if (!validation.ok) {
      setSubmitError('여행 조건을 확인해 주세요. 표시된 칸을 고치면 돼요.');
      startDateRef.current?.focus();
      return;
    }
    const failing = validatePlans(pinned, effectivePlans, dayCount, stayAsked);
    const firstBad = pinned.find((place) => pinnedKey(place) in failing);
    if (firstBad) {
      // 어디가 문제인지 배너에 장소 이름으로 말하고, 그 장소로 화면과 포커스를 옮긴다.
      const others = Object.keys(failing).length - 1;
      setSubmitError(`${firstBad.name}: ${failing[pinnedKey(firstBad)]}${others > 0 ? ` (그 밖에 ${others}곳)` : ''}`);
      const row = document.getElementById(pinnedRowId(pinnedKey(firstBad)));
      row?.scrollIntoView?.({ block: 'center' });
      // 오류가 가리키는 칸에 포커스를 둔다. '빼기' 버튼에 두면 Enter 한 번에 장소가 빠진다.
      focusFix(row, failing[pinnedKey(firstBad)] ?? '');
      return;
    }
    if (pinned.length > PINNED_LIMIT) {
      setSubmitError(`${PINNED_LIMIT_MESSAGE} ${pinned.length - PINNED_LIMIT}곳을 빼 주세요.`);
      return;
    }
    setSubmitting(true);
    setUnplaced({});
    // 여행 조건이 그대로일 때만 저장하지 못한 빈 여행을 다시 쓴다. 담은 장소·계획은 전체를 다시 보낸다.
    const retryTripId = unsaved.current?.conditionsKey === conditionsKey ? unsaved.current.tripId : undefined;
    try {
      const outcome = await createCourse(validation.value, pinned, effectivePlans, { retryTripId, asked: stayAsked });
      if (outcome.kind === 'saved') {
        const sentBefore = unsaved.current?.selectionKey;
        unsaved.current = null;
        if (outcome.earlier && sentBefore !== selectionKey) {
          // 이전 요청이 이미 저장해서 방금 고친 내용은 보내지 않았다. 조용히 이동하지 않고 알린다.
          setSavedEarlier(outcome.tripId);
          return;
        }
        goToTimeline(outcome.tripId);
        return;
      }
      unsaved.current = { tripId: outcome.tripId, conditionsKey, selectionKey };
      setUnplaced(Object.fromEntries(Object.entries(outcome.reasons).map(([key, reason]) => [key, reason.cause])));
      // 체류시간 근거가 없어 넣지 못한 장소는 공공 DB 장소라도 머무를 시간을 고르게 한다(#18 PM 결정 4).
      const needStay = Object.entries(outcome.reasons).filter(([, reason]) => reason.type === STAY_NEEDS_CHECK);
      if (needStay.length > 0) setStayAsked((prev) => new Set([...prev, ...needStay.map(([key]) => key)]));
      setSubmitError(
        Object.keys(outcome.reasons).length > 0
          ? '일정에 넣지 못한 장소가 있어 아직 저장하지 않았어요. 표시된 장소를 고친 뒤 다시 눌러 주세요.'
          : '일정을 저장하지 못했어요. 장소나 시간을 바꿔 다시 눌러 주세요.',
      );
    } catch (error) {
      if (error instanceof CourseFailedError) {
        unsaved.current = { tripId: error.tripId, conditionsKey, selectionKey };
        // 고정 시각 충돌이면 서버가 알려 준 장소 아래에 문구를 보여 준다. 담은 장소가 아닌 키는 버린다.
        const conflicts = Object.entries(conflictsOf(error.apiError)).filter(([key]) => pickedKeys.has(key));
        if (conflicts.length > 0) {
          setUnplaced(Object.fromEntries(conflicts));
          setSubmitError('지정한 시간을 지킬 수 없는 장소가 있어요. 표시된 장소의 시간이나 날짜를 바꿔 다시 눌러 주세요.');
          return;
        }
        setSubmitError(`${error.apiError.message} 다시 누르면 같은 여행으로 이어서 만들어요.`);
      } else {
        unsaved.current = null;
        setSubmitError(toApiError(error).message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <p className={styles.step}>새 여행 · 1/2 단계</p>
        <h1 className={styles.title}>
          꼭 갈 곳만 담아주세요.
          <br />
          사이 동선은 저희가 채울게요.
        </h1>
      </header>

      <section className={styles.section} aria-label="한 줄로 입력">
        <form className={styles.interpretForm} onSubmit={interpret}>
          <label htmlFor="trip-text" className="sr-only">여행 조건 한 줄 입력</label>
          <input
            id="trip-text"
            className={styles.textInput}
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="예: 10/17~19 2박 3일 대중교통"
            maxLength={200}
            autoComplete="off"
          />
          <Button type="submit" variant="outline" disabled={!text.trim()} loading={interpretStatus === 'loading'}>
            {interpretStatus === 'loading' ? '해석 중' : '해석'}
          </Button>
        </form>
        {interpretStatus === 'done' && <Banner>해석한 조건을 아래에 채웠어요. 틀린 항목은 바로 고칠 수 있어요.</Banner>}
        {interpretStatus === 'needsForm' && <Banner tone="warn">문장을 해석하지 못했어요. 아래 항목을 직접 입력해 주세요.</Banner>}
      </section>

      <section className={styles.card} aria-label="여행 조건">
        <div className={styles.row}>
          <span className={styles.rowLabel}>날짜</span>
          <span className={styles.rowInputs}>
            <input
              ref={startDateRef}
              className={styles.field}
              type="date"
              aria-label="여행 시작일"
              aria-invalid={Boolean(errors.dates)}
              value={conditions.dates?.start ?? ''}
              onChange={(event) => changeDates({ start: event.target.value })}
            />
            <span aria-hidden="true">–</span>
            <input
              className={styles.field}
              type="date"
              aria-label="여행 종료일"
              aria-invalid={Boolean(errors.dates)}
              min={conditions.dates?.start || undefined}
              value={conditions.dates?.end ?? ''}
              onChange={(event) => changeDates({ end: event.target.value })}
            />
          </span>
          {days !== null && <span className={styles.rowNote}>{tripLengthLabel(days)}</span>}
          {errors.dates && <p className={styles.error} role="alert">{errors.dates}</p>}
        </div>

        <div className={styles.row}>
          <span className={styles.rowLabel}>하루 일정</span>
          <span className={styles.rowInputs}>
            <input
              className={`${styles.field} ${styles.time}`}
              type="time"
              aria-label="하루 시작 시각"
              aria-invalid={Boolean(errors.hours)}
              value={conditions.dayStart}
              onChange={(event) => setConditions({ dayStart: event.target.value })}
            />
            <span aria-hidden="true">–</span>
            <input
              className={`${styles.field} ${styles.time}`}
              type="time"
              aria-label="하루 종료 시각"
              aria-invalid={Boolean(errors.hours)}
              value={conditions.dayEnd}
              onChange={(event) => setConditions({ dayEnd: event.target.value })}
            />
          </span>
          {errors.hours && <p className={styles.error} role="alert">{errors.hours}</p>}
        </div>

        <div className={styles.row}>
          <span className={styles.rowLabel} id="trip-mode-label">이동</span>
          <span className={styles.modes} role="radiogroup" aria-labelledby="trip-mode-label">
            {MODE_OPTIONS.map(({ mode, label }) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={conditions.mode === mode}
                className={styles.mode}
                onClick={() => setConditions({ mode })}
              >
                {label}
              </button>
            ))}
          </span>
        </div>

        <details className={styles.optional}>
          <summary>동행·예산 (선택)</summary>
          <label className={styles.optionalField}>
            <span>동행</span>
            <input
              className={styles.field}
              value={conditions.companions ?? ''}
              onChange={(event) => setConditions({ companions: event.target.value })}
              placeholder="예: 친구 2명"
              maxLength={50}
            />
          </label>
          <label className={styles.optionalField}>
            <span>예산(원)</span>
            <input
              className={styles.field}
              type="number"
              inputMode="numeric"
              min={0}
              step={1000}
              aria-invalid={Boolean(errors.budget)}
              value={conditions.budget ?? ''}
              onChange={(event) => setConditions({ budget: event.target.value === '' ? undefined : Number(event.target.value) })}
            />
          </label>
          {errors.budget && <p className={styles.error} role="alert">{errors.budget}</p>}
        </details>
      </section>

      <section className={styles.section} aria-label="꼭 갈 곳">
        <div className={styles.sectionHead}>
          <h2 className={styles.sectionTitle}>
            꼭 갈 곳 <span className={styles.count}>{pinned.length}</span>
          </h2>
          <span className={styles.sectionNote}>시간을 정하면 고정돼요</span>
        </div>

        {pinned.length > 0 && (
          <ul className={styles.pinnedList}>
            {pinned.map((place) => {
              const key = pinnedKey(place);
              return (
                <PinnedItem
                  key={key}
                  place={place}
                  plan={planOf(effectivePlans, key)}
                  askStay={stayRequired(place, stayAsked)}
                  dayCount={dayCount}
                  startDate={conditions.dates?.start}
                  error={planErrors[key] ?? unplaced[key]}
                  onPlan={(plan) => {
                    setPlan(key, plan);
                    clearUnplaced(key);
                  }}
                  onRemove={() => {
                    removePinned(key);
                    clearUnplaced(key);
                  }}
                />
              );
            })}
          </ul>
        )}

        <PlaceSearch
          pickedKeys={pickedKeys}
          onPick={(item) => addPinned(toPinnedPlace(item))}
          pickBlocked={pinned.length >= PINNED_LIMIT ? PINNED_LIMIT_MESSAGE : null}
          onUnpick={(item) => removePinned(pinnedKey(toPinnedPlace(item)))}
          fallbackHint={MAP_HINT}
        />

        <Link className={styles.moodLink} to={paths.moodSearch()}>
          <span>{mood ? '고른 분위기 바꾸기' : '원하는 분위기로 찾기'}</span>
          <span aria-hidden="true">›</span>
        </Link>
        {mood && (
          <div className={styles.mood} role="group" aria-label="고른 분위기">
            <p className={styles.moodLabels}>
              {[...mood.tags.map((tag) => tag.label), ...mood.avoid].join(' · ')}
            </p>
            <button type="button" className={styles.moodClear} onClick={() => setMood(null)}>
              분위기 지우기
            </button>
          </div>
        )}
      </section>

      <footer className={styles.footer}>
        {savedEarlier ? (
          <>
            <Banner tone="warn" title="이전 요청으로 코스가 이미 만들어졌어요">
              응답을 받지 못했던 요청이 먼저 저장돼, 그 뒤 고친 내용은 반영되지 않았어요. 타임라인에서 고쳐 주세요.
            </Banner>
            <Button block onClick={() => goToTimeline(savedEarlier)}>타임라인에서 확인하기</Button>
          </>
        ) : (
          <>
            {visibleSubmitError && <Banner tone="warn">{visibleSubmitError}</Banner>}
            <p className={styles.footerNote}>
              {pinned.length === 0 ? '꼭 갈 곳을 1곳 이상 담으면 코스를 만들 수 있어요' : '사이 구간의 경유지는 코스를 만든 뒤에 찾아요'}
            </p>
            <Button block disabled={pinned.length === 0} loading={submitting} onClick={submit}>
              {submitting ? '코스 만드는 중' : '코스 만들기'}
            </Button>
          </>
        )}
      </footer>
    </main>
  );
}

/** 오류 문구에 맞는 칸(시각 → 비어 있는 시각 칸, 일차 → 일차 칸, 머무를 시간 → 그 칸)으로 포커스를 옮긴다. */
function focusFix(row: HTMLElement | null, message: string) {
  if (!row) return;
  const times = [...row.querySelectorAll<HTMLInputElement>('input[type="time"]')];
  const selects = [...row.querySelectorAll<HTMLSelectElement>('select')];
  const target = message.includes('시각')
    ? times.find((input) => !input.value) ?? times[0]
    : message.includes('일차')
      ? selects.find((select) => (select.getAttribute('aria-label') ?? '').includes('일차')) ?? selects[0]
      : selects.find((select) => (select.getAttribute('aria-label') ?? '').includes('머무를')) ?? times[0] ?? selects[0];
  target?.focus();
}

/** 담은 장소 행의 DOM id. 제출 오류 때 그 행으로 스크롤·포커스한다. */
function pinnedRowId(key: string) {
  return `pinned-${key.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
}

function PinnedItem({ place, plan, askStay, dayCount, startDate, error, onPlan, onRemove }: {
  place: PinnedPlace;
  plan: PinnedPlan;
  /** 머무를 시간을 고르게 할지: 공공 DB에 없는 카카오 장소이거나 서버가 체류시간을 요구한 장소 */
  askStay: boolean;
  dayCount: number;
  startDate: string | undefined;
  error: string | undefined;
  onPlan: (plan: Partial<PinnedPlan>) => void;
  onRemove: () => void;
}) {
  return (
    <li className={styles.pinned} id={pinnedRowId(pinnedKey(place))}>
      <div className={styles.pinnedHead}>
        <span className={styles.pinnedName}>{place.name}</span>
        <Badge kind={pinnedBadgeKind(place)} />
        <button type="button" className={styles.textButton} aria-label={`${place.name} 빼기`} onClick={onRemove}>빼기</button>
      </div>
      <div className={styles.pinnedPlan}>
        {dayCount > 1 && (
          <select
            className={styles.field}
            aria-label={`${place.name} 방문 일차`}
            aria-invalid={Boolean(error)}
            value={plan.dayNo ?? ''}
            onChange={(event) => onPlan({ dayNo: event.target.value ? Number(event.target.value) : null })}
          >
            {/* 일차를 비우면 서버가 여행 기간의 날짜를 차례로 시도한다(API-009 최초 생성). */}
            <option value="">일차 알아서</option>
            {Array.from({ length: dayCount }, (_, index) => {
              const date = dayDate(startDate, index + 1);
              return <option key={index} value={index + 1}>{index + 1}일차{date ? ` · ${formatDate(date)}` : ''}</option>;
            })}
          </select>
        )}
        {plan.fixed ? (
          <>
            <span className={styles.rowInputs}>
              <input
                className={`${styles.field} ${styles.time}`}
                type="time"
                aria-label={`${place.name} 도착 시각`}
                aria-invalid={Boolean(error)}
                value={plan.fixed.start}
                onChange={(event) => onPlan({ fixed: { start: event.target.value, end: plan.fixed?.end ?? '' } })}
              />
              <span aria-hidden="true">–</span>
              <input
                className={`${styles.field} ${styles.time}`}
                type="time"
                aria-label={`${place.name} 출발 시각`}
                aria-invalid={Boolean(error)}
                value={plan.fixed.end}
                onChange={(event) => onPlan({ fixed: { start: plan.fixed?.start ?? '', end: event.target.value } })}
              />
            </span>
            <button type="button" className={styles.textButton} onClick={() => onPlan({ fixed: null })}>시간 빼기</button>
          </>
        ) : (
          <>
            {askStay && (
              // 서버가 체류시간을 정할 근거가 없는 장소는 직접 고른다. 기본값은 두지 않는다.
              <select
                className={styles.field}
                aria-label={`${place.name} 머무를 시간`}
                aria-invalid={Boolean(error)}
                value={plan.stayMin ?? ''}
                onChange={(event) => onPlan({ stayMin: event.target.value ? Number(event.target.value) : null })}
              >
                <option value="">머무를 시간</option>
                {STAY_OPTIONS.map((minutes) => <option key={minutes} value={minutes}>{formatDuration(minutes)}</option>)}
              </select>
            )}
            <button type="button" className={styles.textButton} onClick={() => onPlan({ fixed: { start: '', end: '' } })}>
              시간 정하기
            </button>
          </>
        )}
      </div>
      {error && <p className={styles.error} role="alert">{error}</p>}
    </li>
  );
}
